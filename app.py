"""
========================================================================
 SWING TRADE DASHBOARD  (app.py)
========================================================================
Koyu temalı tek sayfa Streamlit arayüzü. Tüm veri mock_data.py'den gelir.

Çalıştırmak için:
    pip install -r requirements.txt
    streamlit run app.py

Bölümler (yukarıdan aşağı):
    1) Endeks özeti (S&P 500 / Nasdaq / Dow Jones) + mini grafikler
    2) Filtrene uyan 20 şirket — logo + isim, tıkla -> detay grafik & bilgi
    3) Trading Strategy Picks — EMA + S/R + formasyon + seviyeler
    4) Long-term ucuz şirketler tablosu
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

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1500px; }
      h1, h2, h3 { letter-spacing: .3px; }
      .section-title { font-size: 1.35rem; font-weight: 700; margin: .4rem 0 .2rem 0; }
      .section-sub { color: #8b949e; font-size: .85rem; margin-bottom: .8rem; }
      /* Şirket kartı */
      .firm-card {
        display:flex; align-items:center; gap:.6rem;
        background:#161b22; border:1px solid #30363d; border-radius:10px;
        padding:.5rem .7rem; margin-bottom:.15rem;
      }
      .firm-logo { width:34px; height:34px; border-radius:7px; background:#fff;
                   object-fit:contain; padding:2px; }
      .firm-name { font-weight:600; font-size:.95rem; }
      .firm-tick { color:#8b949e; font-size:.75rem; }
      div[data-testid="stHorizontalBlock"] { align-items:center; }
      /* Küçük "aç" butonları */
      .stButton button { width:100%; border-radius:8px; border:1px solid #30363d;
                         background:#1f2630; color:#e6edf3; font-size:.8rem; }
      .stButton button:hover { border-color:#f6c177; color:#f6c177; }
      .kv { background:#161b22; border:1px solid #30363d; border-radius:10px;
            padding:.6rem .8rem; margin-bottom:.4rem; }
      .kv .k { color:#8b949e; font-size:.72rem; text-transform:uppercase; }
      .kv .v { font-size:1.05rem; font-weight:700; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "selected" not in st.session_state:
    st.session_state.selected = None


# ----------------------------------------------------------------------
# Yardımcı grafik fonksiyonları
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _ohlc(ticker):
    return md.add_emas(md.get_ohlc(ticker))


def mini_index_chart(series, change_pct):
    color = UP if change_pct >= 0 else DOWN
    fig = go.Figure(go.Scatter(y=series, mode="lines",
                               line=dict(color=color, width=2),
                               fill="tozeroy",
                               fillcolor=f"rgba({'63,185,80' if change_pct>=0 else '248,81,73'},0.12)"))
    fig.update_layout(template="plotly_dark", height=70, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def ta_chart(df, title, height=560, show_sr=False, show_formation=False,
             formation_type="Trendline"):
    """Candlestick + EMA20/50/100/200 + hacim; opsiyonel S/R ve formasyon."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.76, 0.24], vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=UP, decreasing_line_color=DOWN, name="Price"),
        row=1, col=1)

    for p, color in EMA_COLORS.items():
        fig.add_trace(go.Scatter(x=df.index, y=df[f"EMA{p}"], mode="lines",
                                 line=dict(color=color, width=1.3), name=f"EMA{p}"),
                      row=1, col=1)

    # Ranked S/R zones
    if show_sr:
        for z in md.get_sr_zones(df):
            op = 0.22 if z["rank"] == 1 else (0.14 if z["rank"] == 2 else 0.08)
            fig.add_hrect(y0=z["low"], y1=z["high"], line_width=0,
                          fillcolor=f"rgba(246,193,119,{op})", row=1, col=1)
            fig.add_annotation(x=df.index[2], y=z["high"], text=f"S/R #{z['rank']}",
                               showarrow=False, font=dict(size=9, color="#f6c177"),
                               xanchor="left", row=1, col=1)

    # Formasyon çizgileri
    if show_formation:
        form = md.get_formation(df, formation_type)
        for (x0, y0), (x1, y1) in form["lines"]:
            fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                          line=dict(color="#58a6ff", width=1.6, dash="dot"),
                          row=1, col=1)
        fig.add_annotation(x=df.index[-1], y=df["High"].max(), text=f"📐 {form['type']}",
                           showarrow=False, font=dict(size=11, color="#58a6ff"),
                           xanchor="right", row=1, col=1)

    # Hacim
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


# ======================================================================
# BAŞLIK
# ======================================================================
st.markdown("## 📈 Swing Trade Dashboard")
st.caption("Mock veri ile çalışıyor — gerçek veriyi sonradan mock_data.py üzerinden bağla.")
st.divider()


# ======================================================================
# 1) ENDEKS ÖZETİ
# ======================================================================
st.markdown('<div class="section-title">Piyasa Özeti</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Günlük performans</div>', unsafe_allow_html=True)

cols = st.columns(3)
for col, idx in zip(cols, md.get_index_summary()):
    with col:
        sign = "▲" if idx["change_pct"] >= 0 else "▼"
        color = UP if idx["change_pct"] >= 0 else DOWN
        st.markdown(
            f"<div style='font-size:1.0rem;font-weight:700'>{idx['name']}</div>"
            f"<div style='font-size:1.5rem;font-weight:800'>{idx['last']:,.2f}</div>"
            f"<div style='color:{color};font-weight:700'>{sign} {idx['change_pct']:+.2f}%</div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(mini_index_chart(idx["series"], idx["change_pct"]),
                        use_container_width=True, config={"displayModeBar": False})

st.divider()


# ======================================================================
# 2) FİLTREYE UYAN 20 ŞİRKET
# ======================================================================
st.markdown('<div class="section-title">Filtrene Uyan Şirketler</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Bugün filtreye uyan 20 şirket — birine tıkla, detayı aşağıda açılır</div>',
            unsafe_allow_html=True)

tickers = md.get_filtered_companies()
PER_ROW = 4
for i in range(0, len(tickers), PER_ROW):
    row = st.columns(PER_ROW)
    for col, ticker in zip(row, tickers[i:i + PER_ROW]):
        info = md.COMPANIES[ticker]
        with col:
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
                st.session_state.selected = ticker

# --- Seçilen şirketin detay paneli ---
sel = st.session_state.selected
if sel:
    st.markdown("---")
    info = md.COMPANIES[sel]
    head = st.columns([6, 1])
    with head[0]:
        st.markdown(f"### {info['name']}  ·  {sel}")
        st.caption(f"{info['sector']} — grafiğin sağ üstündeki ⛶ ikonu ile tam ekran yapabilirsin")
    with head[1]:
        if st.button("✕ Kapat"):
            st.session_state.selected = None
            st.rerun()

    df = _ohlc(sel)
    st.plotly_chart(ta_chart(df, f"{sel} — Günlük", height=620, show_sr=True),
                    use_container_width=True)

    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    chg = (last / prev - 1) * 100
    hi52, lo52 = float(df["High"].max()), float(df["Low"].min())
    m = st.columns(5)
    with m[0]: kv_block("Last", f"${last:,.2f}")
    with m[1]: kv_block("Günlük", f"{chg:+.2f}%")
    with m[2]: kv_block("52h Yüksek", f"${hi52:,.2f}")
    with m[3]: kv_block("52h Düşük", f"${lo52:,.2f}")
    with m[4]: kv_block("Hacim (son)", f"{int(df['Volume'].iloc[-1]):,}")

st.divider()


# ======================================================================
# 3) TRADING STRATEGY PICKS
# ======================================================================
st.markdown('<div class="section-title">Trading Strategy Picks</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Teknik analize göre seçilenler — EMA 20/50/100/200, ranked S/R, '
            'formasyon (trendline / bull flag / triangle)</div>', unsafe_allow_html=True)

picks = md.get_strategy_picks()
PICKS_PER_ROW = 2  # yan yana 2 pick ("sağa scroll" hissi); tek sütun istersen 1 yap
for i in range(0, len(picks), PICKS_PER_ROW):
    row = st.columns(PICKS_PER_ROW, gap="large")
    for col, pick in zip(row, picks[i:i + PICKS_PER_ROW]):
        with col:
            df = _ohlc(pick["ticker"])
            st.plotly_chart(
                ta_chart(df, f"{pick['ticker']} — {pick['setup']}", height=480,
                         show_sr=True, show_formation=True, formation_type=pick["formation"]),
                use_container_width=True,
            )
            # Altındaki data bloğu: volume, technical levels, exit/buy levels
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

st.divider()


# ======================================================================
# 4) LONG-TERM UCUZ ŞİRKETLER
# ======================================================================
st.markdown('<div class="section-title">Long-Term — Ucuz Şirketler</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Forward PE\'ye göre sıralı (ucuzdan pahalıya)</div>',
            unsafe_allow_html=True)

value_df = md.get_value_stocks()
st.dataframe(
    value_df,
    use_container_width=True, hide_index=True,
    column_config={
        "Ticker": st.column_config.TextColumn("Ticker", width="small"),
        "PEG": st.column_config.NumberColumn("PEG", format="%.2f"),
        "Forward PE": st.column_config.NumberColumn("Forward PE", format="%.1f"),
        "Profit Margin %": st.column_config.NumberColumn("Profit M %", format="%.1f%%"),
        "EPS Next 5Y %": st.column_config.NumberColumn("EPS Next 5Y %", format="%.1f%%"),
    },
)
