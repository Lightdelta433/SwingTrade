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
import re
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

BACKEND_VERSION = "5.13"

_LOCK = threading.RLock()
CFG = {"store": {}, "mail": {}, "push": {}, "app_url": ""}
DATA_DIR = os.environ.get("PULSE_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                           ".pulse_data")
TZ = "Europe/Berlin"
# v5.8 — paylaşımlı mod: arayüz ve 7/24 worker AYNI veri klasörünü kullanır (Docker / VPS / ev bilgisayarı).
#   Yerel dosya esas kaynaktır; her okumada dosya değiştiyse yeniden okunur, oku-değiştir-yaz adımları süreçler
#   arası dosya kilidiyle korunur → iki süreç aynı anda işlem yapsa da çift alım / kayıp güncelleme olmaz.
SHARED = str(os.environ.get("PULSE_SHARED") or "").strip().lower() in ("1", "true", "yes", "on")
WORKER_STALE = 180           # sn: daha eski kalp atışı = worker çalışmıyor


def _flock(fh, on):
    """Süreçler arası özel kilit — Linux / macOS: fcntl, Windows: msvcrt (60 sn'ye kadar bekler)."""
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if on else fcntl.LOCK_UN)
        return
    except ImportError:          # pragma: no cover — Windows
        pass
    import msvcrt                # pragma: no cover
    fh.seek(0)
    if not on:
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    for _ in range(600):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.1)
    raise OSError("lock timeout")


class _FileLock:
    """Aynı süreçte iç içe girilebilen kilit; paylaşımlı modda ayrıca süreçler arası dosya kilidi."""

    def __init__(self, name):
        self.name, self.fh, self.depth, self.tl = name, None, 0, threading.RLock()

    def __enter__(self):
        self.tl.acquire()
        if self.depth == 0 and SHARED:
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                self.fh = open(os.path.join(DATA_DIR, "." + self.name + ".lock"), "a+")
                _flock(self.fh, True)
            except OSError:
                if self.fh is not None:
                    try:
                        self.fh.close()
                    except OSError:
                        pass
                self.fh = None
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        if self.depth == 0 and self.fh is not None:
            try:
                _flock(self.fh, False)
            except OSError:
                pass
            try:
                self.fh.close()
            except OSError:
                pass
            self.fh = None
        self.tl.release()
        return False


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


def _local_mtime(name):
    """Dosyanın (değişiklik zamanı, boyut) imzası — paylaşımlı modda başka süreç yazdı mı?"""
    try:
        st_ = os.stat(_local_path(name))
        return (st_.st_mtime_ns, st_.st_size)
    except OSError:
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
    e = {"obj": None, "sha": None, "loaded": True, "dirty": False, "t": time.time(), "mt": None}
    if SHARED and os.path.exists(_local_path(name)):       # v5.8: paylaşımlı modda yerel dosya esas
        e["obj"], e["mt"] = _local_read(name), _local_mtime(name)
        _KV[name] = e
        return e
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
    e["mt"] = _local_mtime(name)
    _KV[name] = e
    return e


def kv_get(name, default=None):
    """Depodaki nesnenin kopyası (yoksa default)."""
    with _LOCK:
        e = _KV.get(name)
        if e is None or (not e["loaded"] and time.time() - e["t"] > 45):
            e = _kv_load(name)
        elif SHARED:                                   # v5.8: başka süreç (worker / arayüz) yazdıysa tazele
            mt = _local_mtime(name)
            if mt is not None and mt != e.get("mt"):
                obj = _local_read(name)
                if obj is not None:
                    e["obj"], e["mt"] = obj, mt
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
        if SHARED:                                     # v5.8: en güncel hâl yerel dosyada
            loc = _local_read(name)
            if loc is not None:
                obj = loc
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
        e["mt"] = _local_mtime(name)
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


_PLOCK = _FileLock("profiles")
_ILOCK = _FileLock("inbox")


def profiles():
    return (kv_get("profiles") or {}).get("users") or {}


def profile_get(email):
    return profiles().get(str(email or "").lower()) or {}


def profile_put(email, prof, sync=False):
    """Profili kaydeder (bellek + yerel hemen; GitHub'a arka planda, sync=True ise hemen)."""
    email = str(email or "").lower()
    if not email:
        return
    with _PLOCK:
        with _LOCK:
            allp = kv_get("profiles") or {"v": 1, "users": {}}
            users = allp.setdefault("users", {})
            prof = dict(prof or {})               # v5.12: Datenlinie (gen) bleibt erhalten — neu nur für ein neues Profil
            prof["gen"] = str(prof.get("gen") or (users.get(email) or {}).get("gen") or secrets.token_hex(4))
            users[email] = prof
        return kv_put("profiles", allp, sync=sync)


def profile_remove(email):
    with _PLOCK:
        allp = kv_get("profiles") or {"v": 1, "users": {}}
        if allp.get("users", {}).pop(str(email or "").lower(), None) is not None:
            kv_put("profiles", allp, sync=False)


# ======================================================================
# v5.13 — Short-Interest-Verlauf dauerhaft (Long Term)
# ======================================================================
#   FINRA-Stichtage und die täglich gemerkte Aktienzahl (Float bzw. Aktien im Umlauf) werden je Symbol gespeichert
#   (mit [pulse_store] auch auf GitHub). So bleibt der Verlauf, falls FINRA einmal nicht antwortet, und „% of float“
#   wird mit jedem Tag genauer (für ETFs gibt Yahoo keinen Verlauf der Aktienzahl).
SI_KV = "shortint"
SI_MAX_SYMS = 60
_SILOCK = threading.RLock()


def si_merge(sym, rows, count=None, day=None, store=True):
    """Neue Short-Interest-Zeilen + heutige Aktienzahl in den gespeicherten Verlauf mischen.
    Döner: (rows sortiert, counts {datum: anzahl}). store=False (Testdaten): nur lesen, nichts speichern."""
    sym = re.sub(r"[^A-Z0-9.^=\-]", "", str(sym or "").upper())[:16]
    if not sym:
        return list(rows or []), {}
    day = day or pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d")
    with _SILOCK:
        allv = kv_get(SI_KV) or {"v": 1, "sym": {}}
        rec = allv.setdefault("sym", {}).get(sym) or {"rows": {}, "cnt": {}}
        rec.setdefault("rows", {})
        rec.setdefault("cnt", {})
        changed = False
        if store:
            for r in rows or []:
                d = str(r.get("date") or "")[:10]
                try:
                    v = [float(r["shares"]), None if r.get("adv") is None else float(r["adv"]),
                         None if r.get("dtc") is None else float(r["dtc"])]
                except (KeyError, TypeError, ValueError):
                    continue
                if len(d) == 10 and rec["rows"].get(d) != v:
                    rec["rows"][d] = v
                    changed = True
            try:
                c_ = float(count) if count else 0.0
            except (TypeError, ValueError):
                c_ = 0.0
            if c_ > 0 and not rec["cnt"].get(day):
                rec["cnt"][day] = c_
                changed = True
        if changed and kv_loaded(SI_KV):        # nie über einen unbekannten (nicht gelesenen) Stand schreiben
            rec["ts"] = time.time()
            allv["sym"][sym] = rec
            if len(allv["sym"]) > SI_MAX_SYMS:
                for k_ in sorted(allv["sym"], key=lambda x: allv["sym"][x].get("ts", 0))[:len(allv["sym"]) - SI_MAX_SYMS]:
                    allv["sym"].pop(k_, None)
            kv_put(SI_KV, allv, sync=False)
    merged = {d: {"date": d, "shares": v[0], "adv": v[1], "dtc": v[2]} for d, v in rec["rows"].items()}
    for r in rows or []:                         # frische Zeilen gelten immer (auch ohne Speicher)
        d = str(r.get("date") or "")[:10]
        if len(d) == 10 and r.get("shares") is not None:
            merged[d] = {"date": d, "shares": r.get("shares"), "adv": r.get("adv"), "dtc": r.get("dtc")}
    return [merged[k] for k in sorted(merged)], dict(rec["cnt"])


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


def _inbox_box(email):
    """Kullanıcının bildirim kutusu — paylaşımlı modda worker'ın ürettikleri de (yerel 'inbox' dosyası)."""
    email = str(email or "").lower()
    if SHARED:
        return list(((_local_read("inbox") or {}).get(email)) or [])
    return list(_INBOX.get(email, []))


def inbox_since(email, last_id=0):
    with _LOCK:
        return [dict(x) for x in _inbox_box(email) if x["id"] > int(last_id or 0)]


def deliver(email, prefs, kind, title, body, sym=None, tags=None, priority=3):
    """Kutusuna koyar; ayara göre push ve e-posta yollar. Döner: kullanılan kanallar.
    prefs['_inbox'] = False: olay sayfaya zaten eklendi, yalnızca push / e-posta gönder."""
    email = str(email or "").lower()
    used = []
    if prefs.get("_inbox", True):
        used.append("inbox")
        with _LOCK:
            _SEQ[0] = max(_SEQ[0] + 1, int(time.time() * 1000))     # süreçler arası da artan kimlik
            item = {"id": _SEQ[0], "ts": time.time(), "kind": kind, "sym": sym or "", "title": title, "body": body}
            if SHARED:                                  # v5.8: worker'ın bildirimleri arayüzde de görünsün
                with _ILOCK:
                    allb = _local_read("inbox") or {}
                    box = allb.setdefault(email, [])
                    # v5.10: iki süreç aynı milisaniyede yazarsa kimlik çakışmasın — dosya kilidi altında en büyüğün +1'i
                    top = max([int(x.get("id", 0) or 0) for b_ in allb.values() for x in b_] + [0])
                    if item["id"] <= top:
                        item["id"] = _SEQ[0] = top + 1
                    box.append(item)
                    del box[:-100]
                    _local_write("inbox", allb)
            else:
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
_DLOCK = _FileLock("demo")        # v5.8: paylaşımlı modda süreçler arası da kilit


def _engine():
    import engine
    return engine


def inst_ccy(sym):
    """Enstrümanın işlem para birimi: USD / EUR; desteklenmiyorsa None (FX çiftleri, endeksler, diğer borsalar)."""
    s = str(sym or "").upper().strip()
    if s.endswith("=F") and len(s) > 2:       # v5.3: emtia vadelileri (altın, gümüş, petrol) — USD, birim fiyatı
        return "USD"
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


DEMO_MAX_ACCTS = 12          # kullanıcı başına en fazla demo hesabı
DEMO_NAME_MAX = 32


def demo_new(start=25000, ccy="USD", watch=None, bots=None, name="Main account", acc_id=None):
    start = float(start if start in DEMO_STARTS else 25000)
    return {"v": 2, "id": acc_id or secrets.token_hex(4), "name": demo_clean_name(name) or "Main account",
            "start": start, "ccy": ccy if ccy in DEMO_CCYS else "USD", "cash": start, "pos": {},
            "trades": [], "eq": [[time.time(), start]], "watch": list(watch if watch is not None else DEMO_WATCH),
            "bots": list(bots or []), "log": [], "seq": 0, "created": time.time(), "fx": None, "bot_slot": None,
            "guard": guard_default(), "pend": []}


def demo_clean_name(name):
    """Hesap adı: boşluklar sadeleşir, kontrol karakterleri atılır, en fazla 32 karakter."""
    s_ = re.sub(r"[\x00-\x1f\x7f]", "", str(name or ""))
    return re.sub(r"\s+", " ", s_).strip()[:DEMO_NAME_MAX]


def _demo_all():
    d = kv_get("demo")
    return d if isinstance(d, dict) and isinstance(d.get("users"), dict) else {"v": 2, "users": {}}


def _demo_user(raw):
    """Kullanıcı kaydı (v2): {'active': id, 'order': [id…], 'accounts': {id: hesap}}.
    v1'deki tek hesap ('cash' alanı doğrudan kayıtta) kayıpsız olarak "Main account" adıyla taşınır."""
    if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict) and raw["accounts"]:
        u = raw
    elif isinstance(raw, dict) and "cash" in raw:
        a = dict(raw)
        a.setdefault("id", "main")            # sabit kimlik: kayıt yazılmadan önceki okumalar da aynı hesabı görür
        a.setdefault("name", "Main account")
        a["v"] = 2
        u = {"active": a["id"], "order": [a["id"]], "accounts": {a["id"]: a}}
    else:
        a = demo_new(acc_id="main")
        u = {"active": a["id"], "order": [a["id"]], "accounts": {a["id"]: a}}
    acc = u["accounts"]
    for k, a in list(acc.items()):            # eksik alanları tamamla (eski kayıtlar)
        a.setdefault("id", k)
        a.setdefault("name", "Account")
        a.setdefault("watch", list(DEMO_WATCH))
        a.setdefault("bots", [])
        a.setdefault("log", [])
        a.setdefault("eq", [[time.time(), a.get("start", 25000)]])
        a.setdefault("guard", guard_default())      # v5.4: her hesapta devre kesici (varsayılan 5.000)
        a.setdefault("pend", [])                    # v5.5: bekleyen limit emirleri
    order = [i for i in (u.get("order") or []) if i in acc]
    order += [i for i in acc if i not in order]
    u["order"] = order
    if u.get("active") not in acc:
        u["active"] = order[0]
    return u


def demo_user(email):
    """Kullanıcının tüm demo hesapları (kopya)."""
    return _demo_user(_demo_all()["users"].get(str(email or "").lower()))


# ---------------------------------------------------------------- v5.12 — Browser-Sicherung (localStorage)
#   Der Server bleibt die Quelle (Bots laufen dort). Der Browser bekommt bei jeder Änderung eine Kopie. Startet
#   Streamlit Cloud neu OHNE dauerhaften Speicher ([pulse_store]), ist der Server für das Konto leer — dann holt die
#   App beim nächsten Login in DIESEM Browser die Kopie zurück. Stammt die Kopie aus einer älteren Datenlinie (Server
#   wurde zurückgesetzt und schon neu benutzt), entscheidet der Nutzer — nichts wird still überschrieben.
BACKUP_VER = 1
BACKUP_MAX = 2_400_000        # Zeichen — passt in jedem Browser (localStorage ≈ 5 MB; Safari zählt 2 Byte je Zeichen)
_PROF_WEIGHT_KEYS = ("watchlist", "journal", "journal_closed", "alerts", "saved_filters", "draws", "bt_saved")


def server_blank(email):
    """True: der Server hat für das Konto weder Demo-Konten noch Einstellungen — und der Speicher wurde
    erfolgreich gelesen (ein GitHub-Lesefehler zählt NICHT als leer, sonst würde echte Daten überschrieben)."""
    email = str(email or "").lower()
    if not email or not (kv_loaded("demo") and kv_loaded("profiles")):
        return False
    return email not in _demo_all()["users"] and not profiles().get(email)


def _acct_pristine(a):
    """Unberührtes Demo-Konto: keine Trades, Positionen, Bots oder offenen Orders, Kasse = Startkapital."""
    try:
        return (isinstance(a, dict) and not a.get("trades") and not a.get("pos") and not a.get("bots")
                and not a.get("pend") and abs(float(a.get("cash") or 0) - float(a.get("start") or 0)) < 0.01)
    except (TypeError, ValueError):
        return False


def demo_blankish(email):
    """True: Speicher gelesen und für das Konto kein Demo-Datensatz — oder nur unberührte Konten."""
    email = str(email or "").lower()
    if not email or not kv_loaded("demo"):
        return False
    raw = _demo_all()["users"].get(email)
    if raw is None:
        return True
    return all(_acct_pristine(a) for a in _demo_user(raw)["accounts"].values())


def backup_weight(u):
    """Wie viel steckt in einem Demo-Datensatz: Konten über das erste hinaus + Trades + Positionen + Bots + Orders."""
    if not isinstance(u, dict) or not isinstance(u.get("accounts"), dict):
        return 0
    acc = [a for a in u["accounts"].values() if isinstance(a, dict)]
    return max(0, len(acc) - 1) + sum(len(a.get("trades") or []) + len(a.get("pos") or {}) +
                                      len(a.get("bots") or []) + len(a.get("pend") or []) for a in acc)


def profile_weight(p):
    """Eigene Inhalte im Profil: Watchlist, Journal, Alarme, gespeicherte Filter, Zeichnungen, Backtests."""
    if not isinstance(p, dict):
        return 0
    return sum(len(p.get(k_) or []) for k_ in _PROF_WEIGHT_KEYS if isinstance(p.get(k_), (list, dict)))


def user_gen(email):
    """v5.12 — Datenlinie des Kontos (zufällige Kennung im Profil). Nach einem Server-Reset ohne dauerhaften
    Speicher entsteht eine neue Linie → so erkennt die App, dass eine Browser-Kopie aus der Zeit davor stammt."""
    return str(profile_get(email).get("gen") or "")


def _server_copy(email):
    """(Demo-Datensatz, Profil, Signatur) des Kontos auf dem Server."""
    email = str(email or "").lower()
    u = _demo_all()["users"].get(email)
    prof = profiles().get(email) or None
    sig = hashlib.sha1(json.dumps({"d": u, "p": prof}, sort_keys=True, separators=(",", ":"),
                                  default=str).encode("utf-8")).hexdigest()
    return u, prof, sig


def _backup_trim(u, keep):
    """Große Listen kürzen, falls die Kopie zu groß für den Browser wird."""
    u = copy.deepcopy(u)
    for a in (u.get("accounts") or {}).values():
        for k_ in ("trades", "eq", "log"):
            if isinstance(a.get(k_), list):
                a[k_] = a[k_][-keep:]
    return u


def backup_blob(email):
    """(kopya, imza, metin) — imza yalnızca içerik değişince değişir; metin None ise kopya çok büyük.
    Enthält nie Passwörter (nur Demo-Konten + Einstellungen)."""
    email = str(email or "").lower()
    u, prof, sig = _server_copy(email)
    blob = {"v": BACKUP_VER, "app": BACKEND_VERSION, "ts": round(time.time()), "email_h": _email_h(email),
            "gen": str((prof or {}).get("gen") or ""), "sig": sig, "demo": u, "profile": prof}
    txt = json.dumps(blob, separators=(",", ":"), default=str)
    for keep in (300, 120, 40):
        if len(txt) <= BACKUP_MAX or not u:
            break
        blob["demo"] = _backup_trim(u, keep)
        txt = json.dumps(blob, separators=(",", ":"), default=str)
    return blob, sig, (txt if len(txt) <= BACKUP_MAX else None)


def _email_h(email):
    return hashlib.sha256(str(email or "").lower().encode("utf-8")).hexdigest()[:16]


def backup_summary(blob):
    """Kısa özet: {'ts','accounts','bots','positions','trades','gen'}."""
    u = (blob or {}).get("demo") or {}
    acc = [a for a in (u.get("accounts") or {}).values() if isinstance(a, dict)]
    return {"ts": (blob or {}).get("ts"), "accounts": len(acc), "bots": sum(len(a.get("bots") or []) for a in acc),
            "positions": sum(len(a.get("pos") or {}) for a in acc),
            "trades": sum(len(a.get("trades") or []) for a in acc), "gen": str((blob or {}).get("gen") or "")}


def server_summary(email):
    """Gleiche Kurzform für den aktuellen Server-Stand (für die Rückfrage)."""
    u, prof, _s = _server_copy(email)
    return backup_summary({"demo": u, "gen": (prof or {}).get("gen")})


def backup_check(email, blob, fresh=False):
    """Browser-Kopie gegen den Server prüfen. Döner: (karar, açıklama)
       'bad' / 'foreign' / 'empty' — unbrauchbar · 'wait' — Speicher gerade nicht lesbar (später nochmal)
       'same' — identisch · 'ok' — der Server ist die gültige, neuere Linie (Kopie wird überschrieben)
       'restore' — Server leer (oder seit Sitzungsbeginn nur unberührt: fresh) → automatisch zurückholen
       'ask' — Kopie aus einer älteren Datenlinie mit eigenen Inhalten → der Nutzer entscheidet."""
    email = str(email or "").lower()
    if not isinstance(blob, dict) or int(blob.get("v") or 0) != BACKUP_VER:
        return "bad", "unknown backup format"
    if blob.get("email_h") and blob["email_h"] != _email_h(email):
        return "foreign", "backup belongs to another account"
    u, prof = blob.get("demo"), blob.get("profile")
    has_demo = isinstance(u, dict) and isinstance(u.get("accounts"), dict) and bool(u["accounts"])
    if not has_demo and not (isinstance(prof, dict) and prof):
        return "empty", "the backup is empty"
    if not (kv_loaded("demo") and kv_loaded("profiles")):
        return "wait", "the data store cannot be read right now"
    su, sp, sig = _server_copy(email)
    if blob.get("sig") and blob["sig"] == sig:
        return "same", "the backup equals the server copy"
    if server_blank(email) or (fresh and demo_blankish(email)):
        return "restore", "the server has no data for this account"
    mine = backup_weight(u) + profile_weight(prof)
    g_bak, g_srv = str(blob.get("gen") or ""), str((sp or {}).get("gen") or "")
    if g_bak and g_srv:
        if g_bak == g_srv:
            return "ok", "same data line — the server copy is the newer one"
        return ("ask", "the backup is from before a server reset") if mine else ("ok", "nothing to bring back")
    srv = backup_weight(su) + profile_weight(sp)          # alte Daten ohne Kennung: nur fragen, wenn mehr drin ist
    return ("ask", "the backup holds more than the server copy") if mine > srv else ("ok", "the server copy is fuller")


def backup_restore(email, blob, force=False, fresh=False):
    """Tarayıcı kopyasını geri yükler. Ohne force nur, wenn backup_check 'restore' sagt (Server leer); force=True
    nach ausdrücklicher Bestätigung des Nutzers. Döner: (ok, mesaj)."""
    email = str(email or "").lower()
    verdict, info = backup_check(email, blob, fresh=fresh)
    if verdict in ("bad", "foreign", "empty", "wait"):
        return False, info
    if verdict == "same":
        return False, info
    if not force and verdict != "restore":
        return False, "the server already has data for this account"
    u, prof = blob.get("demo"), blob.get("profile")
    if isinstance(u, dict) and isinstance(u.get("accounts"), dict) and u["accounts"]:
        with _DLOCK:
            if not force and not (server_blank(email) or (fresh and demo_blankish(email))):
                return False, "the server already has data for this account"
            _demo_save_user(email, _demo_user(copy.deepcopy(u)), sync=True)
    if isinstance(prof, dict) and prof:
        profile_put(email, copy.deepcopy(prof), sync=True)     # gen der Kopie → die alte Datenlinie läuft weiter
    return True, "restored"


def demo_accounts(email):
    """Seçim listesi için: [{'id','name','ccy','start','equity','active','bots'}] (sıralı)."""
    u = demo_user(email)
    out = []
    for i in u["order"]:
        a = u["accounts"][i]
        eq = float((a.get("eq") or [[0, a.get("start", 0)]])[-1][1])
        out.append({"id": i, "name": a.get("name") or "Account", "ccy": a.get("ccy", "USD"),
                    "start": float(a.get("start", 0)), "equity": eq, "active": i == u["active"],
                    "bots": sum(1 for b in a.get("bots") or [] if b.get("on")),
                    "positions": len(a.get("pos") or {})})
    return out


def _demo_save_user(email, u, sync=False):
    email = str(email or "").lower()
    if not email:
        return False
    allp = _demo_all()
    allp["v"] = 2
    allp["users"][email] = u
    return kv_put("demo", allp, sync=sync)


def demo_get(email, acc_id=None):
    """Hesabın kopyası — verilmezse kullanıcının etkin hesabı; hiç yoksa varsayılan (25.000 $) hesap."""
    u = demo_user(email)
    return u["accounts"].get(acc_id or u["active"]) or u["accounts"][u["active"]]


def demo_put(email, acct, sync=False):
    """Hesabı kendi kimliğiyle (acct['id']) kaydeder; diğer hesaplara dokunmaz."""
    email = str(email or "").lower()
    if not email:
        return False
    with _DLOCK:
        u = demo_user(email)
        aid = acct.get("id") or u["active"]
        acct["id"] = aid
        u["accounts"][aid] = acct
        if aid not in u["order"]:
            u["order"].append(aid)
        return _demo_save_user(email, u, sync=sync)


def demo_edit(email, fn, acc_id=None, sync=False):
    """Hesabı (verilmezse etkin hesap) kilit altında okur, fn(acct) ile değiştirir, kaydeder.
    v5.12: sync=True → kalıcı depoya (GitHub) HEMEN yazılır (bot oluşturma / silme / açma-kapama)."""
    with _DLOCK:
        acct = demo_get(email, acc_id)
        res = fn(acct)
        demo_put(email, acct, sync=sync)
        return res


def _name_taken(u, name, skip=None):
    n = name.casefold()
    return any((a.get("name") or "").casefold() == n for i, a in u["accounts"].items() if i != skip)


def demo_create(email, name, start, ccy, watch=None):
    """Yeni demo hesabı açar ve etkin yapar. Döner: (ok, mesaj, hesap kimliği)."""
    name = demo_clean_name(name)
    if not name:
        return False, "Give the account a name.", None
    if start not in DEMO_STARTS or ccy not in DEMO_CCYS:
        return False, "Choose a currency and a starting balance.", None
    with _DLOCK:
        u = demo_user(email)
        if len(u["accounts"]) >= DEMO_MAX_ACCTS:
            return False, f"You can keep up to {DEMO_MAX_ACCTS} demo accounts. Delete one first.", None
        if _name_taken(u, name):
            return False, f"An account called “{name}” already exists.", None
        a = demo_new(start, ccy, watch, name=name)
        u["accounts"][a["id"]] = a
        u["order"].append(a["id"])
        u["active"] = a["id"]
        _demo_save_user(email, u, sync=True)
        return True, f"“{name}” created", a["id"]


def demo_switch(email, acc_id):
    """Etkin hesabı değiştirir — hiçbir hesabın verisine dokunmaz."""
    with _DLOCK:
        u = demo_user(email)
        if acc_id not in u["accounts"]:
            return False
        if u["active"] != acc_id:
            u["active"] = acc_id
            _demo_save_user(email, u, sync=True)
        return True


def demo_rename(email, acc_id, name):
    name = demo_clean_name(name)
    if not name:
        return False, "The name cannot be empty."
    with _DLOCK:
        u = demo_user(email)
        if acc_id not in u["accounts"]:
            return False, "Account not found."
        if _name_taken(u, name, skip=acc_id):
            return False, f"An account called “{name}” already exists."
        u["accounts"][acc_id]["name"] = name
        _demo_save_user(email, u, sync=True)
        return True, f"Renamed to “{name}”"


def demo_delete(email, acc_id):
    """Hesabı kalıcı olarak siler (en az bir hesap kalır). Silinen etkin hesapsa sıradaki etkin olur."""
    with _DLOCK:
        u = demo_user(email)
        if acc_id not in u["accounts"]:
            return False, "Account not found."
        if len(u["accounts"]) <= 1:
            return False, "This is your only demo account — reset it instead of deleting it."
        name = u["accounts"][acc_id].get("name") or "Account"
        u["accounts"].pop(acc_id)
        idx = u["order"].index(acc_id) if acc_id in u["order"] else 0
        u["order"] = [i for i in u["order"] if i != acc_id]
        if u["active"] == acc_id:
            u["active"] = u["order"][min(idx, len(u["order"]) - 1)]
        _demo_save_user(email, u, sync=True)
        return True, f"“{name}” deleted"


def demo_reset(email, start, ccy, keep=True, acc_id=None):
    """Hesabı yeni başlangıç tutarı / para birimiyle sıfırlar. Adı, kimliği, izleme listesi ve botları
    (kapalı olarak) kalır; pozisyonlar, emirler ve geçmiş silinir. Diğer hesaplar etkilenmez."""
    def run(acct):
        bots = []
        for b in (acct.get("bots") or []) if keep else []:
            b = dict(b, on=False, last=None, cool={})
            b.pop("guard_paused", None)
            bots.append(b)
        new = demo_new(start, ccy, acct.get("watch") if keep else None, bots, name=acct.get("name") or "Account",
                       acc_id=acct.get("id"))
        new["guard"] = dict(guard_cfg(acct), breach=None)     # v5.4: limit ayarları kalır, kilit kalkar
        new["pend"] = []                                      # v5.5: bekleyen emirler silinir
        acct.clear()
        acct.update(new)
        return True
    return demo_edit(email, run, acc_id)


_KEEP = object()


def pos_orders(p):
    """Pozisyonun bekleyen emirleri: {'stop','tp','mode','trail'} (0 = yok)."""
    tp = float(p.get("tp2") or 0) or (float(p.get("tp1") or 0) if not p.get("tp1_done") else 0.0)
    return {"stop": float(p.get("stop") or 0) if has_orders(p) else 0.0, "tp": tp if has_orders(p) else 0.0,
            "mode": "trailing" if p.get("trail") else "regular", "trail": float(p.get("trail") or 0)}


def demo_set_orders(email, key, stop=_KEEP, tp=_KEEP, mode=_KEEP, acc_id=None, last=None):
    """Bir pozisyonun Stop-Loss / Take-Profit emrini ayarlar ya da kapatır (0 / None = kapalı; verilmeyen taraf
    aynen kalır). mode: 'regular' (sabit fiyat) | 'trailing' (en yüksek fiyatın, ayar anındaki mesafe kadar altı).
    Bot pozisyonunda kendi emirlerin botun çıkış planının yerine geçer. Döner: (ok, mesaj)."""
    def run(acct):
        p = acct["pos"].get(key)
        if not p:
            return False, "Position not found."
        lp = float(last) if last else float(p.get("last") or p["entry"])     # canlı fiyat (arayüzden) öncelikli
        cur = pos_orders(p)
        short = p.get("side") == "short"
        st_ = cur["stop"] if stop is _KEEP else float(stop or 0)
        tp_ = cur["tp"] if tp is _KEEP else float(tp or 0)
        md_ = cur["mode"] if mode is _KEEP else ("trailing" if str(mode or "").lower().startswith("trail") else "regular")
        if short:                                  # v5.3: short pozisyonda stop yukarıda, hedef aşağıda
            if stop is not _KEEP and st_ and st_ <= lp:
                return False, f"For a short the stop-loss must be above the current price ({lp:.2f})."
            if tp is not _KEEP and tp_ and tp_ >= lp:
                return False, f"For a short the take-profit must be below the current price ({lp:.2f})."
        if not short and stop is not _KEEP and st_ and st_ >= lp:
            return False, f"The stop-loss must be below the current price ({lp:.2f})."
        if not short and tp is not _KEEP and tp_ and tp_ <= lp:
            return False, f"The take-profit must be above the current price ({lp:.2f})."
        if st_ < 0 or tp_ < 0:
            return False, "Prices cannot be negative."
        changed = (st_ != cur["stop"]) or (tp_ != cur["tp"]) or (md_ != cur["mode"])
        if not st_ and not tp_:
            if p["owner"] == "manual":
                for k_ in ("stop", "tp1", "tp2", "atr", "manual_orders", "checked", "hi", "tp1_done", "trail"):
                    p.pop(k_, None)
            else:                     # bot pozisyonu: botun planı da kapanır (kullanıcı istedi)
                p.update({"stop": 0.0, "tp1": 0.0, "tp2": 0.0, "atr": 0.0, "tp1_done": True, "manual_orders": True})
                p.pop("trail", None)
            return True, "Stop-loss and take-profit cancelled"
        p.update({"stop": st_, "tp1": 0.0, "tp2": tp_, "atr": 0.0, "tp1_done": True, "manual_orders": True})
        if short:
            p["lo"] = min(float(p.get("lo") or lp), lp)
        else:
            p["hi"] = max(float(p.get("hi") or 0), lp)
        if md_ == "trailing" and st_:
            if stop is not _KEEP or mode is not _KEEP or not p.get("trail"):
                p["trail"] = round(abs(lp - st_), 6)
                if short:
                    p["lo"] = lp
                else:
                    p["hi"] = lp
        else:
            p.pop("trail", None)
        if changed:                   # yeni emir geçmiş mumlara karşı denenmez
            p["checked"] = max(float(p.get("checked") or 0), time.time())
        parts = []
        if st_:
            parts.append(("trailing stop " if p.get("trail") else "stop-loss ") + f"{st_:.2f}")
        if tp_:
            parts.append(f"take-profit {tp_:.2f}")
        return True, "Orders saved: " + " · ".join(parts)
    return demo_edit(email, run, acc_id)


def _apply_plan(pos, plan, price, ts, owner):
    """Bot / elle verilen planı pozisyona yazar (stop, hedefler, izleme türü). v5.3: yön, aşama, bulut izi."""
    pos.update({k: plan[k] for k in ("stop", "tp1", "tp2", "atr", "why", "cfg", "trail", "strat",
                                     "trail_n", "trail_kj", "trail_cloud", "no_time", "stage") if k in plan})
    if int(plan.get("stage") or 0) == 2:          # aşama 2 eklendi: artık Kijun izliyor, bulut izi biter
        pos.pop("trail_cloud", None)
    if pos.get("side") == "short":
        pos["lo"] = min(price, float(pos.get("lo") or price))
    else:
        pos["hi"] = max(price, float(pos.get("hi") or 0))
    pos.update({"tp1_done": bool(plan.get("tp1_done", False)), "checked": plan.get("checked") or ts})
    if owner == "manual":
        pos["manual_orders"] = True


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
    psh = bool(pos and pos.get("side") == "short")
    if side in ("buy", "sell") and psh:
        return False, "This is a short position — use cover to close it.", None
    if side in ("short", "cover") and pos and not psh:
        return False, "Close the long position first.", None
    if side == "buy":
        if amt > pend_free(acct) + 1e-6:         # v5.6: bekleyen açılış emirlerinin ayırdığı sermaye hariç
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
            _apply_plan(pos, plan, price, ts, owner)
        acct["cash"] -= amt
    elif side == "short":               # v5.3: açığa satış — teminat kadar nakit ayrılır, K/Z ters yönde
        if amt > pend_free(acct) + 1e-6:
            return False, "Not enough cash (margin) for this short.", None
        if pos:
            pos["entry"] = (pos["entry"] * pos["qty"] + price * qty) / (pos["qty"] + qty)
            pos["qty"] += qty
            pos["cost"] += amt
        else:
            pos = {"sym": sym, "owner": owner, "bot": bot, "qty": qty, "entry": price, "cost": amt, "opened": ts,
                   "last": price, "side": "short", "lo": price}
            acct["pos"][key] = pos
        if plan:
            _apply_plan(pos, plan, price, ts, owner)
        acct["cash"] -= amt
    elif side == "cover":
        if not pos or qty > pos["qty"] + 1e-9:
            return False, "There is no short position of that size.", None
        part = pos["cost"] * qty / pos["qty"]
        pnl = part - amt
        pos["qty"] -= qty
        pos["cost"] -= part
        acct["cash"] += part + pnl
        if pos["qty"] <= 1e-9:
            acct["pos"].pop(key, None)
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
        short = p.get("side") == "short"
        mkt = p["qty"] * last * fxm
        pl = (p["cost"] - mkt) if short else (mkt - p["cost"])     # v5.3: short'ta fiyat düşerse kâr
        val = p["cost"] + pl
        inv += val
        upl += pl
        rows.append({"key": key, "sym": p["sym"], "owner": p["owner"], "bot": p.get("bot") or "", "qty": p["qty"],
                     "entry": p["entry"], "last": last, "value": val, "pnl": pl,
                     "pnl_pct": (pl / p["cost"] * 100) if p["cost"] else 0.0, "stop": p.get("stop"),
                     "tp1": p.get("tp1"), "tp2": p.get("tp2"), "tp1_done": p.get("tp1_done"),
                     "trail": p.get("trail"), "orders": has_orders(p), "manual_orders": bool(p.get("manual_orders")),
                     "strat": p.get("strat"), "trail_n": p.get("trail_n"), "trail_kj": p.get("trail_kj"),
                     "trail_cloud": p.get("trail_cloud"), "side": "short" if short else "long",
                     "stage": p.get("stage"), "fxm": fxm,
                     "opened": p.get("opened"), "why": p.get("why") or "", "live": q.get("src") == "real"})
    rpl = sum(t["pnl"] for t in acct.get("trades") or [] if t.get("pnl") is not None)
    eq = float(acct["cash"]) + inv
    rows.sort(key=lambda r: -r["value"])
    res = pend_reserved(acct)
    return {"equity": eq, "cash": float(acct["cash"]), "invested": inv, "upl": upl, "rpl": rpl,
            "reserved": res, "free": float(acct["cash"]) - res,      # v5.6: açılış emirleri için ayrılan sermaye
            "total": eq - float(acct["start"]), "total_pct": (eq / float(acct["start"]) - 1) * 100, "rows": rows}


# ---------------------------------------------------------------------------------------------------------------
# v5.4 — İstatistik, açık risk ve Prop-Firm devre kesici (haftalık / aylık zarar limiti, "ACCOUNT BREACHED")
# ---------------------------------------------------------------------------------------------------------------
GUARD_PERIODS = ("week", "month")
GUARD_BASES = ("fixed", "pct")
GUARD_LIMIT_DEFAULT = 5000.0         # her yeni hesapta hesabın para biriminde
GUARD_PCT_DEFAULT = 5.0              # yüzde modunda: başlangıç bakiyesinin %'si
# v5.5: kalan "account health" = %100 − harcanan limit yüzdesi; çubuk 4 kademe
# health 100–75 koyu yeşil · 75–50 açık yeşil · 50–25 sarı/amber · 25–0 kırmızı
GUARD_STEPS = (0.25, 0.50, 0.75)     # harcanan limit oranının kademe sınırları
GUARD_WARN, GUARD_RED = GUARD_STEPS[1], GUARD_STEPS[2]


def demo_stats(acct):
    """Kapanmış işlemlerden (geçmişte sonucu olan her satış / kapama) isabet oranı ve ortalama kazanç : kayıp.
    Döner: {'n','wins','losses','win_rate','avg_win','avg_loss','rr'} — rr: ort. kazanç / ort. kayıp (yoksa None)."""
    pnl = [float(t["pnl"]) for t in acct.get("trades") or [] if t.get("pnl") is not None]
    wins = [x for x in pnl if x > 0]
    loss = [-x for x in pnl if x < 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(loss) / len(loss) if loss else 0.0
    return {"n": len(pnl), "wins": len(wins), "losses": len(loss),
            "win_rate": (len(wins) / len(pnl) * 100.0) if pnl else 0.0, "avg_win": aw, "avg_loss": al,
            "rr": (aw / al) if al > 0 else (0.0 if not wins else None)}


def demo_open_risk(val):
    """Açık risk: her stop şimdiki fiyattan tetiklenirse özsermayenin ne kadar düşeceği (long: son − stop,
    short: stop − son; kârı kilitlenmiş stop da "geri verilecek" tutar olarak sayılır). Stopsuz pozisyonlar ayrı.
    Döner: {'risk','n','naked','naked_val','naked_syms'}."""
    risk, n, naked, nval, nsyms = 0.0, 0, 0, 0.0, []
    for r in (val or {}).get("rows") or []:
        stop = float(r.get("stop") or 0) if r.get("orders") else 0.0
        if stop <= 0:
            naked += 1
            nval += float(r.get("value") or 0)
            nsyms.append(r["sym"])
            continue
        last, q, fxm = float(r["last"]), float(r["qty"]), float(r.get("fxm") or 1.0)
        d = (stop - last) if r.get("side") == "short" else (last - stop)
        risk += max(0.0, d) * q * fxm
        n += 1
    return {"risk": risk, "n": n, "naked": naked, "naked_val": nval, "naked_syms": nsyms}


def guard_default():
    return {"on": True, "period": "week", "basis": "fixed", "limit": GUARD_LIMIT_DEFAULT, "pct": GUARD_PCT_DEFAULT,
            "breach": None}


def guard_cfg(acct):
    """Hesabın devre kesici ayarları (eksik / bozuk alanlar varsayılanla)."""
    g = guard_default()
    raw = acct.get("guard")
    if isinstance(raw, dict):
        g.update({k: raw[k] for k in g if k in raw})
    g["on"] = bool(g["on"])
    g["period"] = g["period"] if g["period"] in GUARD_PERIODS else "week"
    g["basis"] = g["basis"] if g["basis"] in GUARD_BASES else "fixed"
    try:
        g["limit"] = max(0.0, float(g["limit"]))
    except (TypeError, ValueError):
        g["limit"] = GUARD_LIMIT_DEFAULT
    try:
        g["pct"] = min(100.0, max(0.0, float(g["pct"])))
    except (TypeError, ValueError):
        g["pct"] = GUARD_PCT_DEFAULT
    if not isinstance(g.get("breach"), dict):
        g["breach"] = None
    return g


def guard_limit(acct, g=None):
    """Etkin limit hesabın para biriminde: sabit tutar ya da başlangıç bakiyesinin yüzdesi."""
    g = g or guard_cfg(acct)
    if g["basis"] == "pct":
        return float(acct.get("start") or 0) * g["pct"] / 100.0
    return float(g["limit"])


def guard_period_start(period, now=None):
    """Dönemin başlangıcı (Europe/Berlin): hafta → pazartesi 00:00, ay → ayın 1'i 00:00. Döner: unix zamanı."""
    t = pd.Timestamp(float(now or time.time()), unit="s", tz="UTC").tz_convert(TZ)
    d = t.replace(day=1) if period == "month" else t - pd.Timedelta(days=t.weekday())
    return float(d.normalize().timestamp())


def guard_status(acct, val=None, now=None):
    """Dönem zararı = dönem içinde gerçekleşen K/Z + açık pozisyonların K/Z'si (zarar pozitif sayı).
    level: off · ok · warn · red · breach. locked: limit aşıldı ve devre kesici açık."""
    g = guard_cfg(acct)
    now = float(now or time.time())
    t0 = guard_period_start(g["period"], now)
    realized = sum(float(t["pnl"]) for t in acct.get("trades") or []
                   if t.get("pnl") is not None and float(t.get("ts") or 0) >= t0)
    upl = float((val if val is not None else demo_value(acct, None, acct.get("fx")))["upl"])
    pl = realized + upl
    loss = max(0.0, -pl)
    lim = guard_limit(acct, g)
    ratio = (loss / lim) if lim > 0 else 0.0
    locked = bool(g["on"] and g["breach"])
    s1, s2, s3 = GUARD_STEPS
    level = ("breach" if locked else "off" if not g["on"] else
             "red" if ratio >= s3 else "warn" if ratio >= s2 else "good" if ratio >= s1 else "ok")
    return {"on": g["on"], "period": g["period"], "basis": g["basis"], "limit": lim, "fixed": g["limit"],
            "pct": g["pct"], "loss": loss, "realized": realized, "open": upl, "pl": pl, "ratio": ratio,
            "health": max(0.0, (1.0 - ratio) * 100.0), "level": level, "locked": locked, "breach": g["breach"],
            "t0": t0}


def guard_locked(acct):
    g = guard_cfg(acct)
    return bool(g["on"] and g["breach"])


def guard_eval(acct, val=None, now=None):
    """Kilit İÇİNDE: dönem zararı limite ulaştıysa hesap kilitlenir (breach kaydı) ve hesabın TÜM botları hemen
    durdurulur (guard_paused işaretiyle). Kilit kendiliğinden kalkmaz. Döner: (durum, yeni_kilit_mi)."""
    s = guard_status(acct, val, now)
    if not s["on"] or s["locked"] or s["limit"] <= 0 or s["loss"] < s["limit"] - 1e-9:
        return s, False
    now = float(now or time.time())
    g = guard_cfg(acct)
    g["breach"] = {"ts": round(now), "loss": round(s["loss"], 2), "limit": round(s["limit"], 2),
                   "period": s["period"]}
    acct["guard"] = g
    paused = 0
    for b in acct.get("bots") or []:
        if b.get("on"):
            b["on"] = False
            b["guard_paused"] = True
            paused += 1
    per = "Weekly" if s["period"] == "week" else "Monthly"
    acct.setdefault("log", []).append({"ts": round(now), "bot": "Circuit breaker", "sym": "",
                                       "text": f"ACCOUNT BREACHED — {per.lower()} loss {s['loss']:.2f} reached the "
                                               f"limit {s['limit']:.2f}; {paused} bot(s) paused, manual trading "
                                               f"blocked"})
    del acct["log"][:-200]
    s = guard_status(acct, val, now)
    s["paused"] = paused
    return s, True


def guard_check(email, acc_id, val, now=None):
    """Arayüz için: durumu döndürür; limit yeni aşıldıysa hesabı kilit altında kilitler (yalnız o zaman yazar).
    Döner: (durum, yeni_kilit_mi)."""
    acct = demo_get(email, acc_id)
    s = guard_status(acct, val, now)
    if s["on"] and not s["locked"] and s["limit"] > 0 and s["loss"] >= s["limit"] - 1e-9:
        return demo_edit(email, lambda a: guard_eval(a, val, now), acc_id)
    return s, False


def guard_set(email, acc_id=None, **chg):
    """Devre kesici ayarlarını değiştirir: on, period ('week'|'month'), basis ('fixed'|'pct'), limit, pct.
    Hesap kilitliyse: kapatmak kilidi kaldırır; limit / dönem / tür değişirse kilit kalkar ve yeni ayarla
    yeniden değerlendirilir (zarar hâlâ limitin üstündeyse hesap kilitli kalır). Döner: (ok, mesaj)."""
    def run(acct):
        g = guard_cfg(acct)
        old = dict(g)
        if "on" in chg:
            g["on"] = bool(chg["on"])
        if chg.get("period") in GUARD_PERIODS:
            g["period"] = chg["period"]
        if chg.get("basis") in GUARD_BASES:
            g["basis"] = chg["basis"]
        if "limit" in chg:
            try:
                v = float(chg["limit"])
            except (TypeError, ValueError):
                return False, "The loss limit must be a number."
            if not v > 0:
                return False, "The loss limit must be above zero."
            g["limit"] = round(v, 2)
        if "pct" in chg:
            try:
                v = float(chg["pct"])
            except (TypeError, ValueError):
                return False, "The percentage must be a number."
            if not 0 < v <= 100:
                return False, "The percentage must be between 0 and 100."
            g["pct"] = round(v, 2)
        msg = "Circuit breaker " + ("on" if g["on"] else "off")
        if g["breach"]:
            if not g["on"]:
                g["breach"] = None
                msg = "Circuit breaker off — account unlocked"
            elif any(g[k] != old[k] for k in ("period", "basis", "limit", "pct")):
                g["breach"] = None
                msg = "Limit changed — account re-checked"
        elif any(g[k] != old[k] for k in ("period", "basis", "limit", "pct")):
            msg = "Loss limit saved"
        acct["guard"] = g
        s, new = guard_eval(acct, chg.get("val"))
        if new:
            msg = "Still above the new limit — the account stays locked"
        return True, msg
    return demo_edit(email, run, acc_id)


# ---------------------------------------------------------------------------------------------------------------
# v5.5 — Bekleyen limit emirleri ("Pending orders"): kurs istenen seviyeye gelince kendiliğinden dolar
# ---------------------------------------------------------------------------------------------------------------
PEND_MAX = 20                 # hesap başına en fazla bekleyen emir


def pend_list(acct):
    return list(acct.get("pend") or [])


def pend_syms(acct):
    return sorted({o["sym"] for o in acct.get("pend") or []})


def pend_add(acct, sym, side, qty, limit, stop=0.0, tp=0.0, mode="regular", ts=None, kind="limit", est=0.0,
             fxm=1.0):
    """Kilit İÇİNDE: bekleyen emir ekler.
    kind='limit': buy kurs ≤ limit · sell kurs ≥ limit · kind='open' (v5.6): borsa kapalıyken verilen emir,
    açılışta piyasa fiyatından dolar (est = o anki referans fiyat, planlanan tutar için). Döner: (ok, mesaj, emir)."""
    sym = str(sym or "").upper().strip()
    side = "buy" if str(side).lower().startswith("b") else "sell"
    kind = "open" if str(kind) == "open" else "limit"
    try:
        qty, limit = float(qty), float(limit or 0)
        stop, tp = float(stop or 0), float(tp or 0)
        est, fxm = float(est or 0), float(fxm or 1.0)
    except (TypeError, ValueError):
        return False, "Quantity and price must be numbers.", None
    if inst_ccy(sym) is None:
        return False, f"{sym} cannot be traded in the demo account.", None
    if not qty > 0:
        return False, "Enter a quantity above zero.", None
    if kind == "limit" and not limit > 0:
        return False, "Enter a limit price above zero.", None
    if len(acct.get("pend") or []) >= PEND_MAX:
        return False, f"An account holds up to {PEND_MAX} pending orders — cancel one first.", None
    ref = limit if kind == "limit" else est
    if side == "sell":
        stop = tp = 0.0
        have = sum(p["qty"] for p in acct["pos"].values()
                   if p["sym"] == sym and p["owner"] == "manual" and p.get("side") != "short")
        held = have - sum(float(x["qty"]) for x in acct.get("pend") or []
                          if x["side"] == "sell" and x["sym"] == sym)        # aynı adet iki kez satılmasın
        if held < qty - 1e-9:
            return False, (f"You only hold {max(0.0, held):g} {sym} by hand that is not already in a pending "
                           f"order."), None
    else:
        if stop and ref and stop >= ref:
            return False, f"The stop-loss ({stop:g}) must be below the order price ({ref:g}).", None
        if tp and ref and tp <= ref:
            return False, f"The take-profit ({tp:g}) must be above the order price ({ref:g}).", None
        if kind == "open" and ref > 0:          # açılışa kadar ayrılacak sermaye (serbest nakitle sınırlı)
            need = qty * ref * fxm
            if need > pend_free(acct) + 1e-6:
                return False, (f"Not enough free cash for this order — {need:.2f} needed, "
                               f"{pend_free(acct):.2f} available (pending orders already reserve "
                               f"{pend_reserved(acct):.2f})."), None
    acct["seq"] = int(acct.get("seq") or 0) + 1
    o = {"id": f'p{acct["seq"]}', "sym": sym, "side": side, "qty": qty, "limit": limit, "stop": stop, "tp": tp,
         "mode": "trailing" if str(mode).lower().startswith("trail") else "regular", "ts": round(float(ts or time.time())),
         "err": None, "kind": kind, "est": est, "amt": (qty * ref * fxm) if ref else 0.0, "fxm": fxm}
    acct.setdefault("pend", []).append(o)
    if kind == "open":
        st_ = market_status(sym, ts)
        return True, (f'Order queued: {side} {qty:g} {sym} at the market open — {st_["label"]} is closed'
                      + (f', it opens at {st_["txt"]}' if st_["txt"] else "") + '.'), o
    return True, (f'Limit order placed: {"buy" if side == "buy" else "sell"} {qty:g} {sym} at {limit:g} — it fills as '
                  f'soon as the price {"falls to" if side == "buy" else "rises to"} {limit:g}.'), o


def pend_reserved(acct):
    """v5.6: açılışta dolacak ALIŞ emirleri için ayrılan sermaye (hesabın para biriminde)."""
    return sum(float(o.get("amt") or 0) for o in acct.get("pend") or []
               if o.get("kind") == "open" and o["side"] == "buy")


def pend_free(acct):
    """Serbest nakit = nakit − ayrılan sermaye."""
    return float(acct.get("cash") or 0) - pend_reserved(acct)


def pend_cancel(email, oid, acc_id=None):
    """Bekleyen emri iptal eder. Döner: (ok, mesaj)."""
    def run(a):
        keep = [o for o in a.get("pend") or [] if o["id"] != oid]
        if len(keep) == len(a.get("pend") or []):
            return False, "This order is no longer pending."
        gone = [o for o in a.get("pend") or [] if o["id"] == oid][0]
        a["pend"] = keep
        return True, f'Limit order cancelled: {gone["side"]} {gone["qty"]:g} {gone["sym"]} at {gone["limit"]:g}'
    return demo_edit(email, run, acc_id)


def pend_hit(o, px, now=None):
    """Emir tetiklendi mi? (kilitsiz ön kontrol) — limit: fiyat seviyeye geldi · open: borsa açıldı.
    Her iki tür de yalnızca normal seansta dolar."""
    if px is None or not o or not market_open(o["sym"], now):
        return False
    if o.get("kind") == "open":
        return True
    return (px <= float(o["limit"]) + 1e-12) if o["side"] == "buy" else (px >= float(o["limit"]) - 1e-12)


def pend_check(acct, live, eurusd, now=None, log=None):
    """Kilit İÇİNDE: tetiklenen limit emirlerini doldurur. Dolum fiyatı kursla limitin iyisi (alışta düşük olan).
    Hesap devre kesiciyle kilitliyse ALIŞ emirleri beklemede kalır, satışlar (risk azaltma) dolar.
    Döner: olay listesi."""
    now = float(now or time.time())
    out = []
    locked = guard_locked(acct)
    for o in list(acct.get("pend") or []):
        px = live.get(o["sym"])
        if not pend_hit(o, px, now):
            continue
        if locked and o["side"] == "buy":
            o["err"] = "Blocked — account breached"
            continue
        fxm = fx_mult(acct["ccy"], inst_ccy(o["sym"]), eurusd)
        if fxm is None:
            continue
        px = float(px)
        if o.get("kind") == "open":                 # açılış emri: piyasa fiyatından
            fill = px
        else:
            fill = min(px, float(o["limit"])) if o["side"] == "buy" else max(px, float(o["limit"]))
        stop, tp = float(o.get("stop") or 0), float(o.get("tp") or 0)
        trail = round(fill - stop, 6) if (stop and o.get("mode") == "trailing") else 0.0
        plan = ({"stop": stop, "tp1": 0.0, "tp2": tp, "atr": 0.0, "tp1_done": True, "checked": now, "trail": trail}
                if (stop or tp) and o["side"] == "buy" else None)
        why = ((f'Queued at {market_label(o["sym"])} open' if o.get("kind") == "open"
                else f'Limit order at {o["limit"]:g}')
               + ((f' · trailing SL {stop:g}' if trail else f' · SL {stop:g}') if stop else "")
               + (f' · TP {tp:g}' if tp else ""))
        rest = [x for x in acct.get("pend") or [] if x["id"] != o["id"]]
        acct["pend"] = rest                         # ayrılan sermaye bu emir için serbest bırakılır
        ok, msg, tr = demo_trade(acct, o["sym"], o["side"], float(o["qty"]), fill, fxm, "manual", why, plan=plan,
                                 ts=now)
        if not ok:                       # ör. nakit yetmiyor / pozisyon satılmış → emir hatasıyla beklemede kalır
            o["err"] = msg
            acct["pend"] = rest + [o]
            continue
        kind_ = "open" if o.get("kind") == "open" else "limit"
        out.append({"kind": "limit", "otype": kind_, "side": o["side"], "sym": o["sym"], "qty": float(o["qty"]),
                    "price": fill, "limit": float(o["limit"] or 0), "bot": "Limit order", "reason": why,
                    "pnl": tr["pnl"] if tr else None})
        if log:
            log("Limit order", o["sym"], f'{o["side"].upper()} {o["qty"]:g} @ {fill:.2f} — '
                                        + (f'{market_label(o["sym"])} open' if kind_ == "open"
                                           else f'limit {o["limit"]:g}'))
    return out


# ---------------------------------------------------------------------------------------------------------------
# v5.6 — Borsa saatleri: emir, enstrümanın kendi borsası kapalıyken açılışa kadar bekletilir
# ---------------------------------------------------------------------------------------------------------------
# kural: (saat dilimi, açılış dk, kapanış dk) — yerel borsa saatiyle
MKT_RULES = {"us": ("America/New_York", 9 * 60 + 30, 16 * 60), "eu": (TZ, 9 * 60, 17 * 60 + 30)}
MKT_SFX = {".DE": ("eu", "XETRA"), ".F": ("eu", "Börse Frankfurt"), ".PA": ("eu", "Euronext Paris"),
           ".AS": ("eu", "Euronext Amsterdam"), ".BR": ("eu", "Euronext Brussels"), ".LS": ("eu", "Euronext Lisbon"),
           ".IR": ("eu", "Euronext Dublin"), ".MI": ("eu", "Borsa Italiana"), ".MC": ("eu", "BME Madrid"),
           ".VI": ("eu", "Wiener Börse"), ".HE": ("eu", "Nasdaq Helsinki")}
# NYSE / NASDAQ ve Avrupa borsalarının tatilleri (2026–2027). Sonraki yıllarda yalnızca hafta sonu + saatler geçerli.
MKT_HOL = {
    "us": {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
           "2026-09-07", "2026-11-26", "2026-12-25",
           "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
           "2027-09-06", "2027-11-25", "2027-12-24"},
    "eu": {"2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-12-24", "2026-12-25", "2026-12-31",
           "2027-01-01", "2027-03-26", "2027-03-29", "2027-12-24", "2027-12-31"}}
MKT_HALF = {"us": {"2026-11-27": 13 * 60, "2026-12-24": 13 * 60, "2027-11-26": 13 * 60},
            "eu": {}}
MKT_YEARS = (2026, 2027)              # tatil listesinin kapsadığı yıllar


def sym_market(sym):
    """Enstrümanın borsası. Döner: (kural, ad) — kural: 'us' | 'eu' | 'crypto' | 'fut'."""
    s_ = str(sym or "").upper().strip()
    if s_.endswith(("-USD", "-EUR")):
        return "crypto", "Crypto (24/7)"
    if s_.endswith("=F"):
        return "fut", "CME Globex"
    for sfx, v in MKT_SFX.items():
        if s_.endswith(sfx):
            return v
    return "us", "NYSE / NASDAQ"


def market_label(sym):
    return sym_market(sym)[1]


def _fut_open(t):
    """CME: pazar 18:00 ET → cuma 17:00 ET, her gün 17:00–18:00 ET arası kapalı."""
    hm, wd = t.hour * 60 + t.minute, t.weekday()
    if 17 * 60 <= hm < 18 * 60:
        return False
    if wd == 5:                                   # cumartesi
        return False
    if wd == 6 and hm < 18 * 60:                  # pazar akşamı açılır
        return False
    if wd == 4 and hm >= 17 * 60:                 # cuma akşamı kapanır
        return False
    return True


def _day_hours(rule, t):
    """O günün seans saatleri (yerel borsa dakikası) ya da None (hafta sonu / tatil)."""
    tzn, o, c = MKT_RULES[rule]
    if t.weekday() >= 5:
        return None
    day = t.strftime("%Y-%m-%d")
    if day in MKT_HOL.get(rule, ()):
        return None
    half = MKT_HALF.get(rule, {}).get(day)
    return (o, half) if half else (o, c)


def market_open(sym, now=None):
    """Enstrümanın borsası şu an normal seansta mı? (kripto her zaman açık)"""
    rule, _ = sym_market(sym)
    if rule == "crypto":
        return True
    t = pd.Timestamp(float(now or time.time()), unit="s", tz="UTC")
    if rule == "fut":
        return _fut_open(t.tz_convert("America/New_York"))
    t = t.tz_convert(MKT_RULES[rule][0])
    h = _day_hours(rule, t)
    return bool(h and h[0] <= t.hour * 60 + t.minute < h[1])


def market_next_open(sym, now=None):
    """Bir sonraki normal açılışın zamanı (unix) — zaten açıksa None."""
    rule, _ = sym_market(sym)
    now = float(now or time.time())
    if rule == "crypto" or market_open(sym, now):
        return None
    t0 = pd.Timestamp(now, unit="s", tz="UTC")
    if rule == "fut":                                  # en fazla 3 gün ileriye bak (saatlik adım yeterli)
        for i in range(1, 72 * 60, 5):
            t = t0 + pd.Timedelta(minutes=i)
            if _fut_open(t.tz_convert("America/New_York")):
                return float(t.timestamp())
        return None
    tzn, _, _ = MKT_RULES[rule]
    t = t0.tz_convert(tzn)
    for i in range(0, 12):
        d = (t + pd.Timedelta(days=i)).normalize()
        h = _day_hours(rule, d)
        if not h:
            continue
        op = d + pd.Timedelta(minutes=h[0])
        if op.timestamp() > now:
            return float(op.timestamp())
    return None


def market_status(sym, now=None, tz=None):
    """Arayüz için: {'open','label','rule','next','txt'} — txt: kullanıcının saatiyle açılış ('15:30 CET')."""
    rule, lab = sym_market(sym)
    now = float(now or time.time())
    op = market_open(sym, now)
    nx = None if op else market_next_open(sym, now)
    txt = ""
    if nx:
        t = pd.Timestamp(nx, unit="s", tz="UTC").tz_convert(tz or TZ)
        same = t.strftime("%Y-%m-%d") == pd.Timestamp(now, unit="s", tz="UTC").tz_convert(tz or TZ).strftime("%Y-%m-%d")
        txt = (t.strftime("%H:%M %Z") if same else t.strftime("%a %H:%M %Z"))
    return {"open": op, "label": lab, "rule": rule, "next": nx, "txt": txt,
            "known": pd.Timestamp(now, unit="s", tz="UTC").year in MKT_YEARS}


def _eq_point(acct, equity, now, gap=840):
    eq = acct.setdefault("eq", [])
    if not eq or now - eq[-1][0] >= gap:
        eq.append([round(now), round(equity, 2)])
        del eq[:-1500]
    else:
        eq[-1][1] = round(equity, 2)


def bot_new(name, src, universe, cfg=None, flt=None, params=None, ichi=None, pairs=None, rot=None):
    """src: 'ai' (formasyon kırılımı) · 'filter' (kendi filtren) · v4.9: 'donchian2' · 'flag' (hazır stratejiler).
    v5.3: Ichimoku botu yalnızca seçilen piyasalarda (altın, gümüş, petrol, Bitcoin) long + short işlem yapar;
    ichi = {'mkts': [...], 'btc': 'btc1030'} — her piyasa kendi ön ayarıyla."""
    en = _engine()
    src = src if (src in ("filter", "pairs", "rotation") or src in en.STRAT_PARAMS) else "ai"
    b = {"id": secrets.token_hex(4), "name": str(name or "Bot").strip()[:40] or "Bot",
         "on": True, "src": src,
         "universe": "scan" if universe == "scan" else "demo", "cfg": en.bot_cfg(cfg),
         "flt": flt if (src == "filter" and isinstance(flt, dict)) else None,
         "params": en.strat_params(src, params) if src in en.STRAT_PARAMS else None,
         "created": time.time(), "last": None, "cool": {}}
    if src == "ichimoku":
        ok_ = [m[0] for m in en.ICHI_MARKETS]
        mk = [s_ for s_ in ((ichi or {}).get("mkts") or ok_) if s_ in ok_] or ok_
        btc = (ichi or {}).get("btc")
        b["ichi"] = {"mkts": mk, "btc": btc if btc in en.ICHI_BTC else "btc1030",
                     "auto": bool((ichi or {}).get("auto"))}      # v5.12: Modus + BTC-Variante wählt der Bot
        b["universe"] = "ichi"
    if src == "pairs":                       # v5.8: çift listesi + çift ayarları; açık çiftler 'pt' içinde
        lst, seen = [], set()
        for x in (pairs or {}).get("list") or []:
            if isinstance(x, (list, tuple)) and len(x) == 2:
                a_, b_ = str(x[0]).upper().strip()[:24], str(x[1]).upper().strip()[:24]
                if a_ and b_ and a_ != b_ and en.pair_key(a_, b_) not in seen:
                    seen.add(en.pair_key(a_, b_))
                    lst.append([a_, b_])
        b["pairs"] = {"list": lst[:20], "p": en.pair_cfg((pairs or {}).get("p")),
                      "auto": bool((pairs or {}).get("auto"))}    # v5.12: der Bot sucht die besten Paare selbst
        b["universe"], b["pt"] = "pairs", {}
    if src == "rotation":                    # v5.8: evren + rotasyon ayarları; ay başında yeniden dengeler
        r_ = rot or {}
        uni = r_.get("uni") if r_.get("uni") in list(en.ROT_UNIVERSES) + ["watch", "custom"] else "us_sectors"
        syms = [str(x).upper().strip()[:24] for x in (r_.get("syms") or []) if str(x).strip()][:40]
        b["rot"] = {"uni": uni, "syms": syms, "p": en.rot_cfg(r_.get("p"))}
        b["universe"] = "rotation"
    return b


def rot_month(now=None):
    return pd.Timestamp(now or time.time(), unit="s", tz="UTC").tz_convert(TZ).strftime("%Y-%m")


def rot_due(b, now=None):
    """Rotasyon botu bu turda yeniden dengelemeli mi? (yeni ay ya da kullanıcı "şimdi" dedi)"""
    return bool(b.get("rot_force")) or b.get("rot_month") != rot_month(now)


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


# ---------------------------------------------------------------- v5.12 — Ichimoku-Stage + bestes Paar automatisch
_ICHI_AUTO = {}
_PAIRS_AUTO = {"key": None, "list": [], "rows": [], "running": False, "ts": 0.0, "err": ""}
PAIRS_AUTO_N = 8             # so viele nutzbare Paare beobachtet der Bot (das beste Signal zuerst)
PAIRS_AUTO_GROUPS = ("US stocks", "ETFs")


def ichi_auto_pick(sym, df, bp=None):
    """v5.12 — Ichimoku-'Stage' automatisch: pro Markt der Modus (0 = Kumo-Ausbruch + Kijun-Trail, 1 = gestaffelt
    ⅓ + ⅔) und bei Bitcoin zusätzlich die Einstellung, die in den letzten 3 Jahren im Backtest besser war
    (Rendite ÷ max. Drawdown, mindestens 3 Trades). Einmal pro Tag und Markt."""
    en = _engine()
    bp = bp or {}
    try:
        last = str(pd.Timestamp(df.index[-1]).date())
    except Exception:
        last = ""
    key = (str(sym).upper(), time.strftime("%Y-%m-%d"), last)
    if key in _ICHI_AUTO:
        return dict(_ICHI_AUTO[key])
    variants = list(en.ICHI_BTC) if str(sym).upper() == "BTC-USD" else ["btc1030"]
    best = None
    for v in variants:
        for mode in (0, 1):
            P = en.ichi_market_params(sym, v, mode, int(bp.get("bounce", 1)), float(bp.get("max_atr") or 2.0))
            try:
                res = en.backtest_strategy(df, {"strat": "ichimoku", "sp": P, "yrs": 3})
            except Exception:
                continue
            k = (res or {}).get("kpi") or {}
            if not (res or {}).get("ok") or int(k.get("n", 0)) < 3:
                continue
            sc = float(k.get("net_pct", 0.0)) / max(5.0, -float(k.get("mdd", 0.0)))
            if best is None or sc > best["score"] + 1e-9:
                best = {"mode": mode, "btc": v, "score": round(sc, 3), "net": round(float(k.get("net_pct", 0.0)), 1),
                        "mdd": round(float(k.get("mdd", 0.0)), 1), "n": int(k.get("n", 0))}
    if best is None:
        best = {"mode": 0, "btc": "btc1030", "score": None, "net": None, "mdd": None, "n": 0}
    if len(_ICHI_AUTO) > 64:
        _ICHI_AUTO.clear()
    _ICHI_AUTO[key] = best
    return dict(best)


def _pairs_rank(md, pc):
    """Alle Kandidaten-Paare (US-Aktien + ETFs) wie im Pair Lab prüfen → nutzbare Paare nach Qualität."""
    en = _engine()
    c = en.pair_cfg(pc)
    cands = [(a, b_) for a, b_, g, _n in en.PAIR_CANDIDATES if g in PAIRS_AUTO_GROUPS]
    syms = sorted({x for pr in cands for x in pr})
    yrs = float(c.get("yrs") or 3) + 1
    daily = md.get_daily_batch(tuple(syms), period="2y" if yrs <= 2 else "5y" if yrs <= 5 else "10y") or {}
    rows = []
    for a, b_ in cands:
        da, db = daily.get(a), daily.get(b_)
        if not (_real(da) and _real(db)):
            continue
        try:
            r = en.pair_analyze(da, db, c, a, b_)
        except Exception:
            r = None
        if r and r.get("verdict") == "usable":
            rows.append(r)
    rows.sort(key=en.pair_rank_key)
    top = rows[:PAIRS_AUTO_N]
    info = [{"key": r["key"], "win": round(float((r.get("kpi") or {}).get("win", 0.0)), 0),
             "pf": (round(float((r.get("kpi") or {}).get("pf", 0.0)), 2)
                    if (r.get("kpi") or {}).get("pf", 0.0) != float("inf") else None),
             "z": (round(float(r["z"]), 2) if r.get("z") == r.get("z") and r.get("z") is not None else None)}
            for r in top]
    return [[r["a"], r["b"]] for r in top], info


def pairs_auto_list(md, pc=None, wait=False):
    """v5.12 — 'bestes Paar' automatisch: einmal am Tag im Hintergrund (Seite blockiert nicht); bis dahin gilt die
    letzte Liste. Döner: (liste, durum)."""
    en = _engine()
    st_ = _PAIRS_AUTO
    key = (time.strftime("%Y-%m-%d"), json.dumps(en.pair_cfg(pc), sort_keys=True))
    stale = st_["key"] != key or (st_["err"] and time.time() - st_["ts"] > 7200)
    if stale and not st_["running"]:
        st_["running"] = True

        def job():
            try:
                lst, rows = _pairs_rank(md, pc)
                st_.update(list=lst, rows=rows, err="" if lst else "no usable pair today")
            except Exception as ex:
                st_["err"] = f"{type(ex).__name__}: {ex}"[:160]
            finally:
                st_.update(key=key, ts=time.time(), running=False)
        if wait:
            job()
        else:
            threading.Thread(target=job, name="pulse-pairs-auto", daemon=True).start()
    return [list(x) for x in st_["list"]], dict(st_)


def bots_collect(md, acct):
    """Kilidin DIŞINDA: botların ihtiyacı olan tüm veriyi çeker ve sinyalleri hesaplar."""
    en = _engine()
    bots = [b for b in acct.get("bots") or [] if b.get("on") or (b.get("src") == "pairs" and b.get("pt"))]
    held = sorted({p["sym"] for p in acct["pos"].values() if has_orders(p)})
    watch = [s for s in acct.get("watch") or [] if inst_ccy(s)]
    data = {"sig": {}, "skip": {}, "n": {}, "i15": {}, "px": {}, "regime_ok": True, "regime_dn": False, "eurusd": None,
            "err": {}, "chan": {}}
    # v4.9/5.1/5.3: izleyen stoplu pozisyonlar — Donchian: N günlük dip · Ichimoku: Kijun · kademeli aşama 1: bulut
    chan = {}
    for p in acct["pos"].values():
        if p.get("manual_orders"):
            continue
        spec = trail_spec(p)
        if spec:
            chan[(p["sym"], spec)] = spec
    if chan:
        try:
            dd = md.get_daily_batch(tuple(sorted({t for t, _ in chan})), period="5y")
            for (t, spec) in chan:
                if not _real(dd.get(t)):
                    continue
                if spec[0] == "n":
                    v_ = en.channel_stop(dd[t], int(spec[1:]))
                elif spec[0] == "k":
                    v_ = en.kijun_stop(dd[t], int(spec[1:]))
                else:                                        # 'c9-26-52l' / 'c9-26-52s'
                    v_ = en.cloud_stop(dd[t], spec[1:-1], "short" if spec.endswith("s") else "long")
                if v_:
                    data["chan"][f"{t}|{spec}"] = v_
        except Exception:
            pass
    try:
        q = md.get_quotes(["EURUSD=X"]).get("EURUSD=X") or {}
        if q.get("src") == "real" and q.get("last"):
            data["eurusd"] = float(q["last"])
    except Exception:
        pass
    if bots:
        try:
            reg_ = en.ai_regime(md.get_daily_batch(("SPY", "QQQ")), 50)
            data["regime_ok"], data["regime_dn"] = bool(reg_.get("ok")), bool(reg_.get("dn"))   # v5.11: dn = short
        except Exception:
            data["regime_ok"], data["regime_dn"] = False, False
    need15, evals = set(held), {}
    for b in bots:
        try:
            if b["src"] == "ai":
                meta, sides = {}, {}
                both = en.bot_cfg(b.get("cfg")).get("ai_dir") == "both"      # v5.11: ayı formasyonlarında short
                if b["universe"] == "scan":
                    snap_ = md.get_market_snapshot()
                    cand, _ = en.ai_prefilter(snap_, None)
                    syms = [t for t in list(cand["ticker"].head(40)) if inst_ccy(t)] if len(cand) else []
                    meta = cand.set_index("ticker").to_dict("index") if len(cand) else {}
                    sides = {t: "long" for t in syms}
                    if both:
                        cs_, _ = en.ai_prefilter(snap_, None, side="short")
                        sh_ = [t for t in list(cs_["ticker"].head(20)) if inst_ccy(t) and t not in sides] \
                            if cs_ is not None and len(cs_) else []
                        if sh_:
                            meta = dict(cs_.set_index("ticker").to_dict("index"), **meta)
                        syms += sh_
                        sides.update({t: "short" for t in sh_})
                else:
                    syms = list(watch)
                daily = md.get_daily_batch(tuple(syms)) if syms else {}
                rs = []
                for t in syms:
                    df = daily.get(t)
                    if not _real(df):
                        continue
                    r = en.ai_evaluate(t, df, meta=meta.get(t), side=sides.get(t) or (None if both else "long"))
                    if r:
                        rs.append(r)
                        bb = r.get("best")
                        if bb and r.get("ema_ok") and bb.get("state") in ("breakout", "retest"):
                            need15.add(t)
                evals[b["id"]] = ("ai", rs)
                data["n"][b["id"]] = len(rs)
            elif b["src"] == "pairs":                              # v5.8: iki bacaklı çift işlemi
                pc_ = b.get("pairs") or {}
                lst = [tuple(x) for x in (pc_.get("list") or []) if len(x) == 2]
                if pc_.get("auto"):                                # v5.12: beste Paare automatisch (täglich)
                    auto_, st_ = pairs_auto_list(md, pc_.get("p"))
                    lst = [tuple(x) for x in auto_]
                    data.setdefault("pauto", {})[b["id"]] = {"n": len(auto_), "running": st_["running"],
                                                             "err": st_["err"], "top": st_["rows"][:3]}
                    for t_ in (b.get("pt") or {}).values():        # offene Paare bleiben in der Liste
                        if (t_["a"], t_["b"]) not in lst:
                            lst.append((t_["a"], t_["b"]))
                syms = sorted({s_ for pr in lst for s_ in pr if inst_ccy(s_)})
                daily = md.get_daily_batch(tuple(syms), period="2y") if syms else {}
                pdat = {}
                for a_, b_ in lst:
                    if _real(daily.get(a_)) and _real(daily.get(b_)):
                        pdat[en.pair_key(a_, b_)] = (a_, b_, daily[a_], daily[b_])
                        need15.update((a_, b_))
                for t_ in (b.get("pt") or {}).values():           # açık çiftlerin bacakları her zaman izlenir
                    need15.update((t_["a"], t_["b"]))
                data.setdefault("pdat", {})[b["id"]] = pdat
                data["n"][b["id"]] = len(pdat)
                evals[b["id"]] = ("pairs", [])
            elif b["src"] == "rotation":                           # v5.8: aylık momentum rotasyonu
                ro = b.get("rot") or {}
                uni = en.rot_universe(ro.get("uni") or "us_sectors", watch=acct.get("watch"), custom=ro.get("syms"))
                held_r = sorted({p["sym"] for p in acct["pos"].values() if p["owner"] == b["id"]})
                info = {"due": rot_due(b), "held": held_r, "uni": uni["key"]}
                if info["due"]:
                    want = list(dict.fromkeys(uni["syms"] + [x for x in (uni.get("bench"), uni.get("safe")) if x]))
                    daily = md.get_daily_batch(tuple(want), period="2y") if want else {}
                    fr = en.rot_frame({t_: df for t_, df in daily.items() if _real(df)}, want)
                    if fr is not None:                             # yalnızca tamamlanmış günler (bugünkü yarım mum yok)
                        fr = fr[fr.index < pd.Timestamp.now(tz=TZ).normalize().tz_localize(None)]
                    rk = en.rot_rank(fr, uni, ro.get("p"), held=held_r) if fr is not None and len(fr) > 260 else None
                    if rk:
                        info.update({"pick": rk["pick"], "risk_on": rk["risk_on"], "safe": uni.get("safe"),
                                     "free": rk["free"], "date": rk["date"],
                                     "top": [(r_["sym"], round(float(r_["score"]), 1)) for r_ in rk["rows"][:5]]})
                        need15.update(set(held_r) | set(rk["pick"]) |
                                      ({uni["safe"]} if uni.get("safe") and rk["free"] > 0 else set()))
                    else:
                        info["err"] = "no price data for the universe"
                data.setdefault("rot", {})[b["id"]] = info
                data["n"][b["id"]] = len(uni["syms"])
                evals[b["id"]] = ("rotation", [])
            elif b["src"] == "ichimoku":                           # v5.3: yalnızca altın / gümüş / petrol / Bitcoin
                ich = b.get("ichi") or {}
                syms = [s_ for s_ in (ich.get("mkts") or [m[0] for m in en.ICHI_MARKETS]) if inst_ccy(s_)]
                daily = md.get_daily_batch(tuple(syms), period="5y") if syms else {}
                bp = b.get("params") or {}
                rs, n_ok = [], 0
                for t in syms:
                    df = daily.get(t)
                    if not _real(df):
                        continue
                    n_ok += 1
                    mode_, btc_ = int(bp.get("mode") or 0), ich.get("btc") or "btc1030"
                    if ich.get("auto"):                            # v5.12: Stage wählt der Bot (Backtest, täglich)
                        held = (acct.get("pos") or {}).get(f"{t}|{b['id']}")
                        pk_ = ichi_auto_pick(t, df, bp)
                        mode_, btc_ = int(pk_["mode"]), pk_["btc"]
                        if held is not None:                       # offene Position: Modus bleibt, bis sie zu ist
                            mode_ = 1 if held.get("stage") else 0
                        data.setdefault("ichi_auto", {}).setdefault(b["id"], {})[t] = dict(pk_, mode=mode_)
                    P = en.ichi_market_params(t, btc_, mode_,
                                              int(bp.get("bounce", 1)), float(bp.get("max_atr") or 2.0))
                    r = en.strat_evaluate("ichimoku", t, df, meta={"name": en.ichi_market_name(t)}, params=P)
                    if r:
                        rs.append(r)
                        if r["best"]["state"] in ("breakout", "retest", "cloud_in"):
                            need15.add(t)
                evals[b["id"]] = ("strat", rs)
                data["n"][b["id"]] = n_ok
            elif b["src"] in en.STRAT_PARAMS:                      # hazır strateji — v5.3: filtresiz evren
                meta = {}
                if b["universe"] == "scan":
                    cand, _ = en.strat_universe(md.get_market_snapshot(), 60)
                    syms = [t for t in list(cand["ticker"]) if inst_ccy(t)] if cand is not None and len(cand) else []
                    meta = cand.set_index("ticker").to_dict("index") if cand is not None and len(cand) else {}
                else:
                    syms = list(watch)
                daily = md.get_daily_batch(tuple(syms)) if syms else {}
                rs, n_ok = [], 0
                for t in syms:
                    df = daily.get(t)
                    if not _real(df):
                        continue
                    n_ok += 1
                    r = en.strat_evaluate(b["src"], t, df, meta=meta.get(t), params=b.get("params"))
                    if r:
                        rs.append(r)
                        if r["best"]["state"] in ("breakout", "retest"):
                            need15.add(t)
                evals[b["id"]] = ("strat", rs)
                data["n"][b["id"]] = n_ok
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
    for bid, pdat in (data.pop("pdat", None) or {}).items():       # v5.8: çiftlerin güncel z-skoru (canlı fiyatla)
        bb_ = next((x for x in bots if x["id"] == bid), {})
        pc_ = (bb_.get("pairs") or {}).get("p")
        zz = {}
        for k_, (a_, b_, da, db) in pdat.items():
            try:
                s_ = en.pair_signal_live(da, db, pc_, data["px"].get(a_), data["px"].get(b_))
            except Exception:
                s_ = None
            if s_:
                zz[k_] = s_
        data.setdefault("pz", {})[bid] = zz
    for b in bots:
        kind, rows = evals.get(b["id"], (None, []))
        sig, skip = [], []
        if kind == "ai":                              # v5.11: önce 15 dk teyidi, sonra skora göre (mum bonusu = öncelik)
            for r in rows:
                bb = r.get("best")
                if bb and r["ticker"] in data["i15"]:
                    en.ai_apply_15m(r, en.confirm_15m(data["i15"][r["ticker"]], bb["level"], bb["kind"]))
            rows = sorted(rows, key=lambda r_: -float(r_.get("score") or 0.0))
        for r in rows:
            t = r["ticker"]
            if kind == "ai":
                s, why = en.bot_signal_ai(r, b["cfg"], data["regime_ok"], data.get("regime_dn", False))
            elif kind == "strat":                     # v5.3: 15 dk teyidi / rejim yok — yalnızca stratejinin kuralı
                s, why = en.bot_signal_strat(r, b["cfg"])
            else:
                s, why = en.bot_signal_filter(r, b["cfg"])
            if s and t in data["px"]:
                s["entry"] = data["px"][t]            # alım fiyatı: son kapanmış 15 dk mumu
                if s.get("side") == "short":
                    bad_ = s["entry"] >= s["stop"] or (s["tp1"] and s["entry"] <= s["tp1"])
                else:
                    bad_ = s["entry"] <= s["stop"] or (s["tp1"] and s["entry"] >= s["tp1"])
                if bad_:
                    skip.append((t, "price moved out of the plan"))
                    continue
            if s and t not in data["i15"]:
                skip.append((t, "no live 15-minute data"))
                continue
            (sig.append((t, s)) if s else skip.append((t, why)))
        data["sig"][b["id"]] = sig
        data["skip"][b["id"]] = skip[:12]
    return data


def _bot_used(acct, bid, px, eurusd=None):
    """v5.12: botun açık pozisyonlarının hesap parasıyla değeri (canlı fiyat; yoksa giriş fiyatı)."""
    tot = 0.0
    for p in (acct.get("pos") or {}).values():
        if p.get("owner") != bid:
            continue
        sym = p.get("sym")
        last = float((px or {}).get(sym) or p.get("entry") or 0.0)
        fxm = fx_mult(acct.get("ccy", "USD"), inst_ccy(sym), eurusd) or 1.0
        tot += abs(float(p.get("qty") or 0.0)) * last * fxm
    return tot


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

    # 0) v4.9/5.1/5.3: izleyen stop — long'ta yalnızca yükselir, short'ta yalnızca iner (asla geri gitmez)
    for p in acct["pos"].values():
        if p.get("manual_orders"):
            continue
        spec = trail_spec(p)
        if not spec:
            continue
        new = (data.get("chan") or {}).get(f'{p["sym"]}|{spec}')
        short = p.get("side") == "short"
        cur = float(p.get("stop") or 0)
        if new and ((short and (cur <= 0 or new < cur - 1e-9)) or (not short and new > cur + 1e-9)):
            p["stop"] = float(new)
            what = (f'new {int(p["trail_n"])}-day low' if spec[0] == "n" else
                    f'the Kijun ({int(p["trail_kj"])}) moved {"down" if short else "up"}' if spec[0] == "k" else
                    f'the cloud {"top" if short else "bottom"} moved {"down" if short else "up"}')
            log(names.get(p["owner"]) or p.get("bot") or "Bot", p["sym"],
                f'stop {"lowered" if short else "raised"} to {new:.2f} — {what}')

    # 1) çıkışlar (kapanmış 15 dk mumlarıyla)
    def bars_of(p):
        return _bars15(data["i15"].get(p["sym"]), float(p.get("checked") or p.get("opened") or 0))
    ev_x, sells = apply_exits(acct, bars_of, eurusd, now, live=False, log=log)
    events += ev_x
    # 1a) v5.5: bekleyen limit emirleri — 15 dakikalık turda da kontrol edilir
    events += pend_check(acct, {k: float(v) for k, v in data["px"].items() if v}, eurusd, now, log=log)
    # 1b) v5.4: devre kesici — dönem zararı limite ulaştıysa tüm botlar durur, yeni alım yapılmaz
    gs, gnew = guard_eval(acct, demo_value(acct, {k: {"last": v, "src": "real"} for k, v in data["px"].items()},
                                           eurusd), now)
    if gnew:
        events.append({"kind": "breach", "sym": "", "qty": 0.0, "price": 0.0, "bot": "Circuit breaker",
                       "reason": "ACCOUNT BREACHED", "pnl": None, "loss": gs["loss"], "limit": gs["limit"],
                       "period": gs["period"], "paused": gs.get("paused", 0)})
    # 2) alımlar — v5.6: her sembol kendi borsasına göre (kripto / vadeli US seansı dışında da işlem görür)
    hours = bool(BOT_HOURS_ONLY)
    for b in acct.get("bots") or []:
        au_ = (data.get("ichi_auto") or {}).get(b["id"]) or (data.get("pauto") or {}).get(b["id"])
        if au_:                                             # v5.12: was der Bot selbst gewählt hat (Anzeige)
            b["auto"] = au_
        if b.get("src") in ("pairs", "rotation"):          # v5.8: kendi yönetimleri (iki bacak / aylık sepet)
            entries = bool(b.get("on")) and not gs["locked"]
            if not entries and not (b.get("src") == "pairs" and b.get("pt")):
                continue
            fn_ = _pairs_apply if b["src"] == "pairs" else _rot_apply
            try:
                evs_, buys_, sells_, note_ = fn_(acct, b, data, now, eurusd, log, entries)
            except Exception as ex:
                evs_, buys_, sells_, note_ = [], 0, 0, f"error: {type(ex).__name__}: {ex}"[:160]
            events += evs_
            if b.get("on"):
                b["last"] = {"ts": round(now), "checked": int(data["n"].get(b["id"], 0)), "buys": buys_,
                             "sells": sells_, "note": note_}
            continue
        if not b.get("on") or gs["locked"]:
            continue
        bid, cfg = b["id"], en.bot_cfg(b.get("cfg"))
        buys, note = 0, ""
        sigs = data["sig"].get(bid, [])
        if bid in (data.get("err") or {}):
            note = "data error: " + data["err"][bid]
        elif hours and not us_session_open(now) and not any(market_open(sym, now) for sym, _ in sigs):
            note = "markets closed — open positions are still watched"
        else:
            cool = b.setdefault("cool", {})
            for t in [t for t, ts_ in cool.items() if now - ts_ > cfg["cooldown_days"] * 86400]:
                cool.pop(t, None)
            for sym, s in sigs:
                if hours and not market_open(sym, now):
                    note = note or f"{market_label(sym)} closed"
                    continue
                cur_p = acct["pos"].get(f"{sym}|{bid}")
                add = bool(cur_p and int(s.get("stage") or 0) == 2 and int(cur_p.get("stage") or 0) == 1
                           and cur_p.get("side", "long") == s.get("side", "long"))      # v5.3: aşama 2 ekleme
                have = sum(1 for p in acct["pos"].values() if p["owner"] == bid)
                if have >= cfg["max_pos"] and not add:
                    note = note or f"position limit reached ({cfg['max_pos']})"
                    break
                if (cur_p and not add) or (sym in cool and not add):
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
                frac = str(sym).upper().endswith("-USD")             # kripto: kesirli adet
                short = s.get("side") == "short"
                used = _bot_used(acct, bid, data["px"], eurusd)      # v5.12: strateji payının dolu kısmı
                qty = en.bot_size(eq, pend_free(acct), s["entry"], s["stop"], fxm, cfg, frac=frac, used=used)
                if qty < (0.0001 if frac else 1) and used > 0 and \
                        used >= eq * cfg["strat_pct"] / 100.0 - float(s["entry"]) * fxm:
                    note = note or "strategy size reached (%d %% of the account)" % round(cfg["strat_pct"])
                    continue
                if s.get("size_frac"):                               # kademeli mod: ⅓ / ⅔
                    q_ = float(qty) * float(s["size_frac"])
                    qty = (int(q_ * 10000 + 1e-9) / 10000.0) if frac else int(q_ + 1e-9)
                if qty < (0.0001 if frac else 1):
                    log(b["name"], sym, "skipped — not enough cash for one unit at this risk")
                    continue
                plan = dict(s, cfg={k: cfg[k] for k in ("trail_atr", "max_days", "tp1_part")}, checked=bars[-1][0])
                if add:                                              # birleşik pozisyonun stopu geri gitmez
                    old = float(cur_p.get("stop") or 0)
                    if old > 0:
                        plan["stop"] = min(old, s["stop"]) if short else max(old, s["stop"])
                ok, msg, tr = demo_trade(acct, sym, "short" if short else "buy", qty, s["entry"], fxm, bid, s["why"],
                                         plan=plan, ts=now, bot=b["name"])
                if ok:
                    buys += 1
                    events.append({"kind": "short" if short else "buy", "sym": sym, "qty": float(qty),
                                   "price": float(s["entry"]), "bot": b["name"], "reason": s["why"], "pnl": None,
                                   "stop": plan["stop"], "tp1": s["tp1"], "side": "short" if short else "long"})
                    verb = ("ADD (stage 2) " if add else "") + ("SHORT" if short else "BUY")
                    tail = (f'TP1 {s["tp1"]:.2f}' if s["tp1"] else
                            ('no target, stop trails the Kijun (%d)' % int(s["trail_kj"]) if s.get("trail_kj") else
                             ('stage 1 (⅓) — stop just outside the cloud' if s.get("trail_cloud") else
                              f'no target, stop trails the {int(s.get("trail_n") or 20)}-day low')))
                    log(b["name"], sym, f'{verb} {qty:g} @ {s["entry"]:.2f} — {s["why"]} · stop {plan["stop"]:.2f} · '
                                        + tail)
            if not buys and not note:
                sk = data["skip"].get(bid) or []
                note = ("no setup passed — e.g. " + "; ".join(f"{t}: {w}" for t, w in sk[:2])) if sk else \
                    "no setup passed the filter"
        b["last"] = {"ts": round(now), "checked": int(data["n"].get(bid, 0)), "buys": buys,
                     "sells": int(sells.get(bid, 0)), "note": note}
    val = demo_value(acct, {k: {"last": v, "src": "real"} for k, v in data["px"].items()}, eurusd)
    _eq_point(acct, val["equity"], now)
    return events


def _leg_trade(acct, sym, side, qty, price, owner, why, now, name, eurusd, events, extra=None):
    """v5.8: çift / rotasyon botunun tek emri (olay listesine de yazar). Döner: işlem kaydı ya da None."""
    fxm = fx_mult(acct["ccy"], inst_ccy(sym), eurusd)
    if fxm is None:
        return None, "EUR/USD rate not available"
    ok, msg, tr = demo_trade(acct, sym, side, qty, price, fxm, owner, why, ts=now, bot=name)
    if not ok:
        return None, msg
    events.append(dict({"kind": side, "sym": sym, "qty": float(qty), "price": float(price), "bot": name,
                        "reason": why, "pnl": tr["pnl"], "stop": 0.0, "tp1": None,
                        "side": "short" if side in ("short", "cover") else "long"}, **(extra or {})))
    return tr, ""


def _pairs_apply(acct, b, data, now, eurusd, log, entries=True):
    """v5.8 — çift botu: açık çiftleri kapatır (z ortalamada / durdurma / süre / tek bacak kaldı), sonra yeni
    çiftleri açar (|z| ≥ giriş). İki bacak birlikte: biri başarısız olursa diğeri geri alınır. Bacaklarda stop
    yoktur — çıkışı spread belirler. Döner: (olaylar, açılan, kapanan, not)."""
    en = _engine()
    bid, name = b["id"], b["name"]
    cfg = en.bot_cfg(b.get("cfg"))
    pc = en.pair_cfg((b.get("pairs") or {}).get("p"))
    zs = (data.get("pz") or {}).get(bid) or {}
    px = data.get("px") or {}
    openp = b.setdefault("pt", {})
    cool = b.setdefault("cool", {})
    events, opened, closed, notes = [], 0, 0, []
    just_closed = set()                                    # aynı turda ters yöne hemen girilmez (backtest gibi)
    for k, t in list(openp.items()):                       # 1) çıkışlar
        a_, b_ = t["a"], t["b"]
        has_a, has_b = f"{a_}|{bid}" in acct["pos"], f"{b_}|{bid}" in acct["pos"]
        if not has_a and not has_b:
            openp.pop(k, None)
            continue
        zz = zs.get(k)
        days = (now - float(t.get("opened") or now)) / 86400.0
        why = None
        if has_a != has_b:
            why = "one leg was closed — closing the other"
        elif zz is not None:
            z, d = float(zz["z"]), int(t["d"])
            if (d > 0 and z >= -pc["exit"]) or (d < 0 and z <= pc["exit"]):
                why = "spread back at the mean (z %+.2f)" % z
            elif (d > 0 and z <= -pc["stop"]) or (d < 0 and z >= pc["stop"]):
                why = "spread stop (z %+.2f)" % z
            elif not float(zz["beta"]) > 0:
                why = "hedge ratio no longer valid"
        if why is None and days >= pc["max_days"] * 7.0 / 5.0:
            why = "time exit after %d days" % int(days)
        if not why:
            continue
        legs = [x for x, h_ in ((a_, has_a), (b_, has_b)) if h_]
        if not all(market_open(x, now) for x in legs):
            notes.append("%s: exit waits for the market" % k)
            continue
        if not all(px.get(x) for x in legs):
            notes.append("%s: no live price" % k)
            continue
        res = 0.0
        for x in legs:
            p_ = acct["pos"][f"{x}|{bid}"]
            short = p_.get("side") == "short"
            tr, _m = _leg_trade(acct, x, "cover" if short else "sell", p_["qty"], px[x], bid,
                                "Pair %s: %s" % (k, why), now, name, eurusd, events,
                                {"pair": k, "leg": "a" if x == a_ else "b"})
            res += float((tr or {}).get("pnl") or 0.0)
        closed += 1
        openp.pop(k, None)
        just_closed.add(k)
        if "stop" in why:
            cool[k] = now
        log(name, k, "CLOSE pair %s — %s · result %+.2f" % (k, why, res))
    if not entries:
        return events, opened, closed, "; ".join(notes[:2])
    for k in [k for k, ts_ in cool.items() if now - float(ts_) > max(1, cfg["cooldown_days"]) * 86400]:
        cool.pop(k, None)
    val = demo_value(acct, {k: {"last": v, "src": "real"} for k, v in px.items()}, eurusd)
    for k, zz in sorted(zs.items(), key=lambda kv: -abs(kv[1]["z"])):  # 2) girişler — en uç z önce
        if k in openp or k in cool or k in just_closed:
            continue
        if len(openp) >= cfg["max_pos"]:
            notes.append("pair limit reached (%d)" % cfg["max_pos"])
            break
        a_, b_ = k.split("/", 1)
        z, beta = float(zz["z"]), float(zz["beta"])
        d = 1 if z <= -pc["entry"] else (-1 if z >= pc["entry"] else 0)
        if not d or not beta > 0 or abs(z) >= pc["stop"]:
            continue
        if f"{a_}|{bid}" in acct["pos"] or f"{b_}|{bid}" in acct["pos"]:
            notes.append("%s: a symbol is already used by another pair" % k)
            continue
        if not (market_open(a_, now) and market_open(b_, now)):
            notes.append("%s: market closed" % k)
            continue
        pa, pb = px.get(a_), px.get(b_)
        fa, fb = fx_mult(acct["ccy"], inst_ccy(a_), eurusd), fx_mult(acct["ccy"], inst_ccy(b_), eurusd)
        if not (pa and pb and fa and fb):
            notes.append("%s: no live price" % k)
            continue
        gross = min(en.bot_slot(cfg, val["equity"]), max(0.0, pend_free(acct)) * 0.98)   # v5.12: Anteil ÷ Paare
        na = gross / (1.0 + beta)
        qa, qb = na / (pa * fa), (gross - na) / (pb * fb)
        qa = (int(qa * 10000) / 10000.0) if a_.endswith("-USD") else int(qa)
        qb = (int(qb * 10000) / 10000.0) if b_.endswith("-USD") else int(qb)
        if qa <= 0 or qb <= 0:
            notes.append("%s: not enough cash for both legs" % k)
            continue
        sa, sb = ("buy", "short") if d > 0 else ("short", "buy")
        why = "Pair %s: z %+.2f — %s %s, %s %s (hedge β %.2f)" % (k, z, "long" if d > 0 else "short", a_,
                                                                  "short" if d > 0 else "long", b_, beta)
        tr1, m1 = _leg_trade(acct, a_, sa, qa, pa, bid, why, now, name, eurusd, events, {"pair": k, "leg": "a", "z": z})
        if not tr1:
            notes.append("%s: %s" % (k, m1))
            continue
        tr2, m2 = _leg_trade(acct, b_, sb, qb, pb, bid, why, now, name, eurusd, events, {"pair": k, "leg": "b", "z": z})
        if not tr2:                                         # ikinci bacak olmadı → birincisini geri al
            events.pop()
            _leg_trade(acct, a_, "sell" if sa == "buy" else "cover", qa, pa, bid,
                       "Pair %s: second leg failed — first leg undone" % k, now, name, eurusd, [])
            notes.append("%s: %s" % (k, m2))
            continue
        openp[k] = {"a": a_, "b": b_, "d": d, "opened": now, "z0": round(z, 3), "beta": round(beta, 4),
                    "qa": qa, "qb": qb}
        opened += 1
        log(name, k, "OPEN pair %s — %s %g %s @ %.2f + %s %g %s @ %.2f · z %+.2f"
            % (k, sa.upper(), qa, a_, pa, sb.upper(), qb, b_, pb, z))
    note = "; ".join(notes[:2]) if (notes and not opened) else ""
    if not opened and not closed and not note:
        near = sorted(zs.items(), key=lambda kv: -abs(kv[1]["z"]))[:2]
        pa_ = (data.get("pauto") or {}).get(bid)
        if not near and pa_ is not None:                  # v5.12: automatische Paarsuche
            note = ("looking for the best pairs — the daily check is running" if pa_.get("running") else
                    "no usable pair today — the bot checks all candidate pairs again tomorrow")
        else:
            note = (("no pair beyond ±%s yet — closest: " % pc["entry"]) +
                    ", ".join("%s z %+.2f" % (k, v["z"]) for k, v in near)) if near else "no pair data yet"
    return events, opened, closed, note


def _rot_apply(acct, b, data, now, eurusd, log, entries=True):
    """v5.8 — rotasyon botu: ay başında (ya da "şimdi dengele" ile) sepeti yeniler — listeden düşeni satar, yeni
    girenleri eşit ağırlıkla alır (bot payı = hesabın 'max_alloc' %'si; boş kalan yerler güvenli limana / nakde).
    Pazar kapalıysa o emir sonraki tura kalır; ay ancak her emir tamamlanınca 'yapıldı' sayılır."""
    en = _engine()
    bid, name = b["id"], b["name"]
    info = (data.get("rot") or {}).get(bid) or {}
    if not entries:
        return [], 0, 0, ""
    if not info.get("due"):
        return [], 0, 0, "next rebalance at the start of %s" % (
            pd.Timestamp(now, unit="s", tz="UTC").tz_convert(TZ) + pd.offsets.MonthBegin(1)).strftime("%B")
    if info.get("err") or "pick" not in info:
        return [], 0, 0, "rotation: " + (info.get("err") or "no ranking yet")
    cfg = en.bot_cfg(b.get("cfg"))
    rc = en.rot_cfg((b.get("rot") or {}).get("p"))
    px = data.get("px") or {}
    pick, safe, free = list(info["pick"]), info.get("safe"), int(info.get("free") or 0)
    target = list(pick) + ([safe] if (safe and free > 0 and safe not in pick) else [])
    events, buys, sells, notes, pending = [], 0, 0, [], False
    for p_ in [p_ for p_ in acct["pos"].values() if p_["owner"] == bid]:          # 1) listeden düşenleri sat
        sym = p_["sym"]
        if sym in target:
            continue
        if not market_open(sym, now) or not px.get(sym):
            pending = True
            notes.append("%s: sell waits for the market" % sym)
            continue
        tr, m_ = _leg_trade(acct, sym, "cover" if p_.get("side") == "short" else "sell", p_["qty"], px[sym], bid,
                            "Rotation: dropped out of the top %d" % rc["top"], now, name, eurusd, events, {"rot": True})
        if tr:
            sells += 1
            log(name, sym, "SELL %g @ %.2f — dropped out of the top %d (%+.2f)" % (p_["qty"], px[sym], rc["top"],
                                                                                   tr["pnl"] or 0.0))
        else:
            pending = True
    val = demo_value(acct, {k: {"last": v, "src": "real"} for k, v in px.items()}, eurusd)
    per = val["equity"] * cfg["max_alloc"] / 100.0 / rc["top"]
    for sym in target:                                                          # 2) yeni girenleri al
        if f"{sym}|{bid}" in acct["pos"]:
            continue
        if not market_open(sym, now) or not px.get(sym):
            pending = True
            notes.append("%s: buy waits for the market" % sym)
            continue
        fxm = fx_mult(acct["ccy"], inst_ccy(sym), eurusd)
        if not fxm:
            pending = True
            continue
        slots = free if (sym == safe and sym not in pick) else 1
        q = min(per * slots, max(0.0, pend_free(acct)) * 0.99) / (px[sym] * fxm)
        q = (int(q * 10000) / 10000.0) if sym.endswith("-USD") else int(q)
        if q <= 0:
            notes.append("%s: not enough cash" % sym)
            continue
        why = ("Rotation: rank %d of the momentum list" % (pick.index(sym) + 1) if sym in pick else
               "Rotation: safe haven (%s)" % ("market filter is off-risk" if not info.get("risk_on") else
                                              "not enough assets with positive momentum"))
        tr, m_ = _leg_trade(acct, sym, "buy", q, px[sym], bid, why, now, name, eurusd, events, {"rot": True})
        if tr:
            buys += 1
            log(name, sym, "BUY %g @ %.2f — %s" % (q, px[sym], why.split(": ", 1)[-1]))
        else:
            notes.append("%s: %s" % (sym, m_))
    if not pending:
        b["rot_month"] = rot_month(now)
        b.pop("rot_force", None)
        b["rot_last"] = {"ts": round(now), "pick": pick, "risk_on": bool(info.get("risk_on")),
                         "safe": safe if (safe and free > 0) else None, "top": info.get("top") or [],
                         "date": info.get("date")}
    note = ("rebalanced — holding " + (", ".join(target) if target else "cash")) if not pending else \
        ("rebalance in progress — " + "; ".join(notes[:2]))
    return events, buys, sells, note


EXIT_WHY = {"stop": "Stop Loss triggered", "trail": "Trailing Stop triggered", "be": "Break-even Stop triggered",
            "tp1": "Take Profit 1 hit — partial exit, stop moved to entry", "tp": "Take Profit hit"}


def _exit_reason(raw, manual, p):
    """bot_manage gerekçesi → İşlem geçmişindeki "Why" metni (Take Profit hit / Stop Loss triggered …)."""
    r = str(raw or "").lower()
    if r.startswith("time exit"):
        return raw
    if r.startswith("tp1"):
        return EXIT_WHY["tp1"]
    if r.startswith("tp2") or "take" in r:
        return EXIT_WHY["tp"]
    if manual:
        return EXIT_WHY["trail"] if p.get("trail") else EXIT_WHY["stop"]
    if p.get("trail_n") or p.get("trail_kj") or p.get("trail_cloud"):  # Donchian / Ichimoku — iz süren çizgi
        return EXIT_WHY["trail"]
    if r.startswith("trailing"):
        return EXIT_WHY["trail"]
    if r.startswith("break-even"):
        return EXIT_WHY["be"]
    return EXIT_WHY["stop"]


def trail_spec(p):
    """İzleyen stop türü: 'n20' (Donchian dip) · 'k26' (Kijun) · 'c9-26-52l' / 'c9-26-52s' (bulut kenarı) · None."""
    if p.get("trail_n"):
        return f'n{int(p["trail_n"])}'
    if p.get("trail_kj"):
        return f'k{int(p["trail_kj"])}'
    if p.get("trail_cloud"):
        return f'c{p["trail_cloud"]}{"s" if p.get("side") == "short" else "l"}'
    return None


def has_orders(p):
    """Pozisyonun bekleyen Stop-Loss / Take-Profit emri var mı? (bot pozisyonlarında her zaman stop vardır)"""
    if p["owner"] == "manual" and not p.get("manual_orders"):
        return False
    return bool(p.get("stop") or p.get("tp2") or (p.get("tp1") and not p.get("tp1_done")))


def apply_exits(acct, bars_of, eurusd, now, live=False, log=None):
    """Kilit İÇİNDE: emirli tüm pozisyonları verilen mumlarla yönetir (stop, TP1 kısmi, TP / TP2, iz süren stop,
    bot pozisyonlarında süre sınırı). live=True: canlı fiyatla tek "mum" — 'checked' ilerletilmez, süre çıkışı yok.
    Döner: (olaylar, {sahip: satış sayısı})."""
    en = _engine()
    names = {b["id"]: b["name"] for b in acct.get("bots") or []}
    events, sells = [], {}
    for key, p in list(acct["pos"].items()):
        if not has_orders(p):
            continue
        bars = bars_of(p)
        if not bars:
            continue
        p["last"] = bars[-1][4]
        fxm = fx_mult(acct["ccy"], inst_ccy(p["sym"]), eurusd)
        if fxm is None:
            continue
        manual = bool(p.get("manual_orders"))
        if manual:     # kullanıcının emirleri: stop (sabit / iz süren) + hedef; kısmi satış ve süre sınırı yok
            evs, upd = en.bot_manage(dict(p, tp1=0.0, atr=0.0, tp1_done=True), bars, {"trail_atr": 6.0}, None)
        else:
            evs, upd = en.bot_manage(p, bars, p.get("cfg"), None if live else now)
        bname = ("Manual" if p["owner"] == "manual" else (names.get(p["owner"]) or p.get("bot") or "Bot"))
        short = p.get("side") == "short"
        for e in evs:
            why = _exit_reason(e["reason"], manual, p)
            ok, _, tr = demo_trade(acct, p["sym"], "cover" if short else "sell", float(e["qty"]), float(e["price"]),
                                   fxm, p["owner"], why, ts=e["ts"], bot=bname)
            if not ok:
                continue
            events.append({"kind": "cover" if short else "sell", "sym": p["sym"], "qty": float(e["qty"]),
                           "price": float(e["price"]), "bot": bname, "reason": why, "pnl": tr["pnl"],
                           "manual": p["owner"] == "manual", "side": "short" if short else "long"})
            if log:
                log(bname, p["sym"], f'{"COVER" if short else "SELL"} {e["qty"]:g} @ {e["price"]:.2f} — {why} '
                                     f'({tr["pnl"]:+.2f})')
            sells[p["owner"]] = sells.get(p["owner"], 0) + 1
            if p["owner"] != "manual" and not manual and "stop" in why.lower() and tr["pnl"] < 0:
                for b in acct.get("bots") or []:
                    if b["id"] == p["owner"]:
                        b.setdefault("cool", {})[p["sym"]] = now
        if key in acct["pos"]:
            keys = ("stop", "hi", "lo", "tp1_done") if live else ("stop", "hi", "lo", "tp1_done", "checked")
            acct["pos"][key].update({k: upd[k] for k in keys if k in upd})
    return events, sells


_ORD_LAST = {}
EVENT_HOOKS = []             # v5.8: fn(email, hesap adı, olaylar) — ör. broker.py emirleri gerçek hesaba kopyalar
ORD_GAP = 20.0               # aynı hesap için canlı fiyat kontrolleri arası en az (sn)


def _live_hit(p, px):
    """Canlı fiyat bir emri tetikliyor ya da iz süren stopu yukarı taşıyor mu? (kilitsiz ön kontrol)"""
    if px is None or not has_orders(p):
        return False
    stop = float(p.get("stop") or 0)
    if p.get("side") == "short":                  # v5.3: short — her şey aynalı
        if stop and px >= stop:
            return True
        tp1 = float(p.get("tp1") or 0) if not p.get("tp1_done") else 0.0
        tp2 = float(p.get("tp2") or 0)
        if (tp1 and px <= tp1) or (tp2 and px <= tp2):
            return True
        tr_ = float(p.get("trail") or 0)
        if tr_ and stop and px + tr_ < stop - 1e-9:
            return True
        a, done = float(p.get("atr") or 0), bool(p.get("tp1_done"))
        if not p.get("manual_orders") and done and a > 0 and stop:
            mult = float((p.get("cfg") or {}).get("trail_atr") or 2.0)
            return px + mult * a < stop - 1e-9
        return False
    if stop and px <= stop:
        return True
    tp1 = float(p.get("tp1") or 0) if not p.get("tp1_done") else 0.0
    tp2 = float(p.get("tp2") or 0)
    if (tp1 and px >= tp1) or (tp2 and px >= tp2):
        return True
    tr_ = float(p.get("trail") or 0)
    if tr_ and px - tr_ > stop + 1e-9:
        return True
    a, done = float(p.get("atr") or 0), bool(p.get("tp1_done"))
    if not p.get("manual_orders") and done and a > 0:
        mult = float((p.get("cfg") or {}).get("trail_atr") or 2.0)
        return px - mult * a > stop + 1e-9
    return False


def orders_tick(md, only=None, gap=ORD_GAP, now=None):
    """v4.8: Stop-Loss / Take-Profit emirlerini CANLI fiyatla kontrol eder (izleyici her turda, sayfa her açılışta).
    Tetiklenen pozisyon anında kapanır, nakit ve gerçekleşen K/Z güncellenir, işlem geçmişine "Why" ile yazılır.
    Döner: olay listesi [{'email','account','kind','sym','qty','price','reason','pnl', ...}]."""
    now = float(now or time.time())
    out = []
    for email in list(_demo_all()["users"].keys()):
        if only and email != str(only).lower():
            continue
        for acct in list(demo_user(email)["accounts"].values()):
            cand = [p for p in acct["pos"].values() if has_orders(p)]
            pend = pend_list(acct)                       # v5.5: bekleyen limit emirleri
            if not cand and not pend:
                continue
            k = (email, acct["id"])
            if now - _ORD_LAST.get(k, 0) < gap:
                continue
            _ORD_LAST[k] = now
            syms = sorted({p["sym"] for p in cand} | {o["sym"] for o in pend})
            try:
                q = (getattr(md, "get_live_quotes", None) or md.get_quotes)(syms + ["EURUSD=X"])
            except Exception:
                continue
            live = {s_: float(q[s_]["last"]) for s_ in syms
                    if (q.get(s_) or {}).get("src") == "real" and (q.get(s_) or {}).get("last")}
            e_ = q.get("EURUSD=X") or {}
            eurusd = float(e_["last"]) if (e_.get("src") == "real" and e_.get("last")) else acct.get("fx")
            if not (any(_live_hit(p, live.get(p["sym"])) for p in cand)
                    or any(pend_hit(o, live.get(o["sym"]), now) for o in pend)):
                continue
            aid, an = acct["id"], acct.get("name") or "Demo account"

            def run(a, live=live, eurusd=eurusd):
                def log(bot, sym, text):
                    a.setdefault("log", []).append({"ts": round(now), "bot": bot, "sym": sym, "text": text})
                    del a["log"][:-200]
                evs, _ = apply_exits(a, lambda p: ([(now, live[p["sym"]], live[p["sym"]], live[p["sym"]], live[p["sym"]])]
                                                   if p["sym"] in live else []), eurusd, now, live=True, log=log)
                evs = evs + pend_check(a, live, eurusd, now, log=log)        # v5.5: limit emirleri
                if evs:
                    val = demo_value(a, {s_: {"last": v, "src": "real"} for s_, v in live.items()}, eurusd)
                    _eq_point(a, val["equity"], now)
                return evs
            try:
                if aid not in demo_user(email)["accounts"]:
                    continue
                evs = demo_edit(email, run, aid)
            except Exception as ex:
                _MON["err"] = f"orders_tick: {type(ex).__name__}: {ex}"[:200]
                continue
            for e in evs:
                out.append(dict(e, email=email, account=an, acc_id=aid))
            _run_hooks(email, an, evs)
            if evs:
                try:
                    prefs = notify_prefs(profile_get(email))
                    if prefs.get("on") and prefs.get("bot"):
                        for e in evs:
                            if e["kind"] == "limit":
                                deliver(email, prefs, "bot",
                                        f'Limit order filled: {e["side"]} {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}',
                                        f'Your limit of {e["limit"]:g} was reached. Demo account “{an}”.',
                                        sym=e["sym"], tags=["white_check_mark"], priority=3)
                                continue
                            deliver(email, prefs, "bot", f'{e["reason"]}: sold {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}',
                                    f'{e["bot"]} position closed. Result {e["pnl"]:+.2f}. Demo account “{an}”.',
                                    sym=e["sym"], tags=["chart_with_downwards_trend" if e["pnl"] < 0 else "moneybag"],
                                    priority=3)
                except Exception as ex:
                    _MON["err"] = f"orders notify: {type(ex).__name__}: {ex}"[:200]
    return out


def _run_hooks(email, account_name, events):
    """v5.8: olay kancaları (aracı kurum köprüsü vb.) — hata işlemi durdurmaz."""
    if not events:
        return
    for fn_ in list(EVENT_HOOKS):
        try:
            fn_(email, account_name, events)
        except Exception as ex:  # pragma: no cover
            _MON["err"] = f"event hook: {type(ex).__name__}: {ex}"[:200]


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
        for acct in list(demo_user(email)["accounts"].values()):
            n += _bots_tick_acct(md, email, acct, slot, now, force)
    return n


def _bots_tick_acct(md, email, acct, slot, now, force):
    """Tek hesabın 15 dakikalık turu: veriyi kilit dışında topla, hesabı kilit içinde güncelle, haber ver."""
    active = any(b.get("on") for b in acct.get("bots") or [])
    owned = any(has_orders(p) for p in acct["pos"].values()) or bool(acct.get("pend")) or \
        any(b.get("pt") for b in acct.get("bots") or [])          # v5.8: açık çiftler her turda yönetilir
    if not (active or owned) or (not force and acct.get("bot_slot") == slot):
        return 0
    aid = acct["id"]
    try:
        data = bots_collect(md, acct)
    except Exception as ex:
        _MON["err"] = f"bots_collect: {type(ex).__name__}: {ex}"[:200]
        return 0

    def run(a):
        if not force and a.get("bot_slot") == slot:
            return []
        a["bot_slot"] = slot
        return bots_apply(a, data, now)
    try:
        if aid not in demo_user(email)["accounts"]:      # bu arada silindiyse dokunma
            return 0
        events = demo_edit(email, run, aid)
    except Exception as ex:
        _MON["err"] = f"bots_apply: {type(ex).__name__}: {ex}"[:200]
        return 0
    _MON["bots_last"] = now
    _run_hooks(email, acct.get("name") or "Demo account", events)
    n = sum(1 for e in events if e["kind"] != "breach")
    if events:
        try:
            prefs = notify_prefs(profile_get(email))
            an = acct.get("name") or "Demo account"
            if prefs.get("on") and prefs.get("bot"):
                for e in events:
                    if e["kind"] == "breach":
                        deliver(email, prefs, "bot", f'ACCOUNT BREACHED — demo account “{an}”',
                                f'{"Weekly" if e["period"] == "week" else "Monthly"} loss {e["loss"]:.2f} reached the '
                                f'limit {e["limit"]:.2f}. All bots are paused and manual trading is blocked until you '
                                f'raise or switch off the limit, or reset the account.', tags=["rotating_light"],
                                priority=4)
                        continue
                    if e["kind"] == "limit":               # v5.5: bekleyen limit emri doldu
                        title = f'Limit order filled: {e["side"]} {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}'
                        body = f'Your limit of {e["limit"]:g} was reached. Demo account “{an}”.'
                        deliver(email, prefs, "bot", title, body, sym=e["sym"], tags=["white_check_mark"],
                                priority=3)
                        continue
                    if e.get("pair"):                     # v5.8: çift — iki bacak tek bildirimde
                        if e.get("leg") != "a":
                            continue
                        opening = e["kind"] in ("buy", "short")
                        title = f'{e["bot"]}: pair {e["pair"]} {"opened" if opening else "closed"}'
                        body = f'{e["reason"]}. Demo account “{an}”.'
                        deliver(email, prefs, "bot", title, body, sym=e["sym"], tags=["scales"], priority=3)
                        continue
                    if e.get("rot"):                      # v5.8: rotasyon
                        title = f'{e["bot"]}: {"bought" if e["kind"] == "buy" else "sold"} {e["qty"]:g} {e["sym"]} @ ' \
                                f'{e["price"]:.2f}'
                        body = f'{e["reason"]}. Demo account “{an}”.'
                        deliver(email, prefs, "bot", title, body, sym=e["sym"], tags=["arrows_counterclockwise"],
                                priority=3)
                        continue
                    if e["kind"] == "buy":
                        title = f'{e["bot"]}: bought {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}'
                        body = (f'{e["reason"]}. Stop {e["stop"]:.2f} · '
                                + (f'TP1 {e["tp1"]:.2f}' if e.get("tp1") else "no target (trailing stop)")
                                + f'. Demo account “{an}”.')
                    else:
                        title = f'{e["bot"]}: sold {e["qty"]:g} {e["sym"]} @ {e["price"]:.2f}'
                        body = f'{e["reason"]}. Result {e["pnl"]:+.2f}. Demo account “{an}”.'
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
        total += len(orders_tick(md))       # v4.8: Stop-Loss / Take-Profit canlı fiyatla (her turda)
    except Exception as ex:
        _MON["err"] = f"orders_tick: {type(ex).__name__}: {ex}"[:200]
    try:
        total += bots_tick(md)              # v4.3: otomatik işlem botları (15 dakikada bir)
    except Exception as ex:
        _MON["err"] = f"bots_tick: {type(ex).__name__}: {ex}"[:200]
    if state.pop("_dirty", False):
        _state_save(state)
    _MON["ticks"] += 1
    _MON["last"] = time.time()
    return total


ORD_LOOP = 30        # v4.8: tam turlar arasında SL / TP her 30 sn'de bir canlı fiyatla denetlenir


def worker_beat(extra=None):
    """v5.8: worker'ın kalp atışı (yalnızca yerel dosya — arayüz aynı klasörden okur)."""
    w = {"ts": time.time(), "pid": os.getpid(), "ver": BACKEND_VERSION, "ticks": _MON["ticks"],
         "err": _MON["err"], "bots_last": _MON.get("bots_last"), "started": _MON.get("started")}
    w.update(extra or {})
    _local_write("worker", w)
    return w


def worker_info():
    """{'alive', 'age', 'ts', 'pid', …} — paylaşımlı modda 7/24 worker çalışıyor mu?"""
    w = _local_read("worker") or {}
    age = time.time() - float(w.get("ts") or 0)
    return dict(w, age=age, alive=bool(w) and age < WORKER_STALE, shared=SHARED)


def run_worker(md, stop=None, beat=30):
    """v5.8 — 7/24 işçi (worker.py): fiyat alarmları, bilanço / takvim bildirimleri, SL / TP ve limit emirleri
    (30 sn'de bir canlı fiyatla), botlar (15 dakikalık dilimler). Arayüz kapalı ya da uyurken de çalışır.
    stop: threading.Event (testler ve düzgün kapanış için)."""
    _MON["is_worker"] = True
    _MON["started"] = time.time()
    worker_beat({"state": "starting"})
    last_full = 0.0
    while not (stop is not None and stop.is_set()):
        now = time.time()
        if now - last_full >= TICK_SEC:
            last_full = now
            try:
                monitor_tick(md)
            except Exception as ex:  # pragma: no cover
                _MON["err"] = f"{type(ex).__name__}: {ex}"[:200]
        else:
            try:
                orders_tick(md)
            except Exception as ex:  # pragma: no cover
                _MON["err"] = f"orders_tick: {type(ex).__name__}: {ex}"[:200]
        try:
            kv_flush()
        except Exception:  # pragma: no cover
            pass
        worker_beat({"state": "running"})
        end = time.time() + max(1, int(beat))
        while time.time() < end and not (stop is not None and stop.is_set()):
            time.sleep(min(1.0, max(0.05, end - time.time())))
    worker_beat({"state": "stopped", "ts": 0})


def _loop(md):
    time.sleep(20)
    while True:
        if SHARED and worker_info().get("alive"):       # v5.8: 7/24 worker işi yapıyor — arayüz bekler
            time.sleep(ORD_LOOP)
            continue
        try:
            monitor_tick(md)
        except Exception as ex:  # pragma: no cover
            _MON["err"] = f"{type(ex).__name__}: {ex}"[:200]
        try:
            kv_flush()
        except Exception:  # pragma: no cover
            pass
        end = time.time() + TICK_SEC
        while True:
            left = end - time.time()
            if left <= 1:
                break
            time.sleep(min(ORD_LOOP, left))
            if end - time.time() > 1:
                try:
                    if orders_tick(md):
                        kv_flush()
                except Exception as ex:  # pragma: no cover
                    _MON["err"] = f"orders_tick: {type(ex).__name__}: {ex}"[:200]


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
    w = worker_info() if SHARED else {"alive": False, "shared": False}
    return {"running": bool(t is not None and t.is_alive()) or bool(w.get("alive")), "ticks": _MON["ticks"],
            "last": max(_MON["last"] or 0, float(w.get("ts") or 0) if w.get("alive") else 0) or None,
            "err": _MON["err"], "worker": w}
