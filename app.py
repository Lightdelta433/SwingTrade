"""
========================================================================
 PULSE — PİYASA PANELİ  (app.py)
========================================================================
Koyu "Pulse" tarzı tek sayfa. Tüm veri mock_data.py'den gelir
(gerçek veri + mock fallback). app.py sadece çizer.

Düzen (referans tasarıma göre):
  - Üst: başlık + tıklanabilir endeks kartları (tıkla → o sembolün grafiği)
  - Bölüm navigasyonu: Watchlist / Long Term / Short Term & Swings / Forex & News
  - Watchlist (varsayılan, "Piyasalar" görünümü):
      solda büyük mum grafiği (+hacim+RSI),
      sağda  İzleme Listesi (tıkla → grafik) · Teknik Özet · Destek/Direnç,
      altta  Sektör Performansı ısı haritası + Öne Çıkanlar,
      en altta Yaklaşan IPO'lar + Watchlist haberleri
  - Ayrı "detay/aç/çıkar" sayfası YOK: bir ticker'a tıklayınca grafiği açılır.
========================================================================
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import mock_data as md

st.set_page_config(page_title="Pulse — Piyasa Paneli", layout="wide",
                   initial_sidebar_state="collapsed")

# --- Tasarım renkleri ---
BG, PANEL, BORDER = "#0A0B0D", "#111317", "#22262D"
TXT, MUT = "#ECEEF1", "#8D96A5"
UP, DOWN, NEU = "#34D399", "#F87171", "#C4CAD4"
ACCENT = "#5B8CFF"
EMA_COLORS = {20: ACCENT, 50: "#F5B544"}   # tasarım SMA20/SMA50 gibi iki çizgi

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2.6rem; padding-bottom: 3rem; max-width: 1480px; }}
      h1,h2,h3 {{ letter-spacing:-.01em; }}
      .panel {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:16px;
                padding:18px; margin-bottom:14px; }}
      .panel-title {{ font-size:1rem; font-weight:700; margin-bottom:.1rem; }}
      .muted {{ color:{MUT}; font-size:.8rem; }}
      .section-title {{ font-size:1.25rem; font-weight:800; margin:.6rem 0 .2rem 0; }}
      .section-sub {{ color:{MUT}; font-size:.85rem; margin-bottom:.9rem; }}
      /* Endeks kartı başlığı */
      .idx-tick {{ font-size:1.0rem; font-weight:800; }}
      .idx-sub  {{ color:{MUT}; font-size:.72rem; }}
      .idx-last {{ font-size:1.05rem; font-weight:700; }}
      .idx-chg  {{ font-weight:700; font-size:.82rem; }}
      /* Butonları satır/kart gibi göster */
      .stButton button {{ width:100%; border-radius:10px; border:1px solid {BORDER};
                          background:{PANEL}; color:{TXT}; font-size:.82rem;
                          text-align:left; padding:.5rem .7rem; }}
      .stButton button:hover {{ border-color:{ACCENT}; }}
      /* satır bileşenleri */
      .row {{ display:flex; align-items:center; gap:.7rem; padding:.55rem 0;
              border-top:1px solid #1C1F25; }}
      .row .ini {{ width:34px;height:34px;border-radius:9px;background:#1A1D23;
                   display:flex;align-items:center;justify-content:center;
                   font-size:.68rem;font-weight:800;color:{NEU}; }}
      .row .nm {{ flex:1;min-width:0; }}
      .row .nm b {{ font-size:.86rem; }}
      .row .nm span {{ color:{MUT};font-size:.74rem; }}
      .badge {{ font-size:.72rem;font-weight:700;border-radius:6px;padding:2px 7px; }}
      .stat-row {{ display:flex;justify-content:space-between;align-items:baseline;
                   gap:.8rem;padding:.5rem .1rem;border-top:1px solid #1C1F25;font-size:.86rem; }}
      .stat-row .lbl {{ color:{MUT}; }}
      .stat-row .val {{ font-weight:600;text-align:right; }}
      .news-item {{ display:flex;justify-content:space-between;gap:.6rem;
                    padding:.5rem 0;border-top:1px solid #1C1F25; }}
      .news-title {{ font-size:.86rem;line-height:1.35; }}
      .news-meta {{ color:{MUT};font-size:.74rem;white-space:nowrap;padding-top:.1rem; }}
      .news-dot {{ display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:.4rem; }}
      .heat {{ height:76px;border-radius:12px;padding:10px 12px;box-sizing:border-box;
               display:flex;flex-direction:column;justify-content:space-between;margin-bottom:8px; }}
      .heat b {{ font-size:.8rem;color:#fff; }}
      .heat span {{ font-weight:700;color:#fff;font-size:.95rem; }}
    </style>
    """, unsafe_allow_html=True)

# --- State ---
ss = st.session_state
ss.setdefault("active", "SPY")             # grafiği gösterilen sembol (başta SP500)
ss.setdefault("tf", "6M")
ss.setdefault("section", "Watchlist")
ss.setdefault("watchlist", list(md.DEFAULT_WATCHLIST))
ss.setdefault("movers_tab", "up")

TF_DAYS = {"1D": 5, "5D": 10, "1M": 22, "3M": 66, "6M": 132,
           "YTD": None, "1Y": 252, "5Y": 1260, "Max": md._FULL_DAYS}

CHART_CONFIG = {"displayModeBar": True, "displaylogo": False,
                "modeBarButtonsToRemove": ["select2d", "lasso2d"]}


# ======================================================================
# Yardımcılar
# ======================================================================
@st.cache_data(show_spinner=False)
def _ohlc_full(ticker):
    return md.add_emas(md.get_ohlc(ticker, days=md._FULL_DAYS))


def set_active(sym):
    ss.active = sym
    ss.section = "Watchlist"
    st.rerun()


def human_money(x):
    ax = abs(x)
    for d, s in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if ax >= d:
            return f"${x/d:.2f}{s}"
    return f"${x:.2f}"


def human_num(x):
    ax = abs(x)
    for d, s in ((1e9, "B"), (1e6, "M")):
        if ax >= d:
            return f"{x/d:.2f}{s}"
    return f"{x:,.0f}"


def slice_timeframe(df_full, tf):
    if tf == "YTD":
        jan1 = df_full.index[-1].replace(month=1, day=1)
        return df_full[df_full.index >= jan1]
    return df_full.tail(TF_DAYS.get(tf, 132))


def _rsi(close, p=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def compute_tech(df):
    """Gerçek fiyattan teknik göstergeler + Al/Sat/Nötr özeti."""
    close = df["Close"]
    price = float(close.iloc[-1])
    rsi = float(_rsi(close).iloc[-1])
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    macd_v, sig_v = float(macd.iloc[-1]), float(signal.iloc[-1])
    win = df.tail(14)
    hh, ll = float(win["High"].max()), float(win["Low"].min())
    stoch = (price - ll) / ((hh - ll) or 1) * 100
    mom = price - float(close.iloc[-11]) if len(close) > 11 else 0.0
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sig = [
        ("RSI (14)", f"{rsi:.1f}", -1 if rsi > 70 else 1 if rsi < 30 else 0),
        ("MACD (12,26,9)", f"{macd_v:.2f}", 1 if macd_v > sig_v else -1),
        ("Stokastik %K (14)", f"{stoch:.1f}", -1 if stoch > 80 else 1 if stoch < 20 else 0),
        ("Momentum (10)", f"{mom:+.2f}", 1 if mom > 0 else -1),
        ("SMA 20", f"{sma20:.2f}", 1 if price > sma20 else -1),
        ("SMA 50", f"{sma50:.2f}", 1 if price > sma50 else -1),
    ]
    score = sum(v for _, _, v in sig)
    buy = sum(1 for _, _, v in sig if v > 0)
    sell = sum(1 for _, _, v in sig if v < 0)
    label = ("Güçlü Al" if score >= 3 else "Al" if score >= 1 else
             "Güçlü Sat" if score <= -3 else "Sat" if score <= -1 else "Nötr")
    return {"signals": sig, "score": score, "buy": buy, "sell": sell,
            "neutral": len(sig) - buy - sell, "label": label,
            "color": UP if score >= 1 else DOWN if score <= -1 else NEU}


def pivots(df):
    rec = df.tail(5)
    H, L = float(rec["High"].max()), float(rec["Low"].min())
    C = float(df["Close"].iloc[-1])
    P = (H + L + C) / 3
    return [("R2", P + (H - L), DOWN), ("R1", 2 * P - L, DOWN), ("P", P, NEU),
            ("S1", 2 * P - H, UP), ("S2", P - (H - L), UP)], C


# ---- Grafikler ----
def main_chart(df, height=430):
    """Mum + SMA20/50 + hacim + RSI (3 satır), tasarıma yakın."""
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.62, 0.17, 0.21], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                  low=df["Low"], close=df["Close"], increasing_line_color=UP,
                  decreasing_line_color=DOWN, name="Fiyat"), row=1, col=1)
    for p, color in EMA_COLORS.items():
        if f"EMA{p}" in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[f"EMA{p}"], mode="lines",
                          line=dict(color=color, width=1.4), name=f"SMA {p}"), row=1, col=1)
    vol_colors = [UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors,
                  name="Hacim", opacity=0.5), row=2, col=1)
    rsi = _rsi(df["Close"])
    fig.add_trace(go.Scatter(x=df.index, y=rsi, mode="lines",
                  line=dict(color="#C4B5FD", width=1.4), name="RSI 14"), row=3, col=1)
    fig.add_hline(y=70, line=dict(color="#3A404A", width=1, dash="dash"), row=3, col=1)
    fig.add_hline(y=30, line=dict(color="#3A404A", width=1, dash="dash"), row=3, col=1)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_layout(template="plotly_dark", height=height,
                      margin=dict(l=8, r=8, t=28, b=8), showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=10)),
                      xaxis_rangeslider_visible=False, hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor="#1A1D23")
    fig.update_yaxes(gridcolor="#1A1D23")
    return fig


def mini_spark(series, change_pct):
    color = UP if change_pct >= 0 else DOWN
    fig = go.Figure(go.Scatter(y=series, mode="lines", line=dict(color=color, width=1.6)))
    fig.update_layout(template="plotly_dark", height=40, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def tech_gauge(score):
    val = (score + 6) / 12 * 100          # -6..6 -> 0..100
    fig = go.Figure(go.Indicator(
        mode="gauge", value=val,
        gauge={"axis": {"range": [0, 100], "visible": False},
               "bar": {"color": "rgba(0,0,0,0)"},
               "steps": [{"range": [0, 40], "color": DOWN},
                         {"range": [40, 60], "color": "#2A2F37"},
                         {"range": [60, 100], "color": UP}],
               "threshold": {"line": {"color": TXT, "width": 5}, "thickness": 0.9, "value": val}}))
    fig.update_layout(height=150, margin=dict(l=10, r=10, t=6, b=0),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def news_list(items, with_ticker=False):
    sent = {"Positive": UP, "Negative": DOWN, "Neutral": MUT}
    for it in items:
        dot = sent.get(it.get("sentiment", "Neutral"), MUT)
        tag = f'<b style="color:{TXT}">{it["ticker"]}</b>&nbsp; ' if with_ticker else ""
        st.markdown(f'<div class="news-item"><div class="news-title">'
                    f'<span class="news-dot" style="background:{dot}"></span>{tag}{it["title"]}</div>'
                    f'<div class="news-meta">{it["source"]} · {it["when"]}</div></div>',
                    unsafe_allow_html=True)


# ======================================================================
# ÜST: başlık + sağlık + endeks kartları (tıklanabilir)
# ======================================================================
def render_health():
    h = md.get_data_health()
    live = h["yf_ok"]
    badge = "🟢 Canlı veri" if live else "🟡 Mock veri"
    with st.expander(f"🔎 Veri kaynağı durumu — {badge}", expanded=not live):
        ok = lambda b: "✅" if b else "❌"
        st.markdown(f"- {ok(h['yfinance_installed'])} yfinance kurulu  \n"
                    f"- {ok(h['yf_ok'])} yfinance canlı çekim — {h['yf_msg']}  \n"
                    f"- {ok(h['cnn_ok'])} CNN Fear & Greed — {h['cnn_msg']}")
        if not h["yfinance_installed"]:
            st.warning("requirements.txt güncel değil — `yfinance>=0.2.40` eksik. Yükleyip Reboot et.")
        elif not h["yf_ok"]:
            st.warning("yfinance kurulu ama Yahoo veri vermedi (muhtemelen IP rate-limit). "
                       "Sürerse Finnhub gibi anahtarlı kaynağa geçeriz.")


def render_top():
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown("## Piyasalar")
        st.markdown(f'<div class="muted">🟢 Pulse paneli · bir karta tıkla → grafiği açılır</div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)
    render_health()

    cols = st.columns(4)
    for col, idx in zip(cols, md.get_index_summary()):
        color = UP if idx["change_pct"] >= 0 else DOWN
        sign = "▲" if idx["change_pct"] >= 0 else "▼"
        active = ss.active == idx["ticker"]
        with col:
            with st.container(border=True):
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
                    f'<span class="idx-tick">{idx["ticker"]}</span>'
                    f'<span class="idx-sub">{idx["subtitle"]}</span></div>'
                    f'<div><span class="idx-last">{idx["last"]:,.2f}</span> '
                    f'<span class="idx-chg" style="color:{color}">{sign} {idx["change_pct"]:+.2f}%</span></div>',
                    unsafe_allow_html=True)
                st.plotly_chart(mini_spark(idx["series"], idx["change_pct"]),
                                use_container_width=True, config={"displayModeBar": False})
                if st.button(("● " if active else "") + "Grafiği aç",
                             key=f"idx_{idx['ticker']}", use_container_width=True):
                    set_active(idx["ticker"])


# ======================================================================
# BÖLÜM: WATCHLIST = Piyasalar görünümü (ana layout)
# ======================================================================
def render_chart_block():
    sym = ss.active
    d = md.get_company_detail(sym)
    df_full = _ohlc_full(sym)
    tfs = list(TF_DAYS.keys())
    col = UP if d["change_abs"] >= 0 else DOWN
    sign = "+" if d["change_abs"] >= 0 else ""

    st.markdown(f'<div class="panel-title">{d["name"]} '
                f'<span class="muted">· {sym}</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div style="margin:.1rem 0 .4rem 0">'
                f'<span style="font-size:1.8rem;font-weight:700">${d["last"]:,.2f}</span> '
                f'<span style="color:{col};font-weight:700">{sign}{d["change_abs"]:.2f} '
                f'({sign}{d["change_pct"]:.2f}%)</span></div>', unsafe_allow_html=True)

    tf = st.radio("Zaman", tfs, index=tfs.index(ss.tf), horizontal=True,
                  key="tf_main", label_visibility="collapsed")
    ss.tf = tf
    df = slice_timeframe(df_full, tf)
    st.markdown(f'<div class="muted">Açılış {d["open"]:,.2f} · Yüksek {d["day_high"]:,.2f} · '
                f'Düşük {d["day_low"]:,.2f} · Hacim {d["volume"]:,}</div>', unsafe_allow_html=True)
    st.plotly_chart(main_chart(df), use_container_width=True, config=CHART_CONFIG)

    with st.expander("Şirket bilgileri (fundamentaller)"):
        g = st.columns(4)
        with g[0]:
            st.markdown(f'<div class="stat-row"><span class="lbl">Market Cap</span>'
                        f'<span class="val">{human_money(d["market_cap"])}</span></div>'
                        f'<div class="stat-row"><span class="lbl">PE</span>'
                        f'<span class="val">{d["pe"]:.2f}</span></div>', unsafe_allow_html=True)
        with g[1]:
            st.markdown(f'<div class="stat-row"><span class="lbl">Forward PE</span>'
                        f'<span class="val">{d["fwd_pe"]:.2f}</span></div>'
                        f'<div class="stat-row"><span class="lbl">EPS</span>'
                        f'<span class="val">{d["eps"]:.2f}</span></div>', unsafe_allow_html=True)
        with g[2]:
            st.markdown(f'<div class="stat-row"><span class="lbl">52h Yüksek</span>'
                        f'<span class="val">{d["high_52w"]:,.2f}</span></div>'
                        f'<div class="stat-row"><span class="lbl">52h Düşük</span>'
                        f'<span class="val">{d["low_52w"]:,.2f}</span></div>', unsafe_allow_html=True)
        with g[3]:
            st.markdown(f'<div class="stat-row"><span class="lbl">Analist</span>'
                        f'<span class="val">{d["analysts"]}</span></div>'
                        f'<div class="stat-row"><span class="lbl">Hedef</span>'
                        f'<span class="val">${d["price_target"]:,.2f}</span></div>',
                        unsafe_allow_html=True)
    return df


def render_watchlist_panel():
    st.markdown('<div class="panel-title">İzleme Listesi</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted" style="margin-bottom:.4rem">Bir sembole tıkla → grafiği açılır</div>',
                unsafe_allow_html=True)
    if not ss.watchlist:
        st.caption("Liste boş.")
    for t in list(ss.watchlist):
        q = md.get_quote(t)
        c = UP if q["change_pct"] >= 0 else DOWN
        mark = "● " if ss.active == t else ""
        if st.button(f"{mark}{t}   ${q['last']:,.2f}   {q['change_pct']:+.2f}%",
                     key=f"wl_{t}", use_container_width=True):
            set_active(t)


def render_tech_summary(df):
    t = compute_tech(df)
    st.markdown('<div class="panel-title">Teknik Özet</div>', unsafe_allow_html=True)
    st.plotly_chart(tech_gauge(t["score"]), use_container_width=True,
                    config={"displayModeBar": False})
    st.markdown(f'<div style="text-align:center;font-size:1.3rem;font-weight:800;'
                f'color:{t["color"]};margin-top:-1rem">{t["label"]}</div>', unsafe_allow_html=True)
    cc = st.columns(3)
    for col, (lbl, val, clr) in zip(cc, [("Sat", t["sell"], DOWN),
                                         ("Nötr", t["neutral"], NEU), ("Al", t["buy"], UP)]):
        with col:
            st.markdown(f'<div style="background:#0C0D10;border-radius:10px;padding:8px;'
                        f'text-align:center"><div class="muted">{lbl}</div>'
                        f'<div style="font-size:1.1rem;font-weight:700;color:{clr}">{val}</div></div>',
                        unsafe_allow_html=True)
    st.markdown("<div style='height:.4rem'></div>", unsafe_allow_html=True)
    for name, val, v in t["signals"]:
        lab = "Al" if v > 0 else "Sat" if v < 0 else "Nötr"
        fg = UP if v > 0 else DOWN if v < 0 else NEU
        bg = ("rgba(52,211,153,.12)" if v > 0 else "rgba(248,113,113,.12)"
              if v < 0 else "rgba(141,150,165,.14)")
        st.markdown(f'<div class="stat-row"><span class="lbl">{name}</span>'
                    f'<span style="font-family:monospace">{val}</span>'
                    f'<span class="badge" style="color:{fg};background:{bg}">{lab}</span></div>',
                    unsafe_allow_html=True)


def render_support_resistance(df):
    levels, price = pivots(df)
    st.markdown('<div class="panel-title">Destek & Direnç</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted" style="margin-bottom:.3rem">Pivot · klasik</div>',
                unsafe_allow_html=True)
    for k, v, fg in levels:
        dist = (v / price - 1) * 100
        st.markdown(f'<div class="stat-row"><span style="color:{fg};font-weight:700">{k}</span>'
                    f'<span style="font-family:monospace">{v:,.2f}</span>'
                    f'<span class="muted" style="font-family:monospace">{dist:+.2f}%</span></div>',
                    unsafe_allow_html=True)


def render_sector_heatmap():
    st.markdown('<div class="section-title">Sektör Performansı</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Günlük değişim</div>', unsafe_allow_html=True)
    secs = md.get_sector_performance()
    PER = 4
    for i in range(0, len(secs), PER):
        row = st.columns(PER)
        for col, s in zip(row, secs[i:i + PER]):
            ch = s["change_pct"]
            a = min(1.0, 0.28 + abs(ch) / 2.5 * 0.7)
            rgb = "16,122,87" if ch >= 0 else "185,45,55"
            with col:
                st.markdown(f'<div class="heat" style="background:rgba({rgb},{a:.2f})">'
                            f'<b>{s["name"]}</b><span>{ch:+.2f}%</span></div>',
                            unsafe_allow_html=True)


def render_movers():
    head = st.columns([2, 1.3])
    with head[0]:
        st.markdown('<div class="section-title">Öne Çıkanlar</div>', unsafe_allow_html=True)
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
            f'<div class="nm"><b>{q["ticker"]}</b><br><span>{q["name"]}</span></div>'
            f'<div style="text-align:right"><div style="font-family:monospace">${q["last"]:,.2f}</div>'
            f'<span class="badge" style="color:{c};background:{bg}">{q["change_pct"]:+.2f}%</span></div></div>',
            unsafe_allow_html=True)


def render_markets():
    left, right = st.columns([2, 1], gap="medium")
    with left:
        with st.container(border=True):
            df = render_chart_block()
    with right:
        with st.container(border=True):
            render_watchlist_panel()
        with st.container(border=True):
            render_tech_summary(df)
        with st.container(border=True):
            render_support_resistance(df)

    st.divider()
    b_left, b_right = st.columns([2, 1], gap="medium")
    with b_left:
        with st.container(border=True):
            render_sector_heatmap()
    with b_right:
        with st.container(border=True):
            render_movers()

    st.divider()
    c_left, c_right = st.columns([2, 1], gap="medium")
    with c_left:
        st.markdown('<div class="section-title">Yaklaşan Halka Arzlar (IPO)</div>', unsafe_allow_html=True)
        st.dataframe(md.get_upcoming_ipos(), use_container_width=True, hide_index=True)
    with c_right:
        st.markdown('<div class="section-title">Watchlist Haberleri</div>', unsafe_allow_html=True)
        news_list(md.get_watchlist_news(list(ss.watchlist)), with_ticker=True)


# ======================================================================
# BÖLÜM: LONG TERM
# ======================================================================
def fear_greed_gauge(value):
    steps = [{"range": [0, 25], "color": "#F87171"}, {"range": [25, 45], "color": "#F0883E"},
             {"range": [45, 55], "color": "#D9C441"}, {"range": [55, 75], "color": "#56B06A"},
             {"range": [75, 100], "color": "#34D399"}]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, number={"font": {"size": 44, "color": TXT}},
        gauge={"axis": {"range": [0, 100], "tickvals": [0, 25, 50, 75, 100]},
               "bar": {"color": "rgba(0,0,0,0)"},
               "steps": steps,
               "threshold": {"line": {"color": TXT, "width": 5}, "thickness": 0.85, "value": value}}))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": TXT})
    return fig


def render_longterm():
    fg = md.get_fear_greed()
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown('<div class="section-title">Fear & Greed Index</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">Piyasayı şu an hangi duygu yönetiyor?</div>',
                    unsafe_allow_html=True)
        st.plotly_chart(fear_greed_gauge(fg["value"]), use_container_width=True,
                        config={"displayModeBar": False})
        st.markdown(
            f'<div style="text-align:center;font-size:1.1rem;font-weight:700;margin-top:-.5rem">'
            f'{fg["label"]}</div>'
            f'<div style="background:#12171f;border-left:3px solid #F5B544;border-radius:6px;'
            f'padding:.7rem .9rem;margin-top:.8rem;color:#c9d1d9;font-style:italic">'
            f'"{fg["quote"]}"<br><span style="color:{MUT};font-style:normal;font-size:.82rem">'
            f'— {fg["quote_author"]}</span></div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="section-title">Geçmiş</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">&nbsp;</div>', unsafe_allow_html=True)
        for h in fg["history"]:
            hc = DOWN if h["value"] < 45 else ("#D9C441" if h["value"] < 55 else UP)
            st.markdown(f'<div class="stat-row"><span class="lbl">{h["when"]}<br>'
                        f'<b style="color:{TXT}">{h["label"]}</b></span>'
                        f'<span class="val" style="font-size:1.3rem;color:{hc}">{h["value"]}</span></div>',
                        unsafe_allow_html=True)

    st.divider()
    render_sector_heatmap()   # sektör sıralaması yerine sektör performansı

    st.divider()
    st.markdown('<div class="section-title">Ucuz Şirketler (PEG / Forward PE)</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Forward PE\'ye göre sıralı (ucuzdan pahalıya)</div>',
                unsafe_allow_html=True)
    st.dataframe(md.get_value_stocks(), use_container_width=True, hide_index=True,
                 column_config={
                     "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                     "PEG": st.column_config.NumberColumn("PEG", format="%.2f"),
                     "Forward PE": st.column_config.NumberColumn("Forward PE", format="%.1f"),
                     "Profit Margin %": st.column_config.NumberColumn("Profit M %", format="%.1f%%"),
                     "EPS Next 5Y %": st.column_config.NumberColumn("EPS Next 5Y %", format="%.1f%%"),
                 })


# ======================================================================
# BÖLÜM: SHORT TERM & SWINGS
# ======================================================================
def render_short():
    st.markdown('<div class="section-title">Filtrene Uyan Şirketler</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Bir şirkete tıkla → grafiği Piyasalar sekmesinde açılır</div>',
                unsafe_allow_html=True)
    tickers = md.get_filtered_companies()
    PER = 4
    for i in range(0, len(tickers), PER):
        row = st.columns(PER)
        for col, t in zip(row, tickers[i:i + PER]):
            info = md.COMPANIES[t]
            with col:
                with st.container(border=True):
                    lc, nc = st.columns([1, 3])
                    with lc:
                        logo = md.logo_url(t)
                        if logo:
                            st.markdown(f'<img src="{logo}" style="width:32px;height:32px;'
                                        f'border-radius:7px;background:#fff;padding:2px">',
                                        unsafe_allow_html=True)
                    with nc:
                        st.markdown(f'<b style="font-size:.9rem">{info["name"]}</b><br>'
                                    f'<span class="muted">{t} · {info["sector"]}</span>',
                                    unsafe_allow_html=True)
                    if st.button("Grafiği aç", key=f"flt_{t}", use_container_width=True):
                        set_active(t)

    st.divider()
    st.markdown('<div class="section-title">Trading Strategy Picks</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">EMA 20/50, ranked S/R, formasyon</div>', unsafe_allow_html=True)
    picks = md.get_strategy_picks()
    for i in range(0, len(picks), 2):
        row = st.columns(2, gap="large")
        for col, pick in zip(row, picks[i:i + 2]):
            with col:
                df = _ohlc_full(pick["ticker"]).tail(132)
                st.markdown(f'<div class="panel-title">{pick["ticker"]} — {pick["setup"]}</div>',
                            unsafe_allow_html=True)
                st.plotly_chart(main_chart(df, height=360), use_container_width=True,
                                config=CHART_CONFIG)
                d = st.columns(3)
                with d[0]:
                    st.markdown(f'<div class="stat-row"><span class="lbl">Buy</span>'
                                f'<span class="val">${pick["buy_zone"][0]}–{pick["buy_zone"][1]}</span></div>',
                                unsafe_allow_html=True)
                with d[1]:
                    st.markdown(f'<div class="stat-row"><span class="lbl">Stop/Hedef</span>'
                                f'<span class="val">${pick["stop"]}→{pick["target"]}</span></div>',
                                unsafe_allow_html=True)
                with d[2]:
                    st.markdown(f'<div class="stat-row"><span class="lbl">R/R</span>'
                                f'<span class="val">{pick["rr"]}:1</span></div>', unsafe_allow_html=True)
                st.markdown(f'<div style="background:#12171f;border-left:3px solid {ACCENT};'
                            f'border-radius:6px;padding:.6rem .8rem;margin-top:.4rem;'
                            f'color:#b9c2cc;font-size:.8rem">💡 {pick["note"]}</div>',
                            unsafe_allow_html=True)
                if st.button("Grafiği büyüt (Piyasalar)", key=f"pk_{pick['ticker']}",
                             use_container_width=True):
                    set_active(pick["ticker"])


# ======================================================================
# BÖLÜM: FOREX & NEWS
# ======================================================================
def render_forex():
    st.markdown('<div class="section-title">Forex</div>', unsafe_allow_html=True)
    fx_cols = st.columns(6)
    for col, fx in zip(fx_cols, md.get_forex_rates()):
        c = UP if fx["change_pct"] >= 0 else DOWN
        with col:
            with st.container(border=True):
                st.markdown(f'<div style="font-weight:700">{fx["pair"]}</div>'
                            f'<div style="font-size:1.1rem;font-weight:700">{fx["rate"]:.4f}</div>'
                            f'<div style="color:{c};font-weight:700;font-size:.82rem">'
                            f'{fx["change_pct"]:+.2f}%</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="section-title">Ekonomik Takvim</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Yaklaşan makro veri ve açıklamalar</div>', unsafe_allow_html=True)
    st.dataframe(md.get_economic_calendar(), use_container_width=True, hide_index=True)

    st.divider()
    ncols = st.columns(3, gap="large")
    cats = [("war_politics", "⚔️ Savaş & Politika"), ("markets", "📰 Borsa Haberleri"),
            ("index", "🤖 Endeks Bazında (AI, Yarı İletken…)")]
    for col, (cat, title) in zip(ncols, cats):
        with col:
            st.markdown(f'<div class="section-title" style="font-size:1.05rem">{title}</div>',
                        unsafe_allow_html=True)
            news_list(md.get_market_news(cat))


# ======================================================================
# ANA AKIŞ
# ======================================================================
render_top()
st.divider()

sections = ["Watchlist", "Long Term", "Short Term & Swings", "Forex & News"]
sec = st.radio("Bölüm", sections, index=sections.index(ss.section),
               horizontal=True, key="nav", label_visibility="collapsed")
ss.section = sec
st.divider()

if sec == "Watchlist":
    render_markets()
elif sec == "Long Term":
    render_longterm()
elif sec == "Short Term & Swings":
    render_short()
else:
    render_forex()
