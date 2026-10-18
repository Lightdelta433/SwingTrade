import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# ---------- Sayfa ayarlari ----------
st.set_page_config(page_title="Swing Trade Bot", page_icon="", layout="wide")

# ---------- Koyu tema icin CSS ----------
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .card {
        background-color: #1a1d26;
        border-radius: 14px;
        padding: 16px 18px;
        border: 1px solid #2a2e3a;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 16px;
    }
    .logo {
        width: 46px; height: 46px; border-radius: 10px;
        background:#ffffff; object-fit: contain; padding: 4px; flex-shrink:0;
    }
    .badge-flag { background:#3b82f6; color:white; padding:3px 10px; border-radius:20px; font-size:12px; }
    .badge-cons { background:#a855f7; color:white; padding:3px 10px; border-radius:20px; font-size:12px; }
    .sym { font-size:20px; font-weight:700; color:#fafafa; }
    .cname { font-size:13px; color:#9ca3af; }
    .up { color:#22c55e; font-weight:600; }
    .down { color:#ef4444; font-weight:600; }
    .label { color:#9ca3af; font-size:12px; }
    .value { color:#e5e7eb; font-size:15px; font-weight:600; }
    .num { color:#e5e7eb; font-size:16px; font-weight:600; margin-left:auto; text-align:right; }
</style>
""", unsafe_allow_html=True)

# ---------- Ornek (mock) 20 sirket verisi ----------
signals = [
    {"symbol": "NVDA",  "name": "NVIDIA Corp.",        "domain": "nvidia.com",     "price": 128.4, "chg": 3.2, "setup": "Bull Flag",     "breakout": 128.9, "stop": 122.1, "shares": 40},
    {"symbol": "AMD",   "name": "Advanced Micro Dev.", "domain": "amd.com",        "price": 168.7, "chg": 1.8, "setup": "Consolidation", "breakout": 169.5, "stop": 163.0, "shares": 30},
    {"symbol": "PLTR",  "name": "Palantir Tech.",      "domain": "palantir.com",   "price": 41.2,  "chg": 4.1, "setup": "Bull Flag",     "breakout": 41.6,  "stop": 39.0,  "shares": 120},
    {"symbol": "TSLA",  "name": "Tesla Inc.",          "domain": "tesla.com",      "price": 248.5, "chg": 2.6, "setup": "Bull Flag",     "breakout": 250.0, "stop": 240.0, "shares": 20},
    {"symbol": "AAPL",  "name": "Apple Inc.",          "domain": "apple.com",      "price": 227.3, "chg": 0.9, "setup": "Consolidation", "breakout": 229.0, "stop": 222.0, "shares": 22},
    {"symbol": "META",  "name": "Meta Platforms",      "domain": "meta.com",       "price": 512.1, "chg": 1.4, "setup": "Bull Flag",     "breakout": 515.0, "stop": 500.0, "shares": 10},
    {"symbol": "AMZN",  "name": "Amazon.com Inc.",     "domain": "amazon.com",     "price": 186.4, "chg": 2.1, "setup": "Consolidation", "breakout": 188.0, "stop": 181.0, "shares": 27},
    {"symbol": "GOOGL", "name": "Alphabet Inc.",       "domain": "abc.xyz",        "price": 165.2, "chg": 1.2, "setup": "Bull Flag",     "breakout": 167.0, "stop": 160.0, "shares": 30},
    {"symbol": "MSFT",  "name": "Microsoft Corp.",     "domain": "microsoft.com",  "price": 420.8, "chg": 0.7, "setup": "Consolidation", "breakout": 424.0, "stop": 412.0, "shares": 12},
    {"symbol": "NFLX",  "name": "Netflix Inc.",        "domain": "netflix.com",    "price": 685.0, "chg": 2.9, "setup": "Bull Flag",     "breakout": 690.0, "stop": 665.0, "shares": 7},
    {"symbol": "AVGO",  "name": "Broadcom Inc.",       "domain": "broadcom.com",   "price": 168.9, "chg": 3.5, "setup": "Bull Flag",     "breakout": 170.0, "stop": 162.0, "shares": 29},
    {"symbol": "COIN",  "name": "Coinbase Global",     "domain": "coinbase.com",   "price": 215.6, "chg": 5.2, "setup": "Bull Flag",     "breakout": 218.0, "stop": 205.0, "shares": 23},
    {"symbol": "SHOP",  "name": "Shopify Inc.",        "domain": "shopify.com",    "price": 78.4,  "chg": 2.3, "setup": "Consolidation", "breakout": 79.5,  "stop": 75.0,  "shares": 63},
    {"symbol": "SMCI",  "name": "Super Micro Comp.",   "domain": "supermicro.com", "price": 45.1,  "chg": 6.1, "setup": "Bull Flag",     "breakout": 46.0,  "stop": 42.0,  "shares": 110},
    {"symbol": "CRWD",  "name": "CrowdStrike Hldgs.",  "domain": "crowdstrike.com","price": 288.7, "chg": 1.9, "setup": "Consolidation", "breakout": 292.0, "stop": 278.0, "shares": 17},
    {"symbol": "UBER",  "name": "Uber Technologies",   "domain": "uber.com",       "price": 72.3,  "chg": 2.4, "setup": "Bull Flag",     "breakout": 73.5,  "stop": 69.0,  "shares": 68},
    {"symbol": "SNOW",  "name": "Snowflake Inc.",      "domain": "snowflake.com",  "price": 118.2, "chg": 3.0, "setup": "Bull Flag",     "breakout": 120.0, "stop": 113.0, "shares": 42},
    {"symbol": "MU",    "name": "Micron Technology",   "domain": "micron.com",     "price": 102.5, "chg": 2.7, "setup": "Consolidation", "breakout": 104.0, "stop": 98.0,  "shares": 48},
    {"symbol": "MRVL",  "name": "Marvell Tech.",       "domain": "marvell.com",    "price": 74.8,  "chg": 3.8, "setup": "Bull Flag",     "breakout": 76.0,  "stop": 71.0,  "shares": 66},
    {"symbol": "DDOG",  "name": "Datadog Inc.",        "domain": "datadoghq.com",  "price": 121.4, "chg": 1.6, "setup": "Consolidation", "breakout": 123.0, "stop": 116.0, "shares": 41},
]


def mini_chart(sym, breakout):
    n = 30
    base = np.linspace(100, 110, n) + np.random.randn(n)
    o, c = base, base + np.random.randn(n)
    fig = go.Figure(go.Candlestick(
        x=list(range(n)), open=o, high=np.maximum(o, c) + 1,
        low=np.minimum(o, c) - 1, close=c,
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444"))
    fig.add_hline(y=base[-1] + 2, line_dash="dash", line_color="#fbbf24",
                  annotation_text="Kirilim", annotation_font_color="#fbbf24")
    fig.update_layout(height=150, margin=dict(l=0, r=0, t=0, b=0),
                      paper_bgcolor="#1a1d26", plot_bgcolor="#1a1d26",
                      xaxis_rangeslider_visible=False,
                      xaxis=dict(showgrid=False, showticklabels=False),
                      yaxis=dict(showgrid=False, showticklabels=False))
    return fig


# ---------- UST BAR ----------
st.title("Swing Trade Bot")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Piyasa Rejimi", "Risk-On")
c2.metric("Bulunan Sinyal", len(signals))
c3.metric("Acik Pozisyon", 2)
c4.metric("Son Tarama", datetime.now().strftime("%H:%M EST"))
st.button("Simdi Tara", type="primary")
st.divider()

# ---------- SEKMELER ----------
tab1, tab2, tab3 = st.tabs(["Sinyaller", "Acik Pozisyonlar", "Gecmis"])

with tab1:
    st.caption(f"Filtrelere uygun {len(signals)} hisse (asagiya dogru listelenmistir)")
    for i, s in enumerate(signals):
        badge = "badge-flag" if s["setup"] == "Bull Flag" else "badge-cons"
        emoji = "[Flag]" if s["setup"] == "Bull Flag" else "[Cons]"
        chg_cls = "up" if s["chg"] >= 0 else "down"
        logo_url = f"https://logo.clearbit.com/{s['domain']}"
        st.markdown(f"""
        <div class="card">
          <img class="logo" src="{logo_url}" onerror="this.style.visibility='hidden'"/>
          <div>
            <span class="sym">{s['symbol']}</span>
            &nbsp;<span class="{badge}">{emoji} {s['setup']}</span><br>
            <span class="cname">{s['name']}</span>
          </div>
          <div class="num">
            ${s['price']} <span class="{chg_cls}">({s['chg']:+.1f}%)</span>
          </div>
        </div>
        """, unsafe_allow_html=True)
        cc1, cc2 = st.columns([3, 2])
        with cc1:
            st.plotly_chart(mini_chart(s["symbol"], s["breakout"]),
                            use_container_width=True, key=f"ch{i}")
        with cc2:
            a, b, c = st.columns(3)
            a.markdown(f"<span class='label'>Kirilim</span><br><span class='value'>${s['breakout']}</span>", unsafe_allow_html=True)
            b.markdown(f"<span class='label'>Stop</span><br><span class='value'>${s['stop']}</span>", unsafe_allow_html=True)
            c.markdown(f"<span class='label'>Adet</span><br><span class='value'>{s['shares']}</span>", unsafe_allow_html=True)
            x, y = st.columns(2)
            x.button("Aldim", key=f"buy{i}", use_container_width=True)
            y.button("Gec", key=f"skip{i}", use_container_width=True)
        st.divider()

with tab2:
    st.info("Acik pozisyon takibi buraya gelecek (giris, K/Z, stop durumu, 21 EMA takibi).")

with tab3:
    st.dataframe(pd.DataFrame(signals), use_container_width=True)
