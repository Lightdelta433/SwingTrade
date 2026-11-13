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

CHART_VERSION = "5.0"
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
UI_VERSION = "5.0"     # pulse_chart/index.html içindeki <meta name="pulse-ui"> ile aynı olmalı


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
_LIST_B64 = "PCFkb2N0eXBlIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij4KPG1ldGEgbmFtZT0icHVsc2UtbGlzdCIgY29udGVudD0iNS4wIj4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEiPgo8dGl0bGU+UHVsc2Ugc29ydGFibGUgbGlzdDwvdGl0bGU+CjxzdHlsZT4KLyogUHVsc2Ug4oCUIHPEsXJhbGFuYWJpbGlyIGxpc3RlIChpemxlbWUgbGlzdGVsZXJpKS4gdjUuMDogc2F0xLFyxLFuIEhFUkhBTkfEsCBiaXIgeWVyaW5kZW4gc8O8csO8a2xlCiAgIChmYXJlOiA2IHB4IGhhcmVrZXRsZSBiYcWfbGFyIMK3IGRva3VubWF0aWs6IGJhc8SxbMSxIHR1dCwgc29ucmEgc8O8csO8a2xlKSwg4ouu4ouuIHR1dGFtYWPEsSBhbsSxbmRhIHPDvHLDvGtsZXIsCiAgIOKGkSAvIOKGkyBva2xhcsSxIHRlayBrb251bSB0YcWfxLFyOyDimIDvuI8gLyDwn4yZIHNlYW5zIGTEscWfxLEgc2F0xLFyxLEgc2HEn2EgeWFzbMSxIGfDtnN0ZXJpbGlyLiAqLwo6cm9vdHstLWJnOnRyYW5zcGFyZW50Oy0tcm93OiMwRjExMTU7LS1yb3doOiMxNTE5MjI7LS1saW5lOiMxQzFGMjU7LS10eHQ6I0VDRUVGMTstLW11dDojOEQ5NkE1Oy0tZGltOiM1QjYyNzA7CiAtLWFjYzojNUI4Q0ZGOy0tdXA6IzNEREM5NzstLWRvd246I0Y4NzE3MTstLXNlbDojMTUxOTIyfQo6cm9vdC5saWdodHstLXJvdzojRkZGRkZGOy0tcm93aDojRjNGNUY5Oy0tbGluZTojRTZFOUVGOy0tdHh0OiMxNDE3MUM7LS1tdXQ6IzVCNjQ3NTstLWRpbTojOUFBMkIxOy0tc2VsOiNFRUYyRkJ9Cip7Ym94LXNpemluZzpib3JkZXItYm94fQpbaGlkZGVuXXtkaXNwbGF5Om5vbmUgIWltcG9ydGFudH0KaHRtbCxib2R5e21hcmdpbjowO3BhZGRpbmc6MDtiYWNrZ3JvdW5kOnZhcigtLWJnKTtjb2xvcjp2YXIoLS10eHQpOwogZm9udC1mYW1pbHk6IlNvdXJjZSBTYW5zIDMiLCJTb3VyY2UgU2FucyBQcm8iLHN5c3RlbS11aSwtYXBwbGUtc3lzdGVtLCJTZWdvZSBVSSIsc2Fucy1zZXJpZjtmb250LXNpemU6MTNweDsKIC13ZWJraXQtZm9udC1zbW9vdGhpbmc6YW50aWFsaWFzZWQ7b3ZlcmZsb3c6aGlkZGVufQojd3JhcHtwb3NpdGlvbjpyZWxhdGl2ZTtvdmVyZmxvdy15OmF1dG87b3ZlcmZsb3cteDpoaWRkZW47b3ZlcnNjcm9sbC1iZWhhdmlvcjpjb250YWluO3BhZGRpbmc6MCAycHh9CiN3cmFwOjotd2Via2l0LXNjcm9sbGJhcnt3aWR0aDo4cHh9CiN3cmFwOjotd2Via2l0LXNjcm9sbGJhci10aHVtYntiYWNrZ3JvdW5kOmNvbG9yLW1peChpbiBzcmdiLHZhcigtLWFjYykgMzAlLCMyQTJGMzcpO2JvcmRlci1yYWRpdXM6OHB4fQouaGRye2Rpc3BsYXk6Z3JpZDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDtwYWRkaW5nOjZweCA4cHggN3B4IDhweDtmb250LXNpemU6MTAuNXB4O2ZvbnQtd2VpZ2h0OjcwMDsKIGxldHRlci1zcGFjaW5nOi4wN2VtO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtjb2xvcjp2YXIoLS1kaW0pO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWxpbmUpfQoubGlzdHtwb3NpdGlvbjpyZWxhdGl2ZTtsaXN0LXN0eWxlOm5vbmU7bWFyZ2luOjA7cGFkZGluZzowfQoucm93e2Rpc3BsYXk6Z3JpZDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDtwYWRkaW5nOjZweCA4cHg7Ym9yZGVyLXJhZGl1czoxMHB4OwogYmFja2dyb3VuZDp0cmFuc3BhcmVudDtwb3NpdGlvbjpyZWxhdGl2ZTt1c2VyLXNlbGVjdDpub25lOy13ZWJraXQtdXNlci1zZWxlY3Q6bm9uZTstd2Via2l0LXRvdWNoLWNhbGxvdXQ6bm9uZTsKIHRyYW5zaXRpb246dHJhbnNmb3JtIC4xNnMgZWFzZSxiYWNrZ3JvdW5kIC4xMnMgZWFzZSxib3gtc2hhZG93IC4xMnMgZWFzZX0KLnJvdysucm93OjpiZWZvcmV7Y29udGVudDoiIjtwb3NpdGlvbjphYnNvbHV0ZTtsZWZ0OjEwcHg7cmlnaHQ6MTBweDt0b3A6MDtoZWlnaHQ6MXB4O2JhY2tncm91bmQ6dmFyKC0tbGluZSk7CiBwb2ludGVyLWV2ZW50czpub25lfQoucm93OmhvdmVyOjpiZWZvcmUsLnJvdzpob3Zlcisucm93OjpiZWZvcmUsLnJvdy5zZWw6OmJlZm9yZSwucm93LnNlbCsucm93OjpiZWZvcmUsLnJvdy5kcmFnOjpiZWZvcmV7b3BhY2l0eTowfQoucm93OmhvdmVye2JhY2tncm91bmQ6dmFyKC0tcm93aCl9Ci5yb3cuc2Vse2JhY2tncm91bmQ6dmFyKC0tc2VsKTtib3gtc2hhZG93Omluc2V0IDNweCAwIDAgdmFyKC0tYWNjKX0KLnJvdy5kcmFne3RyYW5zaXRpb246bm9uZTt6LWluZGV4OjU7YmFja2dyb3VuZDp2YXIoLS1yb3doKTtjdXJzb3I6Z3JhYmJpbmc7CiBib3gtc2hhZG93OjAgMTJweCAzMHB4IC04cHggcmdiYSgwLDAsMCwuNzApLDAgMCAwIDFweCBjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDU1JSx0cmFuc3BhcmVudCl9Ci5yb3cubGlmdHthbmltYXRpb246bGlmdCAuMTRzIGVhc2V9CkBrZXlmcmFtZXMgbGlmdHswJXtib3gtc2hhZG93Om5vbmV9MTAwJXtib3gtc2hhZG93OjAgMTJweCAzMHB4IC04cHggcmdiYSgwLDAsMCwuNzApfX0KLnJvdy5tb3ZlZHthbmltYXRpb246Zmxhc2ggLjdzIGVhc2V9CkBrZXlmcmFtZXMgZmxhc2h7MCV7YmFja2dyb3VuZDpjb2xvci1taXgoaW4gc3JnYix2YXIoLS1hY2MpIDIyJSx0cmFuc3BhcmVudCl9MTAwJXtiYWNrZ3JvdW5kOnRyYW5zcGFyZW50fX0KLmh7d2lkdGg6MThweDtoZWlnaHQ6MjhweDtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpjZW50ZXI7Y29sb3I6dmFyKC0tZGltKTtjdXJzb3I6Z3JhYjsKIGJvcmRlci1yYWRpdXM6NnB4O3RvdWNoLWFjdGlvbjpub25lO2ZvbnQtc2l6ZToxNXB4O2xldHRlci1zcGFjaW5nOi0zcHg7bGluZS1oZWlnaHQ6MTtvdXRsaW5lOm5vbmV9Ci5oOmhvdmVyLC5oOmZvY3VzLXZpc2libGV7Y29sb3I6dmFyKC0tdHh0KTtiYWNrZ3JvdW5kOmNvbG9yLW1peChpbiBzcmdiLHZhcigtLWFjYykgMTQlLHRyYW5zcGFyZW50KX0KLnJvdy5kcmFnIC5oe2N1cnNvcjpncmFiYmluZztjb2xvcjp2YXIoLS1hY2MpfQouYXZ7cG9zaXRpb246cmVsYXRpdmU7ZGlzcGxheTppbmxpbmUtZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjtib3JkZXItcmFkaXVzOjUwJTtvdmVyZmxvdzpoaWRkZW47CiBmbGV4Om5vbmU7Zm9udC13ZWlnaHQ6ODAwO2xldHRlci1zcGFjaW5nOi0uMDJlbX0KLmF2IGltZ3twb3NpdGlvbjphYnNvbHV0ZTtpbnNldDowO3dpZHRoOjEwMCU7aGVpZ2h0OjEwMCU7b2JqZWN0LWZpdDpjb250YWluO2JhY2tncm91bmQ6I0YxRjJGNDtwYWRkaW5nOjNweH0KLm5te21pbi13aWR0aDowO2xpbmUtaGVpZ2h0OjEuMjU7Y3Vyc29yOmRlZmF1bHR9Ci5jbGlja2FibGUgLm5te2N1cnNvcjpwb2ludGVyfQoubm0gYntkaXNwbGF5OmJsb2NrO2ZvbnQtZmFtaWx5OnVpLW1vbm9zcGFjZSxTRk1vbm8tUmVndWxhcixNZW5sbyxtb25vc3BhY2U7Zm9udC1zaXplOjEyLjVweDt3aGl0ZS1zcGFjZTpub3dyYXA7CiBvdmVyZmxvdzpoaWRkZW47dGV4dC1vdmVyZmxvdzplbGxpcHNpc30KLm5tIGl7ZGlzcGxheTpibG9jaztmb250LXN0eWxlOm5vcm1hbDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtc2l6ZToxMXB4O3doaXRlLXNwYWNlOm5vd3JhcDtvdmVyZmxvdzpoaWRkZW47CiB0ZXh0LW92ZXJmbG93OmVsbGlwc2lzfQouY3t0ZXh0LWFsaWduOnJpZ2h0O2ZvbnQtZmFtaWx5OnVpLW1vbm9zcGFjZSxTRk1vbm8tUmVndWxhcixNZW5sbyxtb25vc3BhY2U7Zm9udC12YXJpYW50LW51bWVyaWM6dGFidWxhci1udW1zOwogd2hpdGUtc3BhY2U6bm93cmFwO2xpbmUtaGVpZ2h0OjEuMjU7bWluLXdpZHRoOjA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9Ci5jIC5ze2Rpc3BsYXk6YmxvY2s7Zm9udC1zaXplOjExcHg7Zm9udC13ZWlnaHQ6NzAwfQouYXJ7ZGlzcGxheTpmbGV4O2dhcDoycHh9Ci5hciBidXR0b24sLnJte3dpZHRoOjI0cHg7aGVpZ2h0OjI0cHg7Ym9yZGVyLXJhZGl1czo3cHg7Ym9yZGVyOjFweCBzb2xpZCB0cmFuc3BhcmVudDtiYWNrZ3JvdW5kOnRyYW5zcGFyZW50O2NvbG9yOnZhcigtLWRpbSk7CiBmb250LXNpemU6MTNweDtsaW5lLWhlaWdodDoxO2N1cnNvcjpwb2ludGVyO2Rpc3BsYXk6aW5saW5lLWZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpjZW50ZXI7cGFkZGluZzowfQouYXIgYnV0dG9uOmhvdmVyOm5vdCg6ZGlzYWJsZWQpe2NvbG9yOnZhcigtLXR4dCk7Ym9yZGVyLWNvbG9yOmNvbG9yLW1peChpbiBzcmdiLHZhcigtLWFjYykgNDUlLHRyYW5zcGFyZW50KTsKIGJhY2tncm91bmQ6Y29sb3ItbWl4KGluIHNyZ2IsdmFyKC0tYWNjKSAxMiUsdHJhbnNwYXJlbnQpfQouYXIgYnV0dG9uOmRpc2FibGVke29wYWNpdHk6LjI1O2N1cnNvcjpkZWZhdWx0fQoucm06aG92ZXJ7Y29sb3I6dmFyKC0tZG93bik7Ym9yZGVyLWNvbG9yOnJnYmEoMjQ4LDExMywxMTMsLjQ1KTtiYWNrZ3JvdW5kOnJnYmEoMjQ4LDExMywxMTMsLjA4KX0KLmVtcHR5e2NvbG9yOnZhcigtLW11dCk7cGFkZGluZzoxMnB4IDZweDtmb250LXNpemU6MTIuNXB4fQouZXh0cXtncmlkLWNvbHVtbjozLy0xO2dyaWQtcm93OjI7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpmbGV4LWVuZDthbGlnbi1pdGVtczpiYXNlbGluZTtnYXA6N3B4OwogbWFyZ2luLXRvcDoxcHg7Zm9udC1mYW1pbHk6dWktbW9ub3NwYWNlLFNGTW9uby1SZWd1bGFyLE1lbmxvLG1vbm9zcGFjZTtmb250LXZhcmlhbnQtbnVtZXJpYzp0YWJ1bGFyLW51bXM7CiBmb250LXNpemU6MTAuNXB4O2ZvbnQtd2VpZ2h0OjYwMDt3aGl0ZS1zcGFjZTpub3dyYXA7b3ZlcmZsb3c6aGlkZGVuO21pbi13aWR0aDowfQouZXh0cSBpe2ZvbnQtc3R5bGU6bm9ybWFsO2ZvbnQtc2l6ZToxMHB4O2ZvbnQtZmFtaWx5OiJTZWdvZSBVSSBFbW9qaSIsIk5vdG8gQ29sb3IgRW1vamkiLHNhbnMtc2VyaWZ9Ci5leHRxIGJ7Zm9udC13ZWlnaHQ6NzAwO2NvbG9yOnZhcigtLXR4dCl9Ci5zcntwb3NpdGlvbjphYnNvbHV0ZTt3aWR0aDoxcHg7aGVpZ2h0OjFweDtvdmVyZmxvdzpoaWRkZW47Y2xpcDpyZWN0KDAgMCAwIDApfQo8L3N0eWxlPgo8L2hlYWQ+Cjxib2R5Pgo8ZGl2IGlkPSJ3cmFwIj48ZGl2IGlkPSJoZHIiIGNsYXNzPSJoZHIiIGhpZGRlbj48L2Rpdj48dWwgaWQ9Imxpc3QiIGNsYXNzPSJsaXN0IiByb2xlPSJsaXN0Ym94Ij48L3VsPgo8ZGl2IGlkPSJlbXB0eSIgY2xhc3M9ImVtcHR5IiBoaWRkZW4+PC9kaXY+PC9kaXY+CjxkaXYgaWQ9ImxpdmUiIGNsYXNzPSJzciIgYXJpYS1saXZlPSJwb2xpdGUiPjwvZGl2Pgo8c2NyaXB0PgoidXNlIHN0cmljdCI7CmNvbnN0IGluU3RyZWFtbGl0ID0gd2luZG93LnBhcmVudCAmJiB3aW5kb3cucGFyZW50ICE9PSB3aW5kb3c7CmNvbnN0IFMgPSB7cm93czogW10sIG9wdHM6IHt9LCBuOiAwLCBkcmFnOiBudWxsLCBzZW50OiBbXSwgdmlzOiAwfTsKY29uc3Qgd3JhcCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ3cmFwIiksIGxpc3QgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibGlzdCIpOwoKZnVuY3Rpb24gc3RTZW5kKHR5cGUsIGRhdGEpeyBpZighaW5TdHJlYW1saXQpIHJldHVybjsKICB3aW5kb3cucGFyZW50LnBvc3RNZXNzYWdlKE9iamVjdC5hc3NpZ24oe2lzU3RyZWFtbGl0TWVzc2FnZTogdHJ1ZSwgdHlwZTogdHlwZX0sIGRhdGEgfHwge30pLCAiKiIpOyB9CmZ1bmN0aW9uIHNlbmQoZXYpewogIFMubiA9IE1hdGgubWF4KFMubiArIDEsIERhdGUubm93KCkpOyAgICAgLy8gaWZyYW1lIHllbmlkZW4gecO8a2xlbnNlIGRlIChzZWttZSBkZcSfacWfaW1pKSBzYXlhw6cgaGVwIHllbmkg4oaSIG9sYXkga2F5Ym9sbWF6CiAgY29uc3QgdiA9IE9iamVjdC5hc3NpZ24oe246IFMubiwga2V5OiBTLm9wdHMua2V5IHx8ICIifSwgZXYpOwogIFMuc2VudC5wdXNoKHYpOwogIHN0U2VuZCgic3RyZWFtbGl0OnNldENvbXBvbmVudFZhbHVlIiwge3ZhbHVlOiB2LCBkYXRhVHlwZTogImpzb24ifSk7Cn0KZnVuY3Rpb24gZXNjKHMpeyByZXR1cm4gU3RyaW5nKHMgPT0gbnVsbCA/ICIiIDogcykucmVwbGFjZSgvWyY8PiInXS9nLCBjID0+ICh7IiYiOiImYW1wOyIsIjwiOiImbHQ7IiwiPiI6IiZndDsiLAogICciJzoiJnF1b3Q7IiwiJyI6IiYjMzk7In0pW2NdKTsgfQoKLyogZGFyIGVrcmFuZGEgKHRlbGVmb24pIHPDvHR1bmxhciBzb25kYW4gZ2l6bGVuaXIg4oCUIHNhecSxbGFyIGFzbGEgdGHFn21heiAvIGtlc2lsbWV6LCBhZCBzw7x0dW51IGVuIGF6IDgwIHB4IGthbMSxciAqLwpmdW5jdGlvbiB2aXNDb2xzKCl7CiAgY29uc3QgY29scyA9IFMub3B0cy5jb2xzIHx8IFtdLCBjb2x3ID0gUy5vcHRzLmNvbHcgfHwgW107CiAgY29uc3QgVyA9ICh3cmFwLmNsaWVudFdpZHRoIHx8IGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5jbGllbnRXaWR0aCB8fCA0MDApIC0gNDsKICBjb25zdCBweCA9IHcgPT4gcGFyc2VGbG9hdCh3KSB8fCA3MDsKICBjb25zdCBmaXhlZCA9IGsgPT4gMTggKyAoUy5vcHRzLmF2IHx8IDI2KSArIGNvbHcuc2xpY2UoMCwgaykucmVkdWNlKChhLCB3KSA9PiBhICsgcHgodyksIDApICsgNTIKICAgICsgKFMub3B0cy5yZW1vdmFibGUgPyAyNCA6IDApICsgOCAqICgzICsgayArIChTLm9wdHMucmVtb3ZhYmxlID8gMSA6IDApKSArIDE2OwogIGxldCBuID0gY29scy5sZW5ndGg7CiAgd2hpbGUobiA+IDEgJiYgVyAtIGZpeGVkKG4pIDwgODApIG4tLTsKICByZXR1cm4gbjsKfQpmdW5jdGlvbiBncmlkKCl7CiAgY29uc3QgbmMgPSBTLnZpczsKICByZXR1cm4gIjE4cHggIiArIChTLm9wdHMuYXYgfHwgMjYpICsgInB4IG1pbm1heCgwLDFmcikgIiArIChTLm9wdHMuY29sdyB8fCBbXSkuc2xpY2UoMCwgbmMpLm1hcCh3ID0+IHcgfHwgImF1dG8iKS5qb2luKCIgIikKICAgICsgIiA1MnB4IiArIChTLm9wdHMucmVtb3ZhYmxlID8gIiAyNHB4IiA6ICIiKTsKfQoKZnVuY3Rpb24gZXh0SFRNTChyKXsKICBjb25zdCBlID0gci5leHQ7CiAgaWYoIWUgfHwgZS5weCA9PSBudWxsKSByZXR1cm4gIiI7CiAgcmV0dXJuICc8c3BhbiBjbGFzcz0iZXh0cSIgdGl0bGU9IicgKyBlc2MoZS5sYWIgfHwgIiIpICsgJyDigJQgY2hhbmdlIHZzIHRoZSByZWd1bGFyIGNsb3NlIj48aSBzdHlsZT0iY29sb3I6JwogICAgKyBlc2MoZS5pYyB8fCAidmFyKC0tbXV0KSIpICsgJyI+JyArIGVzYyhlLmkgfHwgIiIpICsgJzwvaT48Yj4nICsgZXNjKGUucHgpICsgJzwvYj48c3BhbiBzdHlsZT0iY29sb3I6JwogICAgKyBlc2MoZS5jIHx8ICJ2YXIoLS1tdXQpIikgKyAnIj4nICsgZXNjKGUudCB8fCAiIikgKyAnPC9zcGFuPjwvc3Bhbj4nOwp9CgpmdW5jdGlvbiByb3dIVE1MKHIsIGksIG4pewogIGNvbnN0IHN6ID0gUy5vcHRzLmF2IHx8IDI2OwogIGNvbnN0IGF2ID0gJzxzcGFuIGNsYXNzPSJhdiIgc3R5bGU9IndpZHRoOicgKyBzeiArICdweDtoZWlnaHQ6JyArIHN6ICsgJ3B4O2ZvbnQtc2l6ZTonICsgTWF0aC5tYXgoOSwgTWF0aC5yb3VuZChzeiAqIC4zNCkpCiAgICArICdweDtiYWNrZ3JvdW5kOicgKyBlc2Moci5hdmJnIHx8ICIjMjYzMDNGIikgKyAnO2NvbG9yOicgKyBlc2Moci5hdmZnIHx8ICIjQzlEM0UzIikgKyAnIj4nICsgZXNjKHIuaW5pIHx8ICI/IikKICAgICsgKHIubG9nbyA/ICc8aW1nIHNyYz0iJyArIGVzYyhyLmxvZ28pICsgJyIgYWx0PSIiIGxvYWRpbmc9ImxhenkiIG9uZXJyb3I9InRoaXMucmVtb3ZlKCkiPicgOiAiIikgKyAnPC9zcGFuPic7CiAgY29uc3QgY2VsbHMgPSAoci5jZWxscyB8fCBbXSkuc2xpY2UoMCwgUy52aXMpLm1hcChjID0+ICc8c3BhbiBjbGFzcz0iYyI+JyArIChjLnYgIT0gbnVsbCA/ICc8c3BhbicgKyAoYy5jID8gJyBzdHlsZT0iY29sb3I6JyArIGVzYyhjLmMpICsgJyInIDogIiIpCiAgICArIChjLmIgPyAnIGNsYXNzPSJzIicgOiAiIikgKyAnPicgKyBlc2MoYy52KSArICc8L3NwYW4+JyA6ICIiKQogICAgKyAoYy5zICE9IG51bGwgPyAnPHNwYW4gY2xhc3M9InMiJyArIChjLnNjID8gJyBzdHlsZT0iY29sb3I6JyArIGVzYyhjLnNjKSArICciJyA6ICIiKSArICc+JyArIGVzYyhjLnMpICsgJzwvc3Bhbj4nIDogIiIpCiAgICArICc8L3NwYW4+Jykuam9pbigiIik7CiAgcmV0dXJuICc8bGkgY2xhc3M9InJvdycgKyAoci5zZWwgPyAiIHNlbCIgOiAiIikgKyAnIiByb2xlPSJvcHRpb24iIGRhdGEtaWQ9IicgKyBlc2Moci5pZCkgKyAnIiBzdHlsZT0iZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOicKICAgICsgZ3JpZCgpICsgJyI+JwogICAgKyAnPHNwYW4gY2xhc3M9ImgiIHRhYmluZGV4PSIwIiByb2xlPSJidXR0b24iIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgKGRyYWcsIG9yIHVzZSB0aGUgYXJyb3cga2V5cykiICcKICAgICsgJ3RpdGxlPSJEcmFnIHRvIHJlb3JkZXIiPuKLruKLrjwvc3Bhbj4nICsgYXYKICAgICsgJzxzcGFuIGNsYXNzPSJubSIgdGl0bGU9IicgKyBlc2Moci5zdWIgfHwgIiIpICsgJyI+PGI+JyArIGVzYyhyLnRpdGxlKSArICc8L2I+PGk+JyArIGVzYyhyLnN1YiB8fCAiIikgKyAnPC9pPjwvc3Bhbj4nCiAgICArIGNlbGxzCiAgICArIGV4dEhUTUwocikKICAgICsgJzxzcGFuIGNsYXNzPSJhciI+PGJ1dHRvbiBjbGFzcz0idXAiIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgdXAiIHRpdGxlPSJNb3ZlIHVwIicgKyAoaSA9PT0gMCA/ICIgZGlzYWJsZWQiIDogIiIpCiAgICArICc+4oaRPC9idXR0b24+PGJ1dHRvbiBjbGFzcz0iZG4iIGFyaWEtbGFiZWw9Ik1vdmUgJyArIGVzYyhyLnRpdGxlKSArICcgZG93biIgdGl0bGU9Ik1vdmUgZG93biInICsgKGkgPT09IG4gLSAxID8gIiBkaXNhYmxlZCIgOiAiIikKICAgICsgJz7ihpM8L2J1dHRvbj48L3NwYW4+JwogICAgKyAoUy5vcHRzLnJlbW92YWJsZSA/ICc8YnV0dG9uIGNsYXNzPSJybSIgYXJpYS1sYWJlbD0iUmVtb3ZlICcgKyBlc2Moci50aXRsZSkgKyAnIiB0aXRsZT0iUmVtb3ZlIj7DlzwvYnV0dG9uPicgOiAiIikKICAgICsgJzwvbGk+JzsKfQoKZnVuY3Rpb24gcmVuZGVyKCl7CiAgY29uc3Qgcm93cyA9IFMucm93cywgbiA9IHJvd3MubGVuZ3RoOwogIFMudmlzID0gdmlzQ29scygpOwogIGNvbnN0IGhkciA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJoZHIiKSwgZW0gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZW1wdHkiKTsKICB3cmFwLmNsYXNzTGlzdC50b2dnbGUoImNsaWNrYWJsZSIsICEhUy5vcHRzLmNsaWNrYWJsZSk7CiAgaWYoUy5vcHRzLmNvbHMgJiYgUy5vcHRzLmNvbHMuc29tZShCb29sZWFuKSAmJiBuKXsKICAgIGhkci5oaWRkZW4gPSBmYWxzZTsKICAgIGhkci5zdHlsZS5ncmlkVGVtcGxhdGVDb2x1bW5zID0gZ3JpZCgpOwogICAgaGRyLmlubmVySFRNTCA9ICc8c3Bhbj48L3NwYW4+PHNwYW4+PC9zcGFuPjxzcGFuPicgKyBlc2MoUy5vcHRzLnRpdGxlX2NvbCB8fCAiIikgKyAnPC9zcGFuPicKICAgICAgKyBTLm9wdHMuY29scy5zbGljZSgwLCBTLnZpcykubWFwKGMgPT4gJzxzcGFuIHN0eWxlPSJ0ZXh0LWFsaWduOnJpZ2h0Ij4nICsgZXNjKGMpICsgJzwvc3Bhbj4nKS5qb2luKCIiKQogICAgICArICc8c3Bhbj48L3NwYW4+JyArIChTLm9wdHMucmVtb3ZhYmxlID8gIjxzcGFuPjwvc3Bhbj4iIDogIiIpOwogIH0gZWxzZSBoZHIuaGlkZGVuID0gdHJ1ZTsKICBlbS5oaWRkZW4gPSBuID4gMDsKICBlbS50ZXh0Q29udGVudCA9IFMub3B0cy5lbXB0eSB8fCAiVGhlIGxpc3QgaXMgZW1wdHkuIjsKICBsaXN0LmlubmVySFRNTCA9IHJvd3MubWFwKChyLCBpKSA9PiByb3dIVE1MKHIsIGksIG4pKS5qb2luKCIiKTsKICBmaXQoKTsKfQoKZnVuY3Rpb24gZml0KCl7CiAgY29uc3QgZnVsbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJoZHIiKS5vZmZzZXRIZWlnaHQgKyBsaXN0Lm9mZnNldEhlaWdodCArIChTLnJvd3MubGVuZ3RoID8gMCA6IDQ2KSArIDQ7CiAgY29uc3QgaCA9IE1hdGgubWF4KDQwLCBNYXRoLm1pbihmdWxsLCBTLm9wdHMubWF4X2ggfHwgNDIwKSk7CiAgd3JhcC5zdHlsZS5oZWlnaHQgPSBoICsgInB4IjsKICBzdFNlbmQoInN0cmVhbWxpdDpzZXRGcmFtZUhlaWdodCIsIHtoZWlnaHQ6IGh9KTsKfQoKZnVuY3Rpb24gb3JkZXIoKXsgcmV0dXJuIFsuLi5saXN0LmNoaWxkcmVuXS5tYXAobGkgPT4gbGkuZGF0YXNldC5pZCk7IH0KZnVuY3Rpb24gc2F5KHQpeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibGl2ZSIpLnRleHRDb250ZW50ID0gdDsgfQoKZnVuY3Rpb24gY29tbWl0KHByZXYsIGZsYXNoSWQpewogIGNvbnN0IG5vdyA9IG9yZGVyKCk7CiAgaWYobm93LmpvaW4oIlx1MDAwMSIpID09PSBwcmV2LmpvaW4oIlx1MDAwMSIpKSByZXR1cm47CiAgY29uc3QgYnlJZCA9IHt9OyBTLnJvd3MuZm9yRWFjaChyID0+IGJ5SWRbci5pZF0gPSByKTsKICBTLnJvd3MgPSBub3cubWFwKGlkID0+IGJ5SWRbaWRdKTsKICByZW5kZXIoKTsKICBjb25zdCBsaSA9IGxpc3QucXVlcnlTZWxlY3RvcignLnJvd1tkYXRhLWlkPSInICsgQ1NTLmVzY2FwZShmbGFzaElkKSArICciXScpOwogIGlmKGxpKXsgbGkuY2xhc3NMaXN0LmFkZCgibW92ZWQiKTsgfQogIHNlbmQoe3Q6ICJvcmRlciIsIG9yZGVyOiBub3csIG1vdmVkOiBmbGFzaElkfSk7CiAgc2F5KGZsYXNoSWQgKyAiIG1vdmVkIHRvIHBvc2l0aW9uICIgKyAobm93LmluZGV4T2YoZmxhc2hJZCkgKyAxKSk7Cn0KCmZ1bmN0aW9uIG1vdmUoaSwgail7ICAgICAgICAgICAgICAgICAgICAgICAvLyBpIOKGkiBqIChpbmRla3MpCiAgY29uc3QgcHJldiA9IG9yZGVyKCk7CiAgaWYoaiA8IDAgfHwgaiA+PSBwcmV2Lmxlbmd0aCB8fCBpID09PSBqKSByZXR1cm47CiAgY29uc3QgaWQgPSBwcmV2W2ldLCBuZXh0ID0gcHJldi5zbGljZSgpOyBuZXh0LnNwbGljZShpLCAxKTsgbmV4dC5zcGxpY2UoaiwgMCwgaWQpOwogIGNvbnN0IGJ5SWQgPSB7fTsgWy4uLmxpc3QuY2hpbGRyZW5dLmZvckVhY2gobGkgPT4gYnlJZFtsaS5kYXRhc2V0LmlkXSA9IGxpKTsKICBuZXh0LmZvckVhY2goeCA9PiBsaXN0LmFwcGVuZENoaWxkKGJ5SWRbeF0pKTsKICBjb21taXQocHJldiwgaWQpOwogIGNvbnN0IGggPSBsaXN0LnF1ZXJ5U2VsZWN0b3IoJy5yb3dbZGF0YS1pZD0iJyArIENTUy5lc2NhcGUoaWQpICsgJyJdIC5oJyk7IGlmKGgpIGguZm9jdXMoe3ByZXZlbnRTY3JvbGw6IGZhbHNlfSk7Cn0KCi8qIC0tLS0gc8O8csO8a2xlLWLEsXJhazogc2F0xLFyxLFuIEhFUkhBTkfEsCBiaXIgeWVyaW5kZW4gKGxvZ28sIGFkLCBmaXlhdCkgLS0tLQogICBmYXJlOiA2IHB4IGRpa2V5IGhhcmVrZXRsZSBiYcWfbGFyICh0xLFrbGFtYSAiYcOnIiBvbGFyYWsga2FsxLFyKSDCtyDii67ii64gdHV0YW1hY8SxOiBhbsSxbmRhCiAgIGRva3VubWF0aWsgLyBrYWxlbTogMzAwIG1zIGJhc8SxbMSxIHR1dCAoa2F5ZMSxcm1hIHNlcmJlc3Qga2FsxLFyKSwgc29ucmEgc8O8csO8a2xlICovCmNvbnN0IEhPTERfTVMgPSAzMDAsIE1PVVNFX1NMT1AgPSA2LCBUT1VDSF9TTE9QID0gMTA7ClMucGVuZCA9IG51bGw7IFMuanVzdERyYWdnZWQgPSAwOwoKZnVuY3Rpb24gc3RhcnREcmFnKGxpLCBjYXBFbCwgZSl7CiAgY29uc3Qgcm93cyA9IFsuLi5saXN0LmNoaWxkcmVuXTsKICBjb25zdCByZWN0cyA9IHJvd3MubWFwKHIgPT4gci5nZXRCb3VuZGluZ0NsaWVudFJlY3QoKSk7CiAgdHJ5eyBjYXBFbC5zZXRQb2ludGVyQ2FwdHVyZShlLnBvaW50ZXJJZCk7IH1jYXRjaChfKXsgfQogIFMuZHJhZyA9IHtsaTogbGksIGlkOiBsaS5kYXRhc2V0LmlkLCBmcm9tOiByb3dzLmluZGV4T2YobGkpLCB0bzogcm93cy5pbmRleE9mKGxpKSwgeTA6IGUuY2xpZW50WSwgcm93czogcm93cywKICAgICAgICAgICAgbWlkczogcmVjdHMubWFwKHIgPT4gci50b3AgKyByLmhlaWdodCAvIDIpLCBoZ3Q6IHJlY3RzW3Jvd3MuaW5kZXhPZihsaSldLmhlaWdodCArIDAsIHByZXY6IG9yZGVyKCksCiAgICAgICAgICAgIHNjcm9sbDA6IHdyYXAuc2Nyb2xsVG9wfTsKICBsaS5jbGFzc0xpc3QuYWRkKCJkcmFnIiwgImxpZnQiKTsKICBzYXkoIk1vdmluZyAiICsgbGkuZGF0YXNldC5pZCArICIg4oCUIHJlbGVhc2UgdG8gZHJvcCIpOwp9CmZ1bmN0aW9uIGNsZWFyUGVuZCgpeyBjb25zdCBwID0gUy5wZW5kOyBpZihwICYmIHAudGltZXIpIGNsZWFyVGltZW91dChwLnRpbWVyKTsgUy5wZW5kID0gbnVsbDsgfQoKbGlzdC5hZGRFdmVudExpc3RlbmVyKCJwb2ludGVyZG93biIsIGZ1bmN0aW9uKGUpewogIGlmKGUuYnV0dG9uID4gMCB8fCBTLmRyYWcpIHJldHVybjsKICBpZihlLnRhcmdldC5jbG9zZXN0KCIuYXIsLnJtIikpIHJldHVybjsgICAgICAgICAgICAgICAgICAgICAgLy8gb2tsYXIgdmUgw5cgc8O8csO8a2xlbWUgYmHFn2xhdG1hegogIGNvbnN0IGxpID0gZS50YXJnZXQuY2xvc2VzdCgiLnJvdyIpOyBpZighbGkpIHJldHVybjsKICBjb25zdCBoID0gZS50YXJnZXQuY2xvc2VzdCgiLmgiKTsKICBpZihoKXsgZS5wcmV2ZW50RGVmYXVsdCgpOyBzdGFydERyYWcobGksIGgsIGUpOyByZXR1cm47IH0gICAgLy8gdHV0YW1hw6c6IGFuxLFuZGEKICBjb25zdCB0b3VjaCA9IGUucG9pbnRlclR5cGUgIT09ICJtb3VzZSI7CiAgY29uc3QgcCA9IHtsaTogbGksIHgwOiBlLmNsaWVudFgsIHkwOiBlLmNsaWVudFksIGV2OiB7cG9pbnRlcklkOiBlLnBvaW50ZXJJZCwgY2xpZW50WTogZS5jbGllbnRZfSwgdGltZXI6IG51bGx9OwogIGlmKHRvdWNoKSBwLnRpbWVyID0gc2V0VGltZW91dChmdW5jdGlvbigpeyAgICAgICAgICAgICAgICAgICAvLyBiYXPEsWzEsSB0dXQg4oaSIHPDvHLDvGtsZQogICAgaWYoUy5wZW5kID09PSBwICYmICFTLmRyYWcpeyBTLnBlbmQgPSBudWxsOyBzdGFydERyYWcocC5saSwgcC5saSwgcC5ldik7IH0gfSwgSE9MRF9NUyk7CiAgUy5wZW5kID0gcDsgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyBmYXJlOiBoYXJla2V0IGXFn2nEn2luaSBiZWtsZQp9KTsKZG9jdW1lbnQuYWRkRXZlbnRMaXN0ZW5lcigidG91Y2htb3ZlIiwgZnVuY3Rpb24oZSl7IGlmKFMuZHJhZykgZS5wcmV2ZW50RGVmYXVsdCgpOyB9LCB7cGFzc2l2ZTogZmFsc2V9KTsKCmxpc3QuYWRkRXZlbnRMaXN0ZW5lcigicG9pbnRlcm1vdmUiLCBmdW5jdGlvbihlKXsKICBjb25zdCBwID0gUy5wZW5kOwogIGlmKHAgJiYgIVMuZHJhZyl7CiAgICBjb25zdCBkeCA9IE1hdGguYWJzKGUuY2xpZW50WCAtIHAueDApLCBkeSA9IE1hdGguYWJzKGUuY2xpZW50WSAtIHAueTApOwogICAgaWYoZS5wb2ludGVyVHlwZSA9PT0gIm1vdXNlIil7CiAgICAgIGlmKGR5ID4gTU9VU0VfU0xPUCAmJiBkeSA+IGR4KXsgY2xlYXJQZW5kKCk7IHN0YXJ0RHJhZyhwLmxpLCBwLmxpLCB7cG9pbnRlcklkOiBlLnBvaW50ZXJJZCwgY2xpZW50WTogcC55MH0pOyB9CiAgICAgIGVsc2UgaWYoZHggPiAxNCkgY2xlYXJQZW5kKCk7CiAgICB9IGVsc2UgaWYoZHggPiBUT1VDSF9TTE9QIHx8IGR5ID4gVE9VQ0hfU0xPUCkgY2xlYXJQZW5kKCk7IC8vIHBhcm1hayBrYXlkxLFyxLF5b3Ig4oaSIG5vcm1hbCBzY3JvbGwKICB9CiAgY29uc3QgZCA9IFMuZHJhZzsgaWYoIWQpIHJldHVybjsKICAvLyBrZW5hcmEgeWFrbGHFn8SxbmNhIGtheWTEsXIKICBjb25zdCB3ciA9IHdyYXAuZ2V0Qm91bmRpbmdDbGllbnRSZWN0KCk7CiAgaWYoZS5jbGllbnRZIDwgd3IudG9wICsgMjQpIHdyYXAuc2Nyb2xsVG9wIC09IDg7IGVsc2UgaWYoZS5jbGllbnRZID4gd3IuYm90dG9tIC0gMjQpIHdyYXAuc2Nyb2xsVG9wICs9IDg7CiAgY29uc3QgZHMgPSB3cmFwLnNjcm9sbFRvcCAtIGQuc2Nyb2xsMDsKICBjb25zdCBkeSA9IGUuY2xpZW50WSAtIGQueTAgKyBkczsKICBkLmxpLnN0eWxlLnRyYW5zZm9ybSA9ICJ0cmFuc2xhdGVZKCIgKyBkeSArICJweCkgc2NhbGUoMS4wMTIpIjsKICBjb25zdCBjID0gZC5taWRzW2QuZnJvbV0gKyBkeTsKICBsZXQgdG8gPSBkLmZyb207CiAgZm9yKGxldCBrID0gMDsgayA8IGQucm93cy5sZW5ndGg7IGsrKyl7CiAgICBpZihrIDwgZC5mcm9tICYmIGMgPCBkLm1pZHNba10gKyAwKSB7IHRvID0gTWF0aC5taW4odG8sIGspOyB9CiAgICBpZihrID4gZC5mcm9tICYmIGMgPiBkLm1pZHNba10pIHsgdG8gPSBNYXRoLm1heCh0bywgayk7IH0KICB9CiAgZC50byA9IHRvOwogIGQucm93cy5mb3JFYWNoKChyLCBrKSA9PiB7CiAgICBpZihyID09PSBkLmxpKSByZXR1cm47CiAgICBsZXQgc2ggPSAwOwogICAgaWYoZC5mcm9tIDwgdG8gJiYgayA+IGQuZnJvbSAmJiBrIDw9IHRvKSBzaCA9IC1kLmhndDsKICAgIGlmKGQuZnJvbSA+IHRvICYmIGsgPj0gdG8gJiYgayA8IGQuZnJvbSkgc2ggPSBkLmhndDsKICAgIHIuc3R5bGUudHJhbnNmb3JtID0gc2ggPyAidHJhbnNsYXRlWSgiICsgc2ggKyAicHgpIiA6ICIiOwogIH0pOwp9KTsKZnVuY3Rpb24gZW5kRHJhZygpewogIGNsZWFyUGVuZCgpOwogIGNvbnN0IGQgPSBTLmRyYWc7IGlmKCFkKSByZXR1cm47CiAgUy5kcmFnID0gbnVsbDsKICBpZihkLnRvICE9PSBkLmZyb20peyBTLmp1c3REcmFnZ2VkID0gRGF0ZS5ub3coKTsgfSAgICAgICAgICAgLy8gaGVtZW4gYXJkxLFuZGFuIGdlbGVuIGNsaWNrICJhw6ciIHNheW1hc8SxbgogIGQucm93cy5mb3JFYWNoKHIgPT4geyByLnN0eWxlLnRyYW5zZm9ybSA9ICIiOyB9KTsKICBkLmxpLmNsYXNzTGlzdC5yZW1vdmUoImRyYWciLCAibGlmdCIpOwogIGlmKGQudG8gIT09IGQuZnJvbSl7CiAgICBjb25zdCBuZXh0ID0gZC5wcmV2LnNsaWNlKCk7IG5leHQuc3BsaWNlKGQuZnJvbSwgMSk7IG5leHQuc3BsaWNlKGQudG8sIDAsIGQuaWQpOwogICAgY29uc3QgYnlJZCA9IHt9OyBkLnJvd3MuZm9yRWFjaChyID0+IGJ5SWRbci5kYXRhc2V0LmlkXSA9IHIpOwogICAgbmV4dC5mb3JFYWNoKHggPT4gbGlzdC5hcHBlbmRDaGlsZChieUlkW3hdKSk7CiAgICBjb21taXQoZC5wcmV2LCBkLmlkKTsKICB9Cn0KbGlzdC5hZGRFdmVudExpc3RlbmVyKCJwb2ludGVydXAiLCBlbmREcmFnKTsKbGlzdC5hZGRFdmVudExpc3RlbmVyKCJwb2ludGVyY2FuY2VsIiwgZW5kRHJhZyk7Cmxpc3QuYWRkRXZlbnRMaXN0ZW5lcigibG9zdHBvaW50ZXJjYXB0dXJlIiwgZW5kRHJhZyk7CgovKiAtLS0tIHTEsWtsYW1hbGFyICsga2xhdnllIC0tLS0gKi8KbGlzdC5hZGRFdmVudExpc3RlbmVyKCJjbGljayIsIGZ1bmN0aW9uKGUpewogIGNvbnN0IGxpID0gZS50YXJnZXQuY2xvc2VzdCgiLnJvdyIpOyBpZighbGkpIHJldHVybjsKICBjb25zdCBpID0gWy4uLmxpc3QuY2hpbGRyZW5dLmluZGV4T2YobGkpOwogIGlmKGUudGFyZ2V0LmNsb3Nlc3QoIi51cCIpKSByZXR1cm4gbW92ZShpLCBpIC0gMSk7CiAgaWYoZS50YXJnZXQuY2xvc2VzdCgiLmRuIikpIHJldHVybiBtb3ZlKGksIGkgKyAxKTsKICBpZihlLnRhcmdldC5jbG9zZXN0KCIucm0iKSkgcmV0dXJuIHNlbmQoe3Q6ICJyZW1vdmUiLCBpZDogbGkuZGF0YXNldC5pZH0pOwogIGlmKERhdGUubm93KCkgLSBTLmp1c3REcmFnZ2VkIDwgNDAwKSByZXR1cm47ICAgICAgICAgICAgICAgLy8gc8O8csO8a2xlbWUgc29ucmFzxLEgdMSxa2xhbWEgZGXEn2lsCiAgaWYoUy5vcHRzLmNsaWNrYWJsZSAmJiBlLnRhcmdldC5jbG9zZXN0KCIubm0sLmF2LC5jLC5leHRxIikpIHNlbmQoe3Q6ICJvcGVuIiwgaWQ6IGxpLmRhdGFzZXQuaWR9KTsKfSk7Cmxpc3QuYWRkRXZlbnRMaXN0ZW5lcigia2V5ZG93biIsIGZ1bmN0aW9uKGUpewogIGNvbnN0IGggPSBlLnRhcmdldC5jbG9zZXN0KCIuaCIpOyBpZighaCkgcmV0dXJuOwogIGNvbnN0IGxpID0gaC5jbG9zZXN0KCIucm93Iik7IGNvbnN0IGkgPSBbLi4ubGlzdC5jaGlsZHJlbl0uaW5kZXhPZihsaSk7CiAgaWYoZS5rZXkgPT09ICJBcnJvd1VwIil7IGUucHJldmVudERlZmF1bHQoKTsgbW92ZShpLCBpIC0gMSk7IH0KICBlbHNlIGlmKGUua2V5ID09PSAiQXJyb3dEb3duIil7IGUucHJldmVudERlZmF1bHQoKTsgbW92ZShpLCBpICsgMSk7IH0KICBlbHNlIGlmKGUua2V5ID09PSAiSG9tZSIpeyBlLnByZXZlbnREZWZhdWx0KCk7IG1vdmUoaSwgMCk7IH0KICBlbHNlIGlmKGUua2V5ID09PSAiRW5kIil7IGUucHJldmVudERlZmF1bHQoKTsgbW92ZShpLCBsaXN0LmNoaWxkcmVuLmxlbmd0aCAtIDEpOyB9Cn0pOwoKZnVuY3Rpb24gYXBwbHlBcmdzKGEpewogIGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5jbGFzc0xpc3QudG9nZ2xlKCJsaWdodCIsICEhYS5saWdodCk7CiAgaWYoYS5hY2NlbnQpIGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5zdHlsZS5zZXRQcm9wZXJ0eSgiLS1hY2MiLCBhLmFjY2VudCk7CiAgaWYoUy5kcmFnKSByZXR1cm47ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyBzw7xyw7xrbGVtZSBzw7xyZXJrZW4geWVuaWRlbiDDp2l6bWUKICBTLm9wdHMgPSBhLm9wdHMgfHwge307CiAgUy5yb3dzID0gKGEucm93cyB8fCBbXSkuZmlsdGVyKHIgPT4gciAmJiByLmlkICE9IG51bGwpOwogIHJlbmRlcigpOwp9CndpbmRvdy5hZGRFdmVudExpc3RlbmVyKCJtZXNzYWdlIiwgZnVuY3Rpb24oZSl7CiAgY29uc3QgZCA9IGUuZGF0YSB8fCB7fTsKICBpZihkLnR5cGUgPT09ICJzdHJlYW1saXQ6cmVuZGVyIikgYXBwbHlBcmdzKGQuYXJncyB8fCB7fSk7Cn0pOwpuZXcgUmVzaXplT2JzZXJ2ZXIoZml0KS5vYnNlcnZlKGxpc3QpOwpuZXcgUmVzaXplT2JzZXJ2ZXIoZnVuY3Rpb24oKXsgaWYoIVMuZHJhZyAmJiBTLm9wdHMuY29scyAmJiB2aXNDb2xzKCkgIT09IFMudmlzKSByZW5kZXIoKTsgfSkub2JzZXJ2ZShkb2N1bWVudC5kb2N1bWVudEVsZW1lbnQpOwppZih3aW5kb3cuX19QTElTVF9BUkdTX18pIGFwcGx5QXJncyh3aW5kb3cuX19QTElTVF9BUkdTX18pOyAgICAgICAvLyB5YWxuxLF6Y2Egw7ZuaXpsZW1lIC8gdGVzdAplbHNlIGlmKGluU3RyZWFtbGl0KSBzdFNlbmQoInN0cmVhbWxpdDpjb21wb25lbnRSZWFkeSIsIHthcGlWZXJzaW9uOiAxfSk7CndpbmRvdy5QTElTVCA9IHtTOiBTLCBtb3ZlOiBtb3ZlLCBvcmRlcjogb3JkZXIsIGFwcGx5QXJnczogYXBwbHlBcmdzLCBzZW50OiAoKSA9PiBTLnNlbnR9Owo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+Cg=="


@st.cache_resource(show_spinner=False)
def _list_component():
    d = _LIST_DIR
    if not os.path.isfile(_LIST_INDEX):
        if not _LIST_B64:
            return None
        try:
            d = os.path.join(tempfile.gettempdir(), f"pulse_list_{UI_VERSION.replace('.', '_')}")
            os.makedirs(d, exist_ok=True)
            fp = os.path.join(d, "index.html")
            if not os.path.isfile(fp):
                with open(fp, "wb") as f:
                    f.write(base64.b64decode(_LIST_B64))
        except Exception:
            return None
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
