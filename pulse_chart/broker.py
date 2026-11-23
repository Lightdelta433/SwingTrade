"""
========================================================================
 PULSE → BROKER KÖPRÜSÜ  (broker.py)  —  v5.8 · deneysel, varsayılan KAPALI
========================================================================
7/24 worker'daki bot emirlerini (demo hesabı) gerçek bir aracı kuruma
kopyalar. Önce KAĞIT (paper) hesapta haftalarca dene.

  PULSE_BROKER=log        → hiçbir emir gitmez, yalnızca kayıt (kuru test)
  PULSE_BROKER=ibkr       → Interactive Brokers (TWS / IB Gateway, ib_async)
  PULSE_BROKER_ACCOUNT    → yalnızca bu adı taşıyan demo hesabı kopyalanır (zorunlu)
  PULSE_BROKER_SCALE=0.1  → adet çarpanı (gerçek hesap demo hesaptan küçükse)
  PULSE_BROKER_MAX_ORDER  → tek emrin en fazla değeri (enstrüman para birimi, vars. 2000)
  PULSE_BROKER_MAX_DAY    → günde en fazla emir (vars. 20)
  PULSE_BROKER_LIVE=1     → canlı portlar (TWS 7496 / IB Gateway 4001). Yoksa yalnızca paper (7497 / 4002).
  IBKR_HOST / IBKR_PORT / IBKR_CLIENT_ID → bağlantı (vars. 127.0.0.1 / 7497 / 17)
  Acil durdurma: veri klasörüne STOP_TRADING adlı bir dosya koy → hiçbir emir gitmez.

Desteklenen: ABD hisse / ETF (SMART, USD) ve XETRA (.DE → IBIS, EUR). Vadeli,
kripto, döviz ve diğer borsalar atlanır (kayıtta nedeniyle görünür).
========================================================================
"""

import os
import threading
import time

import backend as bk

BROKER_VERSION = "5.11"
_STATE = {"ib": None, "day": "", "n": 0, "err": ""}
_LOCK = threading.RLock()


def cfg():
    e = os.environ.get
    kind = str(e("PULSE_BROKER") or "").strip().lower()
    live = str(e("PULSE_BROKER_LIVE") or "") == "1"
    try:
        scale = max(0.0, float(e("PULSE_BROKER_SCALE") or 1.0))
        max_order = max(0.0, float(e("PULSE_BROKER_MAX_ORDER") or 2000.0))
        max_day = max(0, int(e("PULSE_BROKER_MAX_DAY") or 20))
        port = int(e("IBKR_PORT") or (7496 if live else 7497))
        cid = int(e("IBKR_CLIENT_ID") or 17)
    except ValueError:
        scale, max_order, max_day, port, cid = 1.0, 2000.0, 20, 7497, 17
    if port in (7496, 4001) and not live:  # canlı portlar (TWS 7496 · IB Gateway 4001) açık onay olmadan yok
        port = 7497 if port == 7496 else 4002
    return {"kind": kind if kind in ("log", "ibkr") else "", "account": str(e("PULSE_BROKER_ACCOUNT") or "").strip(),
            "scale": scale, "max_order": max_order, "max_day": max_day, "live": live,
            "host": str(e("IBKR_HOST") or "127.0.0.1"), "port": port, "client_id": cid}


def enabled():
    c = cfg()
    return bool(c["kind"] and c["account"])


def kill_switch():
    return os.path.exists(os.path.join(bk.DATA_DIR, "STOP_TRADING"))


def ib_contract_spec(sym):
    """Yahoo sembolü → (sembol, borsa, para birimi) ya da (None, neden)."""
    s = str(sym or "").upper().strip()
    if not s or any(ch in s for ch in "=^") or s.endswith("-USD"):
        return None, "futures, FX, indices and crypto are not mirrored"
    if s.endswith(".DE"):
        return (s[:-3], "IBIS", "EUR"), ""
    if "." in s:
        if s.count(".") == 1 and len(s.split(".")[1]) == 1:       # BRK.B → "BRK B"
            return (s.replace(".", " "), "SMART", "USD"), ""
        return None, "exchange not supported by the bridge"
    return (s, "SMART", "USD"), ""


def _log(entry):
    """Köprü kaydı (yerel dosya, son 300) — arayüz ve README'deki kontrol adımı bunu okur."""
    entry = dict(entry, ts=round(time.time()))
    with bk._ILOCK:
        log = bk._local_read("broker_log") or []
        log.append(entry)
        bk._local_write("broker_log", log[-300:])
    return entry


def _count_ok(c):
    day = time.strftime("%Y-%m-%d")
    with _LOCK:
        if _STATE["day"] != day:
            _STATE["day"], _STATE["n"] = day, 0
        if _STATE["n"] >= c["max_day"]:
            return False
        _STATE["n"] += 1
        return True


def _ib(c):
    """ib_async bağlantısı (bir kez açılır, koparsa yeniden)."""
    with _LOCK:
        ib = _STATE["ib"]
        if ib is not None and ib.isConnected():
            return ib
        try:
            from ib_async import IB
        except ImportError:
            try:
                from ib_insync import IB      # eski ad
            except ImportError:
                raise RuntimeError("pip install ib_async")
        ib = IB()
        ib.connect(c["host"], c["port"], clientId=c["client_id"], timeout=15)
        _STATE["ib"] = ib
        return ib


def _ib_place(c, spec, action, qty, ref_px):
    """Pazarlanabilir limit emri (referans fiyatın ±%0.3'ü), gün sonuna kadar geçerli."""
    try:
        from ib_async import Stock, LimitOrder
    except ImportError:
        from ib_insync import Stock, LimitOrder
    ib = _ib(c)
    con = Stock(spec[0], spec[1], spec[2])
    ib.qualifyContracts(con)
    lim = round(ref_px * (1.003 if action == "BUY" else 0.997), 2)
    order = LimitOrder(action, qty, lim, tif="DAY")
    tr = ib.placeOrder(con, order)
    return {"order_id": getattr(getattr(tr, "order", None), "orderId", None), "limit": lim}


def mirror(email, account_name, events):
    """Bot olaylarını aracı kuruma kopyalar. Döner: kayıt listesi. Hata fırlatmaz."""
    c = cfg()
    out = []
    if not c["kind"] or not c["account"] or account_name != c["account"]:
        return out
    for e in events or []:
        kind = e.get("kind")
        if kind not in ("buy", "sell", "short", "cover") or e.get("manual") or str(e.get("bot") or "") in (
                "Manual", "Limit order"):
            continue
        base = {"sym": e.get("sym"), "kind": kind, "demo_qty": e.get("qty"), "price": e.get("price"),
                "bot": e.get("bot"), "mode": c["kind"], "live": c["live"]}
        if kill_switch():
            out.append(_log(dict(base, status="blocked", why="STOP_TRADING file present")))
            continue
        spec, why = ib_contract_spec(e.get("sym"))
        if not spec:
            out.append(_log(dict(base, status="skipped", why=why)))
            continue
        qty = int(float(e.get("qty") or 0) * c["scale"])
        px = float(e.get("price") or 0)
        if qty < 1 or px <= 0:
            out.append(_log(dict(base, status="skipped", why="quantity rounds to 0 at scale %g" % c["scale"])))
            continue
        if qty * px > c["max_order"]:
            qty = int(c["max_order"] // px)
            if qty < 1:
                out.append(_log(dict(base, status="skipped", why="one share is above the max. order value")))
                continue
        if not _count_ok(c):
            out.append(_log(dict(base, status="blocked", why="daily order limit reached (%d)" % c["max_day"])))
            continue
        action = "BUY" if kind in ("buy", "cover") else "SELL"
        if c["kind"] == "log":
            out.append(_log(dict(base, status="logged", qty=qty, action=action, why="dry run — no order sent")))
            continue
        try:
            res = _ib_place(c, spec, action, qty, px)
            out.append(_log(dict(base, status="sent", qty=qty, action=action, **res)))
        except Exception as ex:
            _STATE["err"] = f"{type(ex).__name__}: {ex}"[:200]
            out.append(_log(dict(base, status="error", qty=qty, action=action, why=_STATE["err"])))
    return out


def install():
    """worker.py çağırır: köprü açıksa backend'in olay kancasına bağlanır."""
    if not enabled():
        return False
    if mirror not in bk.EVENT_HOOKS:
        bk.EVENT_HOOKS.append(mirror)
    return True
