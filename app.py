"""
========================================================================
 SWING TRADE DASHBOARD  (app.py)
========================================================================
Koyu temalı Streamlit arayüzü. Tüm veri mock_data.py'den gelir.

Çalıştırmak için:
    pip install -r requirements.txt
    streamlit run app.py

İki görünüm (view) vardır:
    - "dashboard" : Market kartları, 20 şirket, strateji picks, value tablo
    - "detail"    : Bir şirkete tıklayınca açılan detay sayfası
                    (solda veriler, sağda grafik + "Full Chart" vollbild)
========================================================================
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import mock_data as md

# ----------------------------------------------------------------------
# Sayfa ayarı + stil
# ----------------------------------------------------------------------
st.set_page_config(page_title="Swing Trade Dashboard", layout="wide",
                   initial_sidebar_state="collapsed")

EMA_COLORS = {20: "#f6c177", 50: "#56b6c2", 100: "#c4a7e7", 200: "#eb6f92"}
UP, DOWN = "#3fb950", "#f85149"

# Dominantere S/R-Zonen: kräftige Füllung + sichtbarer Rahmen, rank'e göre yoğunluk
SR_FILL = {1: "rgba(88,166,255,0.30)", 2: "rgba(88,166,255,0.20)", 3: "rgba(88,166,255,0.13)"}
SR_LINE = "#58a6ff"

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.0rem; padding-bottom: 3rem; max-width: 1500px; }
      h1, h2, h3 { letter-spacing: .3px; }
      .section-title { font-size: 1.35rem; font-weight: 700; margin: .4rem 0 .2rem 0; }
      .section-sub { color: #8b949e; font-size: .85rem; margin-bottom: .8rem; }
      /* Markt-Kartenkopf */
      .idx-head { display:flex; align-items:baseline; justify-content:space-between;
                  gap:.5rem; margin-bottom:.3rem; flex-wrap:wrap; }
      .idx-tick { font-size: 1.1rem; font-weight: 800; line-height: 1.2; white-space:nowrap; }
      .idx-sub  { color: #8b949e; font-size: .72rem; line-height:1.2; }
      .idx-last { font-size: 1.0rem; font-weight: 700; line-height:1.2; white-space:nowrap; }
      .idx-chg  { font-weight:700; font-size:.82rem; white-space:nowrap; }
      /* Haber kartı */
      .news-item { display:flex; justify-content:space-between; gap:.6rem;
                   padding:.55rem 0; border-bottom:1px solid #21262d; }
      .news-title { font-size:.88rem; line-height:1.35; }
      .news-meta  { color:#8b949e; font-size:.74rem; white-space:nowrap; padding-top:.1rem; }
      .news-dot   { display:inline-block; width:7px; height:7px; border-radius:50%;
                    margin-right:.4rem; }
      /* Şirket kartı */
      .firm-name { font-weight:600; font-size:.95rem; line-height:1.05; }
      .firm-tick { color:#8b949e; font-size:.72rem; }
      .firm-logo { width:34px; height:34px; border-radius:7px; background:#fff;
                   object-fit:contain; padding:2px; }
      div[data-testid="stHorizontalBlock"] { align-items:center; }
      .stButton button { width:100%; border-radius:8px; border:1px solid #30363d;
                         background:#1f2630; color:#e6edf3; font-size:.8rem; }
      .stButton button:hover { border-color:#f6c177; color:#f6c177; }
      /* Key-Value Blöcke */
      .kv { background:#161b22; border:1px solid #30363d; border-radius:10px;
            padding:.5rem .7rem; margin-bottom:.4rem; }
      .kv .k { color:#8b949e; font-size:.70rem; text-transform:uppercase; }
      .kv .v { font-size:1.02rem; font-weight:700; }
      /* Detay sayfası stat satırları (Bild 2 benzeri) */
      .stat-row { display:flex; justify-content:space-between;
                  padding:.42rem .2rem; border-bottom:1px solid #21262d; font-size:.9rem; }
      .stat-row .lbl { color:#8b949e; }
      .stat-row .val { font-weight:600; }
      .pick-note { background:#12171f; border-left:3px solid #58a6ff; border-radius:6px;
                   padding:.55rem .75rem; color:#b9c2cc; font-size:.82rem;
                   line-height:1.45; margin-top:.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Görünüm (view) state ---
ss = st.session_state
ss.setdefault("view", "dashboard")
ss.setdefault("selected", None)
ss.setdefault("tf", "6M")


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _ohlc_detail(ticker):
    """Detay için uzun geçmiş + EMA'lar (EMA200 baştan doğru olsun diye)."""
    return md.add_emas(md.get_ohlc(ticker, days=md._FULL_DAYS))


@st.cache_data(show_spinner=False)
def _ohlc(ticker):
    return md.add_emas(md.get_ohlc(ticker))


# Timeframe -> gösterilecek iş günü sayısı
TF_DAYS = {"1D": 5, "5D": 10, "1M": 22, "3M": 66, "6M": 132,
           "YTD": None, "1Y": 252, "5Y": 1260, "Max": md._FULL_DAYS}


def human_money(x):
    ax = abs(x)
    if ax >= 1e12: return f"${x/1e12:.2f}T"
    if ax >= 1e9:  return f"${x/1e9:.2f}B"
    if ax >= 1e6:  return f"${x/1e6:.2f}M"
    if ax >= 1e3:  return f"${x/1e3:.2f}K"
    return f"${x:.2f}"


def human_num(x):
    ax = abs(x)
    if ax >= 1e9: return f"{x/1e9:.2f}B"
    if ax >= 1e6: return f"{x/1e6:.2f}M"
    if ax >= 1e3: return f"{x/1e3:,.0f}"
    return f"{x:,.0f}"


def mini_index_chart(series, prev_close, change_pct):
    """Küçük intraday çizgi + prev_close için kesikli yatay çizgi (Bild 1)."""
    color = UP if change_pct >= 0 else DOWN
    rgb = "63,185,80" if change_pct >= 0 else "248,81,73"
    fig = go.Figure(go.Scatter(y=series, mode="lines",
                               line=dict(color=color, width=1.8),
                               fill="tozeroy", fillcolor=f"rgba({rgb},0.12)"))
    fig.add_hline(y=prev_close, line=dict(color="#6e7681", width=1, dash="dot"))
    ymin, ymax = min(min(series), prev_close), max(max(series), prev_close)
    pad = (ymax - ymin) * 0.15 or 1
    fig.update_layout(template="plotly_dark", height=64, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(visible=False),
                      yaxis=dict(visible=False, range=[ymin - pad, ymax + pad]),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def ta_chart(df, title, height=560, show_sr=False, show_formation=False,
             formation_type="Trendline", show_volume=True):
    """Candlestick + EMA20/50/100/200 + (ops.) hacim, S/R, formasyon."""
    if show_volume:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.76, 0.24], vertical_spacing=0.03)
    else:
        fig = make_subplots(rows=1, cols=1)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=UP, decreasing_line_color=DOWN, name="Price"),
        row=1, col=1)

    for p, color in EMA_COLORS.items():
        if f"EMA{p}" in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[f"EMA{p}"], mode="lines",
                                     line=dict(color=color, width=1.3), name=f"EMA{p}"),
                          row=1, col=1)

    # Ranked S/R zones — dominantere Farbe + Rahmen
    if show_sr:
        for z in md.get_sr_zones(df):
            fig.add_hrect(y0=z["low"], y1=z["high"],
                          fillcolor=SR_FILL.get(z["rank"], SR_FILL[3]),
                          line=dict(color=SR_LINE, width=1.4), opacity=1.0,
                          row=1, col=1)
            fig.add_annotation(x=df.index[2], y=z["high"], text=f"S/R #{z['rank']}",
                               showarrow=False, font=dict(size=10, color=SR_LINE),
                               bgcolor="rgba(13,17,23,0.6)", xanchor="left", row=1, col=1)

    if show_formation:
        form = md.get_formation(df, formation_type)
        for (x0, y0), (x1, y1) in form["lines"]:
            fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                          line=dict(color="#f6c177", width=1.8, dash="dot"), row=1, col=1)
        fig.add_annotation(x=df.index[-1], y=df["High"].max(), text=f"📐 {form['type']}",
                           showarrow=False, font=dict(size=11, color="#f6c177"),
                           xanchor="right", row=1, col=1)

    if show_volume:
        vol_colors = [UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]
        fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors,
                             name="Volume", opacity=0.6), row=2, col=1)

    fig.update_layout(
        template="plotly_dark", height=height, title=dict(text=title, font=dict(size=15)),
        margin=dict(l=10, r=10, t=40, b=10), showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=10)),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(gridcolor="#21262d")
    fig.update_yaxes(gridcolor="#21262d")
    return fig


def kv_block(label, value):
    st.markdown(f'<div class="kv"><div class="k">{label}</div>'
                f'<div class="v">{value}</div></div>', unsafe_allow_html=True)


def stat_row(label, value):
    st.markdown(f'<div class="stat-row"><span class="lbl">{label}</span>'
                f'<span class="val">{value}</span></div>', unsafe_allow_html=True)


def slice_timeframe(df_full, tf):
    if tf == "YTD":
        jan1 = df_full.index[-1].replace(month=1, day=1)
        return df_full[df_full.index >= jan1]
    n = TF_DAYS.get(tf, 132)
    return df_full.tail(n)


def render_news(ticker):
    """Grafiğin altına konan haber listesi. Popup değil, sayfanın normal bir
    parçası — bu yüzden sayfayla birlikte sorunsuz kayar (scroll)."""
    st.markdown('<div class="section-title" style="font-size:1.05rem;margin-top:1rem">'
                'İlgili Haberler</div>', unsafe_allow_html=True)
    sentiment_color = {"Positive": UP, "Negative": DOWN, "Neutral": "#8b949e"}
    for item in md.get_company_news(ticker):
        dot = sentiment_color.get(item["sentiment"], "#8b949e")
        st.markdown(
            f'<div class="news-item">'
            f'<div class="news-title"><span class="news-dot" style="background:{dot}"></span>'
            f'{item["title"]}</div>'
            f'<div class="news-meta">{item["source"]} · {item["when"]}</div>'
            f'</div>', unsafe_allow_html=True)


# ======================================================================
# DETAY SAYFASI (bir şirkete tıklayınca)
# ======================================================================
def render_detail(ticker):
    d = md.get_company_detail(ticker)
    logo = md.logo_url(ticker)

    # Üst bar: geri + isim + aksiyon butonları
    top = st.columns([0.6, 5, 1.2, 1.2])
    with top[0]:
        if st.button("← Geri", key="back"):
            ss.view = "dashboard"
            st.rerun()
    with top[1]:
        logo_html = f'<img src="{logo}" class="firm-logo" style="width:40px;height:40px">' if logo else ""
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:.6rem">{logo_html}'
            f'<div><div style="font-size:1.5rem;font-weight:800;line-height:1.1">{d["name"]}</div>'
            f'<div style="color:#8b949e;font-size:.8rem">{ticker} · {d["sector"]} · USD</div></div></div>',
            unsafe_allow_html=True)
    with top[2]:
        if st.button("⛶ Full Chart", key="fc_btn"):
            ss.view = "fullchart"
            st.rerun()
    with top[3]:
        st.button("☆ Watchlist", key="wl_btn")

    # Fiyat satırı
    col = UP if d["change_abs"] >= 0 else DOWN
    sign = "+" if d["change_abs"] >= 0 else ""
    st.markdown(
        f'<div style="margin:.3rem 0 .2rem 0"><span style="font-size:2rem;font-weight:800">'
        f'${d["last"]:,.2f}</span> <span style="color:{col};font-weight:700;font-size:1.05rem">'
        f'{sign}{d["change_abs"]:.2f} ({sign}{d["change_pct"]:.2f}%)</span></div>',
        unsafe_allow_html=True)
    st.caption(d["desc"])
    st.divider()

    # Sol: veriler  |  Sağ: grafik (Bild 2 düzeni)
    left, right = st.columns([1, 1.9], gap="large")

    with left:
        c1, c2 = st.columns(2)
        with c1:
            stat_row("Market Cap", human_money(d["market_cap"]))
            stat_row("Revenue (ttm)", human_money(d["revenue"]))
            stat_row("Net Income", human_money(d["net_income"]))
            stat_row("EPS", f'{d["eps"]:.2f}')
            stat_row("Shares Out", human_num(d["shares_out"]))
            stat_row("PE Ratio", f'{d["pe"]:.2f}')
            stat_row("Forward PE", f'{d["fwd_pe"]:.2f}')
            stat_row("Beta", f'{d["beta"]:.2f}')
        with c2:
            stat_row("Volume", f'{d["volume"]:,}')
            stat_row("Open", f'${d["open"]:,.2f}')
            stat_row("Previous Close", f'${d["prev_close"]:,.2f}')
            stat_row("Day's Range", f'${d["day_low"]:,.2f} – ${d["day_high"]:,.2f}')
            stat_row("52-Week Range", f'${d["low_52w"]:,.2f} – ${d["high_52w"]:,.2f}')
            div = f'${d["dividend"]:.2f} ({d["div_yield"]:.2f}%)' if d["dividend"] else "—"
            stat_row("Dividend", div)
            stat_row("Analysts", d["analysts"])
            stat_row("Price Target", f'${d["price_target"]:,.2f} (+{d["target_upside"]:.1f}%)')
        ed = d["earnings_date"].strftime("%b %d, %Y")
        xd = d["ex_div_date"].strftime("%b %d, %Y") if d["ex_div_date"] is not None else "—"
        stat_row("Earnings Date", ed)
        stat_row("Ex-Dividend Date", xd)

    with right:
        tfs = list(TF_DAYS.keys())
        tf = st.radio("Zeitraum", tfs, index=tfs.index(ss.tf),
                      horizontal=True, key="tf_detail", label_visibility="collapsed")
        ss.tf = tf
        df_full = _ohlc_detail(ticker)
        df = slice_timeframe(df_full, tf)
        st.plotly_chart(ta_chart(df, "", height=430, show_sr=True),
                        use_container_width=True)
        st.caption("Grafiğe tam ekran bakmak için üstteki **⛶ Full Chart** butonuna bas.")

    st.divider()
    render_news(ticker)


# ======================================================================
# TAM EKRAN GRAFİK SAYFASI ("Full Chart" butonuna basınca)
# ======================================================================
def render_fullchart(ticker):
    info = md.COMPANIES[ticker]
    top = st.columns([0.7, 5])
    with top[0]:
        if st.button("← Geri", key="back_fc"):
            ss.view = "detail"
            st.rerun()
    with top[1]:
        st.markdown(f"### {info['name']} ({ticker}) — Tam Ekran Grafik")

    tfs = list(TF_DAYS.keys())
    tf = st.radio("Zeitraum", tfs, index=tfs.index(ss.tf),
                  horizontal=True, key="tf_full", label_visibility="collapsed")
    ss.tf = tf
    df_full = _ohlc_detail(ticker)
    df = slice_timeframe(df_full, tf)
    st.plotly_chart(ta_chart(df, f"{ticker} — {tf}", height=680, show_sr=True),
                    use_container_width=True)

    st.divider()
    render_news(ticker)


# ======================================================================
# DASHBOARD
# ======================================================================
def render_dashboard():
    st.markdown("## 📈 Swing Trade Dashboard")
    st.caption("Mock veri ile çalışıyor — gerçek veriyi sonradan mock_data.py üzerinden bağla.")
    st.divider()

    # --- 1) MARKET (Bild 1 düzeni) ---
    st.markdown('<div class="section-title">Märkte</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Günlük performans</div>', unsafe_allow_html=True)

    cols = st.columns(4)
    for col, idx in zip(cols, md.get_index_summary()):
        with col:
            with st.container(border=True):
                sign = "▲" if idx["change_pct"] >= 0 else "▼"
                color = UP if idx["change_pct"] >= 0 else DOWN
                # Üst satır: ticker + alt başlık solda, fiyat + değişim sağda
                st.markdown(
                    f'<div class="idx-head">'
                    f'<div><div class="idx-tick">{idx["ticker"]}</div>'
                    f'<div class="idx-sub">{idx["subtitle"]}</div></div>'
                    f'<div style="text-align:right">'
                    f'<div class="idx-last">{idx["last"]:,.2f}</div>'
                    f'<div class="idx-chg" style="color:{color}">{sign} {idx["change_pct"]:+.2f}%</div>'
                    f'</div></div>',
                    unsafe_allow_html=True)
                # Grafik tam genişlikte, altta — artık metinle yarışmıyor
                st.plotly_chart(
                    mini_index_chart(idx["series"], idx["prev_close"], idx["change_pct"]),
                    use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # --- 2) FİLTREYE UYAN 20 ŞİRKET ---
    st.markdown('<div class="section-title">Filtrene Uyan Şirketler</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Bir şirkete tıkla → detay sayfası açılır (solda veri, sağda grafik)</div>',
                unsafe_allow_html=True)

    tickers = md.get_filtered_companies()
    PER_ROW = 4
    for i in range(0, len(tickers), PER_ROW):
        row = st.columns(PER_ROW)
        for col, ticker in zip(row, tickers[i:i + PER_ROW]):
            info = md.COMPANIES[ticker]
            with col:
                with st.container(border=True):
                    lc, nc = st.columns([1, 3])
                    with lc:
                        logo = md.logo_url(ticker)
                        if logo:
                            st.markdown(f'<img src="{logo}" class="firm-logo">', unsafe_allow_html=True)
                    with nc:
                        st.markdown(f'<div class="firm-name">{info["name"]}</div>'
                                    f'<div class="firm-tick">{ticker} · {info["sector"]}</div>',
                                    unsafe_allow_html=True)
                    if st.button("Detayı aç", key=f"btn_{ticker}"):
                        ss.selected = ticker
                        ss.view = "detail"
                        st.rerun()

    st.divider()

    # --- 3) TRADING STRATEGY PICKS ---
    st.markdown('<div class="section-title">Trading Strategy Picks</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Teknik analize göre seçilenler — EMA 20/50/100/200, ranked S/R, '
                'formasyon (trendline / bull flag / triangle)</div>', unsafe_allow_html=True)

    picks = md.get_strategy_picks()
    PICKS_PER_ROW = 2
    for i in range(0, len(picks), PICKS_PER_ROW):
        row = st.columns(PICKS_PER_ROW, gap="large")
        for col, pick in zip(row, picks[i:i + PICKS_PER_ROW]):
            with col:
                df = _ohlc(pick["ticker"])
                st.plotly_chart(
                    ta_chart(df, f"{pick['ticker']} — {pick['setup']}", height=460,
                             show_sr=True, show_formation=True, formation_type=pick["formation"]),
                    use_container_width=True)
                # Trade-Aspekte
                d = st.columns(3)
                with d[0]:
                    kv_block("Avg Volume (20)", f"{pick['avg_volume']:,}")
                    kv_block("Rel Volume", f"{pick['rel_volume']}x")
                with d[1]:
                    kv_block("Buy Zone", f"${pick['buy_zone'][0]} – ${pick['buy_zone'][1]}")
                    kv_block("Formation", pick["formation"])
                with d[2]:
                    kv_block("Stop / Target", f"${pick['stop']} → ${pick['target']}")
                    kv_block("Risk/Reward", f"{pick['rr']} : 1")
                # Kısa açıklama metni (Trade-Aspekte altında)
                st.markdown(f'<div class="pick-note">💡 {pick["note"]}</div>', unsafe_allow_html=True)

    st.divider()

    # --- 4) LONG-TERM UCUZ ŞİRKETLER ---
    st.markdown('<div class="section-title">Long-Term — Ucuz Şirketler</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Forward PE\'ye göre sıralı (ucuzdan pahalıya)</div>',
                unsafe_allow_html=True)

    value_df = md.get_value_stocks()
    st.dataframe(
        value_df, use_container_width=True, hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "PEG": st.column_config.NumberColumn("PEG", format="%.2f"),
            "Forward PE": st.column_config.NumberColumn("Forward PE", format="%.1f"),
            "Profit Margin %": st.column_config.NumberColumn("Profit M %", format="%.1f%%"),
            "EPS Next 5Y %": st.column_config.NumberColumn("EPS Next 5Y %", format="%.1f%%"),
        },
    )


# ======================================================================
# ROUTER
# ======================================================================
if ss.view == "detail" and ss.selected:
    render_detail(ss.selected)
elif ss.view == "fullchart" and ss.selected:
    render_fullchart(ss.selected)
else:
    render_dashboard()
