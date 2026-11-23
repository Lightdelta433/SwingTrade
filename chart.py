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
import zlib

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import engine as en
import mock_data as md

CHART_VERSION = "5.11"
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
    "div": {"on": False, "src": "rsi", "left": 5, "right": 5, "hidden": True, "min": 3},
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
    if out["div"]["src"] not in ("rsi", "macd", "wt", "many"):
        out["div"]["src"] = "rsi"
    out["div"]["min"] = int(min(12, max(1, out["div"].get("min", 3))))      # v5.8: "Many indicators" eşiği
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
    if cfg["div"]["on"] and cfg["div"]["src"] == "many":     # v5.8: 12 indikatör birden (onaylı sinyaller)
        off = len(full) - keep
        try:
            many = en.div_many(full, {"prd": cfg["div"]["left"], "min_n": cfg["div"]["min"],
                                      "kinds": 2 if cfg["div"]["hidden"] else 0}, i_from=off)
        except Exception:
            many = []
        divs = [dict(d_, i1=d_["i1"] - off, i2=d_["i2"] - off, t=d_["t"] - off) for d_ in many if d_["i1"] >= off][-40:]
    elif cfg["div"]["on"]:
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
UI_VERSION = "5.11"     # pulse_chart/index.html içindeki <meta name="pulse-ui"> ile aynı olmalı


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
    "cHVsc2UtbGlzdCIgY29udGVudD0iNS4zIj4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0"
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
    "amkiLHNhbnMtc2VyaWZ9Ci5leHRxIGVte2ZvbnQtc3R5bGU6bm9ybWFsO2ZvbnQtc2l6ZTo5cHg7Zm9udC13ZWlnaHQ6ODAwO2xl"
    "dHRlci1zcGFjaW5nOi4wN2VtO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtjb2xvcjp2YXIoLS1kaW0pfQouZXh0cSBie2ZvbnQt"
    "d2VpZ2h0OjcwMDtjb2xvcjp2YXIoLS10eHQpfQouc3J7cG9zaXRpb246YWJzb2x1dGU7d2lkdGg6MXB4O2hlaWdodDoxcHg7b3Zl"
    "cmZsb3c6aGlkZGVuO2NsaXA6cmVjdCgwIDAgMCAwKX0KPC9zdHlsZT4KPC9oZWFkPgo8Ym9keT4KPGRpdiBpZD0id3JhcCI+PGRp"
    "diBpZD0iaGRyIiBjbGFzcz0iaGRyIiBoaWRkZW4+PC9kaXY+PHVsIGlkPSJsaXN0IiBjbGFzcz0ibGlzdCIgcm9sZT0ibGlzdGJv"
    "eCI+PC91bD4KPGRpdiBpZD0iZW1wdHkiIGNsYXNzPSJlbXB0eSIgaGlkZGVuPjwvZGl2PjwvZGl2Pgo8ZGl2IGlkPSJsaXZlIiBj"
    "bGFzcz0ic3IiIGFyaWEtbGl2ZT0icG9saXRlIj48L2Rpdj4KPHNjcmlwdD4KInVzZSBzdHJpY3QiOwpjb25zdCBpblN0cmVhbWxp"
    "dCA9IHdpbmRvdy5wYXJlbnQgJiYgd2luZG93LnBhcmVudCAhPT0gd2luZG93Owpjb25zdCBTID0ge3Jvd3M6IFtdLCBvcHRzOiB7"
    "fSwgbjogMCwgZHJhZzogbnVsbCwgc2VudDogW10sIHZpczogMH07CmNvbnN0IHdyYXAgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJ"
    "ZCgid3JhcCIpLCBsaXN0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImxpc3QiKTsKCmZ1bmN0aW9uIHN0U2VuZCh0eXBlLCBk"
    "YXRhKXsgaWYoIWluU3RyZWFtbGl0KSByZXR1cm47CiAgd2luZG93LnBhcmVudC5wb3N0TWVzc2FnZShPYmplY3QuYXNzaWduKHtp"
    "c1N0cmVhbWxpdE1lc3NhZ2U6IHRydWUsIHR5cGU6IHR5cGV9LCBkYXRhIHx8IHt9KSwgIioiKTsgfQpmdW5jdGlvbiBzZW5kKGV2"
    "KXsKICBTLm4gPSBNYXRoLm1heChTLm4gKyAxLCBEYXRlLm5vdygpKTsgICAgIC8vIGlmcmFtZSB5ZW5pZGVuIHnDvGtsZW5zZSBk"
    "ZSAoc2VrbWUgZGXEn2nFn2ltaSkgc2F5YcOnIGhlcCB5ZW5pIOKGkiBvbGF5IGtheWJvbG1hegogIGNvbnN0IHYgPSBPYmplY3Qu"
    "YXNzaWduKHtuOiBTLm4sIGtleTogUy5vcHRzLmtleSB8fCAiIn0sIGV2KTsKICBTLnNlbnQucHVzaCh2KTsKICBzdFNlbmQoInN0"
    "cmVhbWxpdDpzZXRDb21wb25lbnRWYWx1ZSIsIHt2YWx1ZTogdiwgZGF0YVR5cGU6ICJqc29uIn0pOwp9CmZ1bmN0aW9uIGVzYyhz"
    "KXsgcmV0dXJuIFN0cmluZyhzID09IG51bGwgPyAiIiA6IHMpLnJlcGxhY2UoL1smPD4iJ10vZywgYyA9PiAoeyImIjoiJmFtcDsi"
    "LCI8IjoiJmx0OyIsIj4iOiImZ3Q7IiwKICAnIic6IiZxdW90OyIsIiciOiImIzM5OyJ9KVtjXSk7IH0KCi8qIGRhciBla3JhbmRh"
    "ICh0ZWxlZm9uKSBzw7x0dW5sYXIgc29uZGFuIGdpemxlbmlyIOKAlCBzYXnEsWxhciBhc2xhIHRhxZ9tYXogLyBrZXNpbG1leiwg"
    "YWQgc8O8dHVudSBlbiBheiA4MCBweCBrYWzEsXIgKi8KZnVuY3Rpb24gdmlzQ29scygpewogIGNvbnN0IGNvbHMgPSBTLm9wdHMu"
    "Y29scyB8fCBbXSwgY29sdyA9IFMub3B0cy5jb2x3IHx8IFtdOwogIGNvbnN0IFcgPSAod3JhcC5jbGllbnRXaWR0aCB8fCBkb2N1"
    "bWVudC5kb2N1bWVudEVsZW1lbnQuY2xpZW50V2lkdGggfHwgNDAwKSAtIDQ7CiAgY29uc3QgcHggPSB3ID0+IHBhcnNlRmxvYXQo"
    "dykgfHwgNzA7CiAgY29uc3QgZml4ZWQgPSBrID0+IDE4ICsgKFMub3B0cy5hdiB8fCAyNikgKyBjb2x3LnNsaWNlKDAsIGspLnJl"
    "ZHVjZSgoYSwgdykgPT4gYSArIHB4KHcpLCAwKSArIDUyCiAgICArIChTLm9wdHMucmVtb3ZhYmxlID8gMjQgOiAwKSArIDggKiAo"
    "MyArIGsgKyAoUy5vcHRzLnJlbW92YWJsZSA/IDEgOiAwKSkgKyAxNjsKICBsZXQgbiA9IGNvbHMubGVuZ3RoOwogIHdoaWxlKG4g"
    "PiAxICYmIFcgLSBmaXhlZChuKSA8IDgwKSBuLS07CiAgcmV0dXJuIG47Cn0KZnVuY3Rpb24gZ3JpZCgpewogIGNvbnN0IG5jID0g"
    "Uy52aXM7CiAgcmV0dXJuICIxOHB4ICIgKyAoUy5vcHRzLmF2IHx8IDI2KSArICJweCBtaW5tYXgoMCwxZnIpICIgKyAoUy5vcHRz"
    "LmNvbHcgfHwgW10pLnNsaWNlKDAsIG5jKS5tYXAodyA9PiB3IHx8ICJhdXRvIikuam9pbigiICIpCiAgICArICIgNTJweCIgKyAo"
    "Uy5vcHRzLnJlbW92YWJsZSA/ICIgMjRweCIgOiAiIik7Cn0KCmZ1bmN0aW9uIGV4dEhUTUwocil7CiAgY29uc3QgZSA9IHIuZXh0"
    "OwogIGlmKCFlIHx8IGUucHggPT0gbnVsbCkgcmV0dXJuICIiOwogIHJldHVybiAnPHNwYW4gY2xhc3M9ImV4dHEiIHRpdGxlPSIn"
    "ICsgZXNjKGUubGFiIHx8ICIiKSArICcg4oCUIGNoYW5nZSB2cyB0aGUgcmVndWxhciBjbG9zZSI+PGkgc3R5bGU9ImNvbG9yOicK"
    "ICAgICsgZXNjKGUuaWMgfHwgInZhcigtLW11dCkiKSArICciPicgKyBlc2MoZS5pIHx8ICIiKSArICc8L2k+JwogICAgKyAoZS5z"
    "ID8gJzxlbT4nICsgZXNjKGUucykgKyAnPC9lbT4nIDogIiIpCiAgICArICc8Yj4nICsgZXNjKGUucHgpICsgJzwvYj48c3BhbiBz"
    "dHlsZT0iY29sb3I6JwogICAgKyBlc2MoZS5jIHx8ICJ2YXIoLS1tdXQpIikgKyAnIj4nICsgZXNjKGUudCB8fCAiIikgKyAnPC9z"
    "cGFuPjwvc3Bhbj4nOwp9CgpmdW5jdGlvbiByb3dIVE1MKHIsIGksIG4pewogIGNvbnN0IHN6ID0gUy5vcHRzLmF2IHx8IDI2Owog"
    "IGNvbnN0IGF2ID0gJzxzcGFuIGNsYXNzPSJhdiIgc3R5bGU9IndpZHRoOicgKyBzeiArICdweDtoZWlnaHQ6JyArIHN6ICsgJ3B4"
    "O2ZvbnQtc2l6ZTonICsgTWF0aC5tYXgoOSwgTWF0aC5yb3VuZChzeiAqIC4zNCkpCiAgICArICdweDtiYWNrZ3JvdW5kOicgKyBl"
    "c2Moci5hdmJnIHx8ICIjMjYzMDNGIikgKyAnO2NvbG9yOicgKyBlc2Moci5hdmZnIHx8ICIjQzlEM0UzIikgKyAnIj4nICsgZXNj"
    "KHIuaW5pIHx8ICI/IikKICAgICsgKHIubG9nbyA/ICc8aW1nIHNyYz0iJyArIGVzYyhyLmxvZ28pICsgJyIgYWx0PSIiIGxvYWRp"
    "bmc9ImxhenkiIG9uZXJyb3I9InRoaXMucmVtb3ZlKCkiPicgOiAiIikgKyAnPC9zcGFuPic7CiAgY29uc3QgY2VsbHMgPSAoci5j"
    "ZWxscyB8fCBbXSkuc2xpY2UoMCwgUy52aXMpLm1hcChjID0+ICc8c3BhbiBjbGFzcz0iYyI+JyArIChjLnYgIT0gbnVsbCA/ICc8"
    "c3BhbicgKyAoYy5jID8gJyBzdHlsZT0iY29sb3I6JyArIGVzYyhjLmMpICsgJyInIDogIiIpCiAgICArIChjLmIgPyAnIGNsYXNz"
    "PSJzIicgOiAiIikgKyAnPicgKyBlc2MoYy52KSArICc8L3NwYW4+JyA6ICIiKQogICAgKyAoYy5zICE9IG51bGwgPyAnPHNwYW4g"
    "Y2xhc3M9InMiJyArIChjLnNjID8gJyBzdHlsZT0iY29sb3I6JyArIGVzYyhjLnNjKSArICciJyA6ICIiKSArICc+JyArIGVzYyhj"
    "LnMpICsgJzwvc3Bhbj4nIDogIiIpCiAgICArICc8L3NwYW4+Jykuam9pbigiIik7CiAgcmV0dXJuICc8bGkgY2xhc3M9InJvdycg"
    "KyAoci5zZWwgPyAiIHNlbCIgOiAiIikgKyAnIiByb2xlPSJvcHRpb24iIGRhdGEtaWQ9IicgKyBlc2Moci5pZCkgKyAnIiBzdHls"
    "ZT0iZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOicKICAgICsgZ3JpZCgpICsgJyI+JwogICAgKyAnPHNwYW4gY2xhc3M9ImgiIHRhYmlu"
    "ZGV4PSIwIiByb2xlPSJidXR0b24iIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgKGRyYWcsIG9yIHVzZSB0"
    "aGUgYXJyb3cga2V5cykiICcKICAgICsgJ3RpdGxlPSJEcmFnIHRvIHJlb3JkZXIiPuKLruKLrjwvc3Bhbj4nICsgYXYKICAgICsg"
    "JzxzcGFuIGNsYXNzPSJubSIgdGl0bGU9IicgKyBlc2Moci5zdWIgfHwgIiIpICsgJyI+PGI+JyArIGVzYyhyLnRpdGxlKSArICc8"
    "L2I+PGk+JyArIGVzYyhyLnN1YiB8fCAiIikgKyAnPC9pPjwvc3Bhbj4nCiAgICArIGNlbGxzCiAgICArIGV4dEhUTUwocikKICAg"
    "ICsgJzxzcGFuIGNsYXNzPSJhciI+PGJ1dHRvbiBjbGFzcz0idXAiIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSAr"
    "ICcgdXAiIHRpdGxlPSJNb3ZlIHVwIicgKyAoaSA9PT0gMCA/ICIgZGlzYWJsZWQiIDogIiIpCiAgICArICc+4oaRPC9idXR0b24+"
    "PGJ1dHRvbiBjbGFzcz0iZG4iIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgZG93biIgdGl0bGU9Ik1vdmUg"
    "ZG93biInICsgKGkgPT09IG4gLSAxID8gIiBkaXNhYmxlZCIgOiAiIikKICAgICsgJz7ihpM8L2J1dHRvbj48L3NwYW4+JwogICAg"
    "KyAoUy5vcHRzLnJlbW92YWJsZSA/ICc8YnV0dG9uIGNsYXNzPSJybSIgYXJpYS1sYWJlbD0iUmVtb3ZlICcgKyBlc2Moci50aXRs"
    "ZSkgKyAnIiB0aXRsZT0iUmVtb3ZlIj7DlzwvYnV0dG9uPicgOiAiIikKICAgICsgJzwvbGk+JzsKfQoKZnVuY3Rpb24gcmVuZGVy"
    "KCl7CiAgY29uc3Qgcm93cyA9IFMucm93cywgbiA9IHJvd3MubGVuZ3RoOwogIFMudmlzID0gdmlzQ29scygpOwogIGNvbnN0IGhk"
    "ciA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJoZHIiKSwgZW0gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZW1wdHkiKTsK"
    "ICB3cmFwLmNsYXNzTGlzdC50b2dnbGUoImNsaWNrYWJsZSIsICEhUy5vcHRzLmNsaWNrYWJsZSk7CiAgaWYoUy5vcHRzLmNvbHMg"
    "JiYgUy5vcHRzLmNvbHMuc29tZShCb29sZWFuKSAmJiBuKXsKICAgIGhkci5oaWRkZW4gPSBmYWxzZTsKICAgIGhkci5zdHlsZS5n"
    "cmlkVGVtcGxhdGVDb2x1bW5zID0gZ3JpZCgpOwogICAgaGRyLmlubmVySFRNTCA9ICc8c3Bhbj48L3NwYW4+PHNwYW4+PC9zcGFu"
    "PjxzcGFuPicgKyBlc2MoUy5vcHRzLnRpdGxlX2NvbCB8fCAiIikgKyAnPC9zcGFuPicKICAgICAgKyBTLm9wdHMuY29scy5zbGlj"
    "ZSgwLCBTLnZpcykubWFwKGMgPT4gJzxzcGFuIHN0eWxlPSJ0ZXh0LWFsaWduOnJpZ2h0Ij4nICsgZXNjKGMpICsgJzwvc3Bhbj4n"
    "KS5qb2luKCIiKQogICAgICArICc8c3Bhbj48L3NwYW4+JyArIChTLm9wdHMucmVtb3ZhYmxlID8gIjxzcGFuPjwvc3Bhbj4iIDog"
    "IiIpOwogIH0gZWxzZSBoZHIuaGlkZGVuID0gdHJ1ZTsKICBlbS5oaWRkZW4gPSBuID4gMDsKICBlbS50ZXh0Q29udGVudCA9IFMu"
    "b3B0cy5lbXB0eSB8fCAiVGhlIGxpc3QgaXMgZW1wdHkuIjsKICBsaXN0LmlubmVySFRNTCA9IHJvd3MubWFwKChyLCBpKSA9PiBy"
    "b3dIVE1MKHIsIGksIG4pKS5qb2luKCIiKTsKICBmaXQoKTsKfQoKZnVuY3Rpb24gZml0KCl7CiAgY29uc3QgZnVsbCA9IGRvY3Vt"
    "ZW50LmdldEVsZW1lbnRCeUlkKCJoZHIiKS5vZmZzZXRIZWlnaHQgKyBsaXN0Lm9mZnNldEhlaWdodCArIChTLnJvd3MubGVuZ3Ro"
    "ID8gMCA6IDQ2KSArIDQ7CiAgY29uc3QgaCA9IE1hdGgubWF4KDQwLCBNYXRoLm1pbihmdWxsLCBTLm9wdHMubWF4X2ggfHwgNDIw"
    "KSk7CiAgd3JhcC5zdHlsZS5oZWlnaHQgPSBoICsgInB4IjsKICBzdFNlbmQoInN0cmVhbWxpdDpzZXRGcmFtZUhlaWdodCIsIHto"
    "ZWlnaHQ6IGh9KTsKfQoKZnVuY3Rpb24gb3JkZXIoKXsgcmV0dXJuIFsuLi5saXN0LmNoaWxkcmVuXS5tYXAobGkgPT4gbGkuZGF0"
    "YXNldC5pZCk7IH0KZnVuY3Rpb24gc2F5KHQpeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibGl2ZSIpLnRleHRDb250ZW50ID0g"
    "dDsgfQoKLyogdjUuMjogVEFNIGRpemkgdGHFn8SxbWEgKHNwbGljZSkg4oCUIHRha2FzIERFxJ7EsEwuIMOWxJ9lIGVza2kgaW5k"
    "ZWtzaW5kZW4gw6fEsWthcsSxbMSxciB2ZSB0YW0gaGVkZWYgaW5kZWtzZSBla2xlbmlyOgogICBhcmFkYWtpIMO2xJ9lbGVyIHRh"
    "bSBiaXIga29udW0ga2F5YXIsIGdlcmkga2FsYW4gaGVya2VzIGfDtnJlbGkgc8SxcmFzxLFuxLEga29ydXIuCiAgIMOWcm4uIFtO"
    "VkRBLCBBQVBMXSDihpIgQUFQTCBiaXIgeXVrYXLEsTogW0FBUEwsIE5WREFdIMK3IDUuIHPEsXJhZGFuIDEuJ3llOiAx4oCTNCBh"
    "cmFzxLEgdGFtIGJpciBhxZ9hxJ/EsSBrYXlhci4gKi8KZnVuY3Rpb24gYXJyYXlNb3ZlKGxpc3QsIGZyb21JbmRleCwgdG9JbmRl"
    "eCl7CiAgY29uc3QgW21vdmVkXSA9IGxpc3Quc3BsaWNlKGZyb21JbmRleCwgMSk7CiAgbGlzdC5zcGxpY2UodG9JbmRleCwgMCwg"
    "bW92ZWQpOwogIHJldHVybiBsaXN0Owp9CgpmdW5jdGlvbiBjb21taXQocHJldiwgZmxhc2hJZCl7CiAgY29uc3Qgbm93ID0gb3Jk"
    "ZXIoKTsKICBpZihub3cuam9pbigiXHUwMDAxIikgPT09IHByZXYuam9pbigiXHUwMDAxIikpIHJldHVybjsKICBjb25zdCBieUlk"
    "ID0ge307IFMucm93cy5mb3JFYWNoKHIgPT4gYnlJZFtyLmlkXSA9IHIpOwogIFMucm93cyA9IG5vdy5tYXAoaWQgPT4gYnlJZFtp"
    "ZF0pOwogIC8vIFN0cmVhbWxpdCd0ZW4gRVNLxLAgc8SxcmF5bGEgZ2VjaWttacWfIGJpciDDp2l6aW0gZ2VsaXJzZSB5ZW5pIHPE"
    "sXJhecSxIGdlcmkgYWxtYXPEsW4gKGHFn2HEn8SxZGEgYXBwbHlBcmdzKQogIFMuZ3VhcmQgPSB7cHJldjogcHJldi5qb2luKCJc"
    "dTAwMDEiKSwgbm93OiBub3cuc2xpY2UoKSwgdW50aWw6IERhdGUubm93KCkgKyA2MDAwfTsKICByZW5kZXIoKTsKICBjb25zdCBs"
    "aSA9IGxpc3QucXVlcnlTZWxlY3RvcignLnJvd1tkYXRhLWlkPSInICsgQ1NTLmVzY2FwZShmbGFzaElkKSArICciXScpOwogIGlm"
    "KGxpKXsgbGkuY2xhc3NMaXN0LmFkZCgibW92ZWQiKTsgfQogIHNlbmQoe3Q6ICJvcmRlciIsIG9yZGVyOiBub3csIG1vdmVkOiBm"
    "bGFzaElkLCBmcm9tOiBwcmV2LmluZGV4T2YoZmxhc2hJZCksIHRvOiBub3cuaW5kZXhPZihmbGFzaElkKX0pOwogIHNheShmbGFz"
    "aElkICsgIiBtb3ZlZCB0byBwb3NpdGlvbiAiICsgKG5vdy5pbmRleE9mKGZsYXNoSWQpICsgMSkpOwp9CgpmdW5jdGlvbiByZW9y"
    "ZGVyRG9tKG5leHQpewogIGNvbnN0IGJ5SWQgPSB7fTsgWy4uLmxpc3QuY2hpbGRyZW5dLmZvckVhY2gobGkgPT4gYnlJZFtsaS5k"
    "YXRhc2V0LmlkXSA9IGxpKTsKICBuZXh0LmZvckVhY2goeCA9PiBsaXN0LmFwcGVuZENoaWxkKGJ5SWRbeF0pKTsKfQoKZnVuY3Rp"
    "b24gbW92ZShpLCBqKXsgICAgICAgICAgICAgICAgICAgICAgIC8vIOKGkSAvIOKGkyAvIGtsYXZ5ZTogaSDihpIgaiAoaW5kZWtz"
    "KSwgYXluxLEgc3BsaWNlIGt1cmFsxLEKICBjb25zdCBwcmV2ID0gb3JkZXIoKTsKICBpZihqIDwgMCB8fCBqID49IHByZXYubGVu"
    "Z3RoIHx8IGkgPT09IGopIHJldHVybjsKICBjb25zdCBpZCA9IHByZXZbaV07CiAgcmVvcmRlckRvbShhcnJheU1vdmUocHJldi5z"
    "bGljZSgpLCBpLCBqKSk7CiAgY29tbWl0KHByZXYsIGlkKTsKICBjb25zdCBoID0gbGlzdC5xdWVyeVNlbGVjdG9yKCcucm93W2Rh"
    "dGEtaWQ9IicgKyBDU1MuZXNjYXBlKGlkKSArICciXSAuaCcpOyBpZihoKSBoLmZvY3VzKHtwcmV2ZW50U2Nyb2xsOiBmYWxzZX0p"
    "Owp9CgovKiAtLS0tIHPDvHLDvGtsZS1ixLFyYWs6IHNhdMSxcsSxbiBIRVJIQU5HxLAgYmlyIHllcmluZGVuIChsb2dvLCBhZCwg"
    "Zml5YXQpIC0tLS0KICAgZmFyZTogNiBweCBkaWtleSBoYXJla2V0bGUgYmHFn2xhciAodMSxa2xhbWEgImHDpyIgb2xhcmFrIGth"
    "bMSxcikgwrcg4ouu4ouuIHR1dGFtYWPEsTogYW7EsW5kYQogICBkb2t1bm1hdGlrIC8ga2FsZW06IDMwMCBtcyBiYXPEsWzEsSB0"
    "dXQgKGtheWTEsXJtYSBzZXJiZXN0IGthbMSxciksIHNvbnJhIHPDvHLDvGtsZSAqLwpjb25zdCBIT0xEX01TID0gMzAwLCBNT1VT"
    "RV9TTE9QID0gNiwgVE9VQ0hfU0xPUCA9IDEwOwpTLnBlbmQgPSBudWxsOyBTLmp1c3REcmFnZ2VkID0gMDsKCi8qIGltbGVjaW4g"
    "bGlzdGUgacOnZXJpxJ9pbmRla2kgeSBrb251bXUgKGxpc3RlIGtheWTEsXLEsWxtxLHFnyBvbHNhIGRhIGRvxJ9ydSkgKi8KZnVu"
    "Y3Rpb24gY29udGVudFkoY2xpZW50WSl7IHJldHVybiBjbGllbnRZIC0gbGlzdC5nZXRCb3VuZGluZ0NsaWVudFJlY3QoKS50b3A7"
    "IH0KCi8qIGhlZGVmIGluZGVrcyA9IGltbGVjaW4gQUxUSU5EQUvEsCBzYXTEsXIuIFNhdMSxcmxhciBzw7xyw7xrbGVtZSBib3l1"
    "bmNhIHllcmluZGUgZHVydXIgKGtheWTEsXJtYSBhbmltYXN5b251IHlvayksCiAgIHlhbmkgZWtyYW5kYSDDvHplcmluZSBnZWxp"
    "bmVuIHNhdMSxciBpbGUgaGVzYXBsYW5hbiBoZWRlZiBoZXIgemFtYW4gYXluxLFkxLFyLiDDnHN0dGUg4oaSIDAsIGFsdHRhIOKG"
    "kiBzb24uICovCmZ1bmN0aW9uIHRhcmdldEluZGV4KGN5KXsKICBjb25zdCByb3dzID0gUy5kcmFnLnJvd3M7IGxldCB0byA9IDA7"
    "CiAgZm9yKGxldCBrID0gMDsgayA8IHJvd3MubGVuZ3RoOyBrKyspeyBpZihjeSA+PSByb3dzW2tdLm9mZnNldFRvcCkgdG8gPSBr"
    "OyBlbHNlIGJyZWFrOyB9CiAgcmV0dXJuIHRvOwp9CgpmdW5jdGlvbiBzdGFydERyYWcobGksIGNhcEVsLCBlKXsKICBjb25zdCBy"
    "b3dzID0gWy4uLmxpc3QuY2hpbGRyZW5dLCBmcm9tID0gcm93cy5pbmRleE9mKGxpKTsKICB0cnl7IGNhcEVsLnNldFBvaW50ZXJD"
    "YXB0dXJlKGUucG9pbnRlcklkKTsgfWNhdGNoKF8peyB9CiAgY29uc3QgZyA9IGxpLmNsb25lTm9kZSh0cnVlKTsgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgLy8gaW1sZWNpIGl6bGV5ZW4gaGF5YWxldAogIGcuY2xhc3NMaXN0LnJlbW92ZSgic2Vs"
    "IiwgIm1vdmVkIik7IGcuY2xhc3NMaXN0LmFkZCgiZ2hvc3QiKTsKICBnLnJlbW92ZUF0dHJpYnV0ZSgicm9sZSIpOyBnLnNldEF0"
    "dHJpYnV0ZSgiYXJpYS1oaWRkZW4iLCAidHJ1ZSIpOwogIGcucXVlcnlTZWxlY3RvckFsbCgiYnV0dG9uLFt0YWJpbmRleF0iKS5m"
    "b3JFYWNoKHggPT4geC5zZXRBdHRyaWJ1dGUoInRhYmluZGV4IiwgIi0xIikpOwogIGNvbnN0IGxuID0gZG9jdW1lbnQuY3JlYXRl"
    "RWxlbWVudCgiZGl2Iik7ICAgICAgICAgICAgICAgICAgICAgIC8vIGVrbGVtZSDDp2l6Z2lzaSArIHllbmkgc8SxcmEgbnVtYXJh"
    "c8SxCiAgbG4uY2xhc3NOYW1lID0gImRyb3BsaW5lIjsgbG4uaGlkZGVuID0gdHJ1ZTsgbG4uaW5uZXJIVE1MID0gJzxzcGFuIGNs"
    "YXNzPSJkbC1uIj48L3NwYW4+JzsKICB3cmFwLmFwcGVuZENoaWxkKGcpOyB3cmFwLmFwcGVuZENoaWxkKGxuKTsKICBTLmRyYWcg"
    "PSB7bGk6IGxpLCBpZDogbGkuZGF0YXNldC5pZCwgZnJvbTogZnJvbSwgdG86IGZyb20sIGxhc3RUbzogZnJvbSwgcm93czogcm93"
    "cywgcHJldjogb3JkZXIoKSwKICAgICAgICAgICAgZ2hvc3Q6IGcsIGxpbmU6IGxuLCBjeTA6IGNvbnRlbnRZKGUuY2xpZW50WSks"
    "IHRvcDA6IGxpLm9mZnNldFRvcCwgaDogbGkub2Zmc2V0SGVpZ2h0LAogICAgICAgICAgICB5OiBlLmNsaWVudFksIHJhZjogMH07"
    "CiAgbGkuY2xhc3NMaXN0LmFkZCgic3JjIik7IHdyYXAuY2xhc3NMaXN0LmFkZCgiZHJhZ2dpbmciKTsKICBwbGFjZSgpOwogIFMu"
    "ZHJhZy5yYWYgPSByZXF1ZXN0QW5pbWF0aW9uRnJhbWUoZWRnZVNjcm9sbCk7CiAgc2F5KCJNb3ZpbmcgIiArIGxpLmRhdGFzZXQu"
    "aWQgKyAiIOKAlCByZWxlYXNlIHRvIGRyb3AsIEVzY2FwZSB0byBjYW5jZWwiKTsKfQoKLyogaGF5YWxldGkgaW1sZWNlIGfDtnJl"
    "IHllcmxlxZ90aXIsIGhlZGVmaSBoZXNhcGxhLCBla2xlbWUgw6dpemdpc2luaSBoZWRlZiBhcmFsxLHEn2Ega295ICovCmZ1bmN0"
    "aW9uIHBsYWNlKCl7CiAgY29uc3QgZCA9IFMuZHJhZzsgaWYoIWQpIHJldHVybjsKICBjb25zdCBjeSA9IGNvbnRlbnRZKGQueSks"
    "IGxvID0gbGlzdC5vZmZzZXRUb3A7CiAgbGV0IHRvcCA9IGQudG9wMCArIChjeSAtIGQuY3kwKTsgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgLy8gdHV0dWxhbiBub2t0YSBrb3J1bnVyCiAgdG9wID0gTWF0aC5tYXgoLWQuaCAqIDAuNSwgTWF0aC5taW4o"
    "bGlzdC5vZmZzZXRIZWlnaHQgLSBkLmggKiAwLjUsIHRvcCkpOwogIGQuZ2hvc3Quc3R5bGUudHJhbnNmb3JtID0gInRyYW5zbGF0"
    "ZVkoIiArIChsbyArIHRvcCkgKyAicHgpIjsKICBjb25zdCB0byA9IHRhcmdldEluZGV4KGN5KTsKICBkLnRvID0gdG87CiAgaWYo"
    "dG8gPT09IGQuZnJvbSl7CiAgICBkLmxpbmUuaGlkZGVuID0gdHJ1ZTsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgLy8ga2VuZGkgeWVyaW5kZSDihpIgZGXEn2nFn2lrbGlrIHlvawogIH0gZWxzZSB7CiAgICBjb25zdCByID0gZC5yb3dz"
    "W3RvXTsKICAgIC8vIHl1a2FyxLEgdGHFn8SxbWE6IGhlZGVmIHNhdMSxcsSxbiDDnFNUw5xORSDCtyBhxZ9hxJ/EsSB0YcWfxLFt"
    "YTogaGVkZWYgc2F0xLFyxLFuIEFMVElOQQogICAgY29uc3QgeSA9IHRvIDwgZC5mcm9tID8gci5vZmZzZXRUb3AgOiByLm9mZnNl"
    "dFRvcCArIHIub2Zmc2V0SGVpZ2h0OwogICAgY29uc3QgeXkgPSBNYXRoLm1heCgxLCBNYXRoLm1pbih3cmFwLnNjcm9sbEhlaWdo"
    "dCAtIDEsIGxvICsgeSkpOwogICAgZC5saW5lLmhpZGRlbiA9IGZhbHNlOwogICAgZC5saW5lLnN0eWxlLnRyYW5zZm9ybSA9ICJ0"
    "cmFuc2xhdGVZKCIgKyAoeXkgLSAxKSArICJweCkiOwogICAgZC5saW5lLmNsYXNzTGlzdC50b2dnbGUoInRvcCIsIHl5IDwgMTEp"
    "OyAgICAgICAgICAgICAgICAgICAgIC8vIG51bWFyYSBrZW5hcmRhIGtlc2lsbWVzaW4g4oaSIGnDp2Uga2F0bGEKICAgIGQubGlu"
    "ZS5jbGFzc0xpc3QudG9nZ2xlKCJib3QiLCB5eSA+IHdyYXAuc2Nyb2xsSGVpZ2h0IC0gMTEpOwogICAgZC5saW5lLmZpcnN0Q2hp"
    "bGQudGV4dENvbnRlbnQgPSBTdHJpbmcodG8gKyAxKTsKICB9CiAgaWYodG8gIT09IGQubGFzdFRvKXsKICAgIGQubGFzdFRvID0g"
    "dG87CiAgICBzYXkodG8gPT09IGQuZnJvbSA/ICJCYWNrIGF0IGl0cyBwbGFjZSIgOiAiRHJvcCBhdCBwb3NpdGlvbiAiICsgKHRv"
    "ICsgMSkpOwogIH0KfQoKLyoga2VuYXJhIHlha2xhxZ/EsW5jYSAoaW1sZcOnIGR1cnNhIGJpbGUpIHl1bXXFn2FrIG90b21hdGlr"
    "IGtheWTEsXJtYSDigJQgemFtYW5hIGJhxJ9sxLEsIGthcmUgaMSxesSxbmRhbiBiYcSfxLFtc8SxejoKICAga2VuYXJhIG5lIGth"
    "ZGFyIHlha8SxbnNhIG8ga2FkYXIgaMSxemzEsSAoa2VuYXLEsW4gZMSxxZ/EsW5kYSBlbiBmYXpsYSB+MTMwMCBweC9zKSAqLwpm"
    "dW5jdGlvbiBlZGdlU2Nyb2xsKHRzKXsKICBjb25zdCBkID0gUy5kcmFnOyBpZighZCkgcmV0dXJuOwogIGNvbnN0IGR0ID0gZC50"
    "cyA/IE1hdGgubWluKDUwLCB0cyAtIGQudHMpIDogMTY7IGQudHMgPSB0czsKICBpZih3cmFwLnNjcm9sbEhlaWdodCA+IHdyYXAu"
    "Y2xpZW50SGVpZ2h0ICsgMSl7CiAgICBjb25zdCB3ciA9IHdyYXAuZ2V0Qm91bmRpbmdDbGllbnRSZWN0KCksIFogPSAyODsKICAg"
    "IGxldCBwcm94ID0gMDsKICAgIGlmKGQueSA8IHdyLnRvcCArIFopIHByb3ggPSAtTWF0aC5taW4oMS41LCAod3IudG9wICsgWiAt"
    "IGQueSkgLyBaKTsKICAgIGVsc2UgaWYoZC55ID4gd3IuYm90dG9tIC0gWikgcHJveCA9IE1hdGgubWluKDEuNSwgKGQueSAtICh3"
    "ci5ib3R0b20gLSBaKSkgLyBaKTsKICAgIGlmKHByb3gpewogICAgICBkLmFjYyA9IChkLmFjYyB8fCAwKSArIHByb3ggKiAwLjkg"
    "KiBkdDsgICAgICAgICAgICAgICAgICAgIC8vIHB4IGJpcmlraW1pIChhbHQtcGlrc2VsIGtheWJvbG1hc8SxbikKICAgICAgY29u"
    "c3Qgc3RlcCA9IGQuYWNjID4gMCA/IE1hdGguZmxvb3IoZC5hY2MpIDogTWF0aC5jZWlsKGQuYWNjKTsKICAgICAgaWYoc3RlcCl7"
    "IGQuYWNjIC09IHN0ZXA7IGNvbnN0IHMwID0gd3JhcC5zY3JvbGxUb3A7IHdyYXAuc2Nyb2xsVG9wICs9IHN0ZXA7IGlmKHdyYXAu"
    "c2Nyb2xsVG9wICE9PSBzMCkgcGxhY2UoKTsgfQogICAgfSBlbHNlIGQuYWNjID0gMDsKICB9CiAgZC5yYWYgPSByZXF1ZXN0QW5p"
    "bWF0aW9uRnJhbWUoZWRnZVNjcm9sbCk7Cn0KZnVuY3Rpb24gY2xlYXJQZW5kKCl7IGNvbnN0IHAgPSBTLnBlbmQ7IGlmKHAgJiYg"
    "cC50aW1lcikgY2xlYXJUaW1lb3V0KHAudGltZXIpOyBTLnBlbmQgPSBudWxsOyB9CgpsaXN0LmFkZEV2ZW50TGlzdGVuZXIoInBv"
    "aW50ZXJkb3duIiwgZnVuY3Rpb24oZSl7CiAgaWYoZS5idXR0b24gPiAwIHx8IFMuZHJhZykgcmV0dXJuOwogIGlmKGUudGFyZ2V0"
    "LmNsb3Nlc3QoIi5hciwucm0iKSkgcmV0dXJuOyAgICAgICAgICAgICAgICAgICAgICAvLyBva2xhciB2ZSDDlyBzw7xyw7xrbGVt"
    "ZSBiYcWfbGF0bWF6CiAgY29uc3QgbGkgPSBlLnRhcmdldC5jbG9zZXN0KCIucm93Iik7IGlmKCFsaSkgcmV0dXJuOwogIGNvbnN0"
    "IGggPSBlLnRhcmdldC5jbG9zZXN0KCIuaCIpOwogIGlmKGgpeyBlLnByZXZlbnREZWZhdWx0KCk7IHN0YXJ0RHJhZyhsaSwgaCwg"
    "ZSk7IHJldHVybjsgfSAgICAvLyB0dXRhbWHDpzogYW7EsW5kYQogIGNvbnN0IHRvdWNoID0gZS5wb2ludGVyVHlwZSAhPT0gIm1v"
    "dXNlIjsKICBjb25zdCBwID0ge2xpOiBsaSwgeDA6IGUuY2xpZW50WCwgeTA6IGUuY2xpZW50WSwgZXY6IHtwb2ludGVySWQ6IGUu"
    "cG9pbnRlcklkLCBjbGllbnRZOiBlLmNsaWVudFl9LCB0aW1lcjogbnVsbH07CiAgaWYodG91Y2gpIHAudGltZXIgPSBzZXRUaW1l"
    "b3V0KGZ1bmN0aW9uKCl7ICAgICAgICAgICAgICAgICAgIC8vIGJhc8SxbMSxIHR1dCDihpIgc8O8csO8a2xlCiAgICBpZihTLnBl"
    "bmQgPT09IHAgJiYgIVMuZHJhZyl7IFMucGVuZCA9IG51bGw7IHN0YXJ0RHJhZyhwLmxpLCBwLmxpLCBwLmV2KTsgfSB9LCBIT0xE"
    "X01TKTsKICBTLnBlbmQgPSBwOyAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC8vIGZh"
    "cmU6IGhhcmVrZXQgZcWfacSfaW5pIGJla2xlCn0pOwpkb2N1bWVudC5hZGRFdmVudExpc3RlbmVyKCJ0b3VjaG1vdmUiLCBmdW5j"
    "dGlvbihlKXsgaWYoUy5kcmFnKSBlLnByZXZlbnREZWZhdWx0KCk7IH0sIHtwYXNzaXZlOiBmYWxzZX0pOwoKbGlzdC5hZGRFdmVu"
    "dExpc3RlbmVyKCJwb2ludGVybW92ZSIsIGZ1bmN0aW9uKGUpewogIGNvbnN0IHAgPSBTLnBlbmQ7CiAgaWYocCAmJiAhUy5kcmFn"
    "KXsKICAgIGNvbnN0IGR4ID0gTWF0aC5hYnMoZS5jbGllbnRYIC0gcC54MCksIGR5ID0gTWF0aC5hYnMoZS5jbGllbnRZIC0gcC55"
    "MCk7CiAgICBpZihlLnBvaW50ZXJUeXBlID09PSAibW91c2UiKXsKICAgICAgaWYoZHkgPiBNT1VTRV9TTE9QICYmIGR5ID4gZHgp"
    "eyBjbGVhclBlbmQoKTsgc3RhcnREcmFnKHAubGksIHAubGksIHtwb2ludGVySWQ6IGUucG9pbnRlcklkLCBjbGllbnRZOiBwLnkw"
    "fSk7IH0KICAgICAgZWxzZSBpZihkeCA+IDE0KSBjbGVhclBlbmQoKTsKICAgIH0gZWxzZSBpZihkeCA+IFRPVUNIX1NMT1AgfHwg"
    "ZHkgPiBUT1VDSF9TTE9QKSBjbGVhclBlbmQoKTsgLy8gcGFybWFrIGtheWTEsXLEsXlvciDihpIgbm9ybWFsIHNjcm9sbAogIH0K"
    "ICBjb25zdCBkID0gUy5kcmFnOyBpZighZCkgcmV0dXJuOwogIGQueSA9IGUuY2xpZW50WTsKICBwbGFjZSgpOwp9KTsKZnVuY3Rp"
    "b24gZW5kRHJhZyhjYW5jZWwpewogIGNsZWFyUGVuZCgpOwogIGNvbnN0IGQgPSBTLmRyYWc7IGlmKCFkKSByZXR1cm47CiAgUy5k"
    "cmFnID0gbnVsbDsKICBjYW5jZWxBbmltYXRpb25GcmFtZShkLnJhZik7CiAgZC5naG9zdC5yZW1vdmUoKTsgZC5saW5lLnJlbW92"
    "ZSgpOwogIGQubGkuY2xhc3NMaXN0LnJlbW92ZSgic3JjIik7IHdyYXAuY2xhc3NMaXN0LnJlbW92ZSgiZHJhZ2dpbmciKTsKICBj"
    "b25zdCB0byA9IGNhbmNlbCA9PT0gdHJ1ZSA/IGQuZnJvbSA6IGQudG87CiAgY29uc3Qgc3Rhc2ggPSBTLnN0YXNoOyBTLnN0YXNo"
    "ID0gbnVsbDsKICBpZih0byAhPT0gZC5mcm9tKXsKICAgIFMuanVzdERyYWdnZWQgPSBEYXRlLm5vdygpOyAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAvLyBoZW1lbiBhcmTEsW5kYW4gZ2VsZW4gY2xpY2sgImHDpyIgc2F5bWFzxLFuCiAgICBpZihz"
    "dGFzaCl7ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8gc8O8csO8a2xlcmtlbiBn"
    "ZWxlbiB0YXplIHZlcmkgKGZpeWF0bGFyKSDigJQgc8SxcmEgeWVyZWwga2FsxLFyCiAgICAgIFMub3B0cyA9IHN0YXNoLm9wdHMg"
    "fHwgUy5vcHRzOwogICAgICBjb25zdCBieSA9IHt9OyAoc3Rhc2gucm93cyB8fCBbXSkuZm9yRWFjaChyID0+IHsgaWYociAmJiBy"
    "LmlkICE9IG51bGwpIGJ5W3IuaWRdID0gcjsgfSk7CiAgICAgIFMucm93cyA9IFMucm93cy5tYXAociA9PiBieVtyLmlkXSB8fCBy"
    "KTsKICAgIH0KICAgIHJlb3JkZXJEb20oYXJyYXlNb3ZlKGQucHJldi5zbGljZSgpLCBkLmZyb20sIHRvKSk7ICAgICAgICAgICAv"
    "LyB0YW0gc3BsaWNlOiDDp8Sxa2FyIOKGkiBoZWRlZmUgZWtsZQogICAgY29tbWl0KGQucHJldiwgZC5pZCk7CiAgfSBlbHNlIHsK"
    "ICAgIGlmKGNhbmNlbCA9PT0gdHJ1ZSkgc2F5KCJNb3ZlIGNhbmNlbGxlZCIpOwogICAgaWYoc3Rhc2gpIGFwcGx5QXJncyhzdGFz"
    "aCk7CiAgfQp9Cmxpc3QuYWRkRXZlbnRMaXN0ZW5lcigicG9pbnRlcnVwIiwgZW5kRHJhZyk7Cmxpc3QuYWRkRXZlbnRMaXN0ZW5l"
    "cigicG9pbnRlcmNhbmNlbCIsIGZ1bmN0aW9uKCl7IGVuZERyYWcodHJ1ZSk7IH0pOyAgIC8vIHRhcmF5xLFjxLEgaGFyZWtldGkg"
    "ZGV2cmFsZMSxIOKGkiBpcHRhbApsaXN0LmFkZEV2ZW50TGlzdGVuZXIoImxvc3Rwb2ludGVyY2FwdHVyZSIsIGVuZERyYWcpOwpk"
    "b2N1bWVudC5hZGRFdmVudExpc3RlbmVyKCJrZXlkb3duIiwgZnVuY3Rpb24oZSl7CiAgaWYoUy5kcmFnICYmIGUua2V5ID09PSAi"
    "RXNjYXBlIil7IGUucHJldmVudERlZmF1bHQoKTsgZW5kRHJhZyh0cnVlKTsgfQp9KTsKCi8qIC0tLS0gdMSxa2xhbWFsYXIgKyBr"
    "bGF2eWUgLS0tLSAqLwpsaXN0LmFkZEV2ZW50TGlzdGVuZXIoImNsaWNrIiwgZnVuY3Rpb24oZSl7CiAgY29uc3QgbGkgPSBlLnRh"
    "cmdldC5jbG9zZXN0KCIucm93Iik7IGlmKCFsaSkgcmV0dXJuOwogIGNvbnN0IGkgPSBbLi4ubGlzdC5jaGlsZHJlbl0uaW5kZXhP"
    "ZihsaSk7CiAgaWYoZS50YXJnZXQuY2xvc2VzdCgiLnVwIikpIHJldHVybiBtb3ZlKGksIGkgLSAxKTsKICBpZihlLnRhcmdldC5j"
    "bG9zZXN0KCIuZG4iKSkgcmV0dXJuIG1vdmUoaSwgaSArIDEpOwogIGlmKGUudGFyZ2V0LmNsb3Nlc3QoIi5ybSIpKSByZXR1cm4g"
    "c2VuZCh7dDogInJlbW92ZSIsIGlkOiBsaS5kYXRhc2V0LmlkfSk7CiAgaWYoRGF0ZS5ub3coKSAtIFMuanVzdERyYWdnZWQgPCA0"
    "MDApIHJldHVybjsgICAgICAgICAgICAgICAvLyBzw7xyw7xrbGVtZSBzb25yYXPEsSB0xLFrbGFtYSBkZcSfaWwKICBpZihTLm9w"
    "dHMuY2xpY2thYmxlICYmIGUudGFyZ2V0LmNsb3Nlc3QoIi5ubSwuYXYsLmMsLmV4dHEiKSkgc2VuZCh7dDogIm9wZW4iLCBpZDog"
    "bGkuZGF0YXNldC5pZH0pOwp9KTsKbGlzdC5hZGRFdmVudExpc3RlbmVyKCJrZXlkb3duIiwgZnVuY3Rpb24oZSl7CiAgY29uc3Qg"
    "aCA9IGUudGFyZ2V0LmNsb3Nlc3QoIi5oIik7IGlmKCFoKSByZXR1cm47CiAgY29uc3QgbGkgPSBoLmNsb3Nlc3QoIi5yb3ciKTsg"
    "Y29uc3QgaSA9IFsuLi5saXN0LmNoaWxkcmVuXS5pbmRleE9mKGxpKTsKICBpZihlLmtleSA9PT0gIkFycm93VXAiKXsgZS5wcmV2"
    "ZW50RGVmYXVsdCgpOyBtb3ZlKGksIGkgLSAxKTsgfQogIGVsc2UgaWYoZS5rZXkgPT09ICJBcnJvd0Rvd24iKXsgZS5wcmV2ZW50"
    "RGVmYXVsdCgpOyBtb3ZlKGksIGkgKyAxKTsgfQogIGVsc2UgaWYoZS5rZXkgPT09ICJIb21lIil7IGUucHJldmVudERlZmF1bHQo"
    "KTsgbW92ZShpLCAwKTsgfQogIGVsc2UgaWYoZS5rZXkgPT09ICJFbmQiKXsgZS5wcmV2ZW50RGVmYXVsdCgpOyBtb3ZlKGksIGxp"
    "c3QuY2hpbGRyZW4ubGVuZ3RoIC0gMSk7IH0KfSk7CgpmdW5jdGlvbiBhcHBseUFyZ3MoYSl7CiAgZG9jdW1lbnQuZG9jdW1lbnRF"
    "bGVtZW50LmNsYXNzTGlzdC50b2dnbGUoImxpZ2h0IiwgISFhLmxpZ2h0KTsKICBpZihhLmFjY2VudCkgZG9jdW1lbnQuZG9jdW1l"
    "bnRFbGVtZW50LnN0eWxlLnNldFByb3BlcnR5KCItLWFjYyIsIGEuYWNjZW50KTsKICBpZihTLmRyYWcpeyBTLnN0YXNoID0gYTsg"
    "cmV0dXJuOyB9ICAgICAgICAgICAgICAgICAgICAvLyBzw7xyw7xrbGVtZSBzw7xyZXJrZW4gw6dpem1lIOKAlCBiaXRpbmNlIHV5"
    "Z3VsYQogIFMub3B0cyA9IGEub3B0cyB8fCB7fTsKICBsZXQgcm93cyA9IChhLnJvd3MgfHwgW10pLmZpbHRlcihyID0+IHIgJiYg"
    "ci5pZCAhPSBudWxsKTsKICBjb25zdCBnID0gUy5ndWFyZDsKICBpZihnKXsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAvLyB0YcWfxLFtYWRhbiBoZW1lbiBzb25yYSBlc2tpIHPEsXJheWxhIGdlbGVuIMOnaXppbQogICAg"
    "Y29uc3QgaWRzID0gcm93cy5tYXAociA9PiByLmlkKS5qb2luKCJcdTAwMDEiKTsKICAgIGlmKERhdGUubm93KCkgPCBnLnVudGls"
    "ICYmIGlkcyA9PT0gZy5wcmV2KXsKICAgICAgY29uc3QgYnkgPSB7fTsgcm93cy5mb3JFYWNoKHIgPT4gYnlbci5pZF0gPSByKTsK"
    "ICAgICAgcm93cyA9IGcubm93Lm1hcChpZCA9PiBieVtpZF0pLmZpbHRlcihCb29sZWFuKTsgICAvLyB2ZXJpIHRhemUsIHPEsXJh"
    "IHllbmkga2FsxLFyCiAgICB9IGVsc2UgUy5ndWFyZCA9IG51bGw7ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLy8geWVu"
    "aSBzxLFyYSAoeWEgZGEgYmHFn2thIGRlxJ9pxZ9pa2xpaykgZ2VsZGkKICB9CiAgUy5yb3dzID0gcm93czsKICByZW5kZXIoKTsK"
    "fQp3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigibWVzc2FnZSIsIGZ1bmN0aW9uKGUpewogIGNvbnN0IGQgPSBlLmRhdGEgfHwge307"
    "CiAgaWYoZC50eXBlID09PSAic3RyZWFtbGl0OnJlbmRlciIpIGFwcGx5QXJncyhkLmFyZ3MgfHwge30pOwp9KTsKbmV3IFJlc2l6"
    "ZU9ic2VydmVyKGZpdCkub2JzZXJ2ZShsaXN0KTsKbmV3IFJlc2l6ZU9ic2VydmVyKGZ1bmN0aW9uKCl7IGlmKCFTLmRyYWcgJiYg"
    "Uy5vcHRzLmNvbHMgJiYgdmlzQ29scygpICE9PSBTLnZpcykgcmVuZGVyKCk7IH0pLm9ic2VydmUoZG9jdW1lbnQuZG9jdW1lbnRF"
    "bGVtZW50KTsKaWYod2luZG93Ll9fUExJU1RfQVJHU19fKSBhcHBseUFyZ3Mod2luZG93Ll9fUExJU1RfQVJHU19fKTsgICAgICAg"
    "Ly8geWFsbsSxemNhIMO2bml6bGVtZSAvIHRlc3QKZWxzZSBpZihpblN0cmVhbWxpdCkgc3RTZW5kKCJzdHJlYW1saXQ6Y29tcG9u"
    "ZW50UmVhZHkiLCB7YXBpVmVyc2lvbjogMX0pOwp3aW5kb3cuUExJU1QgPSB7UzogUywgbW92ZTogbW92ZSwgb3JkZXI6IG9yZGVy"
    "LCBhcHBseUFyZ3M6IGFwcGx5QXJncywgc2VudDogKCkgPT4gUy5zZW50LCBhcnJheU1vdmU6IGFycmF5TW92ZX07Cjwvc2NyaXB0"
    "Pgo8L2JvZHk+CjwvaHRtbD4K"
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


# ----------------------------------------------------------------------
# v5.9 — Global Macro dünya ısı haritası (pulse_macro/index.html)
#   Bileşen uygulamaya gömülü (zlib + base64): klasör yüklenmemiş ya da eski kalmışsa da çalışır.
#   İsteğe bağlı: pulse_macro/countries-110m.json (world-atlas) yüklenirse harita CDN yerine oradan okunur.
# ----------------------------------------------------------------------
_MACRO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_macro")
_MACRO_INDEX = os.path.join(_MACRO_DIR, "index.html")
_MACRO_Z = (
    "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"
    "wk351xX/P+qeDF8="
)


def _macro_html():
    try:
        return zlib.decompress(base64.b64decode("".join(_MACRO_Z))) if _MACRO_Z else b""
    except Exception:
        return b""


def _macro_version(head):
    m = re.search(r'name="pulse-macro"\s+content="([^"]+)"', head or "")
    return m.group(1) if m else "0"


def macro_versions():
    """(gömülü sürüm, klasördeki sürüm ya da None) — ör. ('5.9', None)."""
    emb = _macro_html()
    emb_v = _macro_version(emb[:600].decode("utf-8", "ignore")) if emb else None
    try:
        with open(_MACRO_INDEX, encoding="utf-8") as fh:
            disk = _macro_version(fh.read(600))
    except OSError:
        disk = None
    return emb_v, disk


@st.cache_resource(show_spinner=False)
def _macro_component():
    """Klasördeki dosya gömülü kopyadan eski değilse o kullanılır; yoksa gömülü kopya geçici klasöre yazılır."""
    emb_v, disk = macro_versions()
    d = _MACRO_DIR
    if disk is None or (emb_v and _ver_tuple(disk) < _ver_tuple(emb_v)):
        html = _macro_html()
        if not html:
            if disk is None:
                return None
        else:
            try:
                import hashlib
                import shutil
                d = os.path.join(tempfile.gettempdir(), "pulse_macro_" + hashlib.sha1(html).hexdigest()[:10])
                os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, "index.html")
                if not os.path.isfile(fp):
                    with open(fp, "wb") as f:
                        f.write(html)
                geo = os.path.join(_MACRO_DIR, "countries-110m.json")
                if os.path.isfile(geo) and not os.path.isfile(os.path.join(d, "countries-110m.json")):
                    shutil.copyfile(geo, os.path.join(d, "countries-110m.json"))
            except Exception:
                if disk is None:
                    return None
                d = _MACRO_DIR
    try:
        return components.declare_component("pulse_macro", path=d)
    except Exception:
        return None


def macro_available():
    return _macro_component() is not None


def macro_map(data, key="mc_map", tab="gdp", scope="g20", order="desc", light=False, rev=0):
    """Global Macro bileşeni. Döner: son olay ({'t': 'state', 'tab', 'scope', 'order', 'n'}) ya da None.
    Sekme / ülke seçimi tarayıcıda çalışır; yalnızca sekme / kapsam / sıralama değişince olay gelir."""
    comp = _macro_component()
    if comp is None:
        return None
    return comp(key=key, default=None, data=data, tab=tab, scope=scope, order=order, light=bool(light),
                rev=int(rev or 0))


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
