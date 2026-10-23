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

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import engine as en
import mock_data as md

CHART_VERSION = "3.0"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_chart")
_INDEX = os.path.join(_DIR, "index.html")

# Zaman aralığı → (yfinance periyodu, mum aralığı, gösterilecek gün)  ya da None = günlük
INTRA = {"1G": ("5d", "5m", 1), "1H": ("1mo", "30m", 7)}
TF_BARS = {"1G": 10, "1H": 22, "1A": 22, "3A": 66, "1Y": 252, "5Y": 1260}

# İndikatör varsayılanları — TradingView standartları, arayüzden değiştirilebilir
DEFAULT_CFG = {
    "sma": {"on": True, "ps": [20, 50, 100, 200]},
    "nw": {"on": False, "h": 8.0, "mult": 3.0},
    "zones": {"on": True, "lookback": 300, "left": 8, "right": 8, "merge": 0.6, "max": 8},
    "vol": {"on": True},
    "rsi": {"on": True, "len": 14, "ob": 70, "os": 30},
    "macd": {"on": False, "f": 12, "s": 26, "sig": 9},
    "wt": {"on": False, "n1": 10, "n2": 21, "ob": 60, "os": -60},
    "div": {"on": False, "src": "rsi", "left": 5, "right": 5, "hidden": True},
}
CONDS = {"cross": "keserse", "above": "üstüne çıkarsa", "below": "altına inerse",
         "cross_up": "yukarı keserse", "cross_dn": "aşağı keserse"}


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
    return out


def chart_data(sym, tf):
    """(veri, gösterilecek mum sayısı, gün içi mi). 1G/1H gün içi mumlarla çizilir."""
    if tf in INTRA:
        period, interval, days = INTRA[tf]
        full = md.get_intraday(sym, period, interval)
        if len(full) > 10:
            cutoff = full.index[-1] - pd.Timedelta(days=days)
            return full, max(2, int((full.index > cutoff).sum())), True
    return md.get_history(sym), TF_BARS.get(tf, 22), False


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
