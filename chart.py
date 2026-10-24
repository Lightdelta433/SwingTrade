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

import json
import os
import re

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import engine as en
import mock_data as md

CHART_VERSION = "3.1"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_chart")
_INDEX = os.path.join(_DIR, "index.html")

# Zaman aralığı → (yfinance periyodu, mum aralığı, gösterilecek gün)  ya da None = günlük
# "4S" saatlik barlardan gün içinde 4'erli toplanır, "Hf" günlükten haftalığa çevrilir.
INTRA = {"1G": ("5d", "5m", 1), "1H": ("1mo", "30m", 7), "4S": ("6mo", "1h", 45)}
TF_BARS = {"1G": 10, "1H": 22, "4S": 70, "1A": 22, "3A": 66, "1Y": 252, "5Y": 1260, "Hf": 160}
AGG4 = "4S"       # saatlik → 4 saatlik
WEEKLY = "Hf"     # günlük → haftalık

# İndikatör varsayılanları — TradingView standartları, arayüzden değiştirilebilir
DEFAULT_CFG = {
    "sma": {"on": True, "ps": [20, 50, 100, 200],
            "cols": ["#5B8CFF", "#F5B544", "#C4B5FD", "#EF5350", "#22D3EE", "#F472B6"]},
    "nw": {"on": False, "h": 8.0, "mult": 3.0, "c": "#22D3EE"},
    "boll": {"on": False, "n": 20, "k": 2.0, "c": "#9AA4B2"},
    "sup": {"on": False, "n": 10, "mult": 3.0, "cu": "#26A69A", "cd": "#EF5350"},
    "vidya": {"on": False, "len": 10, "mom": 20, "mult": 2.0, "cu": "#26A69A", "cd": "#EF5350"},
    "vstop": {"on": False, "n": 20, "mult": 2.0, "cu": "#26A69A", "cd": "#EF5350"},
    "zones": {"on": True, "lookback": 300, "left": 8, "right": 8, "merge": 0.6, "max": 8,
              "cs": "#26A69A", "cr": "#EF5350"},
    "vol": {"on": True, "cu": "#26A69A", "cd": "#EF5350"},
    "rsi": {"on": True, "len": 14, "ob": 70, "os": 30, "c": "#C4B5FD"},
    "macd": {"on": False, "f": 12, "s": 26, "sig": 9, "c": "#5B8CFF", "cs": "#F5B544"},
    "wt": {"on": False, "n1": 10, "n2": 21, "ob": 60, "os": -60, "c": "#22D3EE", "cs": "#F5B544"},
    "stoch": {"on": False, "k": 14, "d": 3, "smooth": 3, "ob": 80, "os": 20,
              "c": "#5B8CFF", "cs": "#F5B544"},
    "atr": {"on": False, "n": 14, "c": "#F5B544"},
    "div": {"on": False, "src": "rsi", "left": 5, "right": 5, "hidden": True},
}
CONDS = {"cross": "keserse", "above": "üstüne çıkarsa", "below": "altına inerse",
         "cross_up": "yukarı keserse", "cross_dn": "aşağı keserse"}
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
    out["zones"]["max"] = int(min(20, max(2, out["zones"]["max"])))
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


def _to_weekly(df):
    """Günlük barları haftalığa çevirir (hafta kapanışı etiketi)."""
    if df is None or df.empty:
        return df
    out = df.resample("W-FRI").agg(_OHLC_AGG).dropna(subset=["Close"])
    out.attrs["src"] = df.attrs.get("src", "real")
    return out


def chart_data(sym, tf):
    """(veri, gösterilecek mum sayısı, gün içi mi). 1G/1H/4S gün içi mumlarla çizilir."""
    if tf in INTRA:
        period, interval, days = INTRA[tf]
        full = md.get_intraday(sym, period, interval)
        if len(full) > 10:
            if tf == AGG4:
                full = _to_4h(full)
                return full, min(len(full), TF_BARS[AGG4]), True
            cutoff = full.index[-1] - pd.Timedelta(days=days)
            return full, max(2, int((full.index > cutoff).sum())), True
    daily = md.get_history(sym)
    if tf == WEEKLY and not daily.empty:
        wk = _to_weekly(daily)
        return wk, min(len(wk), TF_BARS[WEEKLY]), False
    return daily, TF_BARS.get(tf, 22), False


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
def build_payload(sym, tf, cfg_json, data_token, max_bars=900):
    """Grafiğin ihtiyaç duyduğu her şeyi tek bir JSON'a toplar (hepsi gerçek veriden)."""
    cfg = merge_cfg(json.loads(cfg_json))
    full, bars_n, intraday = chart_data(sym, tf)
    if full.empty:
        return {"ok": False, "sym": sym}
    # Görünür aralığın birkaç katını gönder: kullanıcı geriye kaydırabilsin
    keep = int(min(len(full), max(max_bars, bars_n * 4)))
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
        zones = en.ranked_sr_zones(df, z["lookback"], z["left"], z["right"], z["merge"], z["max"])
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
            "src": df.attrs.get("src", "real"), "intraday": intraday, "interval": tf,
            "bars": bars, "ind": ind, "zones": zones, "divs": divs, "cfg": cfg,
            "visible": bars_n}


def data_token(sym, tf):
    """Fiyat verisi değişince payload önbelleği yenilensin."""
    full, _, _ = chart_data(sym, tf)
    if full.empty:
        return "none"
    return "%s|%d|%s|%.6g" % (full.attrs.get("src"), len(full), full.index[-1], float(full["Close"].iloc[-1]))


# ----------------------------------------------------------------------
# Bileşen
# ----------------------------------------------------------------------
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


def render_chart(payload, draws, alerts, chart_type="candles", height=640, rev=0, key="chart"):
    """Grafiği çizer. Kullanıcı bir şey değiştirdiyse olay sözlüğü döndürür."""
    comp = _component()
    args = dict(payload)
    args.update({"draws": draws or [], "alerts": alerts or [], "type": chart_type,
                 "height": int(height), "rev": int(rev)})
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
    return "Fiyat %s %s" % (CONDS.get(a.get("cond"), ""), en.fmt_num(a.get("price"), 2))
