"""
========================================================================
 PULSE 7/24 WORKER  (worker.py)  —  v5.8
========================================================================
Botlar, Stop-Loss / Take-Profit, limit emirleri, fiyat alarmları ve
bildirimler tarayıcı kapalıyken de çalışsın diye ayrı bir süreç.

  Başlatma (uygulama klasöründe):
      PULSE_SHARED=1 python worker.py            # Linux / macOS
      set PULSE_SHARED=1 && python worker.py     # Windows (deploy/windows/start_worker.bat)

  Arayüz (Streamlit) de AYNI klasörde ve PULSE_SHARED=1 ile çalışmalı —
  ikisi aynı veri klasörünü (PULSE_DATA_DIR, varsayılan .pulse_data)
  paylaşır. Worker çalışırken arayüz kendi izleyicisini bekletir; çift
  alım olmaz (dosya kilidi + 15 dakikalık dilim kontrolü).

  Ayarlar: .streamlit/secrets.toml (uygulamayla aynı dosya) ya da ortam
  değişkenleri (PULSE_STORE_REPO, PULSE_STORE_TOKEN, PULSE_MAIL_USER …).
  --once : tek tur çalış ve çık (cron / Görev Zamanlayıcı için)
  --check: ayarları ve veri klasörünü göster, işlem yapma
========================================================================
"""

import os
import signal
import sys
import threading
import time

os.environ.setdefault("PULSE_SHARED", "1")
os.environ.setdefault("PULSE_NO_MONITOR", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import backend as bk  # noqa: E402
import mock_data as md  # noqa: E402

WORKER_VERSION = "5.12"


def _load_secrets():
    """.streamlit/secrets.toml → sözlük (Python 3.11+: tomllib; yoksa boş)."""
    path = os.environ.get("PULSE_SECRETS") or os.path.join(HERE, ".streamlit", "secrets.toml")
    if not os.path.exists(path):
        return {}
    try:
        import tomllib
    except ImportError:          # Python 3.10 ve öncesi
        try:
            import tomli as tomllib
        except ImportError:
            print("! secrets.toml found but Python < 3.11 cannot read it — use environment variables instead")
            return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception as ex:
        print(f"! could not read {path}: {type(ex).__name__}")
        return {}


def configure():
    """Uygulamanın _boot_config() ile aynı ayarlar: kalıcı depo, e-posta, push, veri anahtarları."""
    sec = _load_secrets()
    env = os.environ.get
    store = dict(sec.get("pulse_store") or {})
    store.setdefault("repo", env("PULSE_STORE_REPO"))
    store.setdefault("token", env("PULSE_STORE_TOKEN"))
    mail = dict(sec.get("pulse_mail") or {})
    mail.setdefault("user", env("PULSE_MAIL_USER"))
    mail.setdefault("app_password", env("PULSE_MAIL_APP_PASSWORD"))
    push = dict(sec.get("pulse_push") or {})
    url = sec.get("PULSE_URL") or (sec.get("pulse_app") or {}).get("url") or env("PULSE_URL") or ""
    bk.configure({"store": store, "mail": mail, "push": push, "app_url": url})
    uw = sec.get("UNUSUAL_WHALES_TOKEN") or sec.get("UW_TOKEN") or (sec.get("unusual_whales") or {}).get("token")
    for k, v in (("FINNHUB_API_KEY", sec.get("FINNHUB_API_KEY")), ("UNUSUAL_WHALES_TOKEN", uw),
                 ("X_BEARER_TOKEN", sec.get("X_BEARER_TOKEN") or sec.get("TWITTER_BEARER_TOKEN")),
                 ("REDDIT_CLIENT_ID", sec.get("REDDIT_CLIENT_ID")),
                 ("REDDIT_CLIENT_SECRET", sec.get("REDDIT_CLIENT_SECRET")),
                 ("ALPHAVANTAGE_API_KEY", sec.get("ALPHAVANTAGE_API_KEY")),
                 ("BRAVE_SEARCH_KEY", sec.get("BRAVE_SEARCH_KEY"))):
        if v and not os.environ.get(k):
            os.environ[k] = str(v)
    return {"store": bk.store_mode(), "mail": bk.mail_ready(), "url": url or "—"}


def status_line():
    st_ = bk.store_status()
    w = bk.worker_info()
    repo = " (%s)" % st_["repo"] if st_.get("repo") else ""
    beat = " · last heartbeat %d s ago" % int(w["age"]) if w.get("ts") else ""
    return ("Pulse worker v%s · data folder %s · storage %s%s · shared mode %s%s"
            % (WORKER_VERSION, bk.DATA_DIR, st_["mode"], repo, "ON" if bk.SHARED else "OFF", beat))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    info = configure()
    if not bk.SHARED:
        print("! PULSE_SHARED is off — the worker and the app would not see each other's changes. "
              "Start both with PULSE_SHARED=1.")
    print(status_line())
    print(f"  email notifications: {'ready' if info['mail'] else 'not set up'} · app address: {info['url']}")
    try:                                     # v5.8: isteğe bağlı aracı kurum köprüsü (varsayılan kapalı)
        import broker
        if broker.install():
            bc = broker.cfg()
            print(f"  broker bridge ON: {bc['kind']} · demo account “{bc['account']}” · scale {bc['scale']:g} · "
                  f"max. order {bc['max_order']:g} · max. {bc['max_day']} orders/day · "
                  f"{'LIVE port ' + str(bc['port']) if bc['live'] else 'paper port ' + str(bc['port'])}")
    except Exception as ex:
        print(f"! broker bridge not started: {type(ex).__name__}: {ex}")
    if "--check" in argv:
        w = bk.worker_info()
        print(f"  another worker alive: {bool(w.get('alive') and w.get('pid') != os.getpid())}")
        return 0
    w = bk.worker_info()
    if w.get("alive") and w.get("pid") != os.getpid() and w.get("state") != "stopped":
        print(f"! another worker (pid {w.get('pid')}) sent a heartbeat {int(w['age'])} s ago — "
              "two workers are safe (file locks) but pointless. Exiting.")
        return 2
    if "--once" in argv:
        n = bk.monitor_tick(md)
        bk.kv_flush()
        bk.worker_beat({"state": "once"})
        print(f"  one pass done · {n} notifications / trades")
        return 0
    stop = threading.Event()

    def _bye(*_a):
        print("  stopping …")
        stop.set()
    for sig_ in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig_ is not None:
            try:
                signal.signal(sig_, _bye)
            except (ValueError, OSError):
                pass
    print("  running — bots every 15 minutes, stop-loss / take-profit and limit orders every 30 s, "
          "alerts every 2 minutes. Ctrl+C to stop.")
    t0 = time.time()
    bk.run_worker(md, stop=stop)
    print(f"  stopped after {int(time.time() - t0)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
