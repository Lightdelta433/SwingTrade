"""
========================================================================
 PULSE CHART  (chart.py)  —  v3
========================================================================
TradingView tarzı grafik bileşeninin Python tarafı:

  * `chart_data`   — seçilen zaman aralığı için gerçek OHLCV (gün içi / günlük)
  * `build_payload`— indikatörleri gerçek veriyle hesaplar, JSON'a çevirir
  * `render_chart` — bileşeni çizer ve kullanıcı olaylarını (çizim, alarm,
                     indikatör ayarı, grafik türü) Python'a geri verir
  * `check_alerts` — alarm koşullarını son barlara göre kontrol eder

Arayüz kodu `pulse_chart/index.html` dosyasındadır; bu klasörün app.py ile
aynı yerde olması gerekir.
========================================================================
"""

import base64
import json
import os
import re
import tempfile

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import engine as en
import mock_data as md

CHART_VERSION = "5.3"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_chart")
_INDEX = os.path.join(_DIR, "index.html")

# ----------------------------------------------------------------------
# Mum aralıkları — küçükten büyüğe sıralı (TradingView düzeni)
#   src : (yfinance periyodu, yfinance aralığı) · None = günlük geçmişten türet
#   agg : 0 yok · N saatlik barı N'erli topla · "W" haftalık · "M" aylık
#   bars: açılışta görünen mum sayısı
# ----------------------------------------------------------------------
INTERVALS = {
    "1m":  {"name": "1 minute", "adj": "1-minute",   "short": "1m",  "src": ("5d", "1m"),    "agg": 0,   "bars": 180},
    "5m":  {"name": "5 minutes", "adj": "5-minute",  "short": "5m",  "src": ("1mo", "5m"),   "agg": 0,   "bars": 160},
    "15m": {"name": "15 minutes", "adj": "15-minute", "short": "15m", "src": ("1mo", "15m"),  "agg": 0,   "bars": 130},
    "30m": {"name": "30 minutes", "adj": "30-minute", "short": "30m", "src": ("1mo", "30m"),  "agg": 0,   "bars": 120},
    "1h":  {"name": "1 hour", "adj": "1-hour",     "short": "1H",  "src": ("6mo", "1h"),   "agg": 0,   "bars": 120},
    "4h":  {"name": "4 hours", "adj": "4-hour",    "short": "4H",  "src": ("1y", "1h"),    "agg": 4,   "bars": 90},
    "1d":  {"name": "Daily", "adj": "daily",      "short": "1D",  "src": None,            "agg": 0,   "bars": 150},
    "1wk": {"name": "Weekly", "adj": "weekly",     "short": "1W",  "src": None,            "agg": "W", "bars": 160},
    "1mo": {"name": "Monthly", "adj": "monthly",    "short": "1M",  "src": None,            "agg": "M", "bars": 120},
}
INTERVAL_ORDER = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo"]
DEFAULT_INTERVAL = "1d"
# Eski sürümlerden gelen zaman aralığı kodları
LEGACY_TF = {"1G": "5m", "1H": "30m", "4S": "4h", "1A": "1d", "3A": "1d", "1Y": "1d",
             "5Y": "1wk", "Hf": "1wk"}


def norm_tf(tf):
    """Geçersiz ya da eski kodları geçerli bir aralığa çevirir."""
    if tf in INTERVALS:
        return tf
    return LEGACY_TF.get(tf, DEFAULT_INTERVAL)


def tf_name(tf):
    return INTERVALS[norm_tf(tf)]["name"]


def tf_short(tf):
    return INTERVALS[norm_tf(tf)]["short"]


def is_intraday(tf):
    return bool(INTERVALS[norm_tf(tf)]["src"])


def interval_list():
    """Bileşene gönderilecek liste: [anahtar, tam ad, kısa ad]."""
    return [[k, INTERVALS[k]["name"], INTERVALS[k]["short"]] for k in INTERVAL_ORDER]

# İndikatör varsayılanları — TradingView standartları, arayüzden değiştirilebilir
DEFAULT_CFG = {
    "sma": {"on": True, "ps": [20, 50, 100, 200],
            "cols": ["#5B8CFF", "#F5B544", "#C4B5FD", "#EF5350", "#22D3EE", "#F472B6"]},
    "nw": {"on": False, "h": 8.0, "mult": 3.0, "c": "#22D3EE"},
    "boll": {"on": False, "n": 20, "k": 2.0, "c": "#9AA4B2"},
    "sup": {"on": False, "n": 10, "mult": 3.0, "cu": "#26A69A", "cd": "#EF5350"},
    "vidya": {"on": False, "len": 10, "mom": 20, "mult": 2.0, "cu": "#26A69A", "cd": "#EF5350"},
    "vstop": {"on": False, "n": 20, "mult": 2.0, "cu": "#26A69A", "cd": "#EF5350"},
    # v4.0: yalnızca en önemli 3–4 bölge (uzak / ikincil seviyeler çizilmez)
    "zones": {"on": True, "lookback": 300, "left": 8, "right": 8, "merge": 0.6, "max": 4,
              "cs": "#26A69A", "cr": "#EF5350"},
    "gaps": {"on": True, "lookback": 260, "min": 0.25, "max": 2, "cs": "#26A69A", "cr": "#EF5350"},
    "legend": {"on": False},
    "vol": {"on": True, "cu": "#26A69A", "cd": "#EF5350"},
    "rsi": {"on": True, "len": 14, "ob": 70, "os": 30, "c": "#C4B5FD"},
    "macd": {"on": False, "f": 12, "s": 26, "sig": 9, "c": "#5B8CFF", "cs": "#F5B544"},
    "wt": {"on": False, "n1": 10, "n2": 21, "ob": 60, "os": -60, "c": "#22D3EE", "cs": "#F5B544"},
    "stoch": {"on": False, "k": 14, "d": 3, "smooth": 3, "ob": 80, "os": 20,
              "c": "#5B8CFF", "cs": "#F5B544"},
    "atr": {"on": False, "n": 14, "c": "#F5B544"},
    "div": {"on": False, "src": "rsi", "left": 5, "right": 5, "hidden": True},
}
CONDS = {"cross": "crosses", "above": "rises above", "below": "falls below",
         "cross_up": "crosses above", "cross_dn": "crosses below"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(v, fallback):
    v = str(v or "")
    return v if _HEX.match(v) else fallback


def merge_cfg(user):
    """Kullanıcı ayarlarını varsayılanlarla birleştirir ve sınırlar içinde tutar."""
    out = {}
    for k, d in DEFAULT_CFG.items():
        cur = dict(d)
        u = (user or {}).get(k) or {}
        for f, v in u.items():
            if f not in cur:
                continue
            if f == "ps":
                try:
                    v = [int(x) for x in v if 1 < int(x) < 1000][:6] or d["ps"]
                except (TypeError, ValueError):
                    v = d["ps"]
            elif f == "cols":
                try:
                    v = [_color(x, d["cols"][i % len(d["cols"])]) for i, x in enumerate(list(v)[:6])] or d["cols"]
                except TypeError:
                    v = d["cols"]
            elif isinstance(d[f], str) and d[f].startswith("#"):
                v = _color(v, d[f])
            elif isinstance(d[f], bool):
                v = bool(v)
            elif isinstance(d[f], (int, float)):
                try:
                    v = type(d[f])(v)
                except (TypeError, ValueError):
                    v = d[f]
            cur[f] = v
        cur["on"] = bool(cur.get("on"))
        out[k] = cur
    if out["div"]["src"] not in ("rsi", "macd", "wt"):
        out["div"]["src"] = "rsi"
    out["rsi"]["len"] = int(min(100, max(2, out["rsi"]["len"])))
    out["macd"]["s"] = int(max(out["macd"]["f"] + 1, out["macd"]["s"]))
    out["zones"]["lookback"] = int(min(1200, max(60, out["zones"]["lookback"])))
    out["zones"]["max"] = int(min(4, max(2, out["zones"]["max"])))
    out["gaps"]["lookback"] = int(min(2000, max(20, out["gaps"]["lookback"])))
    out["gaps"]["min"] = float(min(10.0, max(0.05, out["gaps"]["min"])))
    out["gaps"]["max"] = int(min(3, max(1, out["gaps"]["max"])))
    out["nw"]["h"] = float(min(100.0, max(1.0, out["nw"]["h"])))
    out["boll"]["n"] = int(min(200, max(2, out["boll"]["n"])))
    out["stoch"]["k"] = int(min(100, max(2, out["stoch"]["k"])))
    out["atr"]["n"] = int(min(100, max(2, out["atr"]["n"])))
    out["sup"]["n"] = int(min(100, max(2, out["sup"]["n"])))
    out["vstop"]["n"] = int(min(100, max(2, out["vstop"]["n"])))
    out["vidya"]["len"] = int(min(100, max(2, out["vidya"]["len"])))
    out["vidya"]["mom"] = int(min(200, max(2, out["vidya"]["mom"])))
    return out


_OHLC_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _to_4h(df, k=4):
    """Saatlik barları gün içinde k'şarlı gruplayıp 4 saatlik mum üretir (TradingView gibi
    seans başından sayar; yarım kalan son grup kendi mumu olur)."""
    if df is None or df.empty:
        return df
    idx = pd.DatetimeIndex(df.index)
    day = idx.normalize().to_numpy()
    gid = np.zeros(len(df), dtype=np.int64)
    g, cnt = 0, 0
    for i in range(len(df)):
        if i and (day[i] != day[i - 1] or cnt >= k):
            g += 1
            cnt = 0
        gid[i] = g
        cnt += 1
    out = df.groupby(gid).agg(**{c: (c, f) for c, f in _OHLC_AGG.items()})
    out.index = pd.DatetimeIndex(idx[np.searchsorted(gid, out.index.to_numpy())], name="Date")
    out.attrs["src"] = df.attrs.get("src", "real")
    return out


def _resample(df, rule):
    """Günlük barları haftalığa / aylığa çevirir."""
    if df is None or df.empty:
        return df
    out = df.resample(rule).agg(_OHLC_AGG).dropna(subset=["Close"])
    out.attrs["src"] = df.attrs.get("src", "real")
    return out


def _to_weekly(df):
    return _resample(df, "W-FRI")


def _to_monthly(df):
    try:
        return _resample(df, "ME")
    except ValueError:          # eski pandas
        return _resample(df, "M")


# ----------------------------------------------------------------------
# Lookback (geriye bakış) — mum aralığından bağımsız: "son 1 ay, 4 saatlik mumlarla"
#   days: takvim günü · sess: son N işlem günü · None = tüm geçmiş
# ----------------------------------------------------------------------
LOOKBACKS = {
    "1D":  {"name": "1 day",    "sess": 1},
    "5D":  {"name": "5 days",   "sess": 5},
    "1M":  {"name": "1 month",  "days": 31},
    "3M":  {"name": "3 months", "days": 92},
    "6M":  {"name": "6 months", "days": 183},
    "YTD": {"name": "Year to date", "ytd": True},
    "1Y":  {"name": "1 year",   "days": 366},
    "2Y":  {"name": "2 years",  "days": 731},
    "5Y":  {"name": "5 years",  "days": 1827},
    "MAX": {"name": "All data"},
}
LOOKBACK_ORDER = list(LOOKBACKS)
DEFAULT_LOOKBACK = "6M"
# yfinance'in gün içi veriyi geriye ne kadar verdiği (gün)
INTRADAY_LIMIT = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730, "4h": 730}
MAX_KEEP = 6000


def norm_lb(lb):
    return lb if lb in LOOKBACKS else DEFAULT_LOOKBACK


def lb_days(lb):
    """Lookback'in yaklaşık takvim günü karşılığı (veri çekme periyodu seçmek için)."""
    spec = LOOKBACKS[norm_lb(lb)]
    if "sess" in spec:
        return spec["sess"] * 1.5 + 2
    if spec.get("ytd"):
        return (pd.Timestamp.today() - pd.Timestamp(year=pd.Timestamp.today().year, month=1, day=1)).days + 1
    return spec.get("days") or 1e9


def _intraday_period(tf, lb):
    """Gün içi aralık için yfinance periyodu: lookback + gösterge ısınması, sınırı aşmadan."""
    need = lb_days(lb)
    if tf == "1m":
        return "7d"
    if tf in ("5m", "15m", "30m"):
        return "1mo" if need <= 12 else "60d"
    return "3mo" if need <= 35 else "1y" if need <= 200 else "730d"


def lookback_start(idx, lb):
    """Görünür aralığın başlangıç zamanı (None = hepsi)."""
    if idx is None or len(idx) == 0:
        return None
    spec = LOOKBACKS[norm_lb(lb)]
    last = pd.Timestamp(idx[-1])
    if "sess" in spec:
        days = pd.DatetimeIndex(idx).normalize().unique()
        return days[-min(len(days), spec["sess"])]
    if spec.get("ytd"):
        return pd.Timestamp(year=last.year, month=1, day=1, tz=last.tz)
    if spec.get("days"):
        return last - pd.Timedelta(days=spec["days"])
    return None


def visible_bars(full, lb):
    """Lookback penceresine düşen mum sayısı (en az 1)."""
    if full is None or full.empty:
        return 0
    start = lookback_start(full.index, lb)
    if start is None:
        return len(full)
    try:
        n = int((full.index >= start).sum())
    except TypeError:
        n = int((full.index.tz_localize(None) >= start.tz_localize(None)).sum())
    return max(1, n)


def chart_data(sym, tf, lb=None):
    """(veri, gösterilecek mum sayısı, gün içi mi). `lb` verilirse görünür mum sayısı
    lookback penceresinden hesaplanır; verilmezse aralığın varsayılan mum sayısı kullanılır."""
    spec = INTERVALS[norm_tf(tf)]
    tfn = norm_tf(tf)
    if spec["src"]:
        period, interval = spec["src"]
        if lb is not None:
            period = _intraday_period(tfn, lb)
        full = md.get_intraday(sym, period, interval)
        if len(full) > 10:
            if spec["agg"]:
                full = _to_4h(full, int(spec["agg"]))
            n = visible_bars(full, lb) if lb is not None else min(len(full), spec["bars"])
            return full, n, True
        daily = md.get_history(sym)          # gün içi veri yoksa günlüğe düş
        n = visible_bars(daily, lb) if lb is not None else min(len(daily) or 150, INTERVALS["1d"]["bars"])
        return daily, n, False
    daily = md.get_history_max(sym) if (lb is not None and norm_lb(lb) == "MAX") else md.get_history(sym)
    if daily.empty:
        return daily, spec["bars"], False
    out = _to_weekly(daily) if spec["agg"] == "W" else \
        _to_monthly(daily) if spec["agg"] == "M" else daily
    n = visible_bars(out, lb) if lb is not None else min(len(out), spec["bars"])
    return out, n, False


def lookback_note(full, tf, lb, bars, intraday):
    """Seçilen lookback + mum aralığı tam karşılanamıyorsa kısa açıklama (yoksa "")."""
    if full is None or full.empty:
        return ""
    tfn, lbn = norm_tf(tf), norm_lb(lb)
    if is_intraday(tfn) and not intraday:
        return "No intraday data for this symbol — showing daily candles."
    start = lookback_start(full.index, lbn)
    if start is not None and pd.Timestamp(full.index[0]) > start and tfn in INTRADAY_LIMIT:
        return (f"{INTERVALS[tfn]['adj'].capitalize()} candles only go back about {INTRADAY_LIMIT[tfn]} days — "
                f"showing all available data. Pick a larger candle interval to see the full "
                f"{LOOKBACKS[lbn]['name']}.")
    if bars > MAX_KEEP:
        return f"Showing the last {MAX_KEEP:,} candles — pick a larger candle interval for the full range."
    if bars < 3:
        return (f"Only {bars} candle{'s' if bars != 1 else ''} in this period — "
                f"pick a smaller candle interval.")
    return ""


def _ser(s, dec=6):
    out = []
    for v in s:
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(None if f != f else round(f, dec))
    return out


@st.cache_data(ttl=900, show_spinner=False)
def build_payload(sym, tf, cfg_json, data_token, max_bars=900, lb=None):
    """Grafiğin ihtiyaç duyduğu her şeyi tek bir JSON'a toplar (hepsi gerçek veriden)."""
    cfg = merge_cfg(json.loads(cfg_json))
    full, bars_n, intraday = chart_data(sym, tf, lb)
    if full.empty:
        return {"ok": False, "sym": sym}
    bars_n = int(min(bars_n, MAX_KEEP))
    # Görünür aralıktan biraz fazlasını gönder: kullanıcı geriye kaydırabilsin
    keep = int(min(len(full), MAX_KEEP, max(max_bars, bars_n + max(300, bars_n // 2))))
    df = full.tail(keep)
    ind = {}
    if cfg["sma"]["on"]:
        for p in cfg["sma"]["ps"]:
            ind["sma%d" % p] = _ser(en.sma(full["Close"], p).tail(keep))
    if cfg["nw"]["on"]:
        up, lo, mid = en.nadaraya_watson(df["Close"], cfg["nw"]["h"], cfg["nw"]["mult"])
        ind["nw_up"], ind["nw_lo"], ind["nw_mid"] = _ser(up), _ser(lo), _ser(mid)
    if cfg["boll"]["on"]:
        bu, bm, bl = en.bollinger(full["Close"], cfg["boll"]["n"], cfg["boll"]["k"])
        ind["bb_up"], ind["bb_mid"], ind["bb_lo"] = _ser(bu.tail(keep)), _ser(bm.tail(keep)), _ser(bl.tail(keep))
    if cfg["sup"]["on"]:
        sl, sd = en.supertrend(full, cfg["sup"]["n"], cfg["sup"]["mult"])
        ind["sup"], ind["sup_dir"] = _ser(sl.tail(keep)), _ser(sd.tail(keep), 0)
    if cfg["vidya"]["on"]:
        vv, vu, vl, vd, flips = en.vidya(full, cfg["vidya"]["len"], cfg["vidya"]["mom"], cfg["vidya"]["mult"])
        ind["vid"], ind["vid_up"], ind["vid_lo"] = _ser(vv.tail(keep)), _ser(vu.tail(keep)), _ser(vl.tail(keep))
        ind["vid_dir"] = _ser(vd.tail(keep), 0)
        off = len(full) - keep
        ind["vid_flips"] = [[f["i"] - off, f["dir"], round(f["p"], 6)] for f in flips if f["i"] >= off]
    if cfg["vstop"]["on"]:
        vs, vsd = en.volatility_stop(full, cfg["vstop"]["n"], cfg["vstop"]["mult"])
        ind["vstop"], ind["vstop_dir"] = _ser(vs.tail(keep)), _ser(vsd.tail(keep), 0)
    if cfg["stoch"]["on"]:
        sk, sd2 = en.stoch(full, cfg["stoch"]["k"], cfg["stoch"]["d"], cfg["stoch"]["smooth"])
        ind["stoch_k"], ind["stoch_d"] = _ser(sk.tail(keep)), _ser(sd2.tail(keep))
    if cfg["atr"]["on"]:
        ind["atr"] = _ser(en.atr(full, cfg["atr"]["n"]).tail(keep))
    rsi = macd_line = wt1 = None
    if cfg["rsi"]["on"] or (cfg["div"]["on"] and cfg["div"]["src"] == "rsi"):
        rsi = en.rsi(full["Close"], cfg["rsi"]["len"]).tail(keep)
        if cfg["rsi"]["on"]:
            ind["rsi"] = _ser(rsi)
    if cfg["macd"]["on"] or (cfg["div"]["on"] and cfg["div"]["src"] == "macd"):
        line, sig, hist = en.macd(full["Close"], cfg["macd"]["f"], cfg["macd"]["s"], cfg["macd"]["sig"])
        macd_line = line.tail(keep)
        if cfg["macd"]["on"]:
            ind["macd"], ind["macd_sig"], ind["macd_hist"] = \
                _ser(macd_line), _ser(sig.tail(keep)), _ser(hist.tail(keep))
    if cfg["wt"]["on"] or (cfg["div"]["on"] and cfg["div"]["src"] == "wt"):
        a, b = en.wavetrend(full, cfg["wt"]["n1"], cfg["wt"]["n2"])
        wt1 = a.tail(keep)
        if cfg["wt"]["on"]:
            ind["wt1"], ind["wt2"] = _ser(wt1), _ser(b.tail(keep))
    zones = []
    if cfg["zones"]["on"]:
        z = cfg["zones"]
        zones = key_zones(en.ranked_sr_zones(df, z["lookback"], z["left"], z["right"], z["merge"], 14),
                          float(df["Close"].iloc[-1]), z["max"])
    gaps = []
    if cfg["gaps"]["on"]:
        g = cfg["gaps"]
        gaps = [{"lo": round(x["lo"], 6), "hi": round(x["hi"], 6), "kind": x["kind"], "dir": x["dir"],
                 "start": x["i"], "pct": round(x["pct"], 2)}
                for x in en.price_gaps(df, g["lookback"], g["min"], g["max"])]
    divs = []
    if cfg["div"]["on"]:
        osc = {"rsi": rsi, "macd": macd_line, "wt": wt1}.get(cfg["div"]["src"])
        if osc is not None:
            divs = en.divergences(df, osc, cfg["div"]["left"], cfg["div"]["right"],
                                  hidden=cfg["div"]["hidden"])
    bars = [[int(pd.Timestamp(ts).value // 10 ** 6), round(float(o), 6), round(float(h), 6),
             round(float(lo2), 6), round(float(c), 6), float(v)]
            for ts, o, h, lo2, c, v in zip(df.index, df["Open"], df["High"], df["Low"],
                                           df["Close"], df["Volume"])]
    d = md.get_company_detail(sym)
    name = (d or {}).get("name") or md.company_name(sym)
    dec = 4 if sym.endswith("=X") else (0 if float(df["Close"].iloc[-1]) >= 10000 else 2)
    return {"ok": True, "sym": sym, "name": name, "dec": dec,
            "src": df.attrs.get("src", "real"), "intraday": intraday,
            "interval": norm_tf(tf), "intervalName": tf_name(tf), "intervals": interval_list(),
            "bars": bars, "ind": ind, "zones": zones, "gaps": gaps, "divs": divs, "cfg": cfg,
            "visible": bars_n, "lookback": norm_lb(lb) if lb is not None else ""}


ZONE_MAX_DIST = 18.0     # fiyata bundan uzak bantlar çizilmez (%)


def key_zones(zones, px, n=4):
    """En önemli n bant: fiyatın hemen üstündeki direnç ve hemen altındaki destek her zaman,
    kalan yerler güce göre. Zayıf ("Weak") ve uzak bantlar elenir."""
    n = int(max(1, n))
    mid = lambda z: (z["lo"] + z["hi"]) / 2.0
    near = [z for z in zones if px > 0 and abs(mid(z) / px - 1) * 100 <= ZONE_MAX_DIST]
    strong = [z for z in near if not z.get("weak")] or near
    pick = []
    above = sorted([z for z in strong if mid(z) >= px], key=lambda z: mid(z))
    below = sorted([z for z in strong if mid(z) < px], key=lambda z: -mid(z))
    for grp in (above, below):
        if grp:
            pick.append(grp[0])
    for z in sorted(strong, key=lambda z: -z.get("pct", 0)):
        if len(pick) >= n:
            break
        if z not in pick:
            pick.append(z)
    return sorted(pick[:n], key=lambda z: -z.get("pct", 0))


def data_token(sym, tf, lb=None):
    """Fiyat verisi değişince payload önbelleği yenilensin."""
    full, n, _ = chart_data(sym, tf, lb)
    if full.empty:
        return "none"
    return "%s|%d|%d|%s|%.6g" % (full.attrs.get("src"), len(full), n, full.index[-1],
                                 float(full["Close"].iloc[-1]))


# ----------------------------------------------------------------------
# Bileşen
# ----------------------------------------------------------------------
UI_VERSION = "5.3"     # pulse_chart/index.html içindeki <meta name="pulse-ui"> ile aynı olmalı


def frontend_version():
    """Sunucudaki pulse_chart/index.html sürümü; dosya yoksa None, işaret yoksa 'old'."""
    try:
        with open(_INDEX, encoding="utf-8") as fh:
            head = fh.read(4000)
    except OSError:
        return None
    m = re.search(r'name="pulse-ui"\s+content="([^"]+)"', head)
    return m.group(1) if m else "old"


@st.cache_resource(show_spinner=False)
def _component():
    if not os.path.isfile(_INDEX):
        return None
    try:
        return components.declare_component("pulse_chart", path=_DIR)
    except Exception:
        return None


def missing_frontend():
    return not os.path.isfile(_INDEX)


# ----------------------------------------------------------------------
# v4.8 — sıralanabilir liste (izleme listeleri): ⋮⋮ ile sürükle-bırak, ↑ / ↓, isteğe bağlı kaldır
# ----------------------------------------------------------------------
_LIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_list")
_LIST_INDEX = os.path.join(_LIST_DIR, "index.html")


# v5.0: bileşen uygulamaya gömülü — pulse_list/index.html yüklenmemiş olsa bile sürükle-bırak çalışır.
# (_LIST_B64, pulse_list/index.html dosyasının birebir base64 kopyasıdır; sürüm testleri eş olduğunu doğrular.)
_LIST_B64 = (
    "PCFkb2N0eXBlIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij4KPG1ldGEgbmFtZT0i"
    "cHVsc2UtbGlzdCIgY29udGVudD0iNS4yIj4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0"
    "aCxpbml0aWFsLXNjYWxlPTEiPgo8dGl0bGU+UHVsc2Ugc29ydGFibGUgbGlzdDwvdGl0bGU+CjxzdHlsZT4KLyogUHVsc2Ug4oCU"
    "IHPEsXJhbGFuYWJpbGlyIGxpc3RlIChpemxlbWUgbGlzdGVsZXJpKS4gdjUuMDogc2F0xLFyxLFuIEhFUkhBTkfEsCBiaXIgeWVy"
    "aW5kZW4gc8O8csO8a2xlCiAgIChmYXJlOiA2IHB4IGhhcmVrZXRsZSBiYcWfbGFyIMK3IGRva3VubWF0aWs6IGJhc8SxbMSxIHR1"
    "dCwgc29ucmEgc8O8csO8a2xlKSwg4ouu4ouuIHR1dGFtYWPEsSBhbsSxbmRhIHPDvHLDvGtsZXIsCiAgIOKGkSAvIOKGkyBva2xh"
    "csSxIHRlayBrb251bSB0YcWfxLFyOyDimIDvuI8gLyDwn4yZIHNlYW5zIGTEscWfxLEgc2F0xLFyxLEgc2HEn2EgeWFzbMSxIGfD"
    "tnN0ZXJpbGlyLgogICB2NS4yOiBoZWRlZiA9IMSwTUxFQ8SwTiBBTFRJTkRBS8SwIHNhdMSxciAodHV0dWxhbiBub2t0YWRhbiBi"
    "YcSfxLFtc8Sxeik7IGRpxJ9lciBzYXTEsXJsYXIgeWVyaW5kZSBrYWzEsXIsCiAgIG1hdmkgZWtsZW1lIMOnaXpnaXNpICgrIHll"
    "bmkgc8SxcmEgbnVtYXJhc8SxKSBixLFyYWvEsWxhY2FrIHllcmkgdGFtIGfDtnN0ZXJpcjsgYsSxcmFrxLFuY2EgdGFtIHNwbGlj"
    "ZSB0YcWfxLFtYS4gKi8KOnJvb3R7LS1iZzp0cmFuc3BhcmVudDstLXJvdzojMEYxMTE1Oy0tcm93aDojMTUxOTIyOy0tbGluZToj"
    "MUMxRjI1Oy0tdHh0OiNFQ0VFRjE7LS1tdXQ6IzhEOTZBNTstLWRpbTojNUI2MjcwOwogLS1hY2M6IzVCOENGRjstLXVwOiMzRERD"
    "OTc7LS1kb3duOiNGODcxNzE7LS1zZWw6IzE1MTkyMn0KOnJvb3QubGlnaHR7LS1yb3c6I0ZGRkZGRjstLXJvd2g6I0YzRjVGOTst"
    "LWxpbmU6I0U2RTlFRjstLXR4dDojMTQxNzFDOy0tbXV0OiM1QjY0NzU7LS1kaW06IzlBQTJCMTstLXNlbDojRUVGMkZCfQoqe2Jv"
    "eC1zaXppbmc6Ym9yZGVyLWJveH0KW2hpZGRlbl17ZGlzcGxheTpub25lICFpbXBvcnRhbnR9Cmh0bWwsYm9keXttYXJnaW46MDtw"
    "YWRkaW5nOjA7YmFja2dyb3VuZDp2YXIoLS1iZyk7Y29sb3I6dmFyKC0tdHh0KTsKIGZvbnQtZmFtaWx5OiJTb3VyY2UgU2FucyAz"
    "IiwiU291cmNlIFNhbnMgUHJvIixzeXN0ZW0tdWksLWFwcGxlLXN5c3RlbSwiU2Vnb2UgVUkiLHNhbnMtc2VyaWY7Zm9udC1zaXpl"
    "OjEzcHg7CiAtd2Via2l0LWZvbnQtc21vb3RoaW5nOmFudGlhbGlhc2VkO292ZXJmbG93OmhpZGRlbn0KI3dyYXB7cG9zaXRpb246"
    "cmVsYXRpdmU7b3ZlcmZsb3cteTphdXRvO292ZXJmbG93LXg6aGlkZGVuO292ZXJzY3JvbGwtYmVoYXZpb3I6Y29udGFpbjtwYWRk"
    "aW5nOjAgMnB4fQojd3JhcDo6LXdlYmtpdC1zY3JvbGxiYXJ7d2lkdGg6OHB4fQojd3JhcDo6LXdlYmtpdC1zY3JvbGxiYXItdGh1"
    "bWJ7YmFja2dyb3VuZDpjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDMwJSwjMkEyRjM3KTtib3JkZXItcmFkaXVzOjhweH0K"
    "LmhkcntkaXNwbGF5OmdyaWQ7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDo4cHg7cGFkZGluZzo2cHggOHB4IDdweCA4cHg7Zm9udC1z"
    "aXplOjEwLjVweDtmb250LXdlaWdodDo3MDA7CiBsZXR0ZXItc3BhY2luZzouMDdlbTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7"
    "Y29sb3I6dmFyKC0tZGltKTtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1saW5lKX0KLmxpc3R7cG9zaXRpb246cmVsYXRp"
    "dmU7bGlzdC1zdHlsZTpub25lO21hcmdpbjowO3BhZGRpbmc6MH0KLnJvd3tkaXNwbGF5OmdyaWQ7YWxpZ24taXRlbXM6Y2VudGVy"
    "O2dhcDo4cHg7cGFkZGluZzo2cHggOHB4O2JvcmRlci1yYWRpdXM6MTBweDsKIGJhY2tncm91bmQ6dHJhbnNwYXJlbnQ7cG9zaXRp"
    "b246cmVsYXRpdmU7dXNlci1zZWxlY3Q6bm9uZTstd2Via2l0LXVzZXItc2VsZWN0Om5vbmU7LXdlYmtpdC10b3VjaC1jYWxsb3V0"
    "Om5vbmU7CiB0cmFuc2l0aW9uOmJhY2tncm91bmQgLjEycyBlYXNlLGJveC1zaGFkb3cgLjEycyBlYXNlLG9wYWNpdHkgLjEycyBl"
    "YXNlfQoucm93Ky5yb3c6OmJlZm9yZXtjb250ZW50OiIiO3Bvc2l0aW9uOmFic29sdXRlO2xlZnQ6MTBweDtyaWdodDoxMHB4O3Rv"
    "cDowO2hlaWdodDoxcHg7YmFja2dyb3VuZDp2YXIoLS1saW5lKTsKIHBvaW50ZXItZXZlbnRzOm5vbmV9Ci5yb3c6aG92ZXI6OmJl"
    "Zm9yZSwucm93OmhvdmVyKy5yb3c6OmJlZm9yZSwucm93LnNlbDo6YmVmb3JlLC5yb3cuc2VsKy5yb3c6OmJlZm9yZXtvcGFjaXR5"
    "OjB9Ci5yb3c6aG92ZXJ7YmFja2dyb3VuZDp2YXIoLS1yb3doKX0KLnJvdy5zZWx7YmFja2dyb3VuZDp2YXIoLS1zZWwpO2JveC1z"
    "aGFkb3c6aW5zZXQgM3B4IDAgMCB2YXIoLS1hY2MpfQovKiB2NS4yIHPDvHLDvGtsZW1lOiBrYXluYWsgc2F0xLFyIHllcmluZGUg"
    "c29sdWsga2FsxLFyIChuZXJlZGVuIGdlbGRpxJ9pIGJlbGxpKSwgImhheWFsZXQiIGtvcHlhIGltbGVjaSBpemxlciwKICAgZWts"
    "ZW1lIMOnaXpnaXNpIGhlZGVmIGFyYWzEscSfxLEgZ8O2c3RlcmlyIOKAlCBkacSfZXIgc2F0xLFybGFyIEtBWU1BWiwgYsO2eWxl"
    "Y2UgaW1sZWNpbiBhbHTEsW5kYWtpIHNhdMSxciA9IGhlZGVmICovCi5yb3cuc3Jje29wYWNpdHk6LjM2O291dGxpbmU6MXB4IGRh"
    "c2hlZCBjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDUwJSx0cmFuc3BhcmVudCk7b3V0bGluZS1vZmZzZXQ6LTJweH0KLnJv"
    "dy5zcmM6OmJlZm9yZSwucm93LnNyYysucm93OjpiZWZvcmV7b3BhY2l0eTowfQoucm93Lmdob3N0e3Bvc2l0aW9uOmFic29sdXRl"
    "O3RvcDowO2xlZnQ6MnB4O3JpZ2h0OjJweDt6LWluZGV4OjEwO3BvaW50ZXItZXZlbnRzOm5vbmU7dHJhbnNpdGlvbjpub25lOwog"
    "YmFja2dyb3VuZDp2YXIoLS1yb3doKTt3aWxsLWNoYW5nZTp0cmFuc2Zvcm07CiBib3gtc2hhZG93OjAgMTRweCAzMnB4IC0xMHB4"
    "IHJnYmEoMCwwLDAsLjcwKSwwIDAgMCAxcHggY29sb3ItbWl4KGluIHNyZ2IsdmFyKC0tYWNjKSA1MCUsdHJhbnNwYXJlbnQpfQo6"
    "cm9vdC5saWdodCAucm93Lmdob3N0e2JveC1zaGFkb3c6MCAxMnB4IDI4cHggLTEwcHggcmdiYSgyMCwyMywyOCwuMzApLDAgMCAw"
    "IDFweCBjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDQ1JSx0cmFuc3BhcmVudCl9Ci5yb3cuZ2hvc3QgLmh7Y29sb3I6dmFy"
    "KC0tYWNjKX0KLmRyb3BsaW5le3Bvc2l0aW9uOmFic29sdXRlO3RvcDowO2xlZnQ6NnB4O3JpZ2h0OjZweDtoZWlnaHQ6MnB4O2Jv"
    "cmRlci1yYWRpdXM6MnB4O3otaW5kZXg6MTI7cG9pbnRlci1ldmVudHM6bm9uZTsKIGJhY2tncm91bmQ6dmFyKC0tYWNjKTt3aWxs"
    "LWNoYW5nZTp0cmFuc2Zvcm07CiBib3gtc2hhZG93OjAgMCAwIDFweCBjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDI1JSx0"
    "cmFuc3BhcmVudCksMCAwIDEwcHggY29sb3ItbWl4KGluIHNyZ2IsdmFyKC0tYWNjKSA2MCUsdHJhbnNwYXJlbnQpfQouZHJvcGxp"
    "bmU6OmFmdGVye2NvbnRlbnQ6IiI7cG9zaXRpb246YWJzb2x1dGU7cmlnaHQ6LTNweDt0b3A6NTAlO3dpZHRoOjZweDtoZWlnaHQ6"
    "NnB4O21hcmdpbi10b3A6LTNweDtib3JkZXItcmFkaXVzOjUwJTsKIGJhY2tncm91bmQ6dmFyKC0tYWNjKX0KLmRsLW57cG9zaXRp"
    "b246YWJzb2x1dGU7bGVmdDotNHB4O3RvcDo1MCU7dHJhbnNmb3JtOnRyYW5zbGF0ZVkoLTUwJSk7bWluLXdpZHRoOjE4cHg7aGVp"
    "Z2h0OjE4cHg7cGFkZGluZzowIDVweDsKIGJvcmRlci1yYWRpdXM6OXB4O2JhY2tncm91bmQ6dmFyKC0tYWNjKTtjb2xvcjojZmZm"
    "O2ZvbnQ6ODAwIDEwLjVweC8xOHB4IHVpLW1vbm9zcGFjZSxTRk1vbm8tUmVndWxhcixNZW5sbyxtb25vc3BhY2U7CiB0ZXh0LWFs"
    "aWduOmNlbnRlcjtib3gtc2hhZG93OjAgMCAwIDJweCByZ2JhKDEwLDExLDEzLC41NSl9Cjpyb290LmxpZ2h0IC5kbC1ue2JveC1z"
    "aGFkb3c6MCAwIDAgMnB4IHJnYmEoMjU1LDI1NSwyNTUsLjkpfQouZHJvcGxpbmUudG9wIC5kbC1ue3RyYW5zZm9ybTp0cmFuc2xh"
    "dGVZKC0zcHgpfQouZHJvcGxpbmUuYm90IC5kbC1ue3RyYW5zZm9ybTp0cmFuc2xhdGVZKGNhbGMoLTEwMCUgKyAzcHgpKX0KI3dy"
    "YXAuZHJhZ2dpbmcgLnJvdzpob3ZlcntiYWNrZ3JvdW5kOnRyYW5zcGFyZW50fQojd3JhcC5kcmFnZ2luZywjd3JhcC5kcmFnZ2lu"
    "ZyAqe2N1cnNvcjpncmFiYmluZyAhaW1wb3J0YW50fQoucm93Lm1vdmVke2FuaW1hdGlvbjpmbGFzaCAuN3MgZWFzZX0KQGtleWZy"
    "YW1lcyBmbGFzaHswJXtiYWNrZ3JvdW5kOmNvbG9yLW1peChpbiBzcmdiLHZhcigtLWFjYykgMjIlLHRyYW5zcGFyZW50KX0xMDAl"
    "e2JhY2tncm91bmQ6dHJhbnNwYXJlbnR9fQouaHt3aWR0aDoxOHB4O2hlaWdodDoyOHB4O2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVt"
    "czpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjtjb2xvcjp2YXIoLS1kaW0pO2N1cnNvcjpncmFiOwogYm9yZGVyLXJhZGl1"
    "czo2cHg7dG91Y2gtYWN0aW9uOm5vbmU7Zm9udC1zaXplOjE1cHg7bGV0dGVyLXNwYWNpbmc6LTNweDtsaW5lLWhlaWdodDoxO291"
    "dGxpbmU6bm9uZX0KLmg6aG92ZXIsLmg6Zm9jdXMtdmlzaWJsZXtjb2xvcjp2YXIoLS10eHQpO2JhY2tncm91bmQ6Y29sb3ItbWl4"
    "KGluIHNyZ2IsdmFyKC0tYWNjKSAxNCUsdHJhbnNwYXJlbnQpfQouYXZ7cG9zaXRpb246cmVsYXRpdmU7ZGlzcGxheTppbmxpbmUt"
    "ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjtib3JkZXItcmFkaXVzOjUwJTtvdmVyZmxvdzpo"
    "aWRkZW47CiBmbGV4Om5vbmU7Zm9udC13ZWlnaHQ6ODAwO2xldHRlci1zcGFjaW5nOi0uMDJlbX0KLmF2IGltZ3twb3NpdGlvbjph"
    "YnNvbHV0ZTtpbnNldDowO3dpZHRoOjEwMCU7aGVpZ2h0OjEwMCU7b2JqZWN0LWZpdDpjb250YWluO2JhY2tncm91bmQ6I0YxRjJG"
    "NDtwYWRkaW5nOjNweH0KLm5te21pbi13aWR0aDowO2xpbmUtaGVpZ2h0OjEuMjU7Y3Vyc29yOmRlZmF1bHR9Ci5jbGlja2FibGUg"
    "Lm5te2N1cnNvcjpwb2ludGVyfQoubm0gYntkaXNwbGF5OmJsb2NrO2ZvbnQtZmFtaWx5OnVpLW1vbm9zcGFjZSxTRk1vbm8tUmVn"
    "dWxhcixNZW5sbyxtb25vc3BhY2U7Zm9udC1zaXplOjEyLjVweDt3aGl0ZS1zcGFjZTpub3dyYXA7CiBvdmVyZmxvdzpoaWRkZW47"
    "dGV4dC1vdmVyZmxvdzplbGxpcHNpc30KLm5tIGl7ZGlzcGxheTpibG9jaztmb250LXN0eWxlOm5vcm1hbDtjb2xvcjp2YXIoLS1t"
    "dXQpO2ZvbnQtc2l6ZToxMXB4O3doaXRlLXNwYWNlOm5vd3JhcDtvdmVyZmxvdzpoaWRkZW47CiB0ZXh0LW92ZXJmbG93OmVsbGlw"
    "c2lzfQouY3t0ZXh0LWFsaWduOnJpZ2h0O2ZvbnQtZmFtaWx5OnVpLW1vbm9zcGFjZSxTRk1vbm8tUmVndWxhcixNZW5sbyxtb25v"
    "c3BhY2U7Zm9udC12YXJpYW50LW51bWVyaWM6dGFidWxhci1udW1zOwogd2hpdGUtc3BhY2U6bm93cmFwO2xpbmUtaGVpZ2h0OjEu"
    "MjU7bWluLXdpZHRoOjA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9Ci5jIC5ze2Rpc3BsYXk6YmxvY2s7"
    "Zm9udC1zaXplOjExcHg7Zm9udC13ZWlnaHQ6NzAwfQouYXJ7ZGlzcGxheTpmbGV4O2dhcDoycHh9Ci5hciBidXR0b24sLnJte3dp"
    "ZHRoOjI0cHg7aGVpZ2h0OjI0cHg7Ym9yZGVyLXJhZGl1czo3cHg7Ym9yZGVyOjFweCBzb2xpZCB0cmFuc3BhcmVudDtiYWNrZ3Jv"
    "dW5kOnRyYW5zcGFyZW50O2NvbG9yOnZhcigtLWRpbSk7CiBmb250LXNpemU6MTNweDtsaW5lLWhlaWdodDoxO2N1cnNvcjpwb2lu"
    "dGVyO2Rpc3BsYXk6aW5saW5lLWZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpjZW50ZXI7cGFkZGluZzow"
    "fQouYXIgYnV0dG9uOmhvdmVyOm5vdCg6ZGlzYWJsZWQpe2NvbG9yOnZhcigtLXR4dCk7Ym9yZGVyLWNvbG9yOmNvbG9yLW1peChp"
    "biBzcmdiLHZhcigtLWFjYykgNDUlLHRyYW5zcGFyZW50KTsKIGJhY2tncm91bmQ6Y29sb3ItbWl4KGluIHNyZ2IsdmFyKC0tYWNj"
    "KSAxMiUsdHJhbnNwYXJlbnQpfQouYXIgYnV0dG9uOmRpc2FibGVke29wYWNpdHk6LjI1O2N1cnNvcjpkZWZhdWx0fQoucm06aG92"
    "ZXJ7Y29sb3I6dmFyKC0tZG93bik7Ym9yZGVyLWNvbG9yOnJnYmEoMjQ4LDExMywxMTMsLjQ1KTtiYWNrZ3JvdW5kOnJnYmEoMjQ4"
    "LDExMywxMTMsLjA4KX0KLmVtcHR5e2NvbG9yOnZhcigtLW11dCk7cGFkZGluZzoxMnB4IDZweDtmb250LXNpemU6MTIuNXB4fQou"
    "ZXh0cXtncmlkLWNvbHVtbjozLy0xO2dyaWQtcm93OjI7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpmbGV4LWVuZDthbGln"
    "bi1pdGVtczpiYXNlbGluZTtnYXA6N3B4OwogbWFyZ2luLXRvcDoxcHg7Zm9udC1mYW1pbHk6dWktbW9ub3NwYWNlLFNGTW9uby1S"
    "ZWd1bGFyLE1lbmxvLG1vbm9zcGFjZTtmb250LXZhcmlhbnQtbnVtZXJpYzp0YWJ1bGFyLW51bXM7CiBmb250LXNpemU6MTAuNXB4"
    "O2ZvbnQtd2VpZ2h0OjYwMDt3aGl0ZS1zcGFjZTpub3dyYXA7b3ZlcmZsb3c6aGlkZGVuO21pbi13aWR0aDowfQouZXh0cSBpe2Zv"
    "bnQtc3R5bGU6bm9ybWFsO2ZvbnQtc2l6ZToxMHB4O2ZvbnQtZmFtaWx5OiJTZWdvZSBVSSBFbW9qaSIsIk5vdG8gQ29sb3IgRW1v"
    "amkiLHNhbnMtc2VyaWZ9Ci5leHRxIGJ7Zm9udC13ZWlnaHQ6NzAwO2NvbG9yOnZhcigtLXR4dCl9Ci5zcntwb3NpdGlvbjphYnNv"
    "bHV0ZTt3aWR0aDoxcHg7aGVpZ2h0OjFweDtvdmVyZmxvdzpoaWRkZW47Y2xpcDpyZWN0KDAgMCAwIDApfQo8L3N0eWxlPgo8L2hl"
    "YWQ+Cjxib2R5Pgo8ZGl2IGlkPSJ3cmFwIj48ZGl2IGlkPSJoZHIiIGNsYXNzPSJoZHIiIGhpZGRlbj48L2Rpdj48dWwgaWQ9Imxp"
    "c3QiIGNsYXNzPSJsaXN0IiByb2xlPSJsaXN0Ym94Ij48L3VsPgo8ZGl2IGlkPSJlbXB0eSIgY2xhc3M9ImVtcHR5IiBoaWRkZW4+"
    "PC9kaXY+PC9kaXY+CjxkaXYgaWQ9ImxpdmUiIGNsYXNzPSJzciIgYXJpYS1saXZlPSJwb2xpdGUiPjwvZGl2Pgo8c2NyaXB0Pgoi"
    "dXNlIHN0cmljdCI7CmNvbnN0IGluU3RyZWFtbGl0ID0gd2luZG93LnBhcmVudCAmJiB3aW5kb3cucGFyZW50ICE9PSB3aW5kb3c7"
    "CmNvbnN0IFMgPSB7cm93czogW10sIG9wdHM6IHt9LCBuOiAwLCBkcmFnOiBudWxsLCBzZW50OiBbXSwgdmlzOiAwfTsKY29uc3Qg"
    "d3JhcCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ3cmFwIiksIGxpc3QgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibGlz"
    "dCIpOwoKZnVuY3Rpb24gc3RTZW5kKHR5cGUsIGRhdGEpeyBpZighaW5TdHJlYW1saXQpIHJldHVybjsKICB3aW5kb3cucGFyZW50"
    "LnBvc3RNZXNzYWdlKE9iamVjdC5hc3NpZ24oe2lzU3RyZWFtbGl0TWVzc2FnZTogdHJ1ZSwgdHlwZTogdHlwZX0sIGRhdGEgfHwg"
    "e30pLCAiKiIpOyB9CmZ1bmN0aW9uIHNlbmQoZXYpewogIFMubiA9IE1hdGgubWF4KFMubiArIDEsIERhdGUubm93KCkpOyAgICAg"
    "Ly8gaWZyYW1lIHllbmlkZW4gecO8a2xlbnNlIGRlIChzZWttZSBkZcSfacWfaW1pKSBzYXlhw6cgaGVwIHllbmkg4oaSIG9sYXkg"
    "a2F5Ym9sbWF6CiAgY29uc3QgdiA9IE9iamVjdC5hc3NpZ24oe246IFMubiwga2V5OiBTLm9wdHMua2V5IHx8ICIifSwgZXYpOwog"
    "IFMuc2VudC5wdXNoKHYpOwogIHN0U2VuZCgic3RyZWFtbGl0OnNldENvbXBvbmVudFZhbHVlIiwge3ZhbHVlOiB2LCBkYXRhVHlw"
    "ZTogImpzb24ifSk7Cn0KZnVuY3Rpb24gZXNjKHMpeyByZXR1cm4gU3RyaW5nKHMgPT0gbnVsbCA/ICIiIDogcykucmVwbGFjZSgv"
    "WyY8PiInXS9nLCBjID0+ICh7IiYiOiImYW1wOyIsIjwiOiImbHQ7IiwiPiI6IiZndDsiLAogICciJzoiJnF1b3Q7IiwiJyI6IiYj"
    "Mzk7In0pW2NdKTsgfQoKLyogZGFyIGVrcmFuZGEgKHRlbGVmb24pIHPDvHR1bmxhciBzb25kYW4gZ2l6bGVuaXIg4oCUIHNhecSx"
    "bGFyIGFzbGEgdGHFn21heiAvIGtlc2lsbWV6LCBhZCBzw7x0dW51IGVuIGF6IDgwIHB4IGthbMSxciAqLwpmdW5jdGlvbiB2aXND"
    "b2xzKCl7CiAgY29uc3QgY29scyA9IFMub3B0cy5jb2xzIHx8IFtdLCBjb2x3ID0gUy5vcHRzLmNvbHcgfHwgW107CiAgY29uc3Qg"
    "VyA9ICh3cmFwLmNsaWVudFdpZHRoIHx8IGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5jbGllbnRXaWR0aCB8fCA0MDApIC0gNDsK"
    "ICBjb25zdCBweCA9IHcgPT4gcGFyc2VGbG9hdCh3KSB8fCA3MDsKICBjb25zdCBmaXhlZCA9IGsgPT4gMTggKyAoUy5vcHRzLmF2"
    "IHx8IDI2KSArIGNvbHcuc2xpY2UoMCwgaykucmVkdWNlKChhLCB3KSA9PiBhICsgcHgodyksIDApICsgNTIKICAgICsgKFMub3B0"
    "cy5yZW1vdmFibGUgPyAyNCA6IDApICsgOCAqICgzICsgayArIChTLm9wdHMucmVtb3ZhYmxlID8gMSA6IDApKSArIDE2OwogIGxl"
    "dCBuID0gY29scy5sZW5ndGg7CiAgd2hpbGUobiA+IDEgJiYgVyAtIGZpeGVkKG4pIDwgODApIG4tLTsKICByZXR1cm4gbjsKfQpm"
    "dW5jdGlvbiBncmlkKCl7CiAgY29uc3QgbmMgPSBTLnZpczsKICByZXR1cm4gIjE4cHggIiArIChTLm9wdHMuYXYgfHwgMjYpICsg"
    "InB4IG1pbm1heCgwLDFmcikgIiArIChTLm9wdHMuY29sdyB8fCBbXSkuc2xpY2UoMCwgbmMpLm1hcCh3ID0+IHcgfHwgImF1dG8i"
    "KS5qb2luKCIgIikKICAgICsgIiA1MnB4IiArIChTLm9wdHMucmVtb3ZhYmxlID8gIiAyNHB4IiA6ICIiKTsKfQoKZnVuY3Rpb24g"
    "ZXh0SFRNTChyKXsKICBjb25zdCBlID0gci5leHQ7CiAgaWYoIWUgfHwgZS5weCA9PSBudWxsKSByZXR1cm4gIiI7CiAgcmV0dXJu"
    "ICc8c3BhbiBjbGFzcz0iZXh0cSIgdGl0bGU9IicgKyBlc2MoZS5sYWIgfHwgIiIpICsgJyDigJQgY2hhbmdlIHZzIHRoZSByZWd1"
    "bGFyIGNsb3NlIj48aSBzdHlsZT0iY29sb3I6JwogICAgKyBlc2MoZS5pYyB8fCAidmFyKC0tbXV0KSIpICsgJyI+JyArIGVzYyhl"
    "LmkgfHwgIiIpICsgJzwvaT48Yj4nICsgZXNjKGUucHgpICsgJzwvYj48c3BhbiBzdHlsZT0iY29sb3I6JwogICAgKyBlc2MoZS5j"
    "IHx8ICJ2YXIoLS1tdXQpIikgKyAnIj4nICsgZXNjKGUudCB8fCAiIikgKyAnPC9zcGFuPjwvc3Bhbj4nOwp9CgpmdW5jdGlvbiBy"
    "b3dIVE1MKHIsIGksIG4pewogIGNvbnN0IHN6ID0gUy5vcHRzLmF2IHx8IDI2OwogIGNvbnN0IGF2ID0gJzxzcGFuIGNsYXNzPSJh"
    "diIgc3R5bGU9IndpZHRoOicgKyBzeiArICdweDtoZWlnaHQ6JyArIHN6ICsgJ3B4O2ZvbnQtc2l6ZTonICsgTWF0aC5tYXgoOSwg"
    "TWF0aC5yb3VuZChzeiAqIC4zNCkpCiAgICArICdweDtiYWNrZ3JvdW5kOicgKyBlc2Moci5hdmJnIHx8ICIjMjYzMDNGIikgKyAn"
    "O2NvbG9yOicgKyBlc2Moci5hdmZnIHx8ICIjQzlEM0UzIikgKyAnIj4nICsgZXNjKHIuaW5pIHx8ICI/IikKICAgICsgKHIubG9n"
    "byA/ICc8aW1nIHNyYz0iJyArIGVzYyhyLmxvZ28pICsgJyIgYWx0PSIiIGxvYWRpbmc9ImxhenkiIG9uZXJyb3I9InRoaXMucmVt"
    "b3ZlKCkiPicgOiAiIikgKyAnPC9zcGFuPic7CiAgY29uc3QgY2VsbHMgPSAoci5jZWxscyB8fCBbXSkuc2xpY2UoMCwgUy52aXMp"
    "Lm1hcChjID0+ICc8c3BhbiBjbGFzcz0iYyI+JyArIChjLnYgIT0gbnVsbCA/ICc8c3BhbicgKyAoYy5jID8gJyBzdHlsZT0iY29s"
    "b3I6JyArIGVzYyhjLmMpICsgJyInIDogIiIpCiAgICArIChjLmIgPyAnIGNsYXNzPSJzIicgOiAiIikgKyAnPicgKyBlc2MoYy52"
    "KSArICc8L3NwYW4+JyA6ICIiKQogICAgKyAoYy5zICE9IG51bGwgPyAnPHNwYW4gY2xhc3M9InMiJyArIChjLnNjID8gJyBzdHls"
    "ZT0iY29sb3I6JyArIGVzYyhjLnNjKSArICciJyA6ICIiKSArICc+JyArIGVzYyhjLnMpICsgJzwvc3Bhbj4nIDogIiIpCiAgICAr"
    "ICc8L3NwYW4+Jykuam9pbigiIik7CiAgcmV0dXJuICc8bGkgY2xhc3M9InJvdycgKyAoci5zZWwgPyAiIHNlbCIgOiAiIikgKyAn"
    "IiByb2xlPSJvcHRpb24iIGRhdGEtaWQ9IicgKyBlc2Moci5pZCkgKyAnIiBzdHlsZT0iZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOicK"
    "ICAgICsgZ3JpZCgpICsgJyI+JwogICAgKyAnPHNwYW4gY2xhc3M9ImgiIHRhYmluZGV4PSIwIiByb2xlPSJidXR0b24iIGFyaWEt"
    "bGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgKGRyYWcsIG9yIHVzZSB0aGUgYXJyb3cga2V5cykiICcKICAgICsgJ3Rp"
    "dGxlPSJEcmFnIHRvIHJlb3JkZXIiPuKLruKLrjwvc3Bhbj4nICsgYXYKICAgICsgJzxzcGFuIGNsYXNzPSJubSIgdGl0bGU9Iicg"
    "KyBlc2Moci5zdWIgfHwgIiIpICsgJyI+PGI+JyArIGVzYyhyLnRpdGxlKSArICc8L2I+PGk+JyArIGVzYyhyLnN1YiB8fCAiIikg"
    "KyAnPC9pPjwvc3Bhbj4nCiAgICArIGNlbGxzCiAgICArIGV4dEhUTUwocikKICAgICsgJzxzcGFuIGNsYXNzPSJhciI+PGJ1dHRv"
    "biBjbGFzcz0idXAiIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgdXAiIHRpdGxlPSJNb3ZlIHVwIicgKyAo"
    "aSA9PT0gMCA/ICIgZGlzYWJsZWQiIDogIiIpCiAgICArICc+4oaRPC9idXR0b24+PGJ1dHRvbiBjbGFzcz0iZG4iIGFyaWEtbGFi"
    "ZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgZG93biIgdGl0bGU9Ik1vdmUgZG93biInICsgKGkgPT09IG4gLSAxID8gIiBk"
    "aXNhYmxlZCIgOiAiIikKICAgICsgJz7ihpM8L2J1dHRvbj48L3NwYW4+JwogICAgKyAoUy5vcHRzLnJlbW92YWJsZSA/ICc8YnV0"
    "dG9uIGNsYXNzPSJybSIgYXJpYS1sYWJlbD0iUmVtb3ZlICcgKyBlc2Moci50aXRsZSkgKyAnIiB0aXRsZT0iUmVtb3ZlIj7Dlzwv"
    "YnV0dG9uPicgOiAiIikKICAgICsgJzwvbGk+JzsKfQoKZnVuY3Rpb24gcmVuZGVyKCl7CiAgY29uc3Qgcm93cyA9IFMucm93cywg"
    "biA9IHJvd3MubGVuZ3RoOwogIFMudmlzID0gdmlzQ29scygpOwogIGNvbnN0IGhkciA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlk"
    "KCJoZHIiKSwgZW0gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZW1wdHkiKTsKICB3cmFwLmNsYXNzTGlzdC50b2dnbGUoImNs"
    "aWNrYWJsZSIsICEhUy5vcHRzLmNsaWNrYWJsZSk7CiAgaWYoUy5vcHRzLmNvbHMgJiYgUy5vcHRzLmNvbHMuc29tZShCb29sZWFu"
    "KSAmJiBuKXsKICAgIGhkci5oaWRkZW4gPSBmYWxzZTsKICAgIGhkci5zdHlsZS5ncmlkVGVtcGxhdGVDb2x1bW5zID0gZ3JpZCgp"
    "OwogICAgaGRyLmlubmVySFRNTCA9ICc8c3Bhbj48L3NwYW4+PHNwYW4+PC9zcGFuPjxzcGFuPicgKyBlc2MoUy5vcHRzLnRpdGxl"
    "X2NvbCB8fCAiIikgKyAnPC9zcGFuPicKICAgICAgKyBTLm9wdHMuY29scy5zbGljZSgwLCBTLnZpcykubWFwKGMgPT4gJzxzcGFu"
    "IHN0eWxlPSJ0ZXh0LWFsaWduOnJpZ2h0Ij4nICsgZXNjKGMpICsgJzwvc3Bhbj4nKS5qb2luKCIiKQogICAgICArICc8c3Bhbj48"
    "L3NwYW4+JyArIChTLm9wdHMucmVtb3ZhYmxlID8gIjxzcGFuPjwvc3Bhbj4iIDogIiIpOwogIH0gZWxzZSBoZHIuaGlkZGVuID0g"
    "dHJ1ZTsKICBlbS5oaWRkZW4gPSBuID4gMDsKICBlbS50ZXh0Q29udGVudCA9IFMub3B0cy5lbXB0eSB8fCAiVGhlIGxpc3QgaXMg"
    "ZW1wdHkuIjsKICBsaXN0LmlubmVySFRNTCA9IHJvd3MubWFwKChyLCBpKSA9PiByb3dIVE1MKHIsIGksIG4pKS5qb2luKCIiKTsK"
    "ICBmaXQoKTsKfQoKZnVuY3Rpb24gZml0KCl7CiAgY29uc3QgZnVsbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJoZHIiKS5v"
    "ZmZzZXRIZWlnaHQgKyBsaXN0Lm9mZnNldEhlaWdodCArIChTLnJvd3MubGVuZ3RoID8gMCA6IDQ2KSArIDQ7CiAgY29uc3QgaCA9"
    "IE1hdGgubWF4KDQwLCBNYXRoLm1pbihmdWxsLCBTLm9wdHMubWF4X2ggfHwgNDIwKSk7CiAgd3JhcC5zdHlsZS5oZWlnaHQgPSBo"
    "ICsgInB4IjsKICBzdFNlbmQoInN0cmVhbWxpdDpzZXRGcmFtZUhlaWdodCIsIHtoZWlnaHQ6IGh9KTsKfQoKZnVuY3Rpb24gb3Jk"
    "ZXIoKXsgcmV0dXJuIFsuLi5saXN0LmNoaWxkcmVuXS5tYXAobGkgPT4gbGkuZGF0YXNldC5pZCk7IH0KZnVuY3Rpb24gc2F5KHQp"
    "eyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibGl2ZSIpLnRleHRDb250ZW50ID0gdDsgfQoKLyogdjUuMjogVEFNIGRpemkgdGHF"
    "n8SxbWEgKHNwbGljZSkg4oCUIHRha2FzIERFxJ7EsEwuIMOWxJ9lIGVza2kgaW5kZWtzaW5kZW4gw6fEsWthcsSxbMSxciB2ZSB0"
    "YW0gaGVkZWYgaW5kZWtzZSBla2xlbmlyOgogICBhcmFkYWtpIMO2xJ9lbGVyIHRhbSBiaXIga29udW0ga2F5YXIsIGdlcmkga2Fs"
    "YW4gaGVya2VzIGfDtnJlbGkgc8SxcmFzxLFuxLEga29ydXIuCiAgIMOWcm4uIFtOVkRBLCBBQVBMXSDihpIgQUFQTCBiaXIgeXVr"
    "YXLEsTogW0FBUEwsIE5WREFdIMK3IDUuIHPEsXJhZGFuIDEuJ3llOiAx4oCTNCBhcmFzxLEgdGFtIGJpciBhxZ9hxJ/EsSBrYXlh"
    "ci4gKi8KZnVuY3Rpb24gYXJyYXlNb3ZlKGxpc3QsIGZyb21JbmRleCwgdG9JbmRleCl7CiAgY29uc3QgW21vdmVkXSA9IGxpc3Qu"
    "c3BsaWNlKGZyb21JbmRleCwgMSk7CiAgbGlzdC5zcGxpY2UodG9JbmRleCwgMCwgbW92ZWQpOwogIHJldHVybiBsaXN0Owp9Cgpm"
    "dW5jdGlvbiBjb21taXQocHJldiwgZmxhc2hJZCl7CiAgY29uc3Qgbm93ID0gb3JkZXIoKTsKICBpZihub3cuam9pbigiXHUwMDAx"
    "IikgPT09IHByZXYuam9pbigiXHUwMDAxIikpIHJldHVybjsKICBjb25zdCBieUlkID0ge307IFMucm93cy5mb3JFYWNoKHIgPT4g"
    "YnlJZFtyLmlkXSA9IHIpOwogIFMucm93cyA9IG5vdy5tYXAoaWQgPT4gYnlJZFtpZF0pOwogIC8vIFN0cmVhbWxpdCd0ZW4gRVNL"
    "xLAgc8SxcmF5bGEgZ2VjaWttacWfIGJpciDDp2l6aW0gZ2VsaXJzZSB5ZW5pIHPEsXJhecSxIGdlcmkgYWxtYXPEsW4gKGHFn2HE"
    "n8SxZGEgYXBwbHlBcmdzKQogIFMuZ3VhcmQgPSB7cHJldjogcHJldi5qb2luKCJcdTAwMDEiKSwgbm93OiBub3cuc2xpY2UoKSwg"
    "dW50aWw6IERhdGUubm93KCkgKyA2MDAwfTsKICByZW5kZXIoKTsKICBjb25zdCBsaSA9IGxpc3QucXVlcnlTZWxlY3RvcignLnJv"
    "d1tkYXRhLWlkPSInICsgQ1NTLmVzY2FwZShmbGFzaElkKSArICciXScpOwogIGlmKGxpKXsgbGkuY2xhc3NMaXN0LmFkZCgibW92"
    "ZWQiKTsgfQogIHNlbmQoe3Q6ICJvcmRlciIsIG9yZGVyOiBub3csIG1vdmVkOiBmbGFzaElkLCBmcm9tOiBwcmV2LmluZGV4T2Yo"
    "Zmxhc2hJZCksIHRvOiBub3cuaW5kZXhPZihmbGFzaElkKX0pOwogIHNheShmbGFzaElkICsgIiBtb3ZlZCB0byBwb3NpdGlvbiAi"
    "ICsgKG5vdy5pbmRleE9mKGZsYXNoSWQpICsgMSkpOwp9CgpmdW5jdGlvbiByZW9yZGVyRG9tKG5leHQpewogIGNvbnN0IGJ5SWQg"
    "PSB7fTsgWy4uLmxpc3QuY2hpbGRyZW5dLmZvckVhY2gobGkgPT4gYnlJZFtsaS5kYXRhc2V0LmlkXSA9IGxpKTsKICBuZXh0LmZv"
    "ckVhY2goeCA9PiBsaXN0LmFwcGVuZENoaWxkKGJ5SWRbeF0pKTsKfQoKZnVuY3Rpb24gbW92ZShpLCBqKXsgICAgICAgICAgICAg"
    "ICAgICAgICAgIC8vIOKGkSAvIOKGkyAvIGtsYXZ5ZTogaSDihpIgaiAoaW5kZWtzKSwgYXluxLEgc3BsaWNlIGt1cmFsxLEKICBj"
    "b25zdCBwcmV2ID0gb3JkZXIoKTsKICBpZihqIDwgMCB8fCBqID49IHByZXYubGVuZ3RoIHx8IGkgPT09IGopIHJldHVybjsKICBj"
    "b25zdCBpZCA9IHByZXZbaV07CiAgcmVvcmRlckRvbShhcnJheU1vdmUocHJldi5zbGljZSgpLCBpLCBqKSk7CiAgY29tbWl0KHBy"
    "ZXYsIGlkKTsKICBjb25zdCBoID0gbGlzdC5xdWVyeVNlbGVjdG9yKCcucm93W2RhdGEtaWQ9IicgKyBDU1MuZXNjYXBlKGlkKSAr"
    "ICciXSAuaCcpOyBpZihoKSBoLmZvY3VzKHtwcmV2ZW50U2Nyb2xsOiBmYWxzZX0pOwp9CgovKiAtLS0tIHPDvHLDvGtsZS1ixLFy"
    "YWs6IHNhdMSxcsSxbiBIRVJIQU5HxLAgYmlyIHllcmluZGVuIChsb2dvLCBhZCwgZml5YXQpIC0tLS0KICAgZmFyZTogNiBweCBk"
    "aWtleSBoYXJla2V0bGUgYmHFn2xhciAodMSxa2xhbWEgImHDpyIgb2xhcmFrIGthbMSxcikgwrcg4ouu4ouuIHR1dGFtYWPEsTog"
    "YW7EsW5kYQogICBkb2t1bm1hdGlrIC8ga2FsZW06IDMwMCBtcyBiYXPEsWzEsSB0dXQgKGtheWTEsXJtYSBzZXJiZXN0IGthbMSx"
    "ciksIHNvbnJhIHPDvHLDvGtsZSAqLwpjb25zdCBIT0xEX01TID0gMzAwLCBNT1VTRV9TTE9QID0gNiwgVE9VQ0hfU0xPUCA9IDEw"
    "OwpTLnBlbmQgPSBudWxsOyBTLmp1c3REcmFnZ2VkID0gMDsKCi8qIGltbGVjaW4gbGlzdGUgacOnZXJpxJ9pbmRla2kgeSBrb251"
    "bXUgKGxpc3RlIGtheWTEsXLEsWxtxLHFnyBvbHNhIGRhIGRvxJ9ydSkgKi8KZnVuY3Rpb24gY29udGVudFkoY2xpZW50WSl7IHJl"
    "dHVybiBjbGllbnRZIC0gbGlzdC5nZXRCb3VuZGluZ0NsaWVudFJlY3QoKS50b3A7IH0KCi8qIGhlZGVmIGluZGVrcyA9IGltbGVj"
    "aW4gQUxUSU5EQUvEsCBzYXTEsXIuIFNhdMSxcmxhciBzw7xyw7xrbGVtZSBib3l1bmNhIHllcmluZGUgZHVydXIgKGtheWTEsXJt"
    "YSBhbmltYXN5b251IHlvayksCiAgIHlhbmkgZWtyYW5kYSDDvHplcmluZSBnZWxpbmVuIHNhdMSxciBpbGUgaGVzYXBsYW5hbiBo"
    "ZWRlZiBoZXIgemFtYW4gYXluxLFkxLFyLiDDnHN0dGUg4oaSIDAsIGFsdHRhIOKGkiBzb24uICovCmZ1bmN0aW9uIHRhcmdldElu"
    "ZGV4KGN5KXsKICBjb25zdCByb3dzID0gUy5kcmFnLnJvd3M7IGxldCB0byA9IDA7CiAgZm9yKGxldCBrID0gMDsgayA8IHJvd3Mu"
    "bGVuZ3RoOyBrKyspeyBpZihjeSA+PSByb3dzW2tdLm9mZnNldFRvcCkgdG8gPSBrOyBlbHNlIGJyZWFrOyB9CiAgcmV0dXJuIHRv"
    "Owp9CgpmdW5jdGlvbiBzdGFydERyYWcobGksIGNhcEVsLCBlKXsKICBjb25zdCByb3dzID0gWy4uLmxpc3QuY2hpbGRyZW5dLCBm"
    "cm9tID0gcm93cy5pbmRleE9mKGxpKTsKICB0cnl7IGNhcEVsLnNldFBvaW50ZXJDYXB0dXJlKGUucG9pbnRlcklkKTsgfWNhdGNo"
    "KF8peyB9CiAgY29uc3QgZyA9IGxpLmNsb25lTm9kZSh0cnVlKTsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8g"
    "aW1sZWNpIGl6bGV5ZW4gaGF5YWxldAogIGcuY2xhc3NMaXN0LnJlbW92ZSgic2VsIiwgIm1vdmVkIik7IGcuY2xhc3NMaXN0LmFk"
    "ZCgiZ2hvc3QiKTsKICBnLnJlbW92ZUF0dHJpYnV0ZSgicm9sZSIpOyBnLnNldEF0dHJpYnV0ZSgiYXJpYS1oaWRkZW4iLCAidHJ1"
    "ZSIpOwogIGcucXVlcnlTZWxlY3RvckFsbCgiYnV0dG9uLFt0YWJpbmRleF0iKS5mb3JFYWNoKHggPT4geC5zZXRBdHRyaWJ1dGUo"
    "InRhYmluZGV4IiwgIi0xIikpOwogIGNvbnN0IGxuID0gZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgiZGl2Iik7ICAgICAgICAgICAg"
    "ICAgICAgICAgIC8vIGVrbGVtZSDDp2l6Z2lzaSArIHllbmkgc8SxcmEgbnVtYXJhc8SxCiAgbG4uY2xhc3NOYW1lID0gImRyb3Bs"
    "aW5lIjsgbG4uaGlkZGVuID0gdHJ1ZTsgbG4uaW5uZXJIVE1MID0gJzxzcGFuIGNsYXNzPSJkbC1uIj48L3NwYW4+JzsKICB3cmFw"
    "LmFwcGVuZENoaWxkKGcpOyB3cmFwLmFwcGVuZENoaWxkKGxuKTsKICBTLmRyYWcgPSB7bGk6IGxpLCBpZDogbGkuZGF0YXNldC5p"
    "ZCwgZnJvbTogZnJvbSwgdG86IGZyb20sIGxhc3RUbzogZnJvbSwgcm93czogcm93cywgcHJldjogb3JkZXIoKSwKICAgICAgICAg"
    "ICAgZ2hvc3Q6IGcsIGxpbmU6IGxuLCBjeTA6IGNvbnRlbnRZKGUuY2xpZW50WSksIHRvcDA6IGxpLm9mZnNldFRvcCwgaDogbGku"
    "b2Zmc2V0SGVpZ2h0LAogICAgICAgICAgICB5OiBlLmNsaWVudFksIHJhZjogMH07CiAgbGkuY2xhc3NMaXN0LmFkZCgic3JjIik7"
    "IHdyYXAuY2xhc3NMaXN0LmFkZCgiZHJhZ2dpbmciKTsKICBwbGFjZSgpOwogIFMuZHJhZy5yYWYgPSByZXF1ZXN0QW5pbWF0aW9u"
    "RnJhbWUoZWRnZVNjcm9sbCk7CiAgc2F5KCJNb3ZpbmcgIiArIGxpLmRhdGFzZXQuaWQgKyAiIOKAlCByZWxlYXNlIHRvIGRyb3As"
    "IEVzY2FwZSB0byBjYW5jZWwiKTsKfQoKLyogaGF5YWxldGkgaW1sZWNlIGfDtnJlIHllcmxlxZ90aXIsIGhlZGVmaSBoZXNhcGxh"
    "LCBla2xlbWUgw6dpemdpc2luaSBoZWRlZiBhcmFsxLHEn2Ega295ICovCmZ1bmN0aW9uIHBsYWNlKCl7CiAgY29uc3QgZCA9IFMu"
    "ZHJhZzsgaWYoIWQpIHJldHVybjsKICBjb25zdCBjeSA9IGNvbnRlbnRZKGQueSksIGxvID0gbGlzdC5vZmZzZXRUb3A7CiAgbGV0"
    "IHRvcCA9IGQudG9wMCArIChjeSAtIGQuY3kwKTsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8gdHV0dWxhbiBub2t0"
    "YSBrb3J1bnVyCiAgdG9wID0gTWF0aC5tYXgoLWQuaCAqIDAuNSwgTWF0aC5taW4obGlzdC5vZmZzZXRIZWlnaHQgLSBkLmggKiAw"
    "LjUsIHRvcCkpOwogIGQuZ2hvc3Quc3R5bGUudHJhbnNmb3JtID0gInRyYW5zbGF0ZVkoIiArIChsbyArIHRvcCkgKyAicHgpIjsK"
    "ICBjb25zdCB0byA9IHRhcmdldEluZGV4KGN5KTsKICBkLnRvID0gdG87CiAgaWYodG8gPT09IGQuZnJvbSl7CiAgICBkLmxpbmUu"
    "aGlkZGVuID0gdHJ1ZTsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8ga2VuZGkgeWVyaW5kZSDihpIg"
    "ZGXEn2nFn2lrbGlrIHlvawogIH0gZWxzZSB7CiAgICBjb25zdCByID0gZC5yb3dzW3RvXTsKICAgIC8vIHl1a2FyxLEgdGHFn8Sx"
    "bWE6IGhlZGVmIHNhdMSxcsSxbiDDnFNUw5xORSDCtyBhxZ9hxJ/EsSB0YcWfxLFtYTogaGVkZWYgc2F0xLFyxLFuIEFMVElOQQog"
    "ICAgY29uc3QgeSA9IHRvIDwgZC5mcm9tID8gci5vZmZzZXRUb3AgOiByLm9mZnNldFRvcCArIHIub2Zmc2V0SGVpZ2h0OwogICAg"
    "Y29uc3QgeXkgPSBNYXRoLm1heCgxLCBNYXRoLm1pbih3cmFwLnNjcm9sbEhlaWdodCAtIDEsIGxvICsgeSkpOwogICAgZC5saW5l"
    "LmhpZGRlbiA9IGZhbHNlOwogICAgZC5saW5lLnN0eWxlLnRyYW5zZm9ybSA9ICJ0cmFuc2xhdGVZKCIgKyAoeXkgLSAxKSArICJw"
    "eCkiOwogICAgZC5saW5lLmNsYXNzTGlzdC50b2dnbGUoInRvcCIsIHl5IDwgMTEpOyAgICAgICAgICAgICAgICAgICAgIC8vIG51"
    "bWFyYSBrZW5hcmRhIGtlc2lsbWVzaW4g4oaSIGnDp2Uga2F0bGEKICAgIGQubGluZS5jbGFzc0xpc3QudG9nZ2xlKCJib3QiLCB5"
    "eSA+IHdyYXAuc2Nyb2xsSGVpZ2h0IC0gMTEpOwogICAgZC5saW5lLmZpcnN0Q2hpbGQudGV4dENvbnRlbnQgPSBTdHJpbmcodG8g"
    "KyAxKTsKICB9CiAgaWYodG8gIT09IGQubGFzdFRvKXsKICAgIGQubGFzdFRvID0gdG87CiAgICBzYXkodG8gPT09IGQuZnJvbSA/"
    "ICJCYWNrIGF0IGl0cyBwbGFjZSIgOiAiRHJvcCBhdCBwb3NpdGlvbiAiICsgKHRvICsgMSkpOwogIH0KfQoKLyoga2VuYXJhIHlh"
    "a2xhxZ/EsW5jYSAoaW1sZcOnIGR1cnNhIGJpbGUpIHl1bXXFn2FrIG90b21hdGlrIGtheWTEsXJtYSDigJQgemFtYW5hIGJhxJ9s"
    "xLEsIGthcmUgaMSxesSxbmRhbiBiYcSfxLFtc8SxejoKICAga2VuYXJhIG5lIGthZGFyIHlha8SxbnNhIG8ga2FkYXIgaMSxemzE"
    "sSAoa2VuYXLEsW4gZMSxxZ/EsW5kYSBlbiBmYXpsYSB+MTMwMCBweC9zKSAqLwpmdW5jdGlvbiBlZGdlU2Nyb2xsKHRzKXsKICBj"
    "b25zdCBkID0gUy5kcmFnOyBpZighZCkgcmV0dXJuOwogIGNvbnN0IGR0ID0gZC50cyA/IE1hdGgubWluKDUwLCB0cyAtIGQudHMp"
    "IDogMTY7IGQudHMgPSB0czsKICBpZih3cmFwLnNjcm9sbEhlaWdodCA+IHdyYXAuY2xpZW50SGVpZ2h0ICsgMSl7CiAgICBjb25z"
    "dCB3ciA9IHdyYXAuZ2V0Qm91bmRpbmdDbGllbnRSZWN0KCksIFogPSAyODsKICAgIGxldCBwcm94ID0gMDsKICAgIGlmKGQueSA8"
    "IHdyLnRvcCArIFopIHByb3ggPSAtTWF0aC5taW4oMS41LCAod3IudG9wICsgWiAtIGQueSkgLyBaKTsKICAgIGVsc2UgaWYoZC55"
    "ID4gd3IuYm90dG9tIC0gWikgcHJveCA9IE1hdGgubWluKDEuNSwgKGQueSAtICh3ci5ib3R0b20gLSBaKSkgLyBaKTsKICAgIGlm"
    "KHByb3gpewogICAgICBkLmFjYyA9IChkLmFjYyB8fCAwKSArIHByb3ggKiAwLjkgKiBkdDsgICAgICAgICAgICAgICAgICAgIC8v"
    "IHB4IGJpcmlraW1pIChhbHQtcGlrc2VsIGtheWJvbG1hc8SxbikKICAgICAgY29uc3Qgc3RlcCA9IGQuYWNjID4gMCA/IE1hdGgu"
    "Zmxvb3IoZC5hY2MpIDogTWF0aC5jZWlsKGQuYWNjKTsKICAgICAgaWYoc3RlcCl7IGQuYWNjIC09IHN0ZXA7IGNvbnN0IHMwID0g"
    "d3JhcC5zY3JvbGxUb3A7IHdyYXAuc2Nyb2xsVG9wICs9IHN0ZXA7IGlmKHdyYXAuc2Nyb2xsVG9wICE9PSBzMCkgcGxhY2UoKTsg"
    "fQogICAgfSBlbHNlIGQuYWNjID0gMDsKICB9CiAgZC5yYWYgPSByZXF1ZXN0QW5pbWF0aW9uRnJhbWUoZWRnZVNjcm9sbCk7Cn0K"
    "ZnVuY3Rpb24gY2xlYXJQZW5kKCl7IGNvbnN0IHAgPSBTLnBlbmQ7IGlmKHAgJiYgcC50aW1lcikgY2xlYXJUaW1lb3V0KHAudGlt"
    "ZXIpOyBTLnBlbmQgPSBudWxsOyB9CgpsaXN0LmFkZEV2ZW50TGlzdGVuZXIoInBvaW50ZXJkb3duIiwgZnVuY3Rpb24oZSl7CiAg"
    "aWYoZS5idXR0b24gPiAwIHx8IFMuZHJhZykgcmV0dXJuOwogIGlmKGUudGFyZ2V0LmNsb3Nlc3QoIi5hciwucm0iKSkgcmV0dXJu"
    "OyAgICAgICAgICAgICAgICAgICAgICAvLyBva2xhciB2ZSDDlyBzw7xyw7xrbGVtZSBiYcWfbGF0bWF6CiAgY29uc3QgbGkgPSBl"
    "LnRhcmdldC5jbG9zZXN0KCIucm93Iik7IGlmKCFsaSkgcmV0dXJuOwogIGNvbnN0IGggPSBlLnRhcmdldC5jbG9zZXN0KCIuaCIp"
    "OwogIGlmKGgpeyBlLnByZXZlbnREZWZhdWx0KCk7IHN0YXJ0RHJhZyhsaSwgaCwgZSk7IHJldHVybjsgfSAgICAvLyB0dXRhbWHD"
    "pzogYW7EsW5kYQogIGNvbnN0IHRvdWNoID0gZS5wb2ludGVyVHlwZSAhPT0gIm1vdXNlIjsKICBjb25zdCBwID0ge2xpOiBsaSwg"
    "eDA6IGUuY2xpZW50WCwgeTA6IGUuY2xpZW50WSwgZXY6IHtwb2ludGVySWQ6IGUucG9pbnRlcklkLCBjbGllbnRZOiBlLmNsaWVu"
    "dFl9LCB0aW1lcjogbnVsbH07CiAgaWYodG91Y2gpIHAudGltZXIgPSBzZXRUaW1lb3V0KGZ1bmN0aW9uKCl7ICAgICAgICAgICAg"
    "ICAgICAgIC8vIGJhc8SxbMSxIHR1dCDihpIgc8O8csO8a2xlCiAgICBpZihTLnBlbmQgPT09IHAgJiYgIVMuZHJhZyl7IFMucGVu"
    "ZCA9IG51bGw7IHN0YXJ0RHJhZyhwLmxpLCBwLmxpLCBwLmV2KTsgfSB9LCBIT0xEX01TKTsKICBTLnBlbmQgPSBwOyAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC8vIGZhcmU6IGhhcmVrZXQgZcWfacSfaW5pIGJla2xl"
    "Cn0pOwpkb2N1bWVudC5hZGRFdmVudExpc3RlbmVyKCJ0b3VjaG1vdmUiLCBmdW5jdGlvbihlKXsgaWYoUy5kcmFnKSBlLnByZXZl"
    "bnREZWZhdWx0KCk7IH0sIHtwYXNzaXZlOiBmYWxzZX0pOwoKbGlzdC5hZGRFdmVudExpc3RlbmVyKCJwb2ludGVybW92ZSIsIGZ1"
    "bmN0aW9uKGUpewogIGNvbnN0IHAgPSBTLnBlbmQ7CiAgaWYocCAmJiAhUy5kcmFnKXsKICAgIGNvbnN0IGR4ID0gTWF0aC5hYnMo"
    "ZS5jbGllbnRYIC0gcC54MCksIGR5ID0gTWF0aC5hYnMoZS5jbGllbnRZIC0gcC55MCk7CiAgICBpZihlLnBvaW50ZXJUeXBlID09"
    "PSAibW91c2UiKXsKICAgICAgaWYoZHkgPiBNT1VTRV9TTE9QICYmIGR5ID4gZHgpeyBjbGVhclBlbmQoKTsgc3RhcnREcmFnKHAu"
    "bGksIHAubGksIHtwb2ludGVySWQ6IGUucG9pbnRlcklkLCBjbGllbnRZOiBwLnkwfSk7IH0KICAgICAgZWxzZSBpZihkeCA+IDE0"
    "KSBjbGVhclBlbmQoKTsKICAgIH0gZWxzZSBpZihkeCA+IFRPVUNIX1NMT1AgfHwgZHkgPiBUT1VDSF9TTE9QKSBjbGVhclBlbmQo"
    "KTsgLy8gcGFybWFrIGtheWTEsXLEsXlvciDihpIgbm9ybWFsIHNjcm9sbAogIH0KICBjb25zdCBkID0gUy5kcmFnOyBpZighZCkg"
    "cmV0dXJuOwogIGQueSA9IGUuY2xpZW50WTsKICBwbGFjZSgpOwp9KTsKZnVuY3Rpb24gZW5kRHJhZyhjYW5jZWwpewogIGNsZWFy"
    "UGVuZCgpOwogIGNvbnN0IGQgPSBTLmRyYWc7IGlmKCFkKSByZXR1cm47CiAgUy5kcmFnID0gbnVsbDsKICBjYW5jZWxBbmltYXRp"
    "b25GcmFtZShkLnJhZik7CiAgZC5naG9zdC5yZW1vdmUoKTsgZC5saW5lLnJlbW92ZSgpOwogIGQubGkuY2xhc3NMaXN0LnJlbW92"
    "ZSgic3JjIik7IHdyYXAuY2xhc3NMaXN0LnJlbW92ZSgiZHJhZ2dpbmciKTsKICBjb25zdCB0byA9IGNhbmNlbCA9PT0gdHJ1ZSA/"
    "IGQuZnJvbSA6IGQudG87CiAgY29uc3Qgc3Rhc2ggPSBTLnN0YXNoOyBTLnN0YXNoID0gbnVsbDsKICBpZih0byAhPT0gZC5mcm9t"
    "KXsKICAgIFMuanVzdERyYWdnZWQgPSBEYXRlLm5vdygpOyAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyBoZW1l"
    "biBhcmTEsW5kYW4gZ2VsZW4gY2xpY2sgImHDpyIgc2F5bWFzxLFuCiAgICBpZihzdGFzaCl7ICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8gc8O8csO8a2xlcmtlbiBnZWxlbiB0YXplIHZlcmkgKGZpeWF0bGFyKSDi"
    "gJQgc8SxcmEgeWVyZWwga2FsxLFyCiAgICAgIFMub3B0cyA9IHN0YXNoLm9wdHMgfHwgUy5vcHRzOwogICAgICBjb25zdCBieSA9"
    "IHt9OyAoc3Rhc2gucm93cyB8fCBbXSkuZm9yRWFjaChyID0+IHsgaWYociAmJiByLmlkICE9IG51bGwpIGJ5W3IuaWRdID0gcjsg"
    "fSk7CiAgICAgIFMucm93cyA9IFMucm93cy5tYXAociA9PiBieVtyLmlkXSB8fCByKTsKICAgIH0KICAgIHJlb3JkZXJEb20oYXJy"
    "YXlNb3ZlKGQucHJldi5zbGljZSgpLCBkLmZyb20sIHRvKSk7ICAgICAgICAgICAvLyB0YW0gc3BsaWNlOiDDp8Sxa2FyIOKGkiBo"
    "ZWRlZmUgZWtsZQogICAgY29tbWl0KGQucHJldiwgZC5pZCk7CiAgfSBlbHNlIHsKICAgIGlmKGNhbmNlbCA9PT0gdHJ1ZSkgc2F5"
    "KCJNb3ZlIGNhbmNlbGxlZCIpOwogICAgaWYoc3Rhc2gpIGFwcGx5QXJncyhzdGFzaCk7CiAgfQp9Cmxpc3QuYWRkRXZlbnRMaXN0"
    "ZW5lcigicG9pbnRlcnVwIiwgZW5kRHJhZyk7Cmxpc3QuYWRkRXZlbnRMaXN0ZW5lcigicG9pbnRlcmNhbmNlbCIsIGZ1bmN0aW9u"
    "KCl7IGVuZERyYWcodHJ1ZSk7IH0pOyAgIC8vIHRhcmF5xLFjxLEgaGFyZWtldGkgZGV2cmFsZMSxIOKGkiBpcHRhbApsaXN0LmFk"
    "ZEV2ZW50TGlzdGVuZXIoImxvc3Rwb2ludGVyY2FwdHVyZSIsIGVuZERyYWcpOwpkb2N1bWVudC5hZGRFdmVudExpc3RlbmVyKCJr"
    "ZXlkb3duIiwgZnVuY3Rpb24oZSl7CiAgaWYoUy5kcmFnICYmIGUua2V5ID09PSAiRXNjYXBlIil7IGUucHJldmVudERlZmF1bHQo"
    "KTsgZW5kRHJhZyh0cnVlKTsgfQp9KTsKCi8qIC0tLS0gdMSxa2xhbWFsYXIgKyBrbGF2eWUgLS0tLSAqLwpsaXN0LmFkZEV2ZW50"
    "TGlzdGVuZXIoImNsaWNrIiwgZnVuY3Rpb24oZSl7CiAgY29uc3QgbGkgPSBlLnRhcmdldC5jbG9zZXN0KCIucm93Iik7IGlmKCFs"
    "aSkgcmV0dXJuOwogIGNvbnN0IGkgPSBbLi4ubGlzdC5jaGlsZHJlbl0uaW5kZXhPZihsaSk7CiAgaWYoZS50YXJnZXQuY2xvc2Vz"
    "dCgiLnVwIikpIHJldHVybiBtb3ZlKGksIGkgLSAxKTsKICBpZihlLnRhcmdldC5jbG9zZXN0KCIuZG4iKSkgcmV0dXJuIG1vdmUo"
    "aSwgaSArIDEpOwogIGlmKGUudGFyZ2V0LmNsb3Nlc3QoIi5ybSIpKSByZXR1cm4gc2VuZCh7dDogInJlbW92ZSIsIGlkOiBsaS5k"
    "YXRhc2V0LmlkfSk7CiAgaWYoRGF0ZS5ub3coKSAtIFMuanVzdERyYWdnZWQgPCA0MDApIHJldHVybjsgICAgICAgICAgICAgICAv"
    "LyBzw7xyw7xrbGVtZSBzb25yYXPEsSB0xLFrbGFtYSBkZcSfaWwKICBpZihTLm9wdHMuY2xpY2thYmxlICYmIGUudGFyZ2V0LmNs"
    "b3Nlc3QoIi5ubSwuYXYsLmMsLmV4dHEiKSkgc2VuZCh7dDogIm9wZW4iLCBpZDogbGkuZGF0YXNldC5pZH0pOwp9KTsKbGlzdC5h"
    "ZGRFdmVudExpc3RlbmVyKCJrZXlkb3duIiwgZnVuY3Rpb24oZSl7CiAgY29uc3QgaCA9IGUudGFyZ2V0LmNsb3Nlc3QoIi5oIik7"
    "IGlmKCFoKSByZXR1cm47CiAgY29uc3QgbGkgPSBoLmNsb3Nlc3QoIi5yb3ciKTsgY29uc3QgaSA9IFsuLi5saXN0LmNoaWxkcmVu"
    "XS5pbmRleE9mKGxpKTsKICBpZihlLmtleSA9PT0gIkFycm93VXAiKXsgZS5wcmV2ZW50RGVmYXVsdCgpOyBtb3ZlKGksIGkgLSAx"
    "KTsgfQogIGVsc2UgaWYoZS5rZXkgPT09ICJBcnJvd0Rvd24iKXsgZS5wcmV2ZW50RGVmYXVsdCgpOyBtb3ZlKGksIGkgKyAxKTsg"
    "fQogIGVsc2UgaWYoZS5rZXkgPT09ICJIb21lIil7IGUucHJldmVudERlZmF1bHQoKTsgbW92ZShpLCAwKTsgfQogIGVsc2UgaWYo"
    "ZS5rZXkgPT09ICJFbmQiKXsgZS5wcmV2ZW50RGVmYXVsdCgpOyBtb3ZlKGksIGxpc3QuY2hpbGRyZW4ubGVuZ3RoIC0gMSk7IH0K"
    "fSk7CgpmdW5jdGlvbiBhcHBseUFyZ3MoYSl7CiAgZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50LmNsYXNzTGlzdC50b2dnbGUoImxp"
    "Z2h0IiwgISFhLmxpZ2h0KTsKICBpZihhLmFjY2VudCkgZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50LnN0eWxlLnNldFByb3BlcnR5"
    "KCItLWFjYyIsIGEuYWNjZW50KTsKICBpZihTLmRyYWcpeyBTLnN0YXNoID0gYTsgcmV0dXJuOyB9ICAgICAgICAgICAgICAgICAg"
    "ICAvLyBzw7xyw7xrbGVtZSBzw7xyZXJrZW4gw6dpem1lIOKAlCBiaXRpbmNlIHV5Z3VsYQogIFMub3B0cyA9IGEub3B0cyB8fCB7"
    "fTsKICBsZXQgcm93cyA9IChhLnJvd3MgfHwgW10pLmZpbHRlcihyID0+IHIgJiYgci5pZCAhPSBudWxsKTsKICBjb25zdCBnID0g"
    "Uy5ndWFyZDsKICBpZihnKXsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyB0YcWfxLFt"
    "YWRhbiBoZW1lbiBzb25yYSBlc2tpIHPEsXJheWxhIGdlbGVuIMOnaXppbQogICAgY29uc3QgaWRzID0gcm93cy5tYXAociA9PiBy"
    "LmlkKS5qb2luKCJcdTAwMDEiKTsKICAgIGlmKERhdGUubm93KCkgPCBnLnVudGlsICYmIGlkcyA9PT0gZy5wcmV2KXsKICAgICAg"
    "Y29uc3QgYnkgPSB7fTsgcm93cy5mb3JFYWNoKHIgPT4gYnlbci5pZF0gPSByKTsKICAgICAgcm93cyA9IGcubm93Lm1hcChpZCA9"
    "PiBieVtpZF0pLmZpbHRlcihCb29sZWFuKTsgICAvLyB2ZXJpIHRhemUsIHPEsXJhIHllbmkga2FsxLFyCiAgICB9IGVsc2UgUy5n"
    "dWFyZCA9IG51bGw7ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8geWVuaSBzxLFyYSAoeWEgZGEgYmHFn2thIGRlxJ9p"
    "xZ9pa2xpaykgZ2VsZGkKICB9CiAgUy5yb3dzID0gcm93czsKICByZW5kZXIoKTsKfQp3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigi"
    "bWVzc2FnZSIsIGZ1bmN0aW9uKGUpewogIGNvbnN0IGQgPSBlLmRhdGEgfHwge307CiAgaWYoZC50eXBlID09PSAic3RyZWFtbGl0"
    "OnJlbmRlciIpIGFwcGx5QXJncyhkLmFyZ3MgfHwge30pOwp9KTsKbmV3IFJlc2l6ZU9ic2VydmVyKGZpdCkub2JzZXJ2ZShsaXN0"
    "KTsKbmV3IFJlc2l6ZU9ic2VydmVyKGZ1bmN0aW9uKCl7IGlmKCFTLmRyYWcgJiYgUy5vcHRzLmNvbHMgJiYgdmlzQ29scygpICE9"
    "PSBTLnZpcykgcmVuZGVyKCk7IH0pLm9ic2VydmUoZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50KTsKaWYod2luZG93Ll9fUExJU1Rf"
    "QVJHU19fKSBhcHBseUFyZ3Mod2luZG93Ll9fUExJU1RfQVJHU19fKTsgICAgICAgLy8geWFsbsSxemNhIMO2bml6bGVtZSAvIHRl"
    "c3QKZWxzZSBpZihpblN0cmVhbWxpdCkgc3RTZW5kKCJzdHJlYW1saXQ6Y29tcG9uZW50UmVhZHkiLCB7YXBpVmVyc2lvbjogMX0p"
    "Owp3aW5kb3cuUExJU1QgPSB7UzogUywgbW92ZTogbW92ZSwgb3JkZXI6IG9yZGVyLCBhcHBseUFyZ3M6IGFwcGx5QXJncywgc2Vu"
    "dDogKCkgPT4gUy5zZW50LCBhcnJheU1vdmU6IGFycmF5TW92ZX07Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRtbD4K"
)


def _ver_tuple(v):
    """'5.2' → (5, 2); okunamazsa (0,)."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return (0,)


def _list_version(head):
    m = re.search(r'name="pulse-list"\s+content="([^"]+)"', head or "")
    return m.group(1) if m else "0"


def list_versions():
    """(gömülü sürüm, klasördeki sürüm ya da None) — ör. ('5.2', '5.0')."""
    emb = _list_version(base64.b64decode(_LIST_B64)[:600].decode("utf-8", "ignore")) if _LIST_B64 else None
    try:
        with open(_LIST_INDEX, encoding="utf-8") as fh:
            disk = _list_version(fh.read(600))
    except OSError:
        disk = None
    return emb, disk


@st.cache_resource(show_spinner=False)
def _list_component():
    """v5.2: klasördeki pulse_list/index.html yalnızca gömülü kopyadan ESKİ değilse kullanılır. Repoda eski bir
    dosya kalmışsa (ör. 5.0) yeni sürükle-bırak yine de devrede olur — gömülü kopya geçici klasöre yazılır."""
    emb, disk = list_versions()
    d = _LIST_DIR
    if (disk is None or (emb and _ver_tuple(disk) < _ver_tuple(emb))) and not _LIST_B64:
        if disk is None:
            return None
    elif disk is None or (emb and _ver_tuple(disk) < _ver_tuple(emb)):
        try:
            import hashlib
            tag = hashlib.sha1(_LIST_B64.encode("ascii")).hexdigest()[:10]
            d = os.path.join(tempfile.gettempdir(), f"pulse_list_{tag}")
            os.makedirs(d, exist_ok=True)
            fp = os.path.join(d, "index.html")
            if not os.path.isfile(fp):
                with open(fp, "wb") as f:
                    f.write(base64.b64decode(_LIST_B64))
        except Exception:
            if disk is None:
                return None
            d = _LIST_DIR
    try:
        return components.declare_component("pulse_list", path=d)
    except Exception:
        return None


def list_available():
    return _list_component() is not None


def sortable_list(rows, key, *, cols=None, colw=None, title_col="", removable=False, clickable=False, max_h=420,
                  av=26, light=False, accent=None, empty=""):
    """rows: [{'id','title','sub','ini','avbg','avfg','logo','sel', 'cells': [{'v','c','s','sc'}]}].
    Döner: son olay ({'t': 'order'|'open'|'remove', 'n', ...}) ya da None. Bileşen yoksa None (çağıran yedeği çizer)."""
    comp = _list_component()
    if comp is None:
        return None
    return comp(key=key, default=None, rows=rows, light=bool(light), accent=accent,
                opts={"key": key, "cols": cols or [], "colw": colw or [], "title_col": title_col,
                      "removable": bool(removable), "clickable": bool(clickable), "max_h": int(max_h), "av": int(av),
                      "empty": empty})


def render_chart(payload, draws, alerts, chart_type="candles", height=640, rev=0, key="chart", light=False,
                 ov=None, fit=0.0, hmax=0, pmin=0):
    """Grafiği çizer. Kullanıcı bir şey değiştirdiyse olay sözlüğü döndürür.
    ov: isteğe bağlı katman (formasyon çizgileri, order block'lar, hacim işaretleri, dark pool seviyeleri, plan seviyeleri).
    fit/hmax/pmin (v4.2): yükseklik görünür pencerenin `fit` oranına büyür, fiyat paneli en az `pmin` px kalır,
    üst sınır `hmax` px."""
    comp = _component()
    args = dict(payload)
    args.update({"draws": draws or [], "alerts": alerts or [], "type": chart_type,
                 "height": int(height), "rev": int(rev), "light": bool(light), "ov": ov,
                 "fit": float(fit or 0), "hmax": int(hmax or 0), "pmin": int(pmin or 0)})
    if comp is None:
        html = open(_INDEX, encoding="utf-8").read() if os.path.isfile(_INDEX) else ""
        if html:
            html = html.replace("</head>", "<script>window.__PULSE_ARGS__=" +
                                json.dumps(args) + ";</script></head>")
            components.html(html, height=int(height) + 8, scrolling=False)
        return None
    return comp(key=key, default=None, **args)


# ----------------------------------------------------------------------
# Alarmlar
# ----------------------------------------------------------------------
def check_alerts(alerts, df, lookback=3):
    """Son barlara bakarak tetiklenen alarmları işaretler; tetiklenenleri döndürür."""
    if not alerts or df is None or len(df) < 2:
        return []
    c = df["Close"].tail(lookback + 1).to_numpy(float)
    hi = df["High"].tail(lookback + 1).to_numpy(float)
    lo = df["Low"].tail(lookback + 1).to_numpy(float)
    fired = []
    for a in alerts:
        if a.get("triggered"):
            continue
        p = float(a.get("price", 0))
        cond, hit = a.get("cond", "cross"), False
        for i in range(1, len(c)):
            prev, cur = c[i - 1], c[i]
            if cond == "above":
                hit = hi[i] >= p
            elif cond == "below":
                hit = lo[i] <= p
            elif cond == "cross_up":
                hit = prev < p <= cur
            elif cond == "cross_dn":
                hit = prev > p >= cur
            else:
                hit = (prev < p <= cur) or (prev > p >= cur)
            if hit:
                break
        if hit:
            a["triggered"] = True
            a["at"] = str(df.index[-1])[:16]
            fired.append(a)
    return fired


def alert_text(a):
    return "Price %s %s" % (CONDS.get(a.get("cond"), ""), en.fmt_num(a.get("price"), 2))
