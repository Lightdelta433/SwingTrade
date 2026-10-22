"""
========================================================================
 PULSE — PİYASA PANELİ  (app.py)
========================================================================
Koyu "Pulse" tasarımına göre tek sayfa. Veri mock_data.py'den gelir
(gerçek veri + mock fallback).

Düzen:
  - Üst bar: Pulse logosu + bölüm sekmeleri YAN YANA (Piyasalar / Long Term /
    Short Term / Forex & Haberler) + arama + bildirim/hesap
  - Piyasalar: solda grafik, sağda Teknik Özet + Destek/Direnç (yan yana),
    ALTINDA İzleme Listesi (zengin satırlar), sonra Sektör Performansı,
    Öne Çıkanlar, IPO'lar, haberler
  - Forex & Haberler: makro şerit, 01 Forex Piyasası (grafik + Pariteler),
    02 Ekonomik Takvim, 03 Piyasa Haberleri (öne çıkan + liste)

Tıklanabilirlik: Streamlit butonları zengin HTML alamadığı için
navigasyon query-param linkleriyle yapılır (?sec=..&sym=..&tf=..).
========================================================================
"""

from urllib.parse import quote

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import mock_data as md

st.set_page_config(page_title="Pulse — Piyasa Paneli", layout="wide",
                   initial_sidebar_state="collapsed")

# --- Tasarım renkleri ---
BG, PANEL, BORDER = "#0A0B0D", "#111317", "#22262D"
TXT, MUT, SOFT = "#ECEEF1", "#8D96A5", "#C4CAD4"
UP, DOWN, NEU = "#34D399", "#F87171", "#C4CAD4"
ACCENT, GOLD, VIOLET = "#5B8CFF", "#F5B544", "#C4B5FD"
EMA_COLORS = {20: ACCENT, 50: GOLD}

SECTIONS = ["Piyasalar", "Long Term", "Short Term", "Forex & Haberler"]
TF_BARS = {"1G": 5, "1H": 10, "1A": 22, "3A": 66, "1Y": 252, "5Y": 1260}
TF_NAME = {"1G": "Son 1 gün", "1H": "Son 1 hafta", "1A": "Son 1 ay",
           "3A": "Son 3 ay", "1Y": "Son 1 yıl", "5Y": "Son 5 yıl"}

CHART_CONFIG = {"displayModeBar": True, "displaylogo": False,
                "modeBarButtonsToRemove": ["select2d", "lasso2d"]}

# ======================================================================
# Durum + query-param yönlendirme
# ======================================================================
ss = st.session_state
ss.setdefault("section", "Piyasalar")
ss.setdefault("active", "SPY")
ss.setdefault("tf", "1A")
ss.setdefault("fx", "EUR/USD")
ss.setdefault("fxc", "Tümü")
ss.setdefault("cal", "Tümü")
ss.setdefault("nc", "Tümü")
ss.setdefault("movers_tab", "up")
ss.setdefault("watchlist", list(md.DEFAULT_WATCHLIST))


def _qp(key, default):
    try:
        v = st.query_params.get(key)
    except Exception:
        v = None
    if isinstance(v, list):
        v = v[0] if v else None
    return v or default


ss.section = _qp("sec", ss.section)
ss.active = _qp("sym", ss.active)
ss.tf = _qp("tf", ss.tf)
ss.fx = _qp("fx", ss.fx)
ss.fxc = _qp("fxc", ss.fxc)
ss.cal = _qp("cal", ss.cal)
ss.nc = _qp("nc", ss.nc)
if ss.section not in SECTIONS:
    ss.section = "Piyasalar"
if ss.tf not in TF_BARS:
    ss.tf = "1A"


def link(**kw):
    """Mevcut durumu koruyarak değişen parametreyle link üretir."""
    base = {"sec": ss.section, "sym": ss.active, "tf": ss.tf,
            "fx": ss.fx, "fxc": ss.fxc, "cal": ss.cal, "nc": ss.nc}
    base.update(kw)
    return "?" + "&".join(f"{k}={quote(str(v))}" for k, v in base.items())


# ======================================================================
# Biçimlendirme + küçük görseller
# ======================================================================
def tr(x, dec=2):
    """Türkçe sayı biçimi: 10.842,56"""
    try:
        s = f"{float(x):,.{dec}f}"
    except (TypeError, ValueError):
        return "—"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def pct_tr(x, dec=2):
    sign = "+" if x >= 0 else "−"
    return f"{sign}%{tr(abs(x), dec)}"


def chg_tr(x, dec=2):
    sign = "+" if x >= 0 else "−"
    return f"{sign}{tr(abs(x), dec)}"


def svg_spark(series, color, w=84, h=30):
    """Hafif inline SVG sparkline (plotly yerine — çok sayıda olduğu için)."""
    s = [float(v) for v in series][-60:]
    if len(s) < 2:
        return ""
    lo, hi = min(s), max(s)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i*w/(len(s)-1):.1f},{h-2-(v-lo)/rng*(h-4):.1f}" for i, v in enumerate(s))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def pills(options, current, param, size="sm"):
    """Tasarımdaki segment buton grubu (tıklanabilir linkler)."""
    html = '<div class="pillbar">'
    for o in options:
        cls = "pill active" if o == current else "pill"
        html += f'<a class="{cls}" target="_self" href="{link(**{param: o})}">{o}</a>'
    return html + "</div>"


# ======================================================================
# Stil
# ======================================================================
st.markdown(f"""
<style>
  .block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1500px; }}
  header[data-testid="stHeader"] {{ background: transparent; }}
  /* ---- Üst bar ---- */
  .hdr {{ display:flex; align-items:center; gap:22px; flex-wrap:wrap;
          border-bottom:1px solid #1C1F25; padding:6px 0 14px 0; margin-bottom:16px; }}
  .brand {{ display:flex; align-items:center; gap:9px; font-weight:800; font-size:18px; }}
  .brand .dot {{ width:28px;height:28px;border-radius:9px;background:{ACCENT};
                 display:flex;align-items:center;justify-content:center;color:#0A0B0D;
                 font-size:15px;font-weight:900; }}
  .navbar {{ display:flex; gap:4px; flex-wrap:wrap; }}
  .navbar a {{ padding:9px 14px; border-radius:10px; text-decoration:none;
               font-size:14px; font-weight:600; color:#A3ABB8; }}
  .navbar a.active {{ background:#171A1F; color:{TXT}; font-weight:700; }}
  .navbar a:hover {{ color:{TXT}; }}
  .hdr-right {{ margin-left:auto; display:flex; align-items:center; gap:9px; }}
  .search {{ display:flex;align-items:center;gap:9px; height:40px; padding:0 12px;
             background:{PANEL}; border:1px solid {BORDER}; border-radius:12px;
             color:{MUT}; font-size:13px; min-width:230px; }}
  .search .kbd {{ margin-left:auto; font-size:11px; border:1px solid #2A2F37;
                  border-radius:6px; padding:1px 6px; }}
  .hbtn {{ width:40px;height:40px;border-radius:12px;border:1px solid {BORDER};
           background:{PANEL}; display:flex;align-items:center;justify-content:center;
           font-size:14px;font-weight:800; }}
  /* ---- Genel ---- */
  .page-title {{ font-size:28px; font-weight:800; letter-spacing:-.02em; margin:2px 0 4px 0; }}
  .muted {{ color:{MUT}; font-size:13px; }}
  .chip {{ font-size:11px; color:{MUT}; background:#1A1D23; border-radius:6px; padding:3px 7px; }}
  .sec-no {{ color:{ACCENT}; font-size:11px; font-weight:800; letter-spacing:.1em; }}
  .sec-head {{ display:flex; align-items:center; gap:10px; margin:6px 0 10px 0; }}
  .sec-head h3 {{ margin:0; font-size:18px; font-weight:800; }}
  .panel-title {{ font-size:16px; font-weight:700; }}
  /* ---- Pill grubu ---- */
  .pillbar {{ display:inline-flex; gap:2px; background:#0C0D10; border:1px solid {BORDER};
              border-radius:12px; padding:3px; }}
  .pillbar .pill {{ min-width:40px; text-align:center; padding:7px 11px; border-radius:9px;
                    font-size:13px; font-weight:700; color:#A3ABB8; text-decoration:none; }}
  .pillbar .pill.active {{ background:{ACCENT}; color:#0A0B0D; }}
  .pillbar .pill:hover {{ color:{TXT}; }}
  /* ---- İzleme listesi satırı ---- */
  .wl-head {{ display:flex; align-items:center; justify-content:space-between;
              padding:4px 2px 10px 2px; }}
  .wl-cols {{ display:flex; justify-content:space-between; font-size:11px; color:{MUT};
              letter-spacing:.08em; padding:8px 2px; border-bottom:1px solid #1C1F25; }}
  .wl-group {{ display:flex; justify-content:space-between; font-size:13px; font-weight:700;
               color:{SOFT}; padding:10px 2px; }}
  .wl-row {{ display:flex; align-items:center; gap:14px; padding:12px 2px;
             border-top:1px solid #1C1F25; }}
  .wl-row:hover {{ background:#141820; }}
  .wl-av {{ width:38px;height:38px;border-radius:50%;flex:none;background:#1A1D23;
            display:flex;align-items:center;justify-content:center;
            font-size:12px;font-weight:800;color:{SOFT};overflow:hidden; }}
  .wl-av img {{ width:38px;height:38px;object-fit:contain;background:#fff;padding:3px; }}
  .wl-nm {{ flex:1; min-width:0; }}
  .wl-nm b {{ font-size:15px; }}
  .wl-nm div {{ color:{MUT}; font-size:12.5px; }}
  .wl-px {{ text-align:right; }}
  .wl-last {{ font-size:16px; font-weight:700; }}
  .wl-chg {{ font-size:12.5px; font-weight:600; }}
  .wl-sub2 {{ font-size:11.5px; color:{MUT}; margin-top:1px; }}
  /* ---- Satır listeleri ---- */
  .row {{ display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid #1C1F25; }}
  .ini {{ width:34px;height:34px;border-radius:10px;background:#1A1D23;flex:none;
          display:flex;align-items:center;justify-content:center;
          font-size:11px;font-weight:800;color:{SOFT}; }}
  .badge {{ font-size:11px;font-weight:700;border-radius:6px;padding:2px 7px; }}
  .stat-row {{ display:flex;justify-content:space-between;align-items:center;gap:10px;
               padding:9px 2px;border-top:1px solid #1C1F25;font-size:13px; }}
  .stat-row .lbl {{ color:{SOFT}; flex:1; }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; }}
  /* ---- Isı haritası ---- */
  .heat {{ height:78px;border-radius:12px;padding:11px 13px;box-sizing:border-box;
           display:flex;flex-direction:column;justify-content:space-between;margin-bottom:8px; }}
  .heat b {{ font-size:13px;color:#fff; }}
  .heat span {{ font-weight:700;color:#fff;font-size:15px; }}
  /* ---- Takvim ---- */
  .cal-row {{ display:flex;align-items:center;gap:12px;padding:10px 4px;
              border-top:1px solid #1C1F25;font-size:13px; }}
  .dots {{ display:flex;gap:3px;width:40px;flex:none; }}
  .dots i {{ width:9px;height:4px;border-radius:2px;display:block; }}
  /* ---- Haber ---- */
  .nw {{ display:flex;gap:12px;padding:11px 0;border-top:1px solid #1C1F25; }}
  .nw .thumb {{ width:84px;flex:none;display:flex;align-items:center; }}
  .nw b {{ font-size:13.5px;font-weight:700;line-height:1.35;display:block; }}
  .feat {{ background:{PANEL};border:1px solid {BORDER};border-radius:16px;overflow:hidden; }}
  .feat .img {{ height:190px;background:#0C0D10;display:flex;align-items:center;
                justify-content:center;color:#3A404A;font-size:12px; }}
  a.plain {{ text-decoration:none; color:inherit; display:block; }}
</style>
""", unsafe_allow_html=True)


# ======================================================================
# ÜST BAR (logo + sekmeler yan yana)
# ======================================================================
def render_header():
    nav = "".join(
        f'<a class="{"active" if s == ss.section else ""}" target="_self" '
        f'href="{link(sec=s)}">{s}</a>' for s in SECTIONS)
    st.markdown(f"""
    <div class="hdr">
      <div class="brand"><span class="dot">◪</span>Pulse</div>
      <nav class="navbar">{nav}</nav>
      <div class="hdr-right">
        <div class="search">🔍 Sembol veya parite ara <span class="kbd">⌘K</span></div>
        <div class="hbtn">🔔</div><div class="hbtn">A</div>
      </div>
    </div>""", unsafe_allow_html=True)


def render_health():
    h = md.get_data_health()
    badge = "🟢 Canlı veri" if h["yf_ok"] else "🟡 Mock veri"
    with st.expander(f"🔎 Veri kaynağı durumu — {badge}", expanded=not h["yf_ok"]):
        ok = lambda b: "✅" if b else "❌"
        st.markdown(f"- {ok(h['yfinance_installed'])} yfinance kurulu  \n"
                    f"- {ok(h['yf_ok'])} yfinance canlı çekim — {h['yf_msg']}  \n"
                    f"- {ok(h['cnn_ok'])} CNN Fear & Greed — {h['cnn_msg']}")
        if not h["yfinance_installed"]:
            st.warning("requirements.txt'te `yfinance>=0.2.40` eksik. Yükleyip Reboot et.")
        elif not h["yf_ok"]:
            st.warning("yfinance kurulu ama Yahoo veri vermedi (IP rate-limit olabilir).")


# ======================================================================
# Grafikler
# ======================================================================
@st.cache_data(show_spinner=False)
def _hist(ticker):
    return md.add_emas(md.get_ohlc(ticker, days=md._FULL_DAYS))


def slice_tf(df, tf):
    return df.tail(TF_BARS.get(tf, 22))


def price_chart(df, height=430, rsi_panel=True):
    rows, heights = (3, [0.62, 0.17, 0.21]) if rsi_panel else (2, [0.78, 0.22])
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=heights, vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                  low=df["Low"], close=df["Close"], increasing_line_color=UP,
                  decreasing_line_color=DOWN, name="Fiyat"), row=1, col=1)
    for p, color in EMA_COLORS.items():
        if f"EMA{p}" in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[f"EMA{p}"], mode="lines",
                          line=dict(color=color, width=1.5), name=f"SMA {p}"), row=1, col=1)
    vol_colors = [UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors,
                  name="Hacim", opacity=0.45), row=2, col=1)
    if rsi_panel:
        rsi = _rsi(df["Close"])
        fig.add_trace(go.Scatter(x=df.index, y=rsi, mode="lines",
                      line=dict(color=VIOLET, width=1.4), name="RSI 14"), row=3, col=1)
        fig.add_hline(y=70, line=dict(color="#3A404A", width=1, dash="dash"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color="#3A404A", width=1, dash="dash"), row=3, col=1)
        fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_layout(template="plotly_dark", height=height,
                      margin=dict(l=6, r=6, t=10, b=6), showlegend=False,
                      xaxis_rangeslider_visible=False, hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor="#1A1D23")
    fig.update_yaxes(gridcolor="#1A1D23")
    return fig


def _rsi(close, p=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def compute_tech(df):
    close = df["Close"]
    price = float(close.iloc[-1])
    rsi = float(_rsi(close).iloc[-1])
    e12 = close.ewm(span=12, adjust=False).mean()
    e26 = close.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    sigl = macd.ewm(span=9, adjust=False).mean()
    macd_v, sig_v = float(macd.iloc[-1]), float(sigl.iloc[-1])
    win = df.tail(14)
    hh, ll = float(win["High"].max()), float(win["Low"].min())
    stoch = (price - ll) / ((hh - ll) or 1) * 100
    mom = price - float(close.iloc[-11]) if len(close) > 11 else 0.0
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(min(50, len(close))).mean().iloc[-1])
    sig = [("RSI (14)", tr(rsi, 1), -1 if rsi > 70 else 1 if rsi < 30 else 0),
           ("MACD (12, 26, 9)", tr(macd_v), 1 if macd_v > sig_v else -1),
           ("Stokastik %K (14)", tr(stoch, 1), -1 if stoch > 80 else 1 if stoch < 20 else 0),
           ("Momentum (10)", chg_tr(mom), 1 if mom > 0 else -1),
           ("SMA 20", tr(sma20), 1 if price > sma20 else -1),
           ("SMA 50", tr(sma50), 1 if price > sma50 else -1)]
    score = sum(v for _, _, v in sig)
    buy = sum(1 for _, _, v in sig if v > 0)
    sell = sum(1 for _, _, v in sig if v < 0)
    label = ("Güçlü Al" if score >= 3 else "Al" if score >= 1 else
             "Güçlü Sat" if score <= -3 else "Sat" if score <= -1 else "Nötr")
    return {"signals": sig, "score": score, "buy": buy, "sell": sell,
            "neutral": len(sig) - buy - sell, "label": label,
            "color": UP if score >= 1 else DOWN if score <= -1 else NEU}


def tech_gauge(score):
    val = (score + 6) / 12 * 100
    fig = go.Figure(go.Indicator(
        mode="gauge", value=val,
        gauge={"axis": {"range": [0, 100], "visible": False},
               "bar": {"color": "rgba(0,0,0,0)"}, "borderwidth": 0,
               "steps": [{"range": [0, 40], "color": DOWN},
                         {"range": [40, 60], "color": "#2A2F37"},
                         {"range": [60, 100], "color": UP}],
               "threshold": {"line": {"color": TXT, "width": 4}, "thickness": 0.95,
                             "value": val}}))
    fig.update_layout(height=140, margin=dict(l=16, r=16, t=4, b=0),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def pivots(df):
    rec = df.tail(5)
    H, L = float(rec["High"].max()), float(rec["Low"].min())
    C = float(df["Close"].iloc[-1])
    P = (H + L + C) / 3
    return [("R2", P + (H - L), DOWN), ("R1", 2 * P - L, DOWN), ("P", P, NEU),
            ("S1", 2 * P - H, UP), ("S2", P - (H - L), UP)], C


# ======================================================================
# BÖLÜM: PİYASALAR
# ======================================================================
def render_chart_panel():
    sym = ss.active
    d = md.get_company_detail(sym)
    df = slice_tf(_hist(sym), ss.tf)
    col = UP if d["change_abs"] >= 0 else DOWN

    head = st.columns([2.2, 1.3])
    with head[0]:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:9px">'
            f'<span class="panel-title">{d["name"]}</span>'
            f'<span class="chip mono">{sym}</span></div>'
            f'<div style="display:flex;align-items:baseline;gap:11px;flex-wrap:wrap;margin-top:4px">'
            f'<span class="mono" style="font-size:30px;font-weight:700">{tr(d["last"])}</span>'
            f'<span class="mono" style="color:{col};font-weight:700;font-size:14px">'
            f'{chg_tr(d["change_abs"])} ({pct_tr(d["change_pct"])})</span>'
            f'<span class="muted">{TF_NAME[ss.tf]}</span></div>', unsafe_allow_html=True)
    with head[1]:
        st.markdown(f'<div style="text-align:right">{pills(list(TF_BARS), ss.tf, "tf")}</div>',
                    unsafe_allow_html=True)

    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px;margin:12px 0 2px 0">'
        f'<span class="muted">Açılış <span class="mono" style="color:{TXT}">{tr(d["open"])}</span></span>'
        f'<span class="muted">Yüksek <span class="mono" style="color:{TXT}">{tr(d["day_high"])}</span></span>'
        f'<span class="muted">Düşük <span class="mono" style="color:{TXT}">{tr(d["day_low"])}</span></span>'
        f'<span class="muted">Kapanış <span class="mono" style="color:{TXT}">{tr(d["last"])}</span></span>'
        f'<span style="flex:1"></span>'
        f'<span style="color:{SOFT}">— SMA 20</span>'
        f'<span style="color:{SOFT}">— SMA 50</span></div>', unsafe_allow_html=True)
    st.plotly_chart(price_chart(df), use_container_width=True, config=CHART_CONFIG)
    return df


def render_tech(df):
    t = compute_tech(df)
    st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span class="panel-title">Teknik Özet</span>'
                f'<span class="muted">{TF_NAME[ss.tf]}</span></div>', unsafe_allow_html=True)
    st.plotly_chart(tech_gauge(t["score"]), use_container_width=True,
                    config={"displayModeBar": False})
    st.markdown(f'<div style="text-align:center;font-size:22px;font-weight:800;'
                f'color:{t["color"]};margin-top:-18px">{t["label"]}</div>',
                unsafe_allow_html=True)
    cc = st.columns(3)
    for col, (lbl, val, clr) in zip(cc, [("Sat", t["sell"], DOWN),
                                         ("Nötr", t["neutral"], NEU), ("Al", t["buy"], UP)]):
        with col:
            st.markdown(f'<div style="background:#0C0D10;border-radius:12px;padding:9px;'
                        f'text-align:center"><div class="muted" style="font-size:11px">{lbl}</div>'
                        f'<div class="mono" style="font-size:18px;font-weight:700;color:{clr}">'
                        f'{val}</div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    for name, val, v in t["signals"]:
        lab = "Al" if v > 0 else "Sat" if v < 0 else "Nötr"
        fg = UP if v > 0 else DOWN if v < 0 else NEU
        bg = ("rgba(52,211,153,.12)" if v > 0 else
              "rgba(248,113,113,.12)" if v < 0 else "rgba(141,150,165,.14)")
        st.markdown(f'<div class="stat-row"><span class="lbl">{name}</span>'
                    f'<span class="mono" style="font-size:12px">{val}</span>'
                    f'<span class="badge" style="color:{fg};background:{bg};width:52px;'
                    f'text-align:center">{lab}</span></div>', unsafe_allow_html=True)


def render_sr(df):
    levels, price = pivots(df)
    st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span class="panel-title">Destek &amp; Direnç</span>'
                f'<span class="muted">Pivot · klasik</span></div>', unsafe_allow_html=True)
    for k, v, fg in levels:
        dist = (v / price - 1) * 100
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:9px 2px">'
            f'<span class="mono" style="width:34px;color:{fg};font-weight:700;font-size:12px">{k}</span>'
            f'<div style="flex:1;height:1px;background:{BORDER}"></div>'
            f'<span class="mono" style="font-size:13px">{tr(v)}</span>'
            f'<span class="mono muted" style="width:58px;text-align:right;font-size:11px">'
            f'{pct_tr(dist)}</span></div>', unsafe_allow_html=True)


def render_watchlist_block():
    """Tasarımdaki zengin izleme listesi — satırlar tıklanabilir."""
    wl = list(ss.watchlist)
    st.markdown(
        f'<div class="wl-head"><div style="display:flex;align-items:center;gap:8px">'
        f'<span style="font-size:19px;font-weight:800">İzleme Listesi</span>'
        f'<span class="muted">⌄</span></div>'
        f'<div style="display:flex;gap:8px"><span class="hbtn">＋</span>'
        f'<span class="hbtn">⋯</span></div></div>'
        f'<div class="wl-cols"><span>SEMBOL</span><span>SON · DEĞ · DEĞ%</span></div>'
        f'<div class="wl-group"><span>⌄ Hisseler</span><span>{len(wl)}</span></div>',
        unsafe_allow_html=True)

    for t in wl:
        q = md.get_quote(t)
        d_prev = q["last"] / (1 + q["change_pct"] / 100) if q["change_pct"] != -100 else q["last"]
        chg_abs = q["last"] - d_prev
        c = UP if q["change_pct"] >= 0 else DOWN
        logo = md.logo_url(t)
        av = (f'<img src="{logo}" alt="">' if logo else t[:2])
        active = "background:#141820;" if ss.active == t else ""
        st.markdown(
            f'<a class="plain" target="_self" href="{link(sym=t)}">'
            f'<div class="wl-row" style="{active}">'
            f'<span class="wl-av">{av}</span>'
            f'<div class="wl-nm"><b>{t}</b><div>{q["name"]}</div></div>'
            f'<div class="wl-px">'
            f'<div class="wl-last mono">{tr(q["last"])}</div>'
            f'<div class="wl-chg mono" style="color:{c}">{chg_tr(chg_abs)} {pct_tr(q["change_pct"])}</div>'
            f'<div class="wl-sub2 mono">önc. kapanış {tr(d_prev)}</div>'
            f'</div></div></a>', unsafe_allow_html=True)

    st.markdown(f'<div class="muted" style="padding:10px 2px;font-size:11.5px">'
                f'Alt satır: önceki kapanış · Logolar canlı veride logo API\'den gelir</div>',
                unsafe_allow_html=True)


def render_sector_heatmap():
    st.markdown('<div class="sec-head"><span class="sec-no">●</span>'
                '<h3>Sektör Performansı</h3><span class="muted">Günlük</span></div>',
                unsafe_allow_html=True)
    secs = md.get_sector_performance()
    for i in range(0, len(secs), 4):
        row = st.columns(4)
        for col, s in zip(row, secs[i:i + 4]):
            ch = s["change_pct"]
            a = min(1.0, 0.28 + abs(ch) / 2.5 * 0.7)
            rgb = "16,122,87" if ch >= 0 else "185,45,55"
            with col:
                st.markdown(f'<div class="heat" style="background:rgba({rgb},{a:.2f})">'
                            f'<b>{s["name"]}</b><span class="mono">{pct_tr(ch)}</span></div>',
                            unsafe_allow_html=True)


def render_movers():
    head = st.columns([1.6, 1.4])
    with head[0]:
        st.markdown('<div class="panel-title">Öne Çıkanlar</div>', unsafe_allow_html=True)
    with head[1]:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Yükselenler", key="mv_up", use_container_width=True):
                ss.movers_tab = "up"; st.rerun()
        with b2:
            if st.button("Düşenler", key="mv_dn", use_container_width=True):
                ss.movers_tab = "down"; st.rerun()
    items = md.get_top_movers() if ss.movers_tab == "up" else md.get_top_losers()
    for q in items:
        c = UP if q["change_pct"] >= 0 else DOWN
        bg = "rgba(52,211,153,.12)" if q["change_pct"] >= 0 else "rgba(248,113,113,.12)"
        st.markdown(
            f'<div class="row"><span class="ini">{q["ticker"][:2]}</span>'
            f'<div style="flex:1;min-width:0"><b class="mono" style="font-size:13px">{q["ticker"]}</b>'
            f'<div class="muted" style="font-size:12px">{q["name"]}</div></div>'
            f'<div style="text-align:right"><div class="mono" style="font-size:13px">{tr(q["last"])}</div>'
            f'<span class="badge mono" style="color:{c};background:{bg}">{pct_tr(q["change_pct"])}</span>'
            f'</div></div>', unsafe_allow_html=True)


def render_piyasalar():
    st.markdown('<div class="page-title">Piyasalar</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="muted">🟢 Bir sembole tıkla → grafiği açılır</div>',
                unsafe_allow_html=True)
    render_health()

    # Endeks kartları
    cols = st.columns(4)
    for col, idx in zip(cols, md.get_index_summary()):
        c = UP if idx["change_pct"] >= 0 else DOWN
        act = f"border-color:{ACCENT};" if ss.active == idx["ticker"] else ""
        with col:
            st.markdown(
                f'<a class="plain" target="_self" href="{link(sym=idx["ticker"])}">'
                f'<div style="background:{PANEL};border:1px solid {BORDER};{act}'
                f'border-radius:14px;padding:13px 15px">'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
                f'<b style="font-size:13px">{idx["subtitle"]}</b>'
                f'<span class="chip mono">{idx["ticker"]}</span></div>'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-end;'
                f'margin-top:10px"><div><div class="mono" style="font-size:18px;font-weight:700">'
                f'{tr(idx["last"])}</div>'
                f'<div class="mono" style="font-size:12px;font-weight:700;color:{c}">'
                f'{pct_tr(idx["change_pct"])}</div></div>'
                f'{svg_spark(idx["series"], c)}</div></div></a>', unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # Grafik | Teknik Özet (yan yana)
    left, right = st.columns([2.1, 1], gap="medium")
    with left:
        with st.container(border=True):
            df = render_chart_panel()
    with right:
        with st.container(border=True):
            render_tech(df)
        with st.container(border=True):
            render_sr(df)

    # İzleme listesi — teknik analizin ALTINDA, tam genişlik
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        render_watchlist_block()

    # Sektör + Öne çıkanlar
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    b1, b2 = st.columns([2.1, 1], gap="medium")
    with b1:
        with st.container(border=True):
            render_sector_heatmap()
    with b2:
        with st.container(border=True):
            render_movers()

    # IPO + haberler
    c1, c2 = st.columns([2.1, 1], gap="medium")
    with c1:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Yaklaşan Halka Arzlar (IPO)</div>',
                        unsafe_allow_html=True)
            st.dataframe(md.get_upcoming_ipos(), use_container_width=True, hide_index=True)
    with c2:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Watchlist Haberleri</div>', unsafe_allow_html=True)
            for it in md.get_watchlist_news(list(ss.watchlist))[:8]:
                st.markdown(f'<div class="nw"><div style="flex:1">'
                            f'<b>{it["title"]}</b>'
                            f'<div class="muted" style="font-size:11.5px;margin-top:3px">'
                            f'{it["ticker"]} · {it["source"]} · {it["when"]}</div></div></div>',
                            unsafe_allow_html=True)


# ======================================================================
# BÖLÜM: FOREX & HABERLER
# ======================================================================
def render_macro_strip():
    cols = st.columns(6)
    for col, m in zip(cols, md.get_macro_strip()):
        c = UP if m["change_pct"] >= 0 else DOWN
        with col:
            st.markdown(
                f'<div style="background:{PANEL};border:1px solid {BORDER};border-radius:14px;'
                f'padding:12px 14px">'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
                f'<b style="font-size:12.5px">{m["name"]}</b>'
                f'<span class="chip mono">{m["code"]}</span></div>'
                f'<div class="mono" style="font-size:19px;font-weight:700;margin-top:6px">'
                f'{tr(m["value"], m["dec"])}</div>'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-end">'
                f'<span class="mono" style="color:{c};font-size:12px;font-weight:700">'
                f'{pct_tr(m["change_pct"])}</span>{svg_spark(m["series"], c, 70, 26)}</div>'
                f'</div>', unsafe_allow_html=True)


def render_fx_market():
    st.markdown('<div class="sec-head"><span class="sec-no">01</span>'
                '<h3>Forex Piyasası</h3></div>', unsafe_allow_html=True)
    left, right = st.columns([2.1, 1], gap="medium")
    meta = md.fx_meta(ss.fx)
    quotes = {q["pair"]: q for q in md.get_fx_list("Tümü")}
    q = quotes.get(ss.fx, {"last": meta["base"], "change_pct": 0.0, "dec": meta["dec"]})
    dec = meta["dec"]

    with left:
        with st.container(border=True):
            c = UP if q["change_pct"] >= 0 else DOWN
            df = md.get_fx_history(ss.fx, TF_BARS.get(ss.tf, 22) + 60).tail(TF_BARS.get(ss.tf, 22))
            h = st.columns([2, 1.3])
            with h[0]:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:9px">'
                    f'<span class="panel-title">{ss.fx}</span>'
                    f'<span class="chip">{meta["name"]}</span></div>'
                    f'<div style="display:flex;align-items:baseline;gap:11px;margin-top:4px">'
                    f'<span class="mono" style="font-size:28px;font-weight:700">{tr(q["last"], dec)}</span>'
                    f'<span class="mono" style="color:{c};font-weight:700;font-size:13px">'
                    f'{pct_tr(q["change_pct"])}</span>'
                    f'<span class="muted">{TF_NAME[ss.tf]}</span></div>', unsafe_allow_html=True)
            with h[1]:
                st.markdown(f'<div style="text-align:right">{pills(list(TF_BARS), ss.tf, "tf")}</div>',
                            unsafe_allow_html=True)
            hi, lo = float(df["High"].max()), float(df["Low"].min())
            st.markdown(
                f'<div style="display:flex;gap:18px;font-size:12px;margin:10px 0 2px 0">'
                f'<span class="muted">Yüksek <span class="mono" style="color:{TXT}">{tr(hi, dec)}</span></span>'
                f'<span class="muted">Düşük <span class="mono" style="color:{TXT}">{tr(lo, dec)}</span></span>'
                f'<span style="flex:1"></span><span style="color:{SOFT}">— SMA 20</span>'
                f'<span style="color:{SOFT}">— SMA 50</span></div>', unsafe_allow_html=True)
            st.plotly_chart(price_chart(df, height=380, rsi_panel=False),
                            use_container_width=True, config=CHART_CONFIG)

    with right:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Pariteler</div>', unsafe_allow_html=True)
            st.markdown(pills(md.FX_CATEGORIES, ss.fxc, "fxc"), unsafe_allow_html=True)
            st.markdown('<div class="wl-cols" style="margin-top:8px">'
                        '<span>SEMBOL</span><span>SON · DEĞ%</span></div>', unsafe_allow_html=True)
            for p in md.get_fx_list(ss.fxc):
                c = UP if p["change_pct"] >= 0 else DOWN
                act = f"background:#141820;border-left:2px solid {ACCENT};" if p["pair"] == ss.fx else ""
                st.markdown(
                    f'<a class="plain" target="_self" href="{link(fx=p["pair"])}">'
                    f'<div class="row" style="{act}padding-left:6px">'
                    f'<div style="flex:1;min-width:0"><b style="font-size:13px">{p["pair"]}</b>'
                    f'<div class="muted" style="font-size:11.5px">{p["name"]}</div></div>'
                    f'<div style="text-align:right"><div class="mono" style="font-size:13px">'
                    f'{tr(p["last"], p["dec"])}</div>'
                    f'<div class="mono" style="font-size:11.5px;color:{c};font-weight:700">'
                    f'{pct_tr(p["change_pct"])}</div></div></div></a>', unsafe_allow_html=True)


def render_calendar():
    st.markdown('<div class="sec-head"><span class="sec-no">02</span>'
                '<h3>Ekonomik Takvim</h3></div>', unsafe_allow_html=True)
    with st.container(border=True):
        f = st.columns([2, 1])
        with f[1]:
            st.markdown(f'<div style="text-align:right">{pills(md.CAL_IMPACTS, ss.cal, "cal")}</div>',
                        unsafe_allow_html=True)
        st.markdown(
            '<div class="cal-row" style="border:0;color:#8D96A5;font-size:11px;'
            'letter-spacing:.07em"><span style="width:46px">SAAT</span>'
            '<span style="width:54px">DÖVİZ</span><span style="width:40px">ETKİ</span>'
            '<span style="flex:1">ETKİNLİK</span><span style="width:84px;text-align:right">AÇIKLANAN</span>'
            '<span style="width:84px;text-align:right">BEKLENTİ</span>'
            '<span style="width:84px;text-align:right">ÖNCEKİ</span></div>',
            unsafe_allow_html=True)
        for r in md.get_calendar_rows(ss.cal):
            imp = int(r["impact"])
            dot_c = DOWN if imp >= 3 else GOLD if imp == 2 else "#4A5159"
            dots = "".join(f'<i style="background:{dot_c if k < imp else "#2A2F37"}"></i>'
                           for k in range(3))
            act_c = TXT if r["actual"] == "—" else (UP if _beats(r) else DOWN)
            st.markdown(
                f'<div class="cal-row"><span class="mono" style="width:46px">{r["time"]}</span>'
                f'<span style="width:54px;font-weight:700;font-size:12px">{r["cur"]}</span>'
                f'<span class="dots">{dots}</span>'
                f'<span style="flex:1">{r["event"]}</span>'
                f'<span class="mono" style="width:84px;text-align:right;color:{act_c}">{r["actual"]}</span>'
                f'<span class="mono muted" style="width:84px;text-align:right">{r["forecast"]}</span>'
                f'<span class="mono muted" style="width:84px;text-align:right">{r["previous"]}</span>'
                f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="muted" style="padding-top:10px;font-size:11.5px">'
                    f'<span style="color:{DOWN}">■</span> Yüksek &nbsp;'
                    f'<span style="color:{GOLD}">■</span> Orta &nbsp;'
                    f'<span style="color:#4A5159">■</span> Düşük &nbsp;·&nbsp; '
                    f'Yeşil: beklentinin üstü · Kırmızı: altı</div>', unsafe_allow_html=True)


def _beats(r):
    """Açıklanan beklentiyi aştı mı (kaba karşılaştırma)."""
    def num(s):
        try:
            return float(str(s).replace("%", "").replace(",", ".")
                         .replace("K", "e3").replace("M", "e6"))
        except Exception:
            return None
    a, f = num(r["actual"]), num(r["forecast"])
    return a is not None and f is not None and a >= f


def render_market_news():
    st.markdown('<div class="sec-head"><span class="sec-no">03</span>'
                '<h3>Piyasa Haberleri</h3></div>', unsafe_allow_html=True)
    st.markdown(pills(md.NEWS_CATEGORIES, ss.nc, "nc"), unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    data = md.get_forex_news(ss.nc)
    f = data["featured"]
    left, right = st.columns([1, 1.15], gap="medium")
    with left:
        tags = " ".join(f'<span class="chip">{t}</span>' for t in f["tags"])
        st.markdown(
            f'<div class="feat"><div class="img">[HABER GÖRSELİ]</div>'
            f'<div style="padding:16px">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
            f'<span class="badge" style="color:{NEU};background:rgba(141,150,165,.14)">'
            f'{f["sentiment"]}</span>'
            f'<span class="muted" style="font-size:11.5px">{f["category"]} · [{f["source"]}] · '
            f'{f["when"]}</span></div>'
            f'<b style="font-size:19px;line-height:1.3;display:block">{f["title"]}</b>'
            f'<div class="muted" style="margin-top:8px;line-height:1.5">{f["summary"]}</div>'
            f'<div style="margin-top:10px;display:flex;gap:6px">{tags}</div>'
            f'</div></div>', unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            for it in data["items"]:
                sc = {"Yükseliş": UP, "Düşüş": DOWN}.get(it["sentiment"], NEU)
                sbg = {"Yükseliş": "rgba(52,211,153,.12)",
                       "Düşüş": "rgba(248,113,113,.12)"}.get(it["sentiment"],
                                                             "rgba(141,150,165,.14)")
                st.markdown(
                    f'<div class="nw"><div class="thumb">{svg_spark(it["spark"], sc, 80, 40)}</div>'
                    f'<div style="flex:1;min-width:0"><b>{it["title"]}</b>'
                    f'<div style="margin-top:5px;display:flex;align-items:center;gap:7px">'
                    f'<span class="badge" style="color:{sc};background:{sbg}">{it["sentiment"]}</span>'
                    f'<span class="muted mono" style="font-size:11.5px">{it["pair"]}</span>'
                    f'<span class="muted" style="font-size:11.5px">[{it["source"]}]</span>'
                    f'<span class="muted" style="font-size:11.5px">{it["when"]}</span>'
                    f'</div></div></div>', unsafe_allow_html=True)
            st.markdown(f'<div style="padding-top:10px"><a class="plain" target="_self" '
                        f'href="{link()}" style="color:{ACCENT};font-size:13px;font-weight:600">'
                        f'Tüm haberleri gör →</a></div>', unsafe_allow_html=True)


def render_forex():
    st.markdown('<div class="page-title">Forex &amp; Haberler</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted">🟢 Londra &amp; New York seansı · canlı veri varsa '
                'gerçek fiyatlar</div>', unsafe_allow_html=True)
    render_health()
    render_macro_strip()
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    render_fx_market()
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    render_calendar()
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    render_market_news()


# ======================================================================
# BÖLÜM: LONG TERM
# ======================================================================
def fg_gauge(value):
    steps = [{"range": [0, 25], "color": DOWN}, {"range": [25, 45], "color": "#F0883E"},
             {"range": [45, 55], "color": "#D9C441"}, {"range": [55, 75], "color": "#56B06A"},
             {"range": [75, 100], "color": UP}]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, number={"font": {"size": 42, "color": TXT}},
        gauge={"axis": {"range": [0, 100], "tickvals": [0, 25, 50, 75, 100]},
               "bar": {"color": "rgba(0,0,0,0)"}, "steps": steps,
               "threshold": {"line": {"color": TXT, "width": 5}, "thickness": .85,
                             "value": value}}))
    fig.update_layout(height=240, margin=dict(l=20, r=20, t=8, b=8),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": TXT})
    return fig


def render_longterm():
    st.markdown('<div class="page-title">Long Term</div>', unsafe_allow_html=True)
    fg = md.get_fear_greed()
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Fear &amp; Greed Index</div>', unsafe_allow_html=True)
            st.markdown('<div class="muted">Piyasayı şu an hangi duygu yönetiyor?</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(fg_gauge(fg["value"]), use_container_width=True,
                            config={"displayModeBar": False})
            st.markdown(
                f'<div style="text-align:center;font-size:17px;font-weight:700;margin-top:-10px">'
                f'{fg["label"]}</div>'
                f'<div style="background:#12171f;border-left:3px solid {GOLD};border-radius:8px;'
                f'padding:12px 14px;margin-top:12px;color:#c9d1d9;font-style:italic">'
                f'"{fg["quote"]}"<br><span class="muted" style="font-style:normal">'
                f'— {fg["quote_author"]}</span></div>', unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Geçmiş</div>', unsafe_allow_html=True)
            for h in fg["history"]:
                hc = DOWN if h["value"] < 45 else ("#D9C441" if h["value"] < 55 else UP)
                st.markdown(f'<div class="stat-row"><span class="lbl">{h["when"]}<br>'
                            f'<b style="color:{TXT}">{h["label"]}</b></span>'
                            f'<span class="mono" style="font-size:20px;font-weight:700;color:{hc}">'
                            f'{h["value"]}</span></div>', unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        render_sector_heatmap()

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="panel-title">Ucuz Şirketler (PEG / Forward PE)</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="muted">Forward PE\'ye göre sıralı (ucuzdan pahalıya)</div>',
                    unsafe_allow_html=True)
        st.dataframe(md.get_value_stocks(), use_container_width=True, hide_index=True)


# ======================================================================
# BÖLÜM: SHORT TERM
# ======================================================================
def render_short():
    st.markdown('<div class="page-title">Short Term &amp; Swings</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted">Bir şirkete tıkla → grafiği Piyasalar sekmesinde açılır</div>',
                unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    tickers = md.get_filtered_companies()
    for i in range(0, len(tickers), 4):
        row = st.columns(4)
        for col, t in zip(row, tickers[i:i + 4]):
            info = md.COMPANIES[t]
            logo = md.logo_url(t)
            av = f'<img src="{logo}" alt="">' if logo else t[:2]
            with col:
                st.markdown(
                    f'<a class="plain" target="_self" href="{link(sec="Piyasalar", sym=t)}">'
                    f'<div style="background:{PANEL};border:1px solid {BORDER};border-radius:14px;'
                    f'padding:12px;display:flex;align-items:center;gap:10px">'
                    f'<span class="wl-av">{av}</span>'
                    f'<div style="min-width:0"><b style="font-size:13.5px">{info["name"]}</b>'
                    f'<div class="muted" style="font-size:11.5px">{t} · {info["sector"]}</div></div>'
                    f'</div></a>', unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-head"><span class="sec-no">●</span>'
                '<h3>Trading Strategy Picks</h3></div>', unsafe_allow_html=True)
    picks = md.get_strategy_picks()
    for i in range(0, len(picks), 2):
        row = st.columns(2, gap="medium")
        for col, pick in zip(row, picks[i:i + 2]):
            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<a class="plain" target="_self" '
                        f'href="{link(sec="Piyasalar", sym=pick["ticker"])}">'
                        f'<div style="display:flex;align-items:center;gap:9px">'
                        f'<span class="panel-title">{pick["ticker"]}</span>'
                        f'<span class="chip">{pick["setup"]}</span></div></a>',
                        unsafe_allow_html=True)
                    df = _hist(pick["ticker"]).tail(90)
                    st.plotly_chart(price_chart(df, height=300, rsi_panel=False),
                                    use_container_width=True, config=CHART_CONFIG)
                    st.markdown(
                        f'<div style="display:flex;gap:16px;font-size:12px">'
                        f'<span class="muted">Buy <span class="mono" style="color:{TXT}">'
                        f'{pick["buy_zone"][0]}–{pick["buy_zone"][1]}</span></span>'
                        f'<span class="muted">Stop <span class="mono" style="color:{DOWN}">'
                        f'{pick["stop"]}</span></span>'
                        f'<span class="muted">Hedef <span class="mono" style="color:{UP}">'
                        f'{pick["target"]}</span></span>'
                        f'<span class="muted">R/R <span class="mono" style="color:{TXT}">'
                        f'{pick["rr"]}:1</span></span></div>'
                        f'<div style="background:#12171f;border-left:3px solid {ACCENT};'
                        f'border-radius:6px;padding:10px 12px;margin-top:9px;color:#b9c2cc;'
                        f'font-size:12.5px;line-height:1.5">💡 {pick["note"]}</div>',
                        unsafe_allow_html=True)


# ======================================================================
# AKIŞ
# ======================================================================
render_header()

if ss.section == "Piyasalar":
    render_piyasalar()
elif ss.section == "Long Term":
    render_longterm()
elif ss.section == "Short Term":
    render_short()
else:
    render_forex()
