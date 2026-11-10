"""
========================================================================
 ARKA PLAN KATMANI  (backend.py)  —  v4.0
========================================================================
Streamlit'ten bağımsız yardımcılar (hiçbiri `streamlit` içe aktarmaz; ayarları
app.py `configure()` ile verir, böylece arka plan iş parçacığından çağrılabilir):

  1) Kalıcı depo  — özel bir GitHub deposundaki JSON dosyaları (Contents API).
     Streamlit Community Cloud'da disk her yeniden başlatmada silinir; girişler,
     izleme listesi, alarmlar ve bildirim ayarları burada kalır. Ayar yoksa
     yerel klasöre (.pulse_data) yazılır.
  2) E-posta      — SMTP (Gmail: uygulama şifresiyle). Şifre sıfırlama kodu ve
     isteğe bağlı bildirimler.
  3) Push         — ntfy (telefon / masaüstü bildirimi; hesap gerekmez).
  4) İzleyici     — arka planda fiyat alarmlarını, izleme listesindeki şirketlerin
     bilançolarını ve ekonomik takvim verilerini kontrol edip bildirim yollar.
========================================================================
"""

import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

BACKEND_VERSION = "4.0"

_LOCK = threading.RLock()
CFG = {"store": {}, "mail": {}, "push": {}, "app_url": ""}
DATA_DIR = os.environ.get("PULSE_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                           ".pulse_data")
TZ = "Europe/Berlin"


def configure(cfg):
    """app.py, Streamlit Secrets'tan okuduğu ayarları buraya verir (her çalıştırmada çağrılabilir)."""
    with _LOCK:
        for k in ("store", "mail", "push"):
            v = cfg.get(k) or {}
            CFG[k] = {kk: vv for kk, vv in dict(v).items() if vv not in (None, "")}
        CFG["app_url"] = str(cfg.get("app_url") or CFG.get("app_url") or "").rstrip("/")


# ======================================================================
# 1) Kalıcı depo
# ======================================================================
_KV = {}                  # ad → {"obj", "sha", "loaded", "dirty", "t"}
_STATUS = {"err": "", "last_write": None, "last_read": None}


def store_mode():
    s = CFG["store"]
    return "github" if (s.get("repo") and s.get("token") and requests is not None) else "local"


def store_status():
    """Arayüz için: {'mode', 'ok', 'err', 'last_write'}."""
    return {"mode": store_mode(), "ok": not _STATUS["err"], "err": _STATUS["err"],
            "last_write": _STATUS["last_write"], "repo": CFG["store"].get("repo", "")}


def _gh(method, name, **kw):
    s = CFG["store"]
    d = str(s.get("dir") or "pulse").strip("/")
    url = f"https://api.github.com/repos/{s['repo']}/contents/{d}/{name}.json"
    headers = {"Authorization": f"Bearer {s['token']}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "pulse-dashboard"}
    if method == "GET" and s.get("branch"):
        kw.setdefault("params", {})["ref"] = s["branch"]
    return requests.request(method, url, headers=headers, timeout=12, **kw)


def _local_path(name):
    return os.path.join(DATA_DIR, name + ".json")


def _local_read(name):
    try:
        with open(_local_path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _local_write(name, obj):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = _local_path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, _local_path(name))
        return True
    except OSError:
        return False


def _kv_load(name):
    e = {"obj": None, "sha": None, "loaded": True, "dirty": False, "t": time.time()}
    if store_mode() == "github":
        try:
            r = _gh("GET", name)
            if r.status_code == 200:
                j = r.json()
                e["obj"] = json.loads(base64.b64decode(j.get("content") or "").decode("utf-8") or "null")
                e["sha"] = j.get("sha")
                _STATUS["err"] = ""
                _STATUS["last_read"] = time.time()
            elif r.status_code == 404:
                _STATUS["err"] = ""           # dosya henüz yok (ilk yazışta oluşur)
            elif r.status_code in (401, 403):
                e["loaded"] = False
                _STATUS["err"] = f"GitHub refused the token (HTTP {r.status_code}) — check [pulse_store] in Secrets"
            else:
                e["loaded"] = False
                _STATUS["err"] = f"GitHub answered HTTP {r.status_code}"
        except Exception as ex:      # ağ / JSON
            e["loaded"] = False
            _STATUS["err"] = f"GitHub not reachable ({type(ex).__name__})"
        if not e["loaded"] or e["obj"] is None:
            loc = _local_read(name)
            if loc is not None and e["obj"] is None:
                e["obj"] = loc
    else:
        e["obj"] = _local_read(name)
    _KV[name] = e
    return e


def kv_get(name, default=None):
    """Depodaki nesnenin kopyası (yoksa default)."""
    with _LOCK:
        e = _KV.get(name)
        if e is None or (not e["loaded"] and time.time() - e["t"] > 45):
            e = _kv_load(name)
        return copy.deepcopy(e["obj"]) if e["obj"] is not None else default


def kv_loaded(name):
    """GitHub deposundan okuma başarılı mı? (False: ağ / yetki hatası — içerik bilinmiyor)"""
    with _LOCK:
        e = _KV.get(name)
        if e is None or (not e["loaded"] and time.time() - e["t"] > 45):
            e = _kv_load(name)
        return bool(e["loaded"])


def _gh_put(name, obj, sha):
    """Kilit tutulmadan çağrılır (ağ isteği). Döner: (ok, yeni_sha)."""
    body = {"message": f"pulse: update {name}",
            "content": base64.b64encode(json.dumps(obj, separators=(",", ":")).encode("utf-8")).decode()}
    if CFG["store"].get("branch"):
        body["branch"] = CFG["store"]["branch"]
    for attempt in range(2):
        if sha:
            body["sha"] = sha
        r = _gh("PUT", name, json=body)
        if r.status_code in (200, 201):
            _STATUS["err"] = ""
            _STATUS["last_write"] = time.time()
            return True, ((r.json() or {}).get("content") or {}).get("sha")
        if r.status_code in (409, 422) and attempt == 0:      # sha eskimiş → güncel sha ile yeniden
            g = _gh("GET", name)
            sha = g.json().get("sha") if g.status_code == 200 else None
            body.pop("sha", None)
            continue
        _STATUS["err"] = (f"GitHub refused the write (HTTP {r.status_code}) — the token needs 'Contents: read and "
                          f"write' on the data repository" if r.status_code in (401, 403, 404)
                          else f"GitHub write failed (HTTP {r.status_code})")
        return False, sha
    return False, sha


def _push_one(name):
    with _LOCK:
        e = _KV.get(name)
        if not e or not e.get("dirty"):
            return True
        obj, sha, stamp = copy.deepcopy(e["obj"]), e.get("sha"), e["t"]
    try:
        ok, new_sha = _gh_put(name, obj, sha)
    except Exception as ex:
        _STATUS["err"] = f"GitHub not reachable ({type(ex).__name__})"
        return False
    with _LOCK:
        e = _KV.get(name)
        if e is not None:
            e["sha"] = new_sha
            if ok and e["t"] == stamp:          # yazım sırasında değişmediyse temiz
                e["dirty"] = False
    return ok


def kv_put(name, obj, sync=True):
    """Nesneyi kaydeder. sync=True: hemen GitHub'a (şifre değişikliği gibi kritik yazımlar);
    sync=False: bellekte + yerelde, GitHub'a arka planda (bkz. kv_flush).
    Döner: 'github' | 'queued' | 'local' | 'memory' (hiçbir yere yazılamadıysa)."""
    with _LOCK:
        e = _KV.get(name) or {"obj": None, "sha": None, "loaded": True, "dirty": False, "t": time.time()}
        e["obj"] = copy.deepcopy(obj)
        e["t"] = time.time()
        _KV[name] = e
        loc = _local_write(name, e["obj"])
        gh = store_mode() == "github"
        if gh:
            e["dirty"] = True
    if gh:
        if not sync:
            return "queued"
        if _push_one(name):
            return "github"
    return "local" if loc else "memory"


_FLUSH = {"t": 0.0}


def kv_flush():
    """Bekleyen (dirty) nesneleri GitHub'a yazar."""
    if store_mode() != "github":
        return
    with _LOCK:
        names = [n for n, e in _KV.items() if e.get("dirty")]
    for n in names:
        _push_one(n)


def kv_flush_async(min_gap=30):
    """Arayüz iş parçacığını bekletmeden yaz (en fazla min_gap saniyede bir)."""
    if store_mode() != "github" or time.time() - _FLUSH["t"] < min_gap:
        return
    with _LOCK:
        if not any(e.get("dirty") for e in _KV.values()):
            return
    _FLUSH["t"] = time.time()
    threading.Thread(target=kv_flush, name="pulse-flush", daemon=True).start()


# ======================================================================
# 2) E-posta (SMTP · Gmail uygulama şifresi)
# ======================================================================
def mail_ready():
    m = CFG["mail"]
    return bool(m.get("user") and m.get("app_password"))


def send_mail(to, subject, text, html=None):
    """(ok, hata). Gmail: [pulse_mail] user = "…@gmail.com", app_password = "16 haneli uygulama şifresi"."""
    if not mail_ready():
        return False, "Email sending is not set up"
    m = CFG["mail"]
    msg = EmailMessage()
    msg["From"] = f'{m.get("name") or "Pulse"} <{m["user"]}>'
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    host, port = str(m.get("host") or "smtp.gmail.com"), int(m.get("port") or 465)
    pw = str(m["app_password"]).replace(" ", "")
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as s:
                s.login(m["user"], pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ctx)
                s.login(m["user"], pw)
                s.send_message(msg)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "The mail server rejected the login — check the Gmail app password in Secrets"
    except Exception as ex:
        return False, f"Email could not be sent ({type(ex).__name__})"


# ---- tek kullanımlık kodlar (şifre sıfırlama) --------------------------
_OTP = {}
OTP_TTL = 15 * 60


def otp_issue(email):
    """6 haneli kod üretir. Döner (kod, '') ya da (None, 'wait:<sn>') — aynı adrese 60 sn'de bir."""
    now = time.time()
    with _LOCK:
        for k in [k for k, v in _OTP.items() if v["exp"] < now]:
            _OTP.pop(k, None)
        cur = _OTP.get(email)
        if cur and now - cur["sent"] < 60:
            return None, f"wait:{int(60 - (now - cur['sent']))}"
        code = f"{secrets.randbelow(10 ** 6):06d}"
        salt = secrets.token_hex(8)
        _OTP[email] = {"h": hashlib.sha256((salt + code).encode()).hexdigest(), "salt": salt,
                       "exp": now + OTP_TTL, "tries": 0, "sent": now}
        return code, ""


def otp_cancel(email):
    with _LOCK:
        _OTP.pop(email, None)


def otp_check(email, code):
    """'ok' | 'bad' | 'expired' | 'locked' (5 yanlış denemeden sonra kod geçersiz)."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    with _LOCK:
        e = _OTP.get(email)
        if not e or e["exp"] < time.time():
            _OTP.pop(email, None)
            return "expired"
        if e["tries"] >= 5:
            _OTP.pop(email, None)
            return "locked"
        if hmac.compare_digest(hashlib.sha256((e["salt"] + code).encode()).hexdigest(), e["h"]):
            _OTP.pop(email, None)
            return "ok"
        e["tries"] += 1
        return "bad"


# ======================================================================
# 3) Push (ntfy)
# ======================================================================
def new_topic():
    return "pulse-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:16]


def push_server():
    return str(CFG["push"].get("server") or "https://ntfy.sh").rstrip("/")


def send_push(topic, title, body, url=None, tags=None, priority=3):
    """ntfy'ye JSON ile yayınlar (başlıkta Unicode sorun çıkarmaz). (ok, hata)."""
    if requests is None or not topic:
        return False, "Push is not available"
    payload = {"topic": str(topic), "title": str(title)[:180], "message": str(body)[:3500],
               "priority": int(priority)}
    if tags:
        payload["tags"] = list(tags)
    if url:
        payload["click"] = url
    headers = {}
    if CFG["push"].get("token"):
        headers["Authorization"] = "Bearer " + str(CFG["push"]["token"])
    try:
        r = requests.post(push_server(), json=payload, headers=headers, timeout=10)
        return (r.status_code < 300), ("" if r.status_code < 300 else f"ntfy answered HTTP {r.status_code}")
    except Exception as ex:
        return False, f"ntfy not reachable ({type(ex).__name__})"


# ======================================================================
# Kullanıcı profilleri (izleme listesi, alarmlar, bildirim ayarları …)
# ======================================================================
NOTIFY_DEFAULT = {"on": True, "push": False, "topic": "", "email": False, "browser": True,
                  "price": True, "earn_up": True, "earn_res": True, "macro": True, "macro_impact": "High"}


def notify_prefs(prof):
    n = dict(NOTIFY_DEFAULT)
    n.update({k: v for k, v in ((prof or {}).get("notify") or {}).items() if k in NOTIFY_DEFAULT})
    return n


def profiles():
    return (kv_get("profiles") or {}).get("users") or {}


def profile_get(email):
    return profiles().get(str(email or "").lower()) or {}


def profile_put(email, prof):
    """Profili kaydeder (bellek + yerel hemen; GitHub'a arka planda)."""
    email = str(email or "").lower()
    if not email:
        return
    with _LOCK:
        allp = kv_get("profiles") or {"v": 1, "users": {}}
        allp.setdefault("users", {})[email] = prof
        kv_put("profiles", allp, sync=False)


def profile_remove(email):
    with _LOCK:
        allp = kv_get("profiles") or {"v": 1, "users": {}}
        if allp.get("users", {}).pop(str(email or "").lower(), None) is not None:
            kv_put("profiles", allp, sync=False)


# ======================================================================
# Bildirim kutusu + gönderim
# ======================================================================
_INBOX = {}               # e-posta → [{id, ts, kind, sym, title, body}]
_SEQ = [int(time.time() * 1000)]


def _state():
    s = kv_get("state") or {}
    s.setdefault("sent", {})
    s.setdefault("earn_seen", {})
    s.setdefault("earn_est", {})
    return s


def _state_save(s):
    now = time.time()
    s["sent"] = {k: v for k, v in s["sent"].items() if now - float(v) < 45 * 86400}
    kv_put("state", s, sync=False)


def inbox_since(email, last_id=0):
    with _LOCK:
        return [dict(x) for x in _INBOX.get(str(email or "").lower(), []) if x["id"] > int(last_id or 0)]


def deliver(email, prefs, kind, title, body, sym=None, tags=None, priority=3):
    """Kutusuna koyar; ayara göre push ve e-posta yollar. Döner: kullanılan kanallar."""
    email = str(email or "").lower()
    used = ["inbox"]
    with _LOCK:
        _SEQ[0] += 1
        item = {"id": _SEQ[0], "ts": time.time(), "kind": kind, "sym": sym or "", "title": title, "body": body}
        box = _INBOX.setdefault(email, [])
        box.append(item)
        del box[:-100]
    url = CFG.get("app_url") or None
    if url and sym:
        url = f"{url}/?sec=Markets&sym={sym}"
    if prefs.get("push") and prefs.get("topic"):
        ok, _ = send_push(prefs["topic"], title, body, url=url, tags=tags, priority=priority)
        if ok:
            used.append("push")
    if prefs.get("email") and mail_ready():
        ok, _ = send_mail(email, f"Pulse · {title}", body + (f"\n\nOpen Pulse: {url}" if url else ""))
        if ok:
            used.append("email")
    return used


def notify_once(state, key, email, prefs, kind, title, body, **kw):
    """Aynı olay (key) için yalnızca bir kez bildirim."""
    if key in state["sent"]:
        return False
    state["sent"][key] = time.time()
    state["_dirty"] = True
    deliver(email, prefs, kind, title, body, **kw)
    return True


# ======================================================================
# 4) İzleyici
# ======================================================================
_LASTPX = {}
_MON = {"thread": None, "ticks": 0, "last": None, "err": ""}
TICK_SEC = 120


def _fmt(x, d=2):
    try:
        return f"{float(x):,.{d}f}"
    except (TypeError, ValueError):
        return "—"


def _money(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    for div, s in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= div:
            return f"{x / div:,.2f}{s}"
    return f"{x:,.0f}"


COND_TXT = {"above": "is above", "below": "is below", "cross_up": "crossed above", "cross_dn": "crossed below",
            "cross": "crossed"}


def alert_hit(a, last, prev):
    """Alarm koşulu: last = son fiyat, prev = önceki gözlem (yoksa önceki kapanış)."""
    try:
        p = float(a.get("price"))
        last, prev = float(last), float(prev)
    except (TypeError, ValueError):
        return False
    if p != p or last != last or prev != prev:
        return False
    cond = a.get("cond", "cross")
    if cond == "above":
        return last >= p
    if cond == "below":
        return last <= p
    if cond == "cross_up":
        return prev < p <= last
    if cond == "cross_dn":
        return prev > p >= last
    return (prev < p <= last) or (prev > p >= last)


def check_prices(md, state, email, prof, prefs):
    alerts = prof.get("alerts") or {}
    syms = [s for s, lst in alerts.items() if any(not a.get("triggered") for a in (lst or []))]
    if not syms or not prefs.get("price"):
        return 0
    quotes = md.get_quotes(syms[:60])
    n = 0
    for s in syms[:60]:
        q = quotes.get(s)
        if not q or q.get("src") != "real":        # örnek (mock) fiyatla alarm çalmaz
            continue
        last = q["last"]
        prev = _LASTPX.get((email, s), q.get("prev"))
        _LASTPX[(email, s)] = last
        for a in alerts.get(s) or []:
            if a.get("triggered"):
                continue
            if alert_hit(a, last, prev):
                key = f"px:{email}:{s}:{a.get('id') or ''}:{a.get('cond')}:{a.get('price')}"
                if notify_once(state, key, email, prefs, "price",
                               f"{s}: price {COND_TXT.get(a.get('cond'), 'crossed')} {_fmt(a.get('price'))}",
                               f"{s} is at {_fmt(last)} ({q.get('change_pct', 0):+.2f}% today). "
                               f"Your alert: price {COND_TXT.get(a.get('cond'), 'crosses')} {_fmt(a.get('price'))}.",
                               sym=s, tags=["bell"], priority=4):
                    n += 1
    return n


WHEN_TXT = {"bmo": "before the market opens", "amc": "after the market closes", "": "time not announced"}


def earnings_summary(sym, last):
    """Bilanço açıklandıktan sonra tek paragraflık özet (bildirim ve arayüz için)."""
    if not last:
        return ""
    bits = []
    v = last.get("verdict")
    if last.get("eps") is not None:
        s = f"EPS {_fmt(last['eps'])}"
        if last.get("eps_est") is not None:
            s += f" vs {_fmt(last['eps_est'])} expected"
            if last.get("surprise_pct") is not None:
                s += f" ({last['surprise_pct']:+.1f}%)"
        if last.get("eps_yoy") is not None:
            s += f", {last['eps_yoy']:+.0f}% YoY"
        bits.append(s)
    if last.get("rev") is not None:
        s = f"Revenue {_money(last['rev'])}"
        if last.get("rev_est") is not None and last["rev_est"]:
            s += f" vs {_money(last['rev_est'])} expected ({(last['rev'] / last['rev_est'] - 1) * 100:+.1f}%)"
        if last.get("rev_yoy") is not None:
            s += f", {last['rev_yoy']:+.0f}% YoY"
        bits.append(s)
    if last.get("ni_adj") is not None and last.get("ni_est") is not None:
        bits.append(f"Net income {_money(last['ni_adj'])} vs {_money(last['ni_est'])} expected")
    elif last.get("ni") is not None:
        bits.append(f"Net income {_money(last['ni'])}")
    if last.get("reaction_pct") is not None:
        bits.append(f"Stock {last['reaction_pct']:+.1f}% since the report")
    head = {"Beat": "BEAT — results above expectations", "Miss": "MISS — results below expectations",
            "In line": "IN LINE with expectations"}.get(v, "Results published")
    return head + ". " + " · ".join(bits) + ("." if bits else "")


def check_earnings(md, state, email, prof, prefs):
    wl = [s for s in (prof.get("watchlist") or []) if s and not any(c in s for c in "=^") and
          not s.endswith("-USD")][:40]
    if not wl or not (prefs.get("earn_up") or prefs.get("earn_res")):
        return 0
    n = 0
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    for s in wl:
        try:
            info = md.get_earnings_info(s)
        except Exception:
            continue
        if not info or info.get("src") != "real":
            continue
        nx, last = info.get("next"), info.get("last")
        if nx and nx.get("date") and prefs.get("earn_up"):
            days = (pd.Timestamp(nx["date"]) - today).days
            est = []
            if nx.get("eps_est") is not None:
                est.append(f"EPS expected {_fmt(nx['eps_est'])}"
                           + (f" ({nx['n']} analysts)" if nx.get("n") else ""))
            if nx.get("ni_est") is not None:
                est.append(f"net income expected {_money(nx['ni_est'])}")
            if nx.get("rev_est") is not None:
                est.append(f"revenue expected {_money(nx['rev_est'])}")
            when = WHEN_TXT.get(nx.get("when") or "", "")
            dtxt = pd.Timestamp(nx["date"]).strftime("%a, %b %d")
            body = (f"{s} reports {nx.get('period') or 'quarterly results'} on {dtxt}, {when}"
                    + ("" if nx.get("confirmed") else " (date not confirmed by the company yet)") + ". "
                    + ("; ".join(est).capitalize() + "." if est else ""))
            if days == 0:
                if notify_once(state, f"eu0:{email}:{s}:{nx['date']}", email, prefs, "earn_up",
                               f"{s} reports earnings today", body, sym=s, tags=["calendar"], priority=4):
                    n += 1
            elif 0 < days <= 5:
                if notify_once(state, f"eu5:{email}:{s}:{nx['date']}", email, prefs, "earn_up",
                               f"{s} reports earnings in {days} day{'s' if days != 1 else ''}", body, sym=s,
                               tags=["calendar"]):
                    n += 1
            if 0 <= days <= 7:        # açıklanmadan önceki beklentiler saklanır → sonuçla karşılaştırılır
                snap = {k: nx.get(k) for k in ("eps_est", "rev_est", "ni_est", "n", "date", "period_end")}
                if state["earn_est"].get(s) != snap:
                    state["earn_est"][s] = snap
                    state["_dirty"] = True
        if last and last.get("period_end") and last.get("eps") is not None:
            pe = str(last["period_end"])
            seen = state["earn_seen"].get(s)
            fresh = False
            if seen is None:
                rd = last.get("date")
                fresh = bool(rd) and 0 <= (today - pd.Timestamp(rd)).days <= 2
            elif pe > seen:
                fresh = True
            if seen != pe and (seen is None or pe > seen):
                state["earn_seen"][s] = pe
                state["_dirty"] = True
            if fresh and prefs.get("earn_res"):
                snap = state["earn_est"].get(s) or {}
                l2 = dict(last)
                for k in ("rev_est", "ni_est"):
                    if l2.get(k) is None and snap.get(k) is not None:
                        l2[k] = snap[k]
                v = l2.get("verdict") or "Results"
                tag = {"Beat": ["white_check_mark"], "Miss": ["x"]}.get(v, ["bar_chart"])
                if notify_once(state, f"er:{email}:{s}:{pe}", email, prefs, "earn_res",
                               f"{s} earnings: {v.upper()}", earnings_summary(s, l2), sym=s, tags=tag, priority=4):
                    n += 1
    return n


def check_macro(md, state, email, prof, prefs):
    if not prefs.get("macro"):
        return 0
    ccys = prof.get("cal_ccy")
    try:
        rows = md.get_calendar_rows("Today", prefs.get("macro_impact") or "High", ccys if ccys else None)
    except Exception:
        return 0
    now = pd.Timestamp.now(tz=md.TZ)
    n = 0
    for r in rows:
        if r.get("src") != "real" or r.get("state") != "released":
            continue
        if (now - r["dt"]) > pd.Timedelta(hours=3) or r["dt"] > now:
            continue
        ev = r.get("eval")
        word = {"better": "better than forecast", "worse": "worse than forecast", "inline": "in line with forecast"}.get(ev, "")
        body = (f"{r.get('cur', '')} {r['event']}: actual {r.get('actual')}"
                + (f" vs forecast {r.get('forecast')}" if r.get("forecast") not in (None, "", "—") else "")
                + (f", previous {r.get('previous')}" if r.get("previous") not in (None, "", "—") else "")
                + (f" — {word}" if word else "") + ".")
        key = f"mc:{email}:{r['dt'].strftime('%Y-%m-%d %H:%M')}:{r.get('cur')}:{r['event']}"
        if notify_once(state, key, email, prefs, "macro", f"{r.get('cur', '')} {r['event']}: {r.get('actual')}",
                       body, tags=["chart_with_upwards_trend"]):
            n += 1
    return n


def monitor_tick(md):
    """Tüm kullanıcılar için bir tur. Döner: gönderilen bildirim sayısı."""
    state = _state()
    total = 0
    for email, prof in profiles().items():
        prefs = notify_prefs(prof)
        if not prefs.get("on"):
            continue
        for fn in (check_prices, check_earnings, check_macro):
            try:
                total += fn(md, state, email, prof, prefs)
            except Exception as ex:      # bir kaynak bozulsa da diğerleri çalışsın
                _MON["err"] = f"{fn.__name__}: {type(ex).__name__}: {ex}"[:200]
    if state.pop("_dirty", False):
        _state_save(state)
    _MON["ticks"] += 1
    _MON["last"] = time.time()
    return total


def _loop(md):
    time.sleep(20)
    while True:
        try:
            monitor_tick(md)
        except Exception as ex:  # pragma: no cover
            _MON["err"] = f"{type(ex).__name__}: {ex}"[:200]
        try:
            kv_flush()
        except Exception:  # pragma: no cover
            pass
        time.sleep(TICK_SEC)


def start_monitor(md):
    """Arka plan izleyicisini (bir kez) başlatır."""
    if os.environ.get("PULSE_NO_MONITOR"):
        return False
    with _LOCK:
        t = _MON["thread"]
        if t is not None and t.is_alive():
            return True
        t = threading.Thread(target=_loop, args=(md,), name="pulse-monitor", daemon=True)
        _MON["thread"] = t
        t.start()
        return True


def monitor_status():
    t = _MON["thread"]
    return {"running": bool(t is not None and t.is_alive()), "ticks": _MON["ticks"], "last": _MON["last"],
            "err": _MON["err"]}
