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

BACKEND_VERSION = "4.5"

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
                  "price": True, "earn_up": True, "earn_res": True, "macro": True, "macro_impact": "High",
                  "ai": True, "hype": True, "bot": True}


def notify_prefs(prof):
    n = dict(NOTIFY_DEFAULT)
    n.update({k: v for k, v in ((prof or {}).get("notify") or {}).items() if k in NOTIFY_DEFAULT})
    return n


def profiles():
    return (kv_get("profiles") or {}).get("users") or {}


def profile_get(email):
    return profiles().get(str(email or "").lower()) or {}


def profile_put(email, prof, sync=False):
    """Profili kaydeder (bellek + yerel hemen; GitHub'a arka planda, sync=True ise hemen)."""
    email = str(email or "").lower()
    if not email:
        return
    with _LOCK:
        allp = kv_get("profiles") or {"v": 1, "users": {}}
        allp.setdefault("users", {})[email] = prof
    return kv_put("profiles", allp, sync=sync)


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
    """Kutusuna koyar; ayara göre push ve e-posta yollar. Döner: kullanılan kanallar.
    prefs['_inbox'] = False: olay sayfaya zaten eklendi, yalnızca push / e-posta gönder."""
    email = str(email or "").lower()
    used = []
    if prefs.get("_inbox", True):
        used.append("inbox")
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


# ======================================================================
# v4.3 — Demo hesabı (kâğıt üzerinde işlem, gerçek fiyatlarla) + otomatik işlem botları
#   · Hesap "demo" deposunda tutulur (profilden ayrı: arka plandaki bot ile açık sayfa birbirini ezmez).
#   · Botlar 15 dakikalık her mum kapanışından sonra bir kez çalışır: önce açık pozisyonlar (stop / TP / iz süren
#     stop / süre), sonra yeni alımlar. Veri çekme kilidin dışında, hesap değişikliği kilidin içinde yapılır.
#   · Örnek (mock) fiyatla hiçbir zaman işlem yapılmaz.
# ======================================================================
DEMO_STARTS = (10000, 25000, 50000, 100000, 500000)
DEMO_CCYS = ("USD", "EUR")
DEMO_WATCH = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD"]
DEMO_WATCH_MAX = 40
BOT_SLOT = 900               # botların kontrol aralığı: 15 dakika
BOT_LAG = 75                 # mum kapandıktan sonra verinin gelmesi için bekleme (sn)
BOT_HOURS_ONLY = True        # yalnızca ABD seansı açıkken alım (09:30–16:00 New York, hafta içi)
BOT_BAR_MAX_AGE = 45 * 60    # alım için son 15 dk mumunun en fazla yaşı
BOT_MAX = 8
_EUR_SFX = (".DE", ".F", ".PA", ".AS", ".MI", ".MC", ".BR", ".VI", ".HE", ".LS", ".IR")
_DLOCK = threading.RLock()


def _engine():
    import engine
    return engine


def inst_ccy(sym):
    """Enstrümanın işlem para birimi: USD / EUR; desteklenmiyorsa None (FX çiftleri, endeksler, diğer borsalar)."""
    s = str(sym or "").upper().strip()
    if not s or "=" in s or s.startswith("^"):
        return None
    if s.endswith("-USD"):
        return "USD"
    if s.endswith(_EUR_SFX):
        return "EUR"
    if "." in s:
        return None
    return "USD"


def fx_mult(acct_ccy, inst, eurusd):
    """Enstrüman para birimi → hesap para birimi çarpanı (EURUSD = 1 EUR kaç USD)."""
    if inst is None:
        return None
    if inst == acct_ccy:
        return 1.0
    if not eurusd or eurusd <= 0:
        return None
    return (1.0 / eurusd) if (inst == "USD" and acct_ccy == "EUR") else float(eurusd)


def demo_new(start=25000, ccy="USD", watch=None, bots=None):
    start = float(start if start in DEMO_STARTS else 25000)
    return {"v": 1, "start": start, "ccy": ccy if ccy in DEMO_CCYS else "USD", "cash": start, "pos": {},
            "trades": [], "eq": [[time.time(), start]], "watch": list(watch if watch is not None else DEMO_WATCH),
            "bots": list(bots or []), "log": [], "seq": 0, "created": time.time(), "fx": None, "bot_slot": None}


def _demo_all():
    d = kv_get("demo")
    return d if isinstance(d, dict) and isinstance(d.get("users"), dict) else {"v": 1, "users": {}}


def demo_get(email):
    """Hesabın kopyası; yoksa varsayılan (25.000 $) hesap."""
    a = _demo_all()["users"].get(str(email or "").lower())
    return a if isinstance(a, dict) and "cash" in a else demo_new()


def demo_put(email, acct, sync=False):
    email = str(email or "").lower()
    if not email:
        return False
    with _DLOCK:
        allp = _demo_all()
        allp["users"][email] = acct
        return kv_put("demo", allp, sync=sync)


def demo_edit(email, fn):
    """Hesabı kilit altında okur, fn(acct) ile değiştirir, kaydeder. fn'in döndürdüğünü döndürür."""
    with _DLOCK:
        acct = demo_get(email)
        res = fn(acct)
        demo_put(email, acct)
        return res


def demo_reset(email, start, ccy, keep=True):
    """Yeni başlangıç tutarı / para birimi: hesap sıfırlanır; izleme listesi ve botlar (kapalı olarak) kalır."""
    def run(acct):
        bots = []
        for b in (acct.get("bots") or []) if keep else []:
            b = dict(b, on=False, last=None, cool={})
            bots.append(b)
        new = demo_new(start, ccy, acct.get("watch") if keep else None, bots)
        acct.clear()
        acct.update(new)
        return True
    return demo_edit(email, run)


def demo_trade(acct, sym, side, qty, price, fxm, owner="manual", reason="", plan=None, ts=None, bot=""):
    """Bir emri hesaba işler (anında, verilen fiyattan). Döner: (ok, mesaj, işlem kaydı)."""
    try:
        qty, price, fxm = float(qty), float(price), float(fxm)
    except (TypeError, ValueError):
        return False, "Quantity and price must be numbers.", None
    if not (qty > 0 and price > 0 and fxm > 0):
        return False, "Quantity and price must be positive.", None
    ts = float(ts or time.time())
    key = f"{sym}|{owner}"
    pos = acct["pos"].get(key)
    amt = qty * price * fxm
    pnl = None
    if side == "buy":
        if amt > acct["cash"] + 1e-6:
            return False, "Not enough cash for this order.", None
        if pos:
            pos["entry"] = (pos["entry"] * pos["qty"] + price * qty) / (pos["qty"] + qty)
            pos["qty"] += qty
            pos["cost"] += amt
        else:
            pos = {"sym": sym, "owner": owner, "bot": bot, "qty": qty, "entry": price, "cost": amt, "opened": ts,
                   "last": price}
            acct["pos"][key] = pos
        if plan:
            pos.update({k: plan[k] for k in ("stop", "tp1", "tp2", "atr", "why", "cfg") if k in plan})
            pos.update({"hi": price, "tp1_done": False, "checked": plan.get("checked") or ts})
        acct["cash"] -= amt
    elif side == "sell":
        if not pos or qty > pos["qty"] + 1e-9:
            return False, "You do not hold that many shares.", None
        part = pos["cost"] * qty / pos["qty"]
        pnl = amt - part
        pos["qty"] -= qty
        pos["cost"] -= part
        acct["cash"] += amt
        if pos["qty"] <= 1e-9:
            acct["pos"].pop(key, None)
    else:
        return False, "Unknown order side.", None
    acct["seq"] = int(acct.get("seq") or 0) + 1
    tr = {"id": acct["seq"], "ts": ts, "sym": sym, "side": side, "qty": qty, "px": price, "fx": fxm,
          "amt": round(amt, 2), "owner": owner, "bot": bot, "reason": reason,
          "pnl": (round(pnl, 2) if pnl is not None else None)}
    acct["trades"].append(tr)
    del acct["trades"][:-400]
    return True, "", tr


def demo_value(acct, quotes=None, eurusd=None):
    """Hesap değeri: nakit + pozisyonlar (son fiyatla). quotes: {sym: {'last', 'src'}}."""
    quotes = quotes or {}
    rows, inv, upl = [], 0.0, 0.0
    for key, p in (acct.get("pos") or {}).items():
        q = quotes.get(p["sym"]) or {}
        last = float(q["last"]) if (q.get("src") == "real" and q.get("last")) else float(p.get("last") or p["entry"])
        fxm = fx_mult(acct["ccy"], inst_ccy(p["sym"]), eurusd or acct.get("fx")) or (p["cost"] / max(p["qty"] * p["entry"], 1e-9))
        val = p["qty"] * last * fxm
        pl = val - p["cost"]
        inv += val
        upl += pl
        rows.append({"key": key, "sym": p["sym"], "owner": p["owner"], "bot": p.get("bot") or "", "qty": p["qty"],
                     "entry": p["entry"], "last": last, "value": val, "pnl": pl,
                     "pnl_pct": (pl / p["cost"] * 100) if p["cost"] else 0.0, "stop": p.get("stop"),
                     "tp1": p.get("tp1"), "tp2": p.get("tp2"), "tp1_done": p.get("tp1_done"),
                     "opened": p.get("opened"), "why": p.get("why") or "", "live": q.get("src") == "real"})
    rpl = sum(t["pnl"] for t in acct.get("trades") or [] if t.get("pnl") is not None)
    eq = float(acct["cash"]) + inv
    rows.sort(key=lambda r: -r["value"])
    return {"equity": eq, "cash": float(acct["cash"]), "invested": inv, "upl": upl, "rpl": rpl,
            "total": eq - float(acct["start"]), "total_pct": (eq / float(acct["start"]) - 1) * 100, "rows": rows}


def _eq_point(acct, equity, now, gap=840):
    eq = acct.setdefault("eq", [])
    if not eq or now - eq[-1][0] >= gap:
        eq.append([round(now), round(equity, 2)])
        del eq[:-1500]
    else:
        eq[-1][1] = round(equity, 2)


def bot_new(name, src, universe, cfg=None, flt=None):
    en = _engine()
    return {"id": secrets.token_hex(4), "name": str(name or "Bot").strip()[:40] or "Bot",
            "on": True, "src": "filter" if src == "filter" else "ai",
            "universe": "scan" if universe == "scan" else "demo", "cfg": en.bot_cfg(cfg),
            "flt": flt if (src == "filter" and isinstance(flt, dict)) else None,
            "created": time.time(), "last": None, "cool": {}}


def bot_stats(acct, bot_id, val=None):
    """Botun toplam sonucu: gerçekleşen + açık kâr/zarar, işlem sayısı, isabet oranı, günlük ortalama."""
    sells = [t for t in acct.get("trades") or [] if t.get("owner") == bot_id and t.get("pnl") is not None]
    rpl = sum(t["pnl"] for t in sells)
    rows = [r for r in (val or {}).get("rows", []) if r["owner"] == bot_id]
    upl = sum(r["pnl"] for r in rows)
    b = next((x for x in acct.get("bots") or [] if x["id"] == bot_id), None)
    days = max(1.0, (time.time() - float((b or {}).get("created") or time.time())) / 86400.0)
    wins = sum(1 for t in sells if t["pnl"] > 0)
    return {"rpl": rpl, "upl": upl, "pnl": rpl + upl, "open": len(rows), "value": sum(r["value"] for r in rows),
            "closed": len(sells), "win": (wins / len(sells) * 100) if sells else None,
            "avg_day": (rpl + upl) / days}


def us_session_open(now=None):
    t = pd.Timestamp(now or time.time(), unit="s", tz="UTC").tz_convert("America/New_York")
    return t.weekday() < 5 and (9 * 60 + 30) <= t.hour * 60 + t.minute < 16 * 60


def _bars15(df, after=0.0):
    """15 dk DataFrame → [(epoch, o, h, l, c)], yalnızca `after` sonrasında KAPANMIŞ mumlar."""
    if df is None or not len(df):
        return []
    idx = df.index
    try:
        idx = idx.tz_localize("America/New_York") if idx.tz is None else idx
        ep = [ts.timestamp() for ts in idx]            # çözünürlükten (ns / s) bağımsız
    except Exception:
        return []
    out = []
    now = time.time()
    for i in range(len(df)):
        end = float(ep[i]) + 900.0                     # mumun kapanış anı
        if end <= after or end > now + 5:
            continue
        r = df.iloc[i]
        o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
        if not (o == o and h == h and l == l and c == c):
            continue
        out.append((end, o, h, l, c))
    return out


def _real(df):
    return df is not None and len(df) > 0 and df.attrs.get("src", "real") == "real"


def bots_collect(md, acct):
    """Kilidin DIŞINDA: botların ihtiyacı olan tüm veriyi çeker ve sinyalleri hesaplar."""
    en = _engine()
    bots = [b for b in acct.get("bots") or [] if b.get("on")]
    held = sorted({p["sym"] for p in acct["pos"].values() if p["owner"] != "manual"})
    watch = [s for s in acct.get("watch") or [] if inst_ccy(s)]
    data = {"sig": {}, "skip": {}, "n": {}, "i15": {}, "px": {}, "regime_ok": True, "eurusd": None, "err": {}}
    try:
        q = md.get_quotes(["EURUSD=X"]).get("EURUSD=X") or {}
        if q.get("src") == "real" and q.get("last"):
            data["eurusd"] = float(q["last"])
    except Exception:
        pass
    if bots:
        try:
            data["regime_ok"] = bool(en.ai_regime(md.get_daily_batch(("SPY", "QQQ")), 50).get("ok"))
        except Exception:
            data["regime_ok"] = False
    need15, evals = set(held), {}
    for b in bots:
        try:
            if b["src"] == "ai":
                meta = {}
                if b["universe"] == "scan":
                    cand, _ = en.ai_prefilter(md.get_market_snapshot(), None)
                    syms = [t for t in list(cand["ticker"].head(40)) if inst_ccy(t)] if len(cand) else []
                    meta = cand.set_index("ticker").to_dict("index") if len(cand) else {}
                else:
                    syms = list(watch)
                daily = md.get_daily_batch(tuple(syms)) if syms else {}
                rs = []
                for t in syms:
                    df = daily.get(t)
                    if not _real(df):
                        continue
                    r = en.ai_evaluate(t, df, meta=meta.get(t))
                    if r:
                        rs.append(r)
                        bb = r.get("best")
                        if bb and r.get("ema_ok") and bb.get("state") in ("breakout", "retest"):
                            need15.add(t)
                evals[b["id"]] = ("ai", rs)
                data["n"][b["id"]] = len(rs)
            else:
                f = b.get("flt") or {}
                if b["universe"] == "scan":
                    hist = md.get_universe_history()["hist"]
                else:
                    hist = md.get_daily_batch(tuple(watch)) if watch else {}
                hist = {t: df for t, df in hist.items() if _real(df) and inst_ccy(t)}
                spy = (md.get_daily_batch(("SPY",)) or {}).get("SPY")
                rows = en.scan(hist, f.get("rows") or [], f.get("logic") or "AND", f.get("min"),
                               spy["Close"] if spy is not None else None, None, getattr(md, "NAMES", None))
                evals[b["id"]] = ("filter", rows)
                data["n"][b["id"]] = len(hist)
                need15.update(o["ticker"] for o in rows[:25])
        except Exception as ex:
            data["err"][b["id"]] = f"{type(ex).__name__}: {ex}"[:160]
    if need15:
        try:
            i15 = md.get_intraday_batch(tuple(sorted(need15)))
            data["i15"] = {t: df for t, df in i15.items() if _real(df)}
        except Exception:
            data["i15"] = {}
    for t, df in data["i15"].items():
        try:
            data["px"][t] = float(df["Close"].iloc[-1])
        except Exception:
            pass
    for b in bots:
        kind, rows = evals.get(b["id"], (None, []))
        sig, skip = [], []
        for r in rows:
            t = r["ticker"]
            if kind == "ai":
                bb = r.get("best")
                if bb and t in data["i15"]:
                    en.ai_apply_15m(r, en.confirm_15m(data["i15"][t], bb["level"], bb["kind"]))
                s, why = en.bot_signal_ai(r, b["cfg"], data["regime_ok"])
            else:
                s, why = en.bot_signal_filter(r, b["cfg"])
            if s and t in data["px"]:
                s["entry"] = data["px"][t]            # alım fiyatı: son kapanmış 15 dk mumu
                if s["entry"] <= s["stop"] or s["entry"] >= s["tp1"]:
                    skip.append((t, "price moved out of the plan"))
                    continue
            if s and t not in data["i15"]:
                skip.append((t, "no live 15-minute data"))
                continue
            (sig.append((t, s)) if s else skip.append((t, why)))
        data["sig"][b["id"]] = sig
        data["skip"][b["id"]] = skip[:12]
    return data


def bots_apply(acct, data, now=None):
    """Kilidin İÇİNDE: açık pozisyonları yönetir, yeni alımları yapar. Döner: olay listesi."""
    en = _engine()
    now = float(now or time.time())
    events = []
    if data.get("eurusd"):
        acct["fx"] = data["eurusd"]
    eurusd = data.get("eurusd") or acct.get("fx")
    names = {b["id"]: b["name"] for b in acct.get("bots") or []}

    def log(bot, sym, text):
        acct.setdefault("log", []).append({"ts": round(now), "bot": bot, "sym": sym, "text": text})
        del acct["log"][:-200]

    # 1) çıkışlar
    sells = {}
    for key, p in list(acct["pos"].items()):
        if p["owner"] == "manual" or "stop" not in p:
            continue
        df = data["i15"].get(p["sym"])
        bars = _bars15(df, float(p.get("checked") or p.get("opened") or 0))
        if not bars:
            continue
        p["last"] = bars[-1][4]
        fxm = fx_mult(acct["ccy"], inst_ccy(p["sym"]), eurusd)
        if fxm is None:
            continue
        evs, upd = en.bot_manage(p, bars, p.get("cfg"), now)
        bname = names.get(p["owner"]) or p.get("bot") or "Bot"
        for e in evs:
            ok, _, tr = demo_trade(acct, p["sym"], "sell", float(e["qty"]), float(e["price"]), fxm, p["owner"],
                                   e["reason"], ts=e["ts"], bot=bname)
            if ok:
                events.append({"kind": "sell", "sym": p["sym"], "qty": float(e["qty"]), "price": float(e["price"]),
                               "bot": bname, "reason": e["reason"], "pnl": tr["pnl"]})
                log(bname, p["sym"], f'SELL {e["qty"]:g} @ {e["price"]:.2f} — {e["reason"]} ({tr["pnl"]:+.2f})')
                sells[p["owner"]] = sells.get(p["owner"], 0) + 1
                if "stop" in e["reason"].lower() and tr["pnl"] < 0:
                    for b in acct.get("bots") or []:
                        if b["id"] == p["owner"]:
                            b.setdefault("cool", {})[p["sym"]] = now
        if key in acct["pos"]:
            acct["pos"][key].update({k: upd[k] for k in ("stop", "hi", "tp1_done", "checked")})
    # 2) alımlar
    is_open = (not BOT_HOURS_ONLY) or us_session_open(now)
    for b in acct.get("bots") or []:
        if not b.get("on"):
            continue
        bid, cfg = b["id"], en.bot_cfg(b.get("cfg"))
        buys, note = 0, ""
        if bid in (data.get("err") or {}):
            note = "data error: " + data["err"][bid]
        elif not is_open:
            note = "US market closed — open positions are still watched"
        else:
            cool = b.setdefault("cool", {})
            for t in [t for t, ts_ in cool.items() if now - ts_ > cfg["cooldown_days"] * 86400]:
                cool.pop(t, None)
            for sym, s in data["sig"].get(bid, []):
                have = sum(1 for p in acct["pos"].values() if p["owner"] == bid)
                if have >= cfg["max_pos"]:
                    note = note or f"position limit reached ({cfg['max_pos']})"
                    break
                if f"{sym}|{bid}" in acct["pos"] or sym in cool:
                    continue
                df = data["i15"].get(sym)
                bars = _bars15(df, 0.0)
                if not bars or (BOT_HOURS_ONLY and now - bars[-1][0] > BOT_BAR_MAX_AGE):
                    log(b["name"], sym, "skipped — no fresh 15-minute bar")
                    continue
                fxm = fx_mult(acct["ccy"], inst_ccy(sym), eurusd)
                if fxm is None:
                    log(b["name"], sym, "skipped — EUR/USD rate not available")
                    continue
                eq = demo_value(acct, {k: {"last": v, "src": "real"} for k, v in data["px"].items()}, eurusd)["equity"]
                qty = en.bot_size(eq, acct["cash"], s["entry"], s["stop"], fxm, cfg)
                if qty < 1:
                    log(b["name"], sym, "skipped — not enough cash for one share at this risk")
                    continue
                plan = dict(s, cfg={k: cfg[k] for k in ("trail_atr", "max_days", "tp1_part")}, checked=bars[-1][0])
                ok, msg, tr = demo_trade(acct, sym, "buy", qty, s["entry"], fxm, bid, s["why"], plan=plan, ts=now,
                                         bot=b["name"])
                if ok:
                    buys += 1
                    events.append({"kind": "buy", "sym": sym, "qty": float(qty), "price": float(s["entry"]),
                                   "bot": b["name"], "reason": s["why"], "pnl": None, "stop": s["stop"],
                                   "tp1": s["tp1"]})
                    log(b["name"], sym, f'BUY {qty:g} @ {s["entry"]:.2f} — {s["why"]} · stop {s["stop"]:.2f} · '
                                        f'TP1 {s["tp1"]:.2f}')
            if not buys and not note:
                sk = data["skip"].get(bid) or []
                note = ("no setup passed — e.g. " + "; ".join(f"{t}: {w}" for t, w in sk[:2])) if sk else \
                    "no setup passed the filter"
        b["last"] = {"ts": round(now), "checked": int(data["n"].get(bid, 0)), "buys": buys,
                     "sells": int(sells.get(bid, 0)), "note": note}
    val = demo_value(acct, {k: {"last": v, "src": "real"} for k, v in data["px"].items()}, eurusd)
    _eq_point(acct, val["equity"], now)
    return events


def bots_tick(md, only=None, force=False):
    """Tüm (ya da tek) kullanıcının botlarını çalıştırır — 15 dakikalık dilim başına bir kez. Döner: işlem sayısı."""
    now = time.time()
    slot = int(now // BOT_SLOT)
    if not force and now % BOT_SLOT < BOT_LAG:
        return 0
    n = 0
    for email in list(_demo_all()["users"].keys()):
        if only and email != str(only).lower():
            continue
        acct = demo_get(email)
        active = any(b.get("on") for b in acct.get("bots") or [])
        owned = any(p["owner"] != "manual" for p in acct["pos"].values())
        if not (active or owned) or (not force and acct.get("bot_slot") == slot):
            continue
        try:
            data = bots_collect(md, acct)
        except Exception as ex:
            _MON["err"] = f"bots_collect: {type(ex).__name__}: {ex}"[:200]
            continue

        def run(a):
            if not force and a.get("bot_slot") == slot:
                return []
            a["bot_slot"] = slot
            return bots_apply(a, data, now)
        try:
            events = demo_edit(email, run)
        except Exception as ex:
            _MON["err"] = f"bots_apply: {type(ex).__name__}: {ex}"[:200]
            continue
        _MON["bots_last"] = now
        n += len(events)
        if events:
            try:
                prefs = notify_prefs(profile_get(email))
                if prefs.get("on") and prefs.get("bot"):
                    for e in events:
                        if e["kind"] == "buy":
                            title = f'{e["bot"]}: bought {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}'
                            body = f'{e["reason"]}. Stop {e["stop"]:.2f} · TP1 {e["tp1"]:.2f}. Demo account.'
                        else:
                            title = f'{e["bot"]}: sold {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}'
                            body = f'{e["reason"]}. Result {e["pnl"]:+.2f}. Demo account.'
                        deliver(email, prefs, "bot", title, body, sym=e["sym"],
                                tags=["robot"], priority=3)
            except Exception as ex:
                _MON["err"] = f"bot notify: {type(ex).__name__}: {ex}"[:200]
    return n


_BUZZ = {"i": 0, "last": {}}
BUZZ_PER_TICK = 2            # her turda kaç izleme listesi hissesi taranır (sırayla, kaynaklara yük bindirmeden)


def check_buzz(md, state, users):
    """v4.2: izleme listelerindeki hisselerin haber + topluluk nabzını arka planda sırayla tarar (sayfalar sıcak
    önbellekle açılır) ve hype "Viral" olduğunda isteyen kullanıcılara bir kez haber verir."""
    if not hasattr(md, "get_market_pulse"):
        return 0
    syms = []
    for email, prof, prefs in users:
        for s_ in (prof.get("watchlist") or [])[:40]:
            if s_ and not any(c in s_ for c in "=^") and not s_.endswith("-USD") and s_ not in syms:
                syms.append(s_)
    if not syms:
        return 0
    n = 0
    day = time.strftime("%Y-%m-%d", time.gmtime())
    for _ in range(min(BUZZ_PER_TICK, len(syms))):
        sym = syms[_BUZZ["i"] % len(syms)]
        _BUZZ["i"] += 1
        try:
            mp = md.get_market_pulse(sym)
        except Exception as ex:
            _MON["err"] = f"check_buzz: {type(ex).__name__}: {ex}"[:200]
            continue
        hy = mp.get("hype") or {}
        _BUZZ["last"][sym] = (time.time(), hy.get("score"), (mp.get("overall") or {}).get("label"))
        if hy.get("level") != "Viral":
            continue
        ov = mp.get("overall") or {}
        why = "; ".join(d["text"] for d in (hy.get("drivers") or [])[:3])
        for email, prof, prefs in users:
            if not prefs.get("hype") or sym not in (prof.get("watchlist") or []):
                continue
            if notify_once(state, f"hype:{email}:{sym}:{day}", email, prefs, "hype",
                           f"{sym}: viral buzz (hype {hy.get('score')}/100)",
                           f"{sym} is drawing unusual attention: {why}. Overall sentiment: "
                           f"{ov.get('label', '—')} ({ov.get('score', 0):+.0f}).",
                           sym=sym, tags=["fire"], priority=4):
                n += 1
    return n


def monitor_tick(md):
    """Tüm kullanıcılar için bir tur. Döner: gönderilen bildirim sayısı."""
    state = _state()
    total = 0
    users = []
    for email, prof in profiles().items():
        prefs = notify_prefs(prof)
        if not prefs.get("on"):
            continue
        users.append((email, prof, prefs))
        for fn in (check_prices, check_earnings, check_macro):
            try:
                total += fn(md, state, email, prof, prefs)
            except Exception as ex:      # bir kaynak bozulsa da diğerleri çalışsın
                _MON["err"] = f"{fn.__name__}: {type(ex).__name__}: {ex}"[:200]
    try:
        total += check_buzz(md, state, users)
    except Exception as ex:
        _MON["err"] = f"check_buzz: {type(ex).__name__}: {ex}"[:200]
    try:
        total += bots_tick(md)              # v4.3: otomatik işlem botları (15 dakikada bir)
    except Exception as ex:
        _MON["err"] = f"bots_tick: {type(ex).__name__}: {ex}"[:200]
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
