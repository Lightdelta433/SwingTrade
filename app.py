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
      /* Üstten bol boşluk — Streamlit'in kendi üst çubuğu içeriği kırpmasın */
      .block-container { padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1500px; }
      h1, h2, h3 { letter-spacing: .3px; }
      .section-title { font-size: 1.35rem; font-weight: 700; margin: 1.1rem 0 .3rem 0; }
      .section-sub { color: #8b949e; font-size: .85rem; margin-bottom: 1.1rem; }
      /* Detay/Full-chart üst barı: normal akışta, altına ayraç + boşluk */
      .st-key-detail_topbar, .st-key-fullchart_topbar, .st-key-watchlist_topbar {
        padding: .3rem 0 .9rem 0; border-bottom: 1px solid #30363d; margin-bottom: 1.1rem;
      }
      /* Markt-Kartenkopf — iki blok dikeyde, üst üste binmeyi tamamen önler */
      .idx-head { margin-bottom:.5rem; }
      .idx-tick { font-size: 1.1rem; font-weight: 800; line-height: 1.25; }
      .idx-sub  { color: #8b949e; font-size: .72rem; line-height:1.3; margin-bottom:.35rem; }
      .idx-last { font-size: 1.0rem; font-weight: 700; line-height:1.3; display:inline; }
      .idx-chg  { font-weight:700; font-size:.82rem; display:inline; margin-left:.4rem; }
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
            padding:.6rem .8rem; margin-bottom:.6rem; }
      .kv .k { color:#8b949e; font-size:.70rem; text-transform:uppercase; }
      .kv .v { font-size:1.02rem; font-weight:700; margin-top:.15rem; }
      /* Detay sayfası stat satırları (Bild 2 benzeri) */
      .stat-row { display:flex; justify-content:space-between; align-items:baseline;
                  gap:.8rem; padding:.6rem .3rem; border-bottom:1px solid #21262d;
                  font-size:.9rem; line-height:1.35; }
      .stat-row .lbl { color:#8b949e; flex:0 0 auto; }
      .stat-row .val { font-weight:600; text-align:right; }
      .pick-note { background:#12171f; border-left:3px solid #58a6ff; border-radius:6px;
                   padding:.65rem .85rem; color:#b9c2cc; font-size:.82rem;
                   line-height:1.5; margin-top:.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Görünüm (view) state ---
ss = st.session_state
ss.setdefault("view", "dashboard")
ss.setdefault("selected", None)
ss.setdefault("tf", "6M")
ss.setdefault("section", "Watchlist")   # varsayılan açılış bölümü
# Watchlist boş başlamasın: ilk açılışta örnek 10 şirketle dolu gelsin
ss.setdefault("watchlist", list(md.DEFAULT_WATCHLIST))


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

    # Başlık artık plotly içinde değil (legend ile çakışıyordu); çağıran taraf
    # markdown ile başlık yazıyor. Legend grafiğin üstünde tek başına duruyor.
    fig.update_layout(
        template="plotly_dark", height=height,
        margin=dict(l=10, r=10, t=34, b=10), showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=10)),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(gridcolor="#21262d")
    fig.update_yaxes(gridcolor="#21262d")
    return fig


# Grafik toolbar'ı HEP görünür (zoom, pan, autoscale, reset her zaman ekranda)
CHART_CONFIG = {
    "displayModeBar": True, "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}


def chart_title(text):
    st.markdown(f'<div style="font-weight:700;font-size:1rem;margin:.2rem 0 .1rem 0">'
                f'{text}</div>', unsafe_allow_html=True)


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

    # Üst bar — normal akışta, üstten bol boşlukla tam görünür
    with st.container(key="detail_topbar"):
        top = st.columns([0.8, 4.4, 1.4, 1.6])
        with top[0]:
            if st.button("← Geri", key="back"):
                ss.view = "dashboard"
                st.rerun()
        with top[1]:
            logo_html = f'<img src="{logo}" class="firm-logo" style="width:34px;height:34px">' if logo else ""
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:.6rem">{logo_html}'
                f'<div><div style="font-size:1.25rem;font-weight:800;line-height:1.15">{d["name"]}</div>'
                f'<div style="color:#8b949e;font-size:.78rem">{ticker} · {d["sector"]} · USD</div></div></div>',
                unsafe_allow_html=True)
        with top[2]:
            if st.button("⛶ Full Chart", key="fc_btn"):
                ss.view = "fullchart"
                st.rerun()
        with top[3]:
            in_wl = ticker in ss.watchlist
            label = "★ Listede" if in_wl else "☆ Watchlist"
            if st.button(label, key="wl_btn"):
                if in_wl:
                    ss.watchlist.remove(ticker)
                else:
                    ss.watchlist.append(ticker)
                st.rerun()

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
        st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)
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
                        use_container_width=True, config=CHART_CONFIG)
        st.caption("Grafiğe tam ekran bakmak için üstteki **⛶ Full Chart** butonuna bas. "
                   "Grafiğin sağ üstündeki araç çubuğundan zoom / autoscale yapabilirsin.")

    st.divider()
    render_news(ticker)


# ======================================================================
# TAM EKRAN GRAFİK SAYFASI ("Full Chart" butonuna basınca)
# ======================================================================
def render_fullchart(ticker):
    info = md.COMPANIES[ticker]
    with st.container(key="fullchart_topbar"):
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
    chart_title(f"{ticker} — {tf}")
    st.plotly_chart(ta_chart(df, "", height=680, show_sr=True),
                    use_container_width=True, config=CHART_CONFIG)

    st.divider()
    render_news(ticker)


# ======================================================================
# ORTAK PARÇALAR
# ======================================================================
def open_detail(ticker):
    ss.selected = ticker
    ss.view = "detail"
    st.rerun()


def company_grid(tickers, key_prefix, show_price=False, removable=False):
    """Şirket kartları ızgarası — her kart tıklanabilir, detay sayfasını açar."""
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
                        if show_price:
                            q = md.get_quote(ticker)
                            c = UP if q["change_pct"] >= 0 else DOWN
                            sub = (f'{ticker} · <span style="color:{c}">${q["last"]:,.2f} '
                                   f'({q["change_pct"]:+.2f}%)</span>')
                        else:
                            sub = f'{ticker} · {info["sector"]}'
                        st.markdown(f'<div class="firm-name">{info["name"]}</div>'
                                    f'<div class="firm-tick">{sub}</div>', unsafe_allow_html=True)
                    if removable:
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("Aç", key=f"{key_prefix}open_{ticker}"):
                                open_detail(ticker)
                        with b2:
                            if st.button("Çıkar", key=f"{key_prefix}rm_{ticker}"):
                                ss.watchlist.remove(ticker)
                                st.rerun()
                    else:
                        if st.button("Detayı aç", key=f"{key_prefix}_{ticker}"):
                            open_detail(ticker)


def movers_list(items, title, color):
    st.markdown(f'<div style="font-weight:700;margin-bottom:.3rem">{title}</div>',
                unsafe_allow_html=True)
    for q in items:
        c = UP if q["change_pct"] >= 0 else DOWN
        st.markdown(
            f'<div class="news-item">'
            f'<div class="news-title"><b>{q["ticker"]}</b> '
            f'<span style="color:#8b949e;font-size:.8rem">{q["name"]}</span></div>'
            f'<div class="news-meta" style="color:{c};font-weight:700">'
            f'${q["last"]:,.2f} &nbsp; {q["change_pct"]:+.2f}%</div>'
            f'</div>', unsafe_allow_html=True)


def news_list(items, with_ticker=False):
    sent = {"Positive": UP, "Negative": DOWN, "Neutral": "#8b949e"}
    for item in items:
        dot = sent.get(item.get("sentiment", "Neutral"), "#8b949e")
        tag = f'<b style="color:#e6edf3">{item["ticker"]}</b>&nbsp; ' if with_ticker else ""
        st.markdown(
            f'<div class="news-item">'
            f'<div class="news-title"><span class="news-dot" style="background:{dot}"></span>'
            f'{tag}{item["title"]}</div>'
            f'<div class="news-meta">{item["source"]} · {item["when"]}</div>'
            f'</div>', unsafe_allow_html=True)


# ======================================================================
# FEAR & GREED göstergesi (Long Term)
# ======================================================================
def fear_greed_gauge(value):
    steps = [
        {"range": [0, 25],   "color": "#f85149"},   # Extreme Fear
        {"range": [25, 45],  "color": "#f0883e"},   # Fear
        {"range": [45, 55],  "color": "#d9c441"},   # Neutral
        {"range": [55, 75],  "color": "#56b06a"},   # Greed
        {"range": [75, 100], "color": "#3fb950"},   # Extreme Greed
    ]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"font": {"size": 46, "color": "#e6edf3"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#8b949e",
                     "tickvals": [0, 25, 50, 75, 100]},
            "bar": {"color": "rgba(0,0,0,0)"},
            "borderwidth": 0,
            "steps": steps,
            "threshold": {"line": {"color": "#e6edf3", "width": 5}, "thickness": 0.85,
                          "value": value},
        },
    ))
    fig.update_layout(height=260, margin=dict(l=20, r=20, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": "#e6edf3"})
    return fig


# ======================================================================
# BÖLÜM: WATCHLIST (varsayılan açılış)
# ======================================================================
def render_sec_watchlist():
    # İzlenen şirketler + ekle/çıkar
    head = st.columns([5, 1])
    with head[0]:
        st.markdown('<div class="section-title">İzlenen Şirketler</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">Günlük performanslarıyla izleme listen — '
                    'karttan aç ya da çıkar</div>', unsafe_allow_html=True)
    if ss.watchlist:
        company_grid(list(ss.watchlist), "wl", show_price=True, removable=True)
    else:
        st.info("İzleme listen boş. Bir şirketin detayını aç ve **☆ Watchlist** ile ekle.")

    # Top movers / losers
    st.divider()
    st.markdown('<div class="section-title">Top Movers & Losers</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Bugün en çok yükselen ve düşen şirketler</div>',
                unsafe_allow_html=True)
    mcol = st.columns(2, gap="large")
    with mcol[0]:
        movers_list(md.get_top_movers(), "📈 Top Movers", UP)
    with mcol[1]:
        movers_list(md.get_top_losers(), "📉 Top Losers", DOWN)

    # Upcoming IPOs
    st.divider()
    st.markdown('<div class="section-title">Yaklaşan Halka Arzlar (IPO)</div>', unsafe_allow_html=True)
    st.dataframe(md.get_upcoming_ipos(), use_container_width=True, hide_index=True,
                 column_config={"Shares (M)": st.column_config.NumberColumn("Shares (M)", format="%.1f")})

    # Watchlist haberleri
    if ss.watchlist:
        st.divider()
        st.markdown('<div class="section-title">Watchlist Haberleri</div>', unsafe_allow_html=True)
        news_list(md.get_watchlist_news(list(ss.watchlist)), with_ticker=True)


# ======================================================================
# BÖLÜM: LONG TERM
# ======================================================================
def render_sec_longterm():
    fg = md.get_fear_greed()
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown('<div class="section-title">Fear & Greed Index</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">Piyasayı şu an hangi duygu yönetiyor?</div>',
                    unsafe_allow_html=True)
        st.plotly_chart(fear_greed_gauge(fg["value"]),
                        use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            f'<div style="text-align:center;font-size:1.1rem;font-weight:700;margin-top:-.5rem">'
            f'{fg["label"]}</div>'
            f'<div style="background:#12171f;border-left:3px solid #f6c177;border-radius:6px;'
            f'padding:.7rem .9rem;margin-top:.8rem;color:#c9d1d9;font-style:italic">'
            f'"{fg["quote"]}"<br><span style="color:#8b949e;font-style:normal;font-size:.82rem">'
            f'— {fg["quote_author"]}</span></div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="section-title">Geçmiş</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">&nbsp;</div>', unsafe_allow_html=True)
        for h in fg["history"]:
            hc = DOWN if h["value"] < 45 else ("#d9c441" if h["value"] < 55 else UP)
            st.markdown(
                f'<div class="stat-row"><span class="lbl">{h["when"]}<br>'
                f'<b style="color:#e6edf3">{h["label"]}</b></span>'
                f'<span class="val" style="font-size:1.3rem;color:{hc}">{h["value"]}</span></div>',
                unsafe_allow_html=True)

    # Endeks / sektör sıralaması
    st.divider()
    st.markdown('<div class="section-title">Sektör Sıralaması</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Büyüme ve kâr marjına göre skorlanıp sıralandı '
                '(Score = Büyüme×0.6 + Marj×0.4)</div>', unsafe_allow_html=True)
    st.dataframe(
        md.get_index_rankings(), use_container_width=True, hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn("#", width="small"),
            "Growth %": st.column_config.NumberColumn("Growth %", format="%.1f%%"),
            "Profit Margin %": st.column_config.NumberColumn("Profit Margin %", format="%.1f%%"),
            "Score": st.column_config.ProgressColumn("Score", format="%.1f",
                                                     min_value=0, max_value=30),
        })

    # PEG / ucuz şirketler
    st.divider()
    st.markdown('<div class="section-title">Ucuz Şirketler (PEG / Forward PE)</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Forward PE\'ye göre sıralı (ucuzdan pahalıya)</div>',
                unsafe_allow_html=True)
    st.dataframe(
        md.get_value_stocks(), use_container_width=True, hide_index=True,
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
def render_sec_short():
    st.markdown('<div class="section-title">Filtrene Uyan Şirketler</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Bir şirkete tıkla → detay sayfası açılır</div>',
                unsafe_allow_html=True)
    company_grid(md.get_filtered_companies(), "flt")

    st.divider()
    st.markdown('<div class="section-title">Trading Strategy Picks</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">EMA 20/50/100/200, ranked S/R, formasyon '
                '(trendline / bull flag / triangle)</div>', unsafe_allow_html=True)

    picks = md.get_strategy_picks()
    PICKS_PER_ROW = 2
    for i in range(0, len(picks), PICKS_PER_ROW):
        row = st.columns(PICKS_PER_ROW, gap="large")
        for col, pick in zip(row, picks[i:i + PICKS_PER_ROW]):
            with col:
                df = _ohlc(pick["ticker"])
                chart_title(f"{pick['ticker']} — {pick['setup']}")   # başlık dışarıda → çakışma yok
                st.plotly_chart(
                    ta_chart(df, "", height=460, show_sr=True,
                             show_formation=True, formation_type=pick["formation"]),
                    use_container_width=True, config=CHART_CONFIG)
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
                st.markdown(f'<div class="pick-note">💡 {pick["note"]}</div>', unsafe_allow_html=True)


# ======================================================================
# BÖLÜM: FOREX & NEWS
# ======================================================================
def render_sec_forex():
    # Forex kur şeridi
    st.markdown('<div class="section-title">Forex</div>', unsafe_allow_html=True)
    fx_cols = st.columns(6)
    for col, fx in zip(fx_cols, md.get_forex_rates()):
        c = UP if fx["change_pct"] >= 0 else DOWN
        with col:
            with st.container(border=True):
                st.markdown(
                    f'<div style="font-weight:700">{fx["pair"]}</div>'
                    f'<div style="font-size:1.1rem;font-weight:700">{fx["rate"]:.4f}</div>'
                    f'<div style="color:{c};font-weight:700;font-size:.82rem">'
                    f'{fx["change_pct"]:+.2f}%</div>', unsafe_allow_html=True)

    # Ekonomik takvim
    st.divider()
    st.markdown('<div class="section-title">Ekonomik Takvim</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Yaklaşan makro veri ve açıklamalar</div>',
                unsafe_allow_html=True)
    cal = md.get_economic_calendar()
    st.dataframe(cal, use_container_width=True, hide_index=True)

    # Haber kategorileri
    st.divider()
    ncols = st.columns(3, gap="large")
    cats = [("war_politics", "⚔️ Savaş & Politika"),
            ("markets", "📰 Borsa Haberleri"),
            ("index", "🤖 Endeks Bazında (AI, Yarı İletken…)")]
    for col, (cat, title) in zip(ncols, cats):
        with col:
            st.markdown(f'<div class="section-title" style="font-size:1.05rem">{title}</div>',
                        unsafe_allow_html=True)
            news_list(md.get_market_news(cat))


# ======================================================================
# DASHBOARD — market kartları (hep üstte) + bölüm navigasyonu
# ======================================================================
def render_market_header():
    st.markdown("## 📈 Swing Trade Dashboard")
    st.markdown('<div class="section-title" style="margin-top:.3rem">Märkte</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Günlük performans — bir endekse tıkla, detayını aç</div>',
                unsafe_allow_html=True)
    cols = st.columns(4)
    for col, idx in zip(cols, md.get_index_summary()):
        with col:
            with st.container(border=True):
                sign = "▲" if idx["change_pct"] >= 0 else "▼"
                color = UP if idx["change_pct"] >= 0 else DOWN
                st.markdown(
                    f'<div class="idx-head">'
                    f'<div class="idx-tick">{idx["ticker"]}</div>'
                    f'<div class="idx-sub">{idx["subtitle"]}</div>'
                    f'<div><span class="idx-last">{idx["last"]:,.2f}</span>'
                    f'<span class="idx-chg" style="color:{color}">{sign} {idx["change_pct"]:+.2f}%</span></div>'
                    f'</div>', unsafe_allow_html=True)
                st.plotly_chart(
                    mini_index_chart(idx["series"], idx["prev_close"], idx["change_pct"]),
                    use_container_width=True, config={"displayModeBar": False})
                if st.button("Detayları gör", key=f"idx_{idx['ticker']}"):
                    open_detail(idx["ticker"])


def render_dashboard():
    render_market_header()
    st.divider()

    # Bölüm navigasyonu — market kartlarının altında
    sections = ["Watchlist", "Long Term", "Short Term & Swings", "Forex & News"]
    sec = st.radio("Bölüm", sections, index=sections.index(ss.section),
                   horizontal=True, key="nav", label_visibility="collapsed")
    ss.section = sec
    st.divider()

    if sec == "Watchlist":
        render_sec_watchlist()
    elif sec == "Long Term":
        render_sec_longterm()
    elif sec == "Short Term & Swings":
        render_sec_short()
    else:
        render_sec_forex()


# ======================================================================
# ROUTER
# ======================================================================
if ss.view == "detail" and ss.selected:
    render_detail(ss.selected)
elif ss.view == "fullchart" and ss.selected:
    render_fullchart(ss.selected)
else:
    render_dashboard()
