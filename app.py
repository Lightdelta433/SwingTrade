"""
========================================================================
 PULSE — PİYASA PANELİ  (app.py)  —  v3
========================================================================
Bu sürüm 3 dosyadan oluşur ve üçü birlikte yüklenmelidir:
    app.py       → arayüz
    mock_data.py → veri (gerçek veri öncelikli, etiketli mock fallback)
    engine.py    → indikatörler, filtre motoru, tarayıcı, backtest

Bölümler: Piyasalar · Long Term · Short Term · Backtest · Forex & Haberler

Gezinme: zengin satırlar/kartlar query-param linkleriyle tıklanır
(?sec=..&sym=..). Link tıklaması sayfayı yeniden yüklediği için kullanıcı
verisi (izleme listesi, filtre, backtest ayarları, işlem günlüğü) URL'deki
`sid` anahtarıyla sunucu tarafında saklanır ve geri yüklenir.
========================================================================
"""

import base64
import copy
import hashlib
import hmac
import html
import inspect
import json
import os
import re
import secrets
import time
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

st.set_page_config(page_title="Pulse — Market Dashboard", layout="wide", initial_sidebar_state="collapsed")

APP_VERSION = "3.9"
import mock_data as md  # noqa: E402

_missing = []
try:
    import engine as en  # noqa: E402
except ModuleNotFoundError:
    en = None
    _missing.append("engine.py")
try:
    import chart as ch  # noqa: E402
except ModuleNotFoundError:
    ch = None
    _missing.append("chart.py")
if _missing:
    st.error("**" + ", ".join(_missing) + " not found.** This version consists of these files: `app.py`, "
             "`mock_data.py`, `engine.py`, `chart.py` and `pulse_chart/index.html`. Upload the missing files "
             "to the same folder as app.py on GitHub and click **Reboot app** in Streamlit.")
    st.stop()

_vers = {"app.py": APP_VERSION, "mock_data.py": getattr(md, "DATA_VERSION", "old"),
         "engine.py": getattr(en, "ENGINE_VERSION", "old"), "chart.py": getattr(ch, "CHART_VERSION", "old")}
if set(_vers.values()) != {APP_VERSION}:
    st.error("**File versions do not match** — " +
             " · ".join(f"{k} v{v}" for k, v in _vers.items()) +
             ". Upload the latest version of all of them to GitHub and click **Reboot app**.")
    st.stop()
_uiv = ch.frontend_version()
if _uiv is not None and _uiv != getattr(ch, "UI_VERSION", _uiv):
    st.warning(f"**pulse_chart/index.html is outdated** (v{_uiv}, this release needs v{ch.UI_VERSION}). The chart "
               "keeps working, but its labels, vertical scrolling and gap boxes come from the new file — upload "
               "`pulse_chart/index.html` to GitHub and click **Reboot app**.")

# ======================================================================
# Tasarım sabitleri
# ======================================================================
BG, PANEL, PANEL2, BORDER, LINE = "#0A0B0D", "#111317", "#0C0D10", "#22262D", "#1C1F25"
TXT, MUT, SOFT, DIM = "#ECEEF1", "#8D96A5", "#C4CAD4", "#A3ABB8"
UP, DOWN, NEU, WARN, ACCENT, VIOLET = "#34D399", "#F87171", "#C4CAD4", "#F5B544", "#5B8CFF", "#C4B5FD"
UP_BG, DOWN_BG, NEU_BG = "rgba(52,211,153,.12)", "rgba(248,113,113,.12)", "rgba(141,150,165,.14)"
WARN_BG, ACC_BG = "rgba(245,181,68,.13)", "rgba(91,140,255,.14)"
SETUP_STYLE = {"Pullback": ("#9DB8FF", "rgba(91,140,255,.14)"), "Breakout": ("#6EE7B7", "rgba(52,211,153,.12)"),
               "Support bounce": ("#FCD34D", "rgba(245,181,68,.13)"), "Momentum": ("#D8B4FE", "rgba(167,139,250,.14)")}
TONE = {"good": (UP, "#0F1A15", "#1F4D3A", "#0A0B0D"), "warn": (WARN, "#1A160E", "#4D3D1F", "#0A0B0D"),
        "bad": (DOWN, "#1A0F10", "#4D1F24", "#ECEEF1")}

SECTIONS = ["Markets", "Valuation", "Long Term", "Short Term", "Backtest", "Forex & News"]
# Mum aralıkları tek yerde tanımlı: chart.py (küçükten büyüğe sıralı)
TF_LIST = ch.INTERVAL_ORDER
TF_DEF = ch.DEFAULT_INTERVAL
LB_LIST = ch.LOOKBACK_ORDER
LB_DEF = ch.DEFAULT_LOOKBACK
TF_NAME = {k: v["name"] for k, v in ch.INTERVALS.items()}
TF_LABEL = {k: v["short"] for k, v in ch.INTERVALS.items()}
TF_ADJ = {k: v.get("adj", v["name"].lower()) for k, v in ch.INTERVALS.items()}
MONTHS_TR = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
CUR = {"USD": "$", "TRY": "₺", "EUR": "€", "GBP": "£", "JPY": "¥"}
CHART_CFG = {"displayModeBar": True, "displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d"]}
LOGO_SVG = ('<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><rect width="30" height="30" '
            'rx="9" fill="#5B8CFF"></rect><path d="M7 18.5l5-5.5 4 4 7-8" fill="none" stroke="#0A0B0D" '
            'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"></path></svg>')

# ======================================================================
# Streamlit sürüm uyumluluğu (use_container_width → width="stretch")
# ======================================================================
_WK = {}


def _wkw(fn):
    name = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", str(id(fn)))
    if name not in _WK:
        try:
            ps = inspect.signature(fn).parameters
            p = ps.get("width")
            _WK[name] = p is not None and (isinstance(p.default, str) or "use_container_width" not in ps)
        except (TypeError, ValueError):
            _WK[name] = False
    return {"width": "stretch"} if _WK[name] else {"use_container_width": True}


def _light_fig(fig):
    try:
        fig.update_layout(template="plotly_white", font=dict(color="#2E3440"),
                          hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#D9DDE3", font=dict(color="#14171C")))
        fig.update_xaxes(gridcolor="#E9ECF0", zerolinecolor="#D5D9E0", linecolor="#D5D9E0")
        fig.update_yaxes(gridcolor="#E9ECF0", zerolinecolor="#D5D9E0", linecolor="#D5D9E0")
    except Exception:
        pass
    return fig


_HAS_SELECT = "on_select" in str(inspect.signature(st.plotly_chart))


def plot(fig, config=None, key=None, select=False):
    """Plotly grafiği. select=True: tıklanan noktayı döndürür (Streamlit ≥ 1.35)."""
    if LIGHT:
        fig = _light_fig(fig)
    kw = {}
    if select and _HAS_SELECT:
        kw = {"on_select": "rerun", "selection_mode": "points"}
    ev = st.plotly_chart(fig, config=config if config is not None else {"displayModeBar": False}, key=key,
                         **_wkw(st.plotly_chart), **kw)
    return ev if select else None


def picked_x(ev, key):
    """Grafikte yeni tıklanan noktanın x değeri (aynı seçim tekrar gelirse None)."""
    try:
        pts = (ev or {}).get("selection", {}).get("points") or []
    except AttributeError:
        try:
            pts = ev.selection.points
        except Exception:
            pts = []
    x = str(pts[0].get("x")) if pts else None
    last = ss.get("_pick_" + key)
    ss["_pick_" + key] = x
    return x if (x and x != last) else None


def table(df, **kw):
    st.dataframe(df, hide_index=True, **_wkw(st.dataframe), **kw)


def button(label, key, primary=False, **kw):
    return st.button(label, key=key, type="primary" if primary else "secondary", **_wkw(st.button), **kw)


def toggle(label, key, help=None):
    """st.toggle eski Streamlit sürümlerinde yok — checkbox'a düşer."""
    fn = getattr(st, "toggle", None) or st.checkbox
    return fn(label, key=key, help=help)


LIGHT = False
# Beyaz tema: koyu paletteki her renk açık karşılığına çevrilir (HTML, CSS, Plotly, grafik bileşeni)
LMAP = {
    # zeminler
    "#0A0B0D": "#F4F5F7", "#0C0D10": "#F3F5F8", "#111317": "#FFFFFF", "#13161C": "#EEF1F5", "#141820": "#EDF0F5",
    "#151922": "#E8EEFB", "#16191E": "#EEF0F3", "#171A1F": "#EEF0F3", "#1A1D23": "#E9ECF0", "#1B2130": "#E3EAF8",
    "#15181D": "#F0F2F5", "#0F1A15": "#E8F7F0", "#1A160E": "#FBF4E6", "#1A0F10": "#FDECEC", "#0E0F12": "#F6F7F9",
    # kenarlar
    "#1C1F25": "#E6E8EC", "#22262D": "#E1E4EA", "#2A2F37": "#D9DDE3", "#3A404A": "#C5CAD2", "#4A515C": "#B4BAC4",
    "#1F4D3A": "#A7DCC4", "#4D3D1F": "#EBCF95", "#4D1F24": "#F0B4B8", "#2F3B52": "#BFCDEB",
    # metin
    "#ECEEF1": "#14171C", "#C4CAD4": "#2E3440", "#A3ABB8": "#4A5260", "#9AA4B2": "#56606E", "#8D96A5": "#5F6878",
    "#6B7383": "#6F7787", "#5A6372": "#7A8292", "#C3D4FF": "#1E4FD6", "#9DB8FF": "#2F5BD8",
    # vurgu renkleri (beyazda okunabilir tonlar)
    "#5B8CFF": "#3B6EF5", "#34D399": "#0B9466", "#F87171": "#DC2F3E", "#F5B544": "#B7791F", "#C4B5FD": "#7C5CDB",
    "#6EE7B7": "#10A37F", "#A3D977": "#5E9E2E", "#F08A6A": "#D9603B", "#FCD34D": "#B98A07", "#D8B4FE": "#8B5CF6",
}
_HEX6 = re.compile(r"#[0-9A-Fa-f]{6}\b")


def lmap(s):
    """Koyu paletteki hex renkleri beyaz tema karşılıklarıyla değiştirir."""
    return _HEX6.sub(lambda m: LMAP.get(m.group(0).upper(), m.group(0)), s) if LIGHT else s


def H(s):
    # Her zaman <div> ile başlat → Markdown bunu HTML bloğu olarak geçirir
    # (aksi halde metindeki $, *, _ karakterleri biçimlendirmeye dönüşebilir).
    head = s.lstrip()[:6]
    s = s if head.startswith(("<div", "<style")) else f"<div>{s}</div>"
    st.markdown(lmap(s), unsafe_allow_html=True)


# ======================================================================
# Kalıcı durum (link tıklamalarında kaybolmasın) + query param
# ======================================================================
ss = st.session_state


@st.cache_resource(show_spinner=False)
def _store():
    return {}


STORE = _store()
# Widget anahtarları (kullanıcı ayarları) — sayfa değişse de korunur
WIDGET_KEYS = ["flt_logic", "flt_min", "flt_name", "acct", "w_risk", "w_tf", "w_fxtf", "w_lb", "w_fxlb", "w_fxc",
               "w_calday",
               "w_aimode", "w_aiauto", "w_savedflt", "w_theme", "flt_import_txt",
               "w_calimp", "w_nc", "w_mov", "w_setup", "w_sort", "w_bttf", "bt_inst", "bt_custom", "bt_pick",
               "bt_yrs", "bt_ind1", "bt_p1", "bt_op1", "bt_v1", "bt_logic", "bt_c2on", "bt_src2", "bt_p2",
               "bt_op2", "bt_dir", "bt_slMode", "bt_slV", "bt_tpMode", "bt_tpV", "bt_maxBars", "bt_cap",
               "bt_risk", "bt_comm", "bt_xmin"]
PERSIST = ["watchlist", "journal", "journal_closed", "flt_rows", "flt_ver", "flt_lastN", "bt_extra",
           "bt_extra_ver", "bt_ran", "bt_saved",
           "draws", "alerts", "ch_cfg", "ch_type", "ch_rev", "ch_n", "tf_pending",
           "theme", "notes", "notes_seen", "notes_gone", "ai_auto", "saved_filters", "flt_pending",
           "vp_cfg", "peer_ovr", "vtype_ovr", "auth", "cal_ccy"] + WIDGET_KEYS


def _qp(key, default=None):
    try:
        v = st.query_params.get(key)
    except Exception:
        v = None
    if isinstance(v, list):
        v = v[-1] if v else None
    return v if v not in (None, "") else default


SID = re.sub(r"[^A-Za-z0-9_\-]", "", _qp("sid", "") or "")[:24]
if not SID:
    SID = secrets.token_urlsafe(6)
    try:
        st.query_params["sid"] = SID
    except Exception:
        pass
if not ss.get("_restored"):
    for k, v in (STORE.get(SID) or {}).items():
        if k not in ss:
            ss[k] = copy.deepcopy(v)
    ss["_restored"] = True


def _save_state():
    try:
        STORE[SID] = {k: copy.deepcopy(ss[k]) for k in PERSIST if k in ss}
        if len(STORE) > 800:
            for k in list(STORE)[:200]:
                STORE.pop(k, None)
    except Exception:
        pass


BT_WIDGETS = {"bt_inst": "AAPL", "bt_custom": "", "bt_yrs": 3, "bt_ind1": "RSI", "bt_p1": 14, "bt_op1": "lt",
              "bt_v1": 30.0, "bt_logic": "and", "bt_c2on": True, "bt_src2": "sma", "bt_p2": 200,
              "bt_op2": "above", "bt_dir": "long", "bt_slMode": "atr", "bt_slV": 2.0, "bt_tpMode": "rr",
              "bt_tpV": 2.0, "bt_maxBars": 0, "bt_cap": 10000.0, "bt_risk": 1.0, "bt_comm": 0.1, "bt_xmin": 0}
for _k, _v in {"watchlist": list(md.DEFAULT_WATCHLIST), "journal": None, "journal_closed": [],
               "flt_rows": copy.deepcopy(en.DEFAULT_FILTER), "flt_logic": "AND",
               "flt_min": len(en.DEFAULT_FILTER) - 1, "flt_lastN": len(en.DEFAULT_FILTER),
               "flt_name": "Trend pullback", "flt_ver": 0,
               "flt_edit": False, "bt_extra": [], "bt_extra_ver": 0, "bt_ran": None, "bt_saved": [],
               "acct": 100000.0, "draws": {}, "alerts": {}, "ch_cfg": copy.deepcopy(ch.DEFAULT_CFG),
               "ch_type": "candles", "ch_rev": 1, "ch_n": None, "tf_pending": None, "ch_tfkey": "w_tf",
               "theme": "gece", "notes": [], "notes_seen": 0, "notes_gone": [], "ai_auto": False,
               "saved_filters": [], "flt_pending": None, "vp_cfg": {}, "peer_ovr": {}, "vtype_ovr": {},
               "ai_nonce": 0, "w_aiauto": False,
               **BT_WIDGETS}.items():
    ss.setdefault(_k, copy.deepcopy(_v))
# Streamlit, o çalıştırmada çizilmeyen widget'ın değerini siler (ör. filtre editörü kapalıyken).
# Değeri kendine yeniden atamak bu temizliği engeller → ayarlar kaybolmaz.
for _k in WIDGET_KEYS:
    if _k in ss:
        ss[_k] = ss[_k]

LIGHT = ss.get("theme") == "beyaz"
if LIGHT:
    BG, PANEL, PANEL2, BORDER, LINE = (LMAP.get(x, x) for x in (BG, PANEL, PANEL2, BORDER, LINE))
    TXT, MUT, SOFT, DIM = (LMAP.get(x, x) for x in (TXT, MUT, SOFT, DIM))
    UP, DOWN, NEU, WARN, ACCENT, VIOLET = (LMAP.get(x, x) for x in (UP, DOWN, NEU, WARN, ACCENT, VIOLET))
    UP_BG, DOWN_BG, NEU_BG = "rgba(11,148,102,.12)", "rgba(220,47,62,.10)", "rgba(95,104,120,.12)"
    WARN_BG, ACC_BG = "rgba(183,121,31,.12)", "rgba(59,110,245,.10)"
    SETUP_STYLE = {k: (LMAP.get(a, a), b) for k, (a, b) in SETUP_STYLE.items()}
    TONE = {k: tuple(LMAP.get(x, x) for x in v[:3]) + ("#FFFFFF",) for k, v in TONE.items()}

_SYM_RE = re.compile(r"[^A-Za-z0-9.^=\-]")
SEC = _qp("sec", "Markets")
# eski (Türkçe) bağlantılar çalışmaya devam etsin
LEGACY_SEC = {"Piyasalar": "Markets", "De\u011fer Analizi": "Valuation", "Forex & Haberler": "Forex & News"}
SEC = LEGACY_SEC.get(SEC, SEC)
SEC = SEC if SEC in SECTIONS else "Markets"
ACTIVE = _SYM_RE.sub("", _qp("sym", "SPY")).upper()[:24] or "SPY"
FX = _qp("fx", "EUR/USD")
FX = FX if FX in md.fx_pairs() else "EUR/USD"
OPP = _SYM_RE.sub("", _qp("opp", "") or "").upper()[:24] or None
AIP = _SYM_RE.sub("", _qp("aip", "") or "").upper()[:24] or None
SECTOR = _qp("sector")
SECTOR = SECTOR if md.sector_by_etf(SECTOR or "") else None


def link(**kw):
    p = {"sid": SID, "sec": SEC, "sym": ACTIVE, "fx": FX, "opp": OPP, "aip": AIP, "sector": SECTOR}
    p.update(kw)
    return "?" + urlencode({k: v for k, v in p.items() if v not in (None, "")})


def _consume(key):
    v = _qp(key)
    if v is not None:
        try:
            del st.query_params[key]
        except Exception:
            pass
    return v


# Link tıklaması sayfayı yeniden yükler ve en üste döner. `f=<bölüm>` parametresi
# taşıyan linklerde sayfa yüklendikten sonra o bölüme kaydırılır (yalnızca bir kez).
FOCUS = _consume("f")
_SCROLL_JS = """<script>
(function(){var n=0,done=0;var t=setInterval(function(){try{
var el=window.parent.document.querySelector('.pa-%s');
if(el){el.scrollIntoView({behavior:'smooth',block:'start'});done++;if(done>2){clearInterval(t);}}
}catch(e){clearInterval(t);} if(++n>40){clearInterval(t);}},250);})();
</script>"""


def anchor(name):
    H(f'<div class="pulse-anchor pa-{name}"></div>')
    if FOCUS == name:
        components.html(_SCROLL_JS % name, height=0)


# ---- tek seferlik link aksiyonları ----
_a = _consume("add_wl")
if _a:
    _a = _SYM_RE.sub("", _a).upper()[:24]
    if _a and _a not in ss.watchlist:
        ss.watchlist.append(_a)
        st.toast(f"{_a} added to the watchlist")
_a = _consume("add_flt")
if _a in en.INDICATORS:
    ss.flt_rows.append(en.suggested_condition(_a))
    ss.flt_ver += 1
    ss.flt_edit = True
    ss["w_aimode"] = "My Filter"      # kendi filtresine geçsin
    ss["_last_w_aimode"] = "My Filter"
    st.toast(f"“{_a}” added to the filter — you can edit its value")
_a = _consume("add_bt")
if _a in en.INDICATORS:
    ss.bt_extra.append(en.suggested_condition(_a))
    ss.bt_extra_ver += 1
    ss["bt_show_extra"] = True
    st.toast(f"“{_a}” added to the backtest conditions")
if _consume("bt_from_flt"):
    ss.bt_extra = [dict(r) for r in en.normalize_conds(ss.flt_rows) if r["Active"]]
    ss.bt_extra_ver += 1
    ss.bt_ind1, ss.bt_c2on = en.IND1_OFF, False
    _n = len(ss.bt_extra)
    _k = int(ss.get("flt_min") or _n)
    ss.bt_xmin = 1 if ss.get("flt_logic") == "OR" else (_k if 0 < _k < _n else 0)  # Short Term ile aynı mantık
    ss["bt_show_extra"] = True
    ss.bt_ran = None  # yeni kurallarla otomatik çalıştır
    st.toast("Short Term filter loaded as the backtest entry condition")
_a = _consume("close_tr")
if _a is not None and ss.journal:
    try:
        i = int(_a)
        tr_ = ss.journal.pop(i)
        q = md.get_quote(tr_["t"])
        tr_["exit"], tr_["closed"] = q["last"], pd.Timestamp.today().strftime("%Y-%m-%d")
        ss.journal_closed.append(tr_)
        st.toast(f"{tr_['t']} trade closed")
    except (ValueError, IndexError):
        pass


# ======================================================================
# Biçim yardımcıları
# ======================================================================
def safe_url(u):
    u = str(u or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


def esc(s):
    # Satır sonları HTML bloğunu bölmesin diye boşluğa çevrilir
    return re.sub(r"\s*[\r\n]+\s*", " ", html.escape(str(s if s is not None else "")))


def tr(x, dec=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x or x in (float("inf"), float("-inf")):
        return "—"
    return f"{x:,.{dec}f}"


def pct(x, dec=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return ("+" if x >= 0 else "−") + tr(abs(x), dec) + "%"


def chg(x, dec=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    return ("+" if x >= 0 else "−") + tr(abs(x), dec)


def pdec(sym, v):
    try:
        v = abs(float(v))
    except (TypeError, ValueError):
        return 2
    if sym.endswith("=X"):
        return 3 if v >= 20 else 4
    return 0 if v >= 10000 else 2


def money(x, cur="USD", dec=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    return ("−" if x < 0 else "") + CUR.get((cur or "").upper(), "") + tr(abs(x), dec)


def big(x, cur="USD"):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    for d, s in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= d:
            return CUR.get((cur or "").upper(), "") + tr(x / d) + s
    return money(x, cur)


def col(x):
    try:
        return UP if float(x) >= 0 else DOWN
    except (TypeError, ValueError):
        return SOFT


def avatar(t, size=34, name=None):
    tt = str(t or "?")
    src = tt if not (name and tt[:1].isdigit()) else str(name)
    ini = re.sub(r"[^A-Z0-9]", "", src.upper().replace("=X", "").replace("-USD", "").replace("^", ""))[:2] or "?"
    hue = sum(ord(c) for c in tt) % 360
    fs = max(9, int(size * 0.33))
    logo = md.logo_url(tt)
    if logo:
        # Logo yüklenemezse img::after baş harfleri gösterir (kırık resim simgesi görünmez)
        return (f'<span class="av" style="width:{size}px;height:{size}px;font-size:{fs}px;background:#F1F2F4;'
                f'color:hsl({hue},55%,32%);--avfg:hsl({hue},55%,32%)">{ini}<img src="{logo}" alt="{ini}" '
                f'loading="lazy"></span>')
    return (f'<span class="av" style="width:{size}px;height:{size}px;font-size:{fs}px;'
            f'background:hsl({hue},32%,20%);color:hsl({hue},70%,80%)">{ini}</span>')


def svg_spark(series, color, w=84, h=30):
    try:
        s = [float(v) for v in series if v == v][-60:]
    except (TypeError, ValueError):
        return ""
    if len(s) < 2:
        return ""
    lo, hi = min(s), max(s)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(s) - 1):.1f},{h - 2 - (v - lo) / rng * (h - 4):.1f}" for i, v in enumerate(s))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" '
            f'stroke-linecap="round"/></svg>')


def src_chip(src):
    if src == "real":
        return '<span class="srcchip live">● live data</span>'
    if src == "mock":
        return '<span class="srcchip mock">sample data</span>'
    return '<span class="srcchip none">no data</span>'


def badge(text, fg, bg):
    return f'<span class="badge" style="color:{fg};background:{bg}">{esc(text)}</span>'


def seg(label, options, key, default, fmt=None, on_change=None):
    """Tasarımdaki segment buton grubu (sayfa yenilemeden çalışır).
    Seçili seçeneğe tekrar tıklamak seçimi boşaltmasın diye son değer korunur."""
    options = list(options)
    last = ss.get("_last_" + key)
    if ss.get(key) not in options:
        ss[key] = last if last in options else default

    def _cb():
        if ss.get(key) not in options:
            ss[key] = ss.get("_last_" + key) if ss.get("_last_" + key) in options else default
        if on_change:
            on_change()

    if hasattr(st, "segmented_control"):
        v = st.segmented_control(label, options, key=key, format_func=fmt or str, label_visibility="collapsed",
                                 on_change=_cb)
    else:
        v = st.radio(label, options, key=key, format_func=fmt or str, horizontal=True,
                     label_visibility="collapsed", on_change=_cb)
    v = v if v in options else default
    ss["_last_" + key] = v
    return v


def step_head(n, title, right=""):
    H(f'<div class="step"><span class="stepno">{n}</span><b>{esc(title)}</b>'
      f'<span class="muted" style="margin-left:auto">{esc(right)}</span></div>')


# ======================================================================
# Stil
# ======================================================================
H("""
<style>
.block-container{padding-top:3.2rem;padding-bottom:3rem;max-width:1480px}
header[data-testid="stHeader"]{background:transparent}
.pulse-anchor{height:0;scroll-margin-top:72px}
div[data-testid="stElementContainer"]:has(iframe[height="0"]),
.element-container:has(iframe[height="0"]){display:none}
.hdr{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:19px;letter-spacing:-.02em}
.navbar{display:flex;gap:4px;flex-wrap:wrap}
.navbar a{padding:9px 13px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;color:#A3ABB8}
.navbar a.active{background:#171A1F;color:#ECEEF1;font-weight:700}
.navbar a:hover{color:#ECEEF1}
.hdr-icons{display:flex;gap:8px;justify-content:flex-end}
.hbtn{width:40px;height:40px;border-radius:12px;border:1px solid #22262D;background:#111317;display:inline-flex;
 align-items:center;justify-content:center;font-size:14px;font-weight:800;color:#ECEEF1}
.hdr-line{border-bottom:1px solid #1C1F25;margin:6px 0 14px 0}
.page-title{font-size:30px;font-weight:800;letter-spacing:-.025em;margin:2px 0 4px 0}
.kicker{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#5B8CFF}
.muted{color:#8D96A5;font-size:13px}
.small{font-size:12px}
.mono{font-family:ui-monospace,"IBM Plex Mono",Menlo,Consolas,monospace}
.dot-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34D399;margin-right:6px}
.chip{font-size:11px;color:#8D96A5;background:#1A1D23;border-radius:6px;padding:3px 7px}
.badge{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px;white-space:nowrap}
.pill{font-size:12px;font-weight:700;border-radius:999px;padding:4px 10px;white-space:nowrap}
.srcchip{font-size:11px;font-weight:700;border-radius:999px;padding:3px 9px;white-space:nowrap}
.srcchip.live{color:#34D399;background:rgba(52,211,153,.10)}
.srcchip.mock{color:#F5B544;background:rgba(245,181,68,.12);border:1px dashed rgba(245,181,68,.5)}
.srcchip.none{color:#F87171;background:rgba(248,113,113,.12)}
.panel-title{font-size:16px;font-weight:700}
.sec-head{display:flex;align-items:center;gap:10px;margin:4px 0 10px 0}
.sec-head h3{margin:0;font-size:18px;font-weight:800}
.sec-no{color:#5B8CFF;font-size:11px;font-weight:800;letter-spacing:.1em;font-family:ui-monospace,monospace}
a.plain{text-decoration:none;color:inherit;display:block}
a.lnk{color:#5B8CFF;text-decoration:none;font-weight:700}
.av{position:relative;flex:none;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
 font-weight:800;overflow:hidden}
.av img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:3px;box-sizing:border-box;
 background:inherit;color:transparent;border-radius:50%}
.av img::after{content:attr(alt);position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 background:#F1F2F4;color:var(--avfg,#334);font-weight:800;border-radius:50%}
.stat-row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 2px;
 border-top:1px solid #1C1F25;font-size:13px}
.stat-row .lbl{color:#C4CAD4;flex:1}
.ind-row{align-items:flex-start}
.ind-row .lbl{min-width:0}
.ind-row .ind-note{display:block;font-size:11px;color:#8D96A5;margin-top:2px;line-height:1.35}
.ind-row .mono,.ind-row .badge{margin-top:1px}
.desc{color:#C4CAD4;font-size:13px;line-height:1.55;margin-top:8px}
/* endeks kartı */
.idx{background:#111317;border:1px solid #22262D;border-radius:14px;padding:13px 15px}
.idx:hover{border-color:#3A404A}
/* izleme listesi (kompakt, sabit yükseklik + kaydırma) */
.wll{max-height:292px;overflow-y:auto;margin:0 -4px;padding-right:2px}
.wlr{display:flex;align-items:center;gap:9px;padding:5px 6px;border-top:1px solid #1C1F25;border-radius:7px}
.wlr:hover{background:#141820}
.wlr .nm{flex:1;min-width:0;line-height:1.25}
.wlr .nm b{font-size:12.5px}
.wlr .nm div{color:#8D96A5;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wlr .px{text-align:right;font-family:ui-monospace,monospace;line-height:1.25}
.tmap{position:relative;width:100%;border-radius:10px;overflow:hidden;background:#0C0D10}
.tmb{position:absolute;box-sizing:border-box;border:2px solid #0A0B0D;display:flex;align-items:center;
 justify-content:center;text-align:center;color:#fff !important;text-decoration:none !important;overflow:hidden;
 transition:filter .12s}
.tmb:hover{filter:brightness(1.25);z-index:2;outline:2px solid #FFFFFFAA;outline-offset:-2px}
.tmi{display:flex;flex-direction:column;align-items:center;gap:1px;padding:2px;line-height:1.15;min-width:0}
.tmi b{font-family:ui-monospace,monospace;font-weight:800;color:#fff}
.tmi i{font-style:normal;font-size:10.5px;opacity:.82;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
 max-width:100%}
.tmi em{font-style:normal;font-family:ui-monospace,monospace;font-weight:600;color:#fff;opacity:.95}
.qfin td,.qfin th{text-align:right;white-space:nowrap}
.qfin td:first-child,.qfin th:first-child{text-align:left}
.qfin tr.qsub td{color:#8D96A5;font-size:11.5px}
.qfin tr.qsub td:first-child{padding-left:14px}
.qfin td.qexp{font-style:italic;background:rgba(91,140,255,.05)}
.qfin td.fytot{border-left:1px solid #22262D;color:#C4CAD4}
.ratebar{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:6px 0 6px 0;background:#16191E}
.ratebar i{display:block;height:100%}
.ptrange{position:relative;height:16px;margin:6px 4px 8px 4px;background:#16191E;border-radius:8px}
.ptrange .rng{position:absolute;top:5px;height:6px;background:#5B8CFF55;border-radius:3px}
.ptrange .mk{position:absolute;top:1px;width:3px;height:14px;margin-left:-1px;border-radius:2px}
.ptrange .mk.mean{background:#5B8CFF}
.ptrange .mk.now{background:#ECEEF1}
.ptab tr.qsel td{background:#151922}
.ptab tr.qsel td:first-child{box-shadow:inset 3px 0 0 #5B8CFF}
.dtab-wrap{overflow-x:auto;margin-top:8px}
.dtab td{padding:7px 8px;font-size:12px}
.dtab td.lbl{color:#C4CAD4;font-weight:600;font-family:inherit}
.dtab td.qsel,.dtab th.qsel{background:#151922}
.dtab tr:last-child td{border-top:1px solid #2A2F38;border-bottom:0;font-size:13px}
.qtab tr.qtot td{border-top:1px solid #2A2F37;color:#C4CAD4}
.qtiles{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.qtiles .tile{padding:7px 9px}
.cal-act{display:inline-block;padding:1px 6px;border-radius:6px;font-weight:700}
.cal-row.done{background:rgba(255,255,255,.012)}
.mixhead,.mixrow{display:grid;grid-template-columns:minmax(110px,1.6fr) 2fr 78px 52px 62px;gap:10px;align-items:center;
 padding:6px 2px;font-size:12.5px}
.mixhead{color:#8D96A5;font-size:11px;border-bottom:1px solid #1C1F25;padding-top:8px}
.mixrow{border-bottom:1px solid #16191E}
.mixrow .ml{color:#C4CAD4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mixrow .mb{height:10px;background:#16191E;border-radius:5px;overflow:hidden}
.mixrow .mb i{display:block;height:100%;background:#5B8CFF;border-radius:5px}
.mixrow .mv,.mixrow .ms,.mixrow .my,.mixhead .mv,.mixhead .ms,.mixhead .my{text-align:right;
 font-family:ui-monospace,monospace}
.kpigrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:8px}
.kpitile .k{white-space:normal;line-height:1.3}
.srstrip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;padding-bottom:4px}
.srstrip .tile{padding:9px 10px;line-height:1.3}
.gapgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;padding-bottom:4px}
.gapgrid .tile{padding:8px 10px;line-height:1.3;border-top-left-radius:4px;border-bottom-left-radius:4px}
.srcap{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
/* A–Z notu */
.grade{display:flex;align-items:center;gap:14px;margin:4px 0 2px 0}
.gletter{width:64px;height:64px;border-radius:16px;display:flex;align-items:center;justify-content:center;
 font-size:34px;font-weight:800;letter-spacing:-.03em;flex:none;font-family:ui-monospace,monospace}
.gact{font-size:19px;font-weight:800;letter-spacing:-.02em;line-height:1.2}
.gsc{font-family:ui-monospace,monospace;font-size:12px;color:#8D96A5;margin-top:2px}
.gscale{height:8px;border-radius:999px;position:relative;margin:12px 0 3px 0;
 background:linear-gradient(90deg,#34D399 0%,#A3D977 26%,#F5B544 52%,#F08A6A 74%,#F87171 100%)}
.gscale i{position:absolute;top:-4px;width:4px;height:16px;border-radius:2px;background:#ECEEF1;
 box-shadow:0 0 0 2px #0A0B0D;transform:translateX(-2px)}
.gax{display:flex;justify-content:space-between;font-size:10.5px;color:#6B7383;margin-bottom:8px}
.grow{display:flex;align-items:center;gap:9px;padding:4px 0;font-size:12px}
.grow .gn{color:#C4CAD4;width:134px;flex:none;line-height:1.22;font-size:11.5px}
.grow .gw{color:#6B7383;font-size:10.5px;width:26px;flex:none;text-align:right}
.grow .gb{flex:1;height:6px;border-radius:999px;background:#1A1D23;overflow:hidden;min-width:20px}
.grow .gb i{display:block;height:6px;border-radius:999px}
.grow .gv{width:26px;text-align:right;font-family:ui-monospace,monospace;color:#8D96A5;flex:none}
.gtext{font-size:12.5px;line-height:1.68;color:#C4CAD4;margin-top:11px;padding-top:11px;
 border-top:1px solid #1C1F25}
.gtext b{color:#ECEEF1}
/* değer analizi */
.vgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.ptab{width:100%;border-collapse:collapse;font-size:12.5px}
.ptab th{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#8D96A5;font-weight:700;
 padding:9px 8px;text-align:right;border-bottom:1px solid #22262D;white-space:nowrap}
.ptab th:first-child{text-align:left}
.ptab td{padding:10px 8px;text-align:right;border-bottom:1px solid #1A1D23;font-family:ui-monospace,monospace;
 font-weight:600;white-space:nowrap}
.ptab td:first-child{text-align:left;font-family:inherit}
.ptab tr.me td{background:#151922}
.ptab tr.med td{color:#8D96A5;font-weight:600;border-bottom:0}
.ptab tr.med td:first-child{color:#C4CAD4}
.vrow{display:flex;align-items:center;gap:9px;padding:6px 0;font-size:12.5px;border-top:1px solid #1C1F25}
.vrow .ic{width:19px;height:19px;flex:none;border-radius:50%;display:flex;align-items:center;
 justify-content:center;font-size:11px;font-weight:800}
.vrow .t{flex:1;color:#C4CAD4}
.vrow .n{color:#8D96A5;font-size:11.5px}
.mbar{display:grid;grid-template-columns:repeat(12,1fr);gap:4px;align-items:end;height:92px;margin-top:6px}
.mbar div{border-radius:4px 4px 0 0;position:relative}
.mlab{display:grid;grid-template-columns:repeat(12,1fr);gap:4px;font-size:10px;color:#6B7383;
 text-align:center;margin-top:4px}
.greason{font-size:11.5px;color:#8D96A5;line-height:1.6;padding:3px 0 3px 10px;border-left:2px solid #22262D}
/* ısı haritası */
.heatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.heat{min-height:78px;height:100%;border-radius:12px;padding:10px 12px;box-sizing:border-box;display:flex;
 flex-direction:column;justify-content:space-between;gap:6px;border:2px solid transparent}
.heat b{font-size:13px;color:#fff;line-height:1.25}
.heat span{font-weight:700;color:#fff;font-size:15px;font-family:ui-monospace,monospace}
.heat.sel{border-color:#ECEEF1}
.heatgrid a.plain,.cgrid a.plain{height:100%}
.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(124px,1fr));gap:6px}
.cgrid .heat{min-height:60px;padding:8px 10px;gap:4px}
.cgrid .heat b{font-size:12px}.cgrid .heat span{font-size:13px}
.cgrid .heat b span{display:block;font-size:10.5px;font-weight:600;opacity:.8;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis;font-family:inherit}
/* satır listeleri */
.row{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid #1C1F25}
.nw{display:flex;gap:12px;padding:11px 6px;border-top:1px solid #1C1F25;text-decoration:none;
 align-items:flex-start;border-radius:10px}
.nw:hover{background:#13161C}
.nw b{font-size:13.5px;font-weight:700;line-height:1.35;display:block;color:#ECEEF1}
.nw:hover b{color:#C3D4FF}
.nw a{color:#ECEEF1;text-decoration:none}.nw a:hover{color:#C3D4FF}
.nwb{flex:1;min-width:0}
.nwm{display:block;margin-top:4px}
.nwi{width:64px;height:46px;flex:none;border-radius:8px;border:1px solid #1C1F25;background:#0C0D10;
 background-size:cover;background-position:center;display:flex;align-items:center;justify-content:center;
 font-size:11px;font-weight:800;color:#5A6372;overflow:hidden}
.nwspark{position:relative;width:84px;flex:none;display:flex;align-items:center;border-radius:10px;padding:4px;
 background:#0C0D10;overflow:hidden}
.nwspark.hasimg{height:56px}
.nwspark img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:10px}
.nwx{color:#5A6372;font-size:13px;flex:none;align-self:center;padding-left:2px}
.nw:hover .nwx{color:#9DB8FF}
/* arama */
.sr-row{display:flex;align-items:center;gap:12px;padding:9px 4px;border-top:1px solid #1C1F25}
.sr-row .sr-main{display:flex;align-items:center;gap:12px;flex:1;min-width:0}
.sr-act{font-size:12px;font-weight:700;color:#5B8CFF;text-decoration:none;white-space:nowrap;margin-left:8px}
/* short term */
.critbar{background:#111317;border:1px solid #22262D;border-radius:18px;padding:14px 18px;display:flex;
 flex-wrap:wrap;align-items:center;gap:12px 16px}
.crit{font-family:ui-monospace,monospace;font-size:12px;padding:6px 10px;border-radius:8px;background:#0C0D10;
 border:1px solid #22262D;color:#C4CAD4}
.ficon{width:36px;height:36px;border-radius:10px;background:#0C0D10;border:1px solid #22262D;display:flex;
 align-items:center;justify-content:center}
.btlink{display:inline-flex;align-items:center;gap:6px;height:40px;padding:0 14px;border-radius:12px;
 border:1px solid #5B8CFF;color:#5B8CFF;text-decoration:none;font-size:14px;font-weight:700;margin-left:auto}
.kpi{padding:16px 18px;border-radius:14px;border:1px solid #22262D;background:#111317;display:flex;
 flex-direction:column;gap:6px;height:100%;box-sizing:border-box}
.kpi .l{font-size:12.5px;font-weight:700;color:#C4CAD4}
.kpi .v{font-family:ui-monospace,monospace;font-size:24px;font-weight:600;letter-spacing:-.02em}
.kpi .s{font-size:12px;color:#8D96A5}
.regime{padding:16px 18px;border-radius:14px;display:flex;flex-direction:column;gap:10px;height:100%;
 box-sizing:border-box}
.opp{background:#111317;border:1px solid #22262D;border-radius:18px;overflow:hidden}
.opp-scroll{overflow-x:auto}
.opp-grid{display:grid;align-items:center;gap:0 12px;min-width:820px;padding:0 14px;box-sizing:border-box;
 grid-template-columns:minmax(0,2.2fr) minmax(0,1.3fr) 86px minmax(0,1.5fr) 74px 74px 46px 104px}
.opp-grid>span{min-width:0;overflow:hidden}
.opp-grid .r{white-space:nowrap;text-align:right;justify-self:stretch}
.ai-grid{grid-template-columns:minmax(0,2.3fr) minmax(0,2fr) 88px 78px 92px 76px 48px 104px;min-width:900px}
.cellsym{display:flex;align-items:center;gap:11px;min-width:0}
.cellsym .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11.5px;color:#8D96A5;
 margin-top:2px}
.cellstk{display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:0}
.cellstk .sub{max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11.5px;
 color:#8D96A5}
.cellscore{display:flex;align-items:center;gap:8px;white-space:nowrap}
.cellscore .scorebar{margin-right:0}
a.opp-row,a.opp-row:hover,a.opp-row:visited,a.opp-row:active{text-decoration:none!important;color:#ECEEF1!important}
a.opp-row *{text-decoration:none!important}
.aist{font-size:10.5px;font-weight:800;border-radius:5px;padding:2px 7px;white-space:nowrap}
.funnel{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px 0}
.funnel div{background:#0C0D10;border:1px solid #22262D;border-radius:10px;padding:7px 11px;font-size:12px}
.funnel b{display:block;font-family:ui-monospace,monospace;font-size:15px;font-weight:700;color:#ECEEF1}
.plan{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:8px 0}
.planrow{display:flex;align-items:center;gap:8px;padding:7px 0;border-top:1px solid #1C1F25;font-size:12.5px}
.planrow .l{color:#8D96A5;flex:1}
.planrow .v{font-family:ui-monospace,monospace;font-weight:600}
.opp-head{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8D96A5;padding-top:12px;
 padding-bottom:10px}
.opp-row{border-top:1px solid #1A1D23;padding-top:8px;padding-bottom:8px;font-size:13px;color:#ECEEF1;
 text-decoration:none}
.opp-row:hover{background:#141820}
.opp-row.sel{background:#151922;box-shadow:inset 3px 0 0 #5B8CFF}
.r{text-align:right;font-family:ui-monospace,monospace}
.scorebar{width:52px;height:6px;border-radius:3px;background:#22262D;overflow:hidden;display:inline-block;
 vertical-align:middle;margin-right:8px}
.opp-foot{border-top:1px solid #1C1F25;padding:12px 18px;display:flex;flex-wrap:wrap;gap:16px;font-size:12px;
 color:#8D96A5}
.tile{background:#0C0D10;border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:2px}
.tile .k{font-size:11px;color:#8D96A5}
.tile .v{font-family:ui-monospace,monospace;font-size:14.5px;font-weight:600}
.chk{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid #1C1F25;font-size:13px}
.chk .ic{width:20px;height:20px;flex:none;border-radius:50%;display:flex;align-items:center;justify-content:center;
 font-size:11px;font-weight:900}
.jt{width:100%;border-collapse:collapse;font-size:13px;min-width:760px}
.jt th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8D96A5;font-weight:600;
 padding:10px 7px;text-align:right;white-space:nowrap}
.jt td{padding:10px 7px;border-top:1px solid #1A1D23;text-align:right;font-family:ui-monospace,monospace;
 white-space:nowrap}
.jt th:first-child,.jt td:first-child{text-align:left;padding-left:18px}
.prog{position:relative;width:130px;height:6px;border-radius:3px;
 background:linear-gradient(90deg,rgba(248,113,113,.35),rgba(52,211,153,.35));display:inline-block}
.prog span{position:absolute;top:-4px;width:14px;height:14px;border-radius:50%;background:#ECEEF1;
 border:3px solid #111317;box-sizing:border-box}
/* backtest */
.step{display:flex;align-items:center;gap:10px;margin:2px 0 8px 0}
.stepno{width:24px;height:24px;border-radius:50%;background:#1A1D23;display:inline-flex;align-items:center;
 justify-content:center;font-family:ui-monospace,monospace;font-size:12px;font-weight:600;color:#5B8CFF}
.step b{font-size:14px;font-weight:800}
.boxlbl{font-size:11px;font-weight:700;color:#8D96A5;text-transform:uppercase;letter-spacing:.06em}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:#C4CAD4;align-items:center}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.tt-wrap{max-height:460px;overflow:auto}
/* takvim */
.cal-row{display:flex;align-items:center;gap:12px;padding:10px 6px;border-top:1px solid #1C1F25;font-size:13px}
.cal-row.next{background:#141820}
.dots{display:flex;gap:3px;width:40px;flex:none}
.dots i{width:9px;height:4px;border-radius:2px;display:block}
/* haber */
.feat{background:#111317;border:1px solid #22262D;border-radius:16px;overflow:hidden}
.feat .img{height:210px;background:#0C0D10;display:flex;align-items:center;justify-content:center;color:#3A404A;
 font-size:12px;overflow:hidden;position:relative}
.feat .img img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;color:transparent}
.feat .img img::after{content:"";position:absolute;inset:0;background:#0C0D10}
.feat a{color:#ECEEF1;text-decoration:none}
/* segment kontrol renkleri (tasarım: mavi aktif pill) */
[data-testid="stBaseButton-segmented_controlActive"]{background:#5B8CFF!important;color:#0A0B0D!important;
 border-color:#5B8CFF!important}
[data-testid="stBaseButton-segmented_control"]{background:#0C0D10;color:#A3ABB8;border-color:#22262D}
</style>
""")


# ======================================================================
# Grafikler
# ======================================================================
def _layout(fig, height, legend=False, margin=None):
    fig.update_layout(template="plotly_dark", height=height, showlegend=legend,
                      margin=margin or dict(l=6, r=6, t=8, b=6), hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=10)))
    fig.update_xaxes(gridcolor="#1A1D23", showspikes=False)
    fig.update_yaxes(gridcolor="#1A1D23", side="right")
    return fig


def _rangebreaks(idx, intraday=False):
    """Hafta sonu / tatil / seans dışı boşluklarını grafikten çıkarır (kripto gibi 7/24 verilerde dokunmaz)."""
    try:
        idx = pd.DatetimeIndex(idx)
        if len(idx) < 3:
            return []
        rb = []
        if not (idx.dayofweek >= 5).any():
            rb.append(dict(bounds=["sat", "mon"]))
            days = pd.bdate_range(idx[0].normalize(), idx[-1].normalize())
            missing = days.difference(pd.DatetimeIndex(idx.normalize().unique()))
            if 0 < len(missing) < 400:
                rb.append(dict(values=[d.strftime("%Y-%m-%d") for d in missing]))
        if intraday:
            hrs = idx.hour + idx.minute / 60.0
            step = float(pd.Series(idx).diff().dt.total_seconds().median() or 300) / 3600.0
            lo, hi = float(hrs.min()), float(hrs.max()) + step
            if hi - lo < 22:
                rb.append(dict(bounds=[round(hi, 4), round(lo, 4)], pattern="hour"))
        return rb
    except Exception:
        return []


chart_data = ch.chart_data   # tek kaynak: chart.py


# ----------------------------------------------------------------------
# Grafik bileşeni olayları (çizim, alarm, indikatör ayarı, grafik türü)
# ----------------------------------------------------------------------
def handle_chart_event(ev):
    if not isinstance(ev, dict):
        return
    n = ev.get("n")
    if n is None or n == ss.get("ch_n"):
        return
    ss.ch_n = n
    sym = _SYM_RE.sub("", str(ev.get("sym") or ACTIVE)).upper()[:24] or ACTIVE
    kind = ev.get("kind")
    if kind == "draws":
        d = ev.get("draws")
        ss.draws[sym] = d if isinstance(d, list) else []
    elif kind == "alerts":
        a = ev.get("alerts")
        ss.alerts[sym] = a if isinstance(a, list) else []
    elif kind == "type":
        ss.ch_type = ev.get("type") or "candles"
    elif kind == "cfg":
        ss.ch_cfg = ch.merge_cfg(ev.get("cfg"))
        st.rerun()   # indikatörler gerçek veriyle yeniden hesaplanacak
    elif kind == "interval":
        v = ev.get("interval")
        if v in ch.INTERVALS:
            # widget değeri yalnızca widget çizilmeden önce değiştirilebilir → beklemeye al
            ss.tf_pending = (ss.get("ch_tfkey") or "w_tf", v)
            st.rerun()


def apply_pending_tf(key):
    """Grafikten gelen aralık seçimini widget çizilmeden önce uygular."""
    p = ss.get("tf_pending")
    if p and p[0] == key:
        ss[key] = p[1]
        ss["_last_" + key] = p[1]
        ss.tf_pending = None


def render_big_chart(sym, tf, height=600, tf_key="w_tf", lb=None):
    """TradingView tarzı grafik; dosya eksikse Plotly'ye düşer."""
    ss.ch_tfkey = tf_key
    if ch.missing_frontend():
        st.warning("`pulse_chart/index.html` is not uploaded — falling back to a simple chart. On GitHub, also upload "
                   "the **pulse_chart** folder with the **index.html** file inside it.")
        full, bars, intr = chart_data(sym, tf, lb)
        if not full.empty:
            plot(price_chart(full, bars, height - 60, intraday=intr), config=CHART_CFG, key="fallback_" + sym)
        return
    payload = ch.build_payload(sym, tf, json.dumps(ss.ch_cfg, sort_keys=True), ch.data_token(sym, tf, lb),
                               lb=lb)
    if not payload.get("ok"):
        H('<div class="muted">Could not load chart data for this symbol.</div>')
        return
    ev = ch.render_chart(payload, ss.draws.get(sym, []), ss.alerts.get(sym, []),
                         ss.ch_type, height=height, rev=ss.ch_rev, key="pulse_chart", light=LIGHT)
    handle_chart_event(ev)


def candle_label(tf, intraday):
    """Grafiğin altındaki açıklama: istenen aralık gerçekten çizilebildi mi?"""
    want = ch.norm_tf(tf)
    if ch.is_intraday(want) and not intraday:
        return "no intraday data · daily candles"
    return "%s candles" % TF_ADJ.get(want, "daily")


def price_chart(full, bars, height=430, rsi_panel=True, intraday=False):
    """Mum + SMA20/50 (+hacim, +RSI). Göstergeler tam geçmişten hesaplanıp kesilir."""
    s20, s50, rsi = en.sma(full["Close"], 20), en.sma(full["Close"], 50), en.rsi(full["Close"], 14)
    df = full.tail(bars)
    s20, s50, rsi = s20.loc[df.index], s50.loc[df.index], rsi.loc[df.index]
    has_vol = float(df["Volume"].sum()) > 0
    rows = 1 + has_vol + rsi_panel
    heights = {1: [1.0], 2: [0.78, 0.22], 3: [0.62, 0.16, 0.22]}[rows]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, row_heights=heights, vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name="Price"), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=s20, mode="lines", line=dict(color=ACCENT, width=1.5), name="SMA 20"), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=s50, mode="lines", line=dict(color=WARN, width=1.5), name="SMA 50"), 1, 1)
    last = float(df["Close"].iloc[-1])
    fig.add_hline(y=last, line=dict(color=col(last - float(df["Open"].iloc[0])), width=1, dash="dot"), row=1, col=1)
    r = 2
    if has_vol:
        fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", opacity=0.45,
                             marker_color=[UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]), r, 1)
        r += 1
    if rsi_panel:
        fig.add_trace(go.Scatter(x=df.index, y=rsi, mode="lines", line=dict(color=VIOLET, width=1.4),
                                 name="RSI 14"), r, 1)
        for y in (70, 30):
            fig.add_hline(y=y, line=dict(color="#3A404A", width=1, dash="dash"), row=r, col=1)
        fig.update_yaxes(range=[0, 100], row=r, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False)
    rb = _rangebreaks(df.index, intraday)
    if rb:
        fig.update_xaxes(rangebreaks=rb)
    return _layout(fig, height)


def compute_tech(df):
    close = df["Close"]
    price = float(close.iloc[-1])
    rsi = en._last(en.rsi(close))
    line, sig, _ = en.macd(close)
    mv, sv = float(line.iloc[-1]), float(sig.iloc[-1])
    st_k = en._last(en.stoch_k(df))
    mom = price - float(close.iloc[-11]) if len(close) > 11 else 0.0
    s20, s50 = en._last(en.sma(close, 20)), en._last(en.sma(close, 50))

    def v(cond_buy, cond_sell):
        return 1 if cond_buy else -1 if cond_sell else 0
    sigs = [("RSI (14)", tr(rsi, 1), v(rsi == rsi and rsi < 30, rsi == rsi and rsi > 70)),
            ("MACD (12, 26, 9)", tr(mv), 1 if mv > sv else -1),
            ("Stochastic %K (14)", tr(st_k, 1), v(st_k == st_k and st_k < 20, st_k == st_k and st_k > 80)),
            ("Momentum (10)", chg(mom), 1 if mom > 0 else -1),
            ("SMA 20", tr(s20), v(s20 == s20 and price > s20, s20 == s20 and price <= s20)),
            ("SMA 50", tr(s50), v(s50 == s50 and price > s50, s50 == s50 and price <= s50))]
    score = sum(x for _, _, x in sigs)
    buy, sell = sum(1 for *_, x in sigs if x > 0), sum(1 for *_, x in sigs if x < 0)
    label = ("Strong Buy" if score >= 3 else "Buy" if score >= 1 else "Strong Sell" if score <= -3 else
             "Sell" if score <= -1 else "Neutral")
    return {"signals": sigs, "score": score, "buy": buy, "sell": sell, "neutral": len(sigs) - buy - sell,
            "label": label, "color": UP if score >= 1 else DOWN if score <= -1 else NEU}


def gauge(value, steps, height=150, number=False):
    fig = go.Figure(go.Indicator(
        mode="gauge+number" if number else "gauge", value=value,
        number={"font": {"size": 44, "color": TXT}},
        gauge={"axis": {"range": [0, 100], "visible": number, "tickvals": [0, 25, 50, 75, 100]},
               "bar": {"color": "rgba(0,0,0,0)"}, "borderwidth": 0, "steps": steps,
               "threshold": {"line": {"color": TXT, "width": 4}, "thickness": 0.92, "value": value}}))
    fig.update_layout(height=height, margin=dict(l=18, r=18, t=6, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      font={"color": TXT})
    return fig


def pivots(df):
    rec = df.tail(5)
    Hh, Ll, C = float(rec["High"].max()), float(rec["Low"].min()), float(df["Close"].iloc[-1])
    P = (Hh + Ll + C) / 3
    return [("S2", P - (Hh - Ll), UP), ("S1", 2 * P - Hh, UP), ("P", P, NEU), ("R1", 2 * P - Ll, DOWN),
            ("R2", P + (Hh - Ll), DOWN)], C


# ======================================================================
# Üst bar + arama
# ======================================================================
SITE_INDEX = [
    ("Value grade · fair value", "Valuation", "A–Z value grade and fair value for the coming years"),
    ("Valuation model · company type", "Valuation", "Cyclical, defensive, growth tech or capital intensive · CAPM"),
    ("Cycle position & timing", "Valuation", "Estimated next peak or trough for cyclical companies"),
    ("Multiples compared with peers", "Valuation", "P/E, PEG, EV/EBITDA and growth map"),
    ("Balance-sheet consistency · Piotroski · Altman Z", "Valuation", "Quality and bankruptcy-risk scores"),
    ("Cyclicality and seasonality", "Valuation", "Beta, behaviour in sell-offs, returns by month"),
    ("Discounted cash flow (DCF) · reverse DCF", "Valuation", "Growth priced in by the market"),
    ("Fear & Greed Index", "Long Term", "Market sentiment gauge (CNN)"),
    ("Cheap companies (PEG / Forward PE)", "Long Term", "Value screen"),
    ("Sector performance · company heat map", "Markets", "Click a sector → daily performance of its companies"),
    ("Technical summary · support & resistance", "Markets", "Indicators and pivot levels for the selected symbol"),
    ("Top movers (gainers / losers)", "Markets", "Today's biggest movers"),
    ("Upcoming IPOs", "Markets", "IPO calendar"),
    ("Swing opportunities · scan", "Short Term", "Stocks matching your filter"),
    ("Edit filter · criteria", "Short Term", "Change RSI, MACD, volume and other conditions"),
    ("Position size calculator", "Short Term", "Shares based on account and risk %"),
    ("My open trades · trade journal", "Short Term", "Tracked trades"),
    ("Strategy lab · backtest", "Backtest", "Combine indicators and test them on history"),
    ("Stop loss · take profit · equity curve", "Backtest", "Exit rules and results"),
    ("FX pairs · forex chart", "Forex & News", "FX pairs"),
    ("Economic calendar", "Forex & News", "Macro data releases"),
    ("Market news", "Forex & News", "Forex, central banks, commodities, Turkey"),
]


def render_search(q):
    ql = q.lower()
    syms = md.search_symbols(q)
    inds = en.find_indicators(q)
    pages = [x for x in SITE_INDEX if ql in x[0].lower() or ql in x[2].lower() or ql == x[1].lower()][:5]
    with st.container(border=True):
        H(f'<div class="muted">Results for “{esc(q)}”</div>')
        parts = []
        if syms:
            rows = ""
            for r in syms:
                t = r["ticker"]
                meta = " · ".join(x for x in [r.get("name"), r.get("type"), r.get("exchange"), r.get("sector")] if x)
                d = f'<div class="muted small" style="margin-top:2px">{esc(r["desc"])}</div>' if r.get("desc") else ""
                add = "" if t in ss.watchlist else \
                    f'<a class="sr-act" target="_self" href="{link(add_wl=t)}">☆ Add to watchlist</a>'
                rows += (f'<div class="sr-row"><a class="plain sr-main" target="_self" '
                         f'href="{link(sec="Markets", sym=t, opp=None)}">{avatar(t, 32)}<div style="min-width:0">'
                         f'<b class="mono">{esc(t)}</b><div class="muted small">{esc(meta)}</div>{d}</div></a>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Markets", sym=t, opp=None)}">'
                         f'Open chart →</a>{add}</div>')
            parts.append(("sym", f'<div class="boxlbl" style="margin-top:10px">Symbols</div>{rows}'))
        if inds:
            rows = ""
            for n in inds:
                meta = en.INDICATORS[n]
                rows += (f'<div class="sr-row"><div class="sr-main"><span class="ficon">∿</span><div>'
                         f'<b>{esc(n)}</b> <span class="chip">{esc(meta["group"])}</span>'
                         f'<div class="muted small" style="margin-top:2px">{esc(meta["desc"])}</div></div></div>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Short Term", add_flt=n)}">Add to filter</a>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Backtest", add_bt=n)}">Add to backtest</a>'
                         f'</div>')
            parts.append(("ind", f'<div class="boxlbl" style="margin-top:10px">Indicators</div>{rows}'))
        # "rsi", "macd" gibi indikatör aramalarında indikatörler üstte
        if inds and (ql in en.ALIASES or any(n.lower().startswith(ql) for n in inds)):
            parts.sort(key=lambda p: p[0] != "ind")
        for _, chunk in parts:
            H(chunk)
        if pages:
            H('<div class="boxlbl" style="margin-top:10px">Pages &amp; settings</div>' + "".join(
                f'<div class="sr-row"><a class="plain sr-main" target="_self" href="{link(sec=p)}">'
                f'<span class="ficon">↗</span><div><b>{esc(t)}</b><div class="muted small">{esc(p)} · '
                f'{esc(dsc)}</div></div></a></div>' for t, p, dsc in pages))
        raw = _SYM_RE.sub("", q).upper()[:24]
        if raw and not any(r["ticker"] == raw for r in syms):
            H(f'<div class="sr-row"><a class="plain sr-main" target="_self" '
              f'href="{link(sec="Markets", sym=raw, opp=None)}"><span class="ficon">⌕</span><div>'
              f'<b class="mono">{esc(raw)}</b><div class="muted small">Open this symbol directly (Yahoo Finance '
              f'symbol, e.g. GARAN.IS, EURUSD=X, BTC-USD)</div></div></a></div>')
        if not (syms or inds or pages):
            H('<div class="muted" style="margin-top:6px">No results.</div>')


THEMES = {
    "gece": {"name": "Night", "bg": "#0A0B0D", "panel": "#111317", "panel2": "#0C0D10",
             "border": "#22262D", "grad": None, "dot": "#5B8CFF"},
    "uzay": {"name": "Space", "bg": "#07060F", "panel": "#131029", "panel2": "#0C0A1A",
             "border": "#2C2457", "dot": "#A78BFA",
             "grad": ("radial-gradient(1200px 620px at 12% -8%, rgba(124,58,237,.26), transparent 62%),"
                      "radial-gradient(900px 520px at 88% 6%, rgba(37,99,235,.20), transparent 60%),"
                      "radial-gradient(700px 400px at 55% 110%, rgba(14,165,233,.12), transparent 60%)")},
    "orman": {"name": "Forest", "bg": "#060D0A", "panel": "#0E1A14", "panel2": "#0A130F",
              "border": "#1F3C2F", "dot": "#34D399",
              "grad": ("radial-gradient(1100px 620px at 8% -6%, rgba(16,122,87,.26), transparent 62%),"
                       "radial-gradient(850px 480px at 92% 10%, rgba(132,204,22,.12), transparent 60%)")},
    "okyanus": {"name": "Ocean", "bg": "#050D14", "panel": "#0C1824", "panel2": "#08121A",
                "border": "#1C3448", "dot": "#22D3EE",
                "grad": ("radial-gradient(1150px 640px at 85% -8%, rgba(14,116,144,.28), transparent 62%),"
                         "radial-gradient(800px 460px at 10% 12%, rgba(37,99,235,.16), transparent 60%)")},
    "gunbatimi": {"name": "Sunset", "bg": "#100A0A", "panel": "#1B1113", "panel2": "#140D0F",
                  "border": "#3E2429", "dot": "#F5B544",
                  "grad": ("radial-gradient(1100px 600px at 18% -6%, rgba(234,88,12,.22), transparent 62%),"
                           "radial-gradient(820px 460px at 88% 14%, rgba(190,24,93,.16), transparent 60%)")},
    "beyaz": {"name": "White", "bg": "#F4F5F7", "panel": "#FFFFFF", "panel2": "#F3F5F8",
              "border": "#E1E4EA", "grad": None, "dot": "#3B6EF5", "light": True},
}
# Beyaz temada Streamlit'in kendi bileşenleri (koyu temel tema) açık renge çekilir
LIGHT_CSS = """
.stApp,[data-testid="stAppViewContainer"]{color:#14171C}
[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] p,[data-testid="stCaptionContainer"],
[data-testid="stWidgetLabel"],[data-testid="stWidgetLabel"] p,label,.stRadio label,.stCheckbox label{color:#2E3440}
[data-testid="stCaptionContainer"]{color:#5F6878 !important}
[data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="input"]>div,[data-baseweb="textarea"],
[data-baseweb="base-input"],input,textarea{background-color:#FFFFFF !important;color:#14171C !important;
 border-color:#D9DDE3 !important}
[data-baseweb="select"] svg,[data-baseweb="input"] svg{fill:#5F6878 !important;color:#5F6878 !important}
[data-baseweb="select"] span,[data-baseweb="select"] div{color:#14171C}
[data-baseweb="popover"] ul,[data-baseweb="popover"] [role="listbox"],[data-baseweb="menu"]{background:#FFFFFF !important}
[data-baseweb="popover"] li,[data-baseweb="popover"] [role="option"]{color:#14171C !important;background:#FFFFFF}
[data-baseweb="popover"] li:hover,[data-baseweb="popover"] [aria-selected="true"]{background:#EEF1F5 !important}
[data-testid="stPopoverBody"],[data-baseweb="popover"]>div{background:#FFFFFF !important;color:#14171C;
 border-color:#E1E4EA !important}
.stButton button,[data-testid="stBaseButton-secondary"],[data-testid="stPopover"] button,
[data-testid="stBaseButton-tertiary"]{background:#FFFFFF !important;color:#14171C !important;
 border:1px solid #D9DDE3 !important}
.stButton button:hover,[data-testid="stBaseButton-secondary"]:hover{border-color:#3B6EF5 !important;
 color:#3B6EF5 !important}
[data-testid="stBaseButton-primary"]{color:#FFFFFF !important}
[data-testid="stExpander"] details,[data-testid="stExpander"] summary{background:#FFFFFF !important;
 color:#14171C !important;border-color:#E1E4EA !important}
[data-testid="stExpander"] summary:hover{color:#3B6EF5 !important}
[data-testid="stExpander"] svg{fill:#5F6878 !important;color:#5F6878 !important}
[data-testid="stButtonGroup"] button,[data-testid="stBaseButton-segmented_control"],
[data-testid="stBaseButton-segmented_controlActive"]{background:#FFFFFF !important;color:#2E3440 !important;
 border-color:#D9DDE3 !important}
[data-testid="stBaseButton-segmented_controlActive"]{background:#E8EEFB !important;color:#1E4FD6 !important;
 border-color:#9FB7F5 !important}
[data-testid="stTabs"] button p{color:#2E3440}
[data-testid="stAlert"]{color:#14171C}
[data-testid="stToast"]{background:#FFFFFF !important;color:#14171C !important}
[data-testid="stSlider"] div{color:#2E3440}
[data-testid="stNumberInput"] button{background:#F3F5F8 !important;color:#2E3440 !important}
[data-testid="stDataFrame"],[data-testid="stDataFrameResizable"]{filter:invert(1) hue-rotate(180deg)}
[data-testid="stTable"] table,[data-testid="stTable"] td,[data-testid="stTable"] th{color:#14171C}
header[data-testid="stHeader"] *{color:#2E3440}
"""


def theme_css(key):
    t = THEMES.get(key) or THEMES["gece"]
    grad = (f"background-image:{t['grad']};background-attachment:fixed;background-repeat:no-repeat;"
            if t.get("grad") else "background-image:none;")
    return (
        "<style>"
        f'[data-testid="stAppViewContainer"],.stApp,body{{background-color:{t["bg"]};{grad}}}'
        '[data-testid="stMain"],[data-testid="stMainBlockContainer"],section.main{background:transparent}'
        f'div[data-testid="stVerticalBlockBorderWrapper"]{{background:{t["panel"]};border-radius:18px;'
        f'border-color:{t["border"]}}}'
        f'.opp,.idx,.feat,.regime,.kpi,.critbar,.wll,.jt{{background:{t["panel"]};border-color:{t["border"]}}}'
        f'.tile,.card,.nwi,.funnel div{{background:{t["panel2"]};border-color:{t["border"]}}}'
        f'.dot-live{{background:{t["dot"]}}}'
        + (LIGHT_CSS if t.get("light") else "") +
        "</style>")


def panel(label, key):
    """Başlıktaki açılır kutu: st.popover varsa onu, yoksa expander'ı kullanır."""
    p = getattr(st, "popover", None)
    return p(label) if p else st.expander(label)


def notes_body():
    n = ss.notes
    H(f'<div style="font-size:13px;font-weight:800;margin-bottom:4px">Notifications</div>'
      f'<div class="muted small">The AI scan posts here when it finds a fresh, confirmed breakout. '
      f'It runs while the app is open; no scanning happens while it is closed.</div>')
    if not n:
        H('<div class="muted" style="padding:10px 0">No notifications yet.</div>')
    else:
        rows = ""
        for x in n[:20]:
            rows += (f'<a class="nw" target="_self" href="{link(sec="Markets", sym=x["ticker"])}">'
                     f'<span class="nwb"><b>{esc(x["title"])}</b>'
                     f'<span class="muted small nwm">{esc(x["body"])} · {esc(x["at"])}</span></span>'
                     f'<span class="nwx">→</span></a>')
        H(rows)
    if button("Mark as read", key="btn_notes_seen"):
        ss.notes_seen = len(ss.notes)
        st.rerun()
    if button("Clear notifications", key="btn_notes_clear"):
        gone = list(ss.get("notes_gone") or [])
        gone += [f'{x["ticker"]}|{x["day"]}' for x in ss.notes]
        ss.notes_gone = list(dict.fromkeys(gone))[-300:]
        ss.notes, ss.notes_seen = [], 0
        st.rerun()


def account_body():
    H(f'<div style="font-size:13px;font-weight:800">Account</div>'
      f'<div class="muted small">Local session · <span class="mono">{esc(SID)}</span></div>'
      f'<div class="muted small" style="margin-top:2px">Settings are kept for this browser session; '
      f'if you share the link it opens with the same settings.</div>')
    au = ss.get("auth") or {}
    cr = auth_load() or {}
    where = {"file": "on this server (cleared when the app restarts — add it to Secrets to keep it)",
             "secrets": "in the app's Secrets (permanent)"}.get(cr.get("where"), "—")
    H(f'<div class="muted small" style="margin-top:6px">Signed in as <b>{esc(au.get("user") or "")}</b> · '
      f'login stored {esc(where)} · you are signed out after {AUTH_IDLE // 60} minutes without activity</div>')
    if button("Sign out", key="btn_signout"):
        ss.auth = None
        ss["auth_mode"] = None
        st.rerun()
    if is_owner():
        users_admin()
    H('<div style="font-size:12px;font-weight:700;margin:12px 0 4px 0">Background theme</div>')
    names = [THEMES[k]["name"] for k in THEMES]
    cur = THEMES.get(ss.get("theme") or "gece", THEMES["gece"])["name"]
    picked = seg("Theme", names, "w_theme", cur)
    key = next((k for k, v in THEMES.items() if v["name"] == picked), "gece")
    if key != ss.get("theme"):
        ss.theme = key
        st.rerun()
    def _rgb(h):     # rgb() yazımı beyaz temadaki renk dönüşümünden etkilenmez → örnekler gerçek renginde
        h = h.lstrip("#")
        return "rgb(%d,%d,%d)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    sw = "".join(f'<span title="{esc(v["name"])}" style="width:26px;height:26px;border-radius:8px;'
                 f'display:inline-block;border:2px solid {ACCENT if k == ss.theme else "transparent"};'
                 f'background:{_rgb(v["bg"])};box-shadow:inset 0 0 0 1px {_rgb(v["border"])}"></span>'
                 for k, v in THEMES.items())
    H(f'<div style="display:flex;gap:7px;margin-top:8px">{sw}</div>')
    H('<div style="font-size:12px;font-weight:700;margin:14px 0 4px 0">Data</div>')
    if button("Clear cache and reload", key="btn_cacheclear"):
        for fn in (md.get_market_snapshot, md.get_daily_batch, md.get_intraday_batch,
                   md.get_universe_history):
            try:
                fn.clear()
            except Exception:
                pass
        for fn in (run_ai_scan, run_scan, ch.build_payload, get_regime):
            try:
                fn.clear()
            except Exception:
                pass
        ss.ai_nonce = int(ss.get("ai_nonce", 0)) + 1
        st.toast("Cache cleared — reloading data")
        st.rerun()
    H('<div class="muted small" style="margin-top:8px">Prices from Yahoo Finance, scan universe from the Nasdaq '
      'screener, sentiment from CNN, calendar from ForexFactory.</div>')


def render_header():
    H(theme_css(ss.get("theme") or "gece"))
    c1, c2, c3 = st.columns([5.0, 2.3, 1.6], vertical_alignment="center")
    with c1:
        nav = "".join(f'<a class="{"active" if s == SEC else ""}" target="_self" '
                      f'href="{link(sec=s, opp=None, aip=None, sector=None)}">{esc(s)}</a>' for s in SECTIONS)
        H(f'<div class="hdr"><div class="brand">{LOGO_SVG}<span>Pulse</span></div><nav class="navbar">{nav}</nav></div>')
    with c2:
        q = st.text_input("Search", key="q", placeholder="🔍  Search symbol, FX pair, indicator…",
                          label_visibility="collapsed")
    with c3:
        n_new = max(0, len(ss.notes) - int(ss.get("notes_seen") or 0))
        p1, p2 = st.columns(2)
        with p1:
            with panel(f"🔔 {n_new}" if n_new else "🔔", "pop_notes"):
                notes_body()
        with p2:
            with panel("A", "pop_acct"):
                account_body()
    H('<div class="hdr-line"></div>')
    if q and q.strip():
        render_search(q.strip()[:60])


def health_panel():
    h = md.get_data_health()
    ok = lambda b: "✅" if b else "⚠️"
    label = "🟢 Live data" if h["yf_ok"] else "🟡 Price data is sample right now"
    with st.expander(f"🔎 Data sources — {label}", expanded=not h["yf_ok"]):
        H(f'<div class="small" style="line-height:1.9">{ok(h["yf_ok"])} Prices / charts / news (Yahoo): '
          f'{esc(h["yf_msg"])}<br>{ok(h["cnn_ok"])} Fear &amp; Greed (CNN)<br>{ok(h["cal_ok"])} Economic calendar '
          f'(ForexFactory)</div>')
        if not h["yfinance_installed"]:
            st.warning("The `yfinance>=0.2.54` line is missing from requirements.txt, or an old file is uploaded. "
                       "Upload the current requirements.txt and reboot.")
        elif not h["yf_ok"]:
            st.info("Yahoo is temporarily not responding (common for shared cloud IPs). Data is retried automatically "
                    "within 1–2 minutes; meanwhile sample data is shown, **clearly labelled**.")


# ======================================================================
# BÖLÜM: PİYASALAR
# ======================================================================
def range_controls(lb_key, tf_key):
    """Lookback (görünür dönem) ve mum aralığı — iki ayrı seçim."""
    apply_pending_tf(tf_key)
    if ss.get(tf_key) not in TF_LIST:
        ss[tf_key] = ch.norm_tf(ss.get(tf_key) or ss.get("_last_" + tf_key) or TF_DEF)
    c1, c2 = st.columns([3.3, 1], vertical_alignment="bottom")
    with c1:
        H('<div class="muted small" style="margin:12px 0 3px 0">Lookback period</div>')
        lb = seg("Lookback period", LB_LIST, lb_key, LB_DEF)
    with c2:
        tf = st.selectbox("Candle interval", TF_LIST, key=tf_key, format_func=lambda t: TF_NAME.get(t, t))
    ss["_last_" + tf_key] = tf
    return lb, tf


def period_stats(df, dec):
    """Lookback dönemi: açılış, yüksek, düşük, kapanış ve dönem getirisi."""
    if df is None or df.empty:
        return ""
    o, c = float(df["Open"].iloc[0]), float(df["Close"].iloc[-1])
    ch_ = (c / o - 1) * 100 if o else 0.0
    return (f'<span class="muted">Open <span class="mono" style="color:{TXT}">{tr(o, dec)}</span></span>'
            f'<span class="muted">High <span class="mono" style="color:{TXT}">{tr(df["High"].max(), dec)}</span></span>'
            f'<span class="muted">Low <span class="mono" style="color:{TXT}">{tr(df["Low"].min(), dec)}</span></span>'
            f'<span class="muted">Close <span class="mono" style="color:{TXT}">{tr(c, dec)}</span></span>'
            f'<span class="muted">Period <span class="mono" style="color:{col(ch_)};font-weight:600">'
            f'{pct(ch_)}</span></span>')


def render_chart_panel(sym):
    """Grafik paneli. Teknik özet ve destek/direnç için günlük geçmişi döndürür."""
    d = md.get_company_detail(sym)
    daily = md.get_history(sym)
    if d is None or daily.empty:
        H(f'<div class="panel-title">{esc(sym)}</div><div class="muted" style="margin:10px 0 16px 0">Could not load '
          f'data for this symbol. Check the Yahoo Finance symbol (e.g. <span class="mono">THYAO.IS</span> for BIST, '
          f'<span class="mono">EURUSD=X</span> for FX pairs) or try again in a few minutes.</div>')
        return None, TF_DEF, None
    cur = d.get("currency") or "USD"
    dec = pdec(sym, d["last"])
    h1, h2 = st.columns([2.6, 1.15], vertical_alignment="top")
    with h1:
        H(f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">{avatar(sym, 30)}'
          f'<span class="panel-title">{esc(d["name"])}</span><span class="chip mono">{esc(sym)}</span>'
          f'{src_chip(d.get("src"))}</div>'
          f'<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-top:6px">'
          f'<span class="mono" style="font-size:32px;font-weight:600;letter-spacing:-.03em">{tr(d["last"], dec)}</span>'
          f'<span class="mono" style="color:{col(d["change_abs"])};font-weight:600;font-size:14px">'
          f'{chg(d["change_abs"], dec)} ({pct(d["change_pct"])})</span>'
          f'<span class="muted">Today · {esc(cur)}</span></div>')
    with h2:
        in_wl = sym in ss.watchlist
        if button("★ Watching — remove from list" if in_wl else "☆ Add to watchlist", key="wl_toggle"):
            if in_wl:
                ss.watchlist.remove(sym)
            else:
                ss.watchlist.append(sym)
            st.rerun()
    lead = d.get("desc") or ""
    en_sum = d.get("summary_en") or ""
    if not lead and en_sum:
        lead = en_sum[:260] + ("…" if len(en_sum) > 260 else "")
    if not lead and d.get("sector"):
        lead = f'{d["name"]} is a company in the {d["sector"]} sector.'
    meta = " · ".join(x for x in [d.get("sector"), d.get("industry"), d.get("country")] if x)
    web = (f' · <a class="lnk" href="{esc(safe_url(d.get("website")))}" target="_blank">website ↗</a>'
           if safe_url(d.get("website")) else "")
    if lead:
        H(f'<div class="desc">{esc(lead)}</div>')
    if meta or web:
        H(f'<div class="muted small" style="margin-top:4px">{esc(meta)}{web}</div>')
    if en_sum and (d.get("desc") or len(en_sum) > 260):
        with st.expander("About the company — details (Yahoo Finance)"):
            H(f'<div class="desc" style="margin:0">{esc(en_sum)}</div>')
    anchor("chart")
    if SECTOR and md.sector_by_etf(SECTOR):
        H(f'<div class="small" style="margin:6px 0 -4px 0"><a class="lnk" target="_self" '
          f'href="{link(f="sectormap")}">↓ back to the {esc(md.sector_by_etf(SECTOR)[0])} heat map</a></div>')
    lb, tf = range_controls("w_lb", "w_tf")
    full, bars, intr = chart_data(sym, tf, lb)
    df = full.tail(bars)
    note = ch.lookback_note(full, tf, lb, bars, intr)
    H(f'<div style="display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px;margin:10px 0 6px 0">'
      f'{period_stats(df, dec)}'
      f'<span class="muted">{esc(ch.LOOKBACKS[ch.norm_lb(lb)]["name"])} · {candle_label(tf, intr)}</span>'
      f'<span style="flex:1"></span>'
      f'<span class="muted small">wheel / double-click: zoom in · right-click or ＋− buttons: zoom out · '
      f'drag: pan (also up / down) · ▲ ▼ · ↑ ↓ or Shift + wheel: scroll up / down · trackpad: two fingers · click a drawing: colour · “Fullscreen”</span></div>'
      + (f'<div class="muted small" style="color:{WARN};margin-bottom:6px">{esc(note)}</div>' if note else ""))
    render_big_chart(sym, tf, height=620, tf_key="w_tf", lb=lb)
    fired = ch.check_alerts(ss.alerts.get(sym, []), daily)
    for a in fired:
        st.toast(f"🔔 {sym}: {ch.alert_text(a)} — triggered")
    with st.expander("Key stats"):
        g = st.columns(4)
        items = [("Market cap", big(d["market_cap"], cur)), ("P/E", tr(d["pe"])), ("Fwd P/E", tr(d["fwd_pe"])),
                 ("EPS", tr(d["eps"])), ("Revenue (ttm)", big(d["revenue"], cur)), ("Net income", big(d["net_income"], cur)),
                 ("52W range", f'{tr(d["low_52w"], dec)} – {tr(d["high_52w"], dec)}'), ("Beta", tr(d["beta"])),
                 ("Dividends", f'{money(d["dividend"], cur)} ({tr(d["div_yield"])}%)' if d["dividend"] else "—"),
                 ("Analysts", d["analysts"]), ("Price target", money(d["price_target"], cur)),
                 ("Earnings", d["earnings_date"].strftime("%b %d, %Y") if d.get("earnings_date") is not None else "—")]
        for i, (k, v) in enumerate(items):
            with g[i % 4]:
                H(f'<div class="stat-row"><span class="lbl">{esc(k)}</span><span class="mono">{esc(v)}</span></div>')
    return daily, tf, full


_BOLD = re.compile(r"\*\*(.+?)\*\*")
GRADE_TONE = {"bull": UP, "flat": NEU, "bear": DOWN}


def grade_color(score):
    """0–100 skoru yeşil→sarı→kırmızı bandına oturtur."""
    if score >= 72:
        return UP
    if score >= 58:
        return "#A3D977"
    if score >= 44:
        return WARN
    if score >= 30:
        return "#F08A6A"
    return DOWN


@st.cache_data(ttl=600, show_spinner=False)
def _grade_cached(sym, tf, token, _df):
    return en.grade(_df, tf_name=TF_ADJ.get(ch.norm_tf(tf), "daily"))


def render_tech(df, tf="1A", sym=""):
    """Teknik Özet: A–Z notu, grup kırılımı, kural tabanlı yorum ve klasik gösterge listesi."""
    H(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
      f'<span class="panel-title">Technical Summary</span>'
      f'<span class="muted small srcap">{esc(TF_ADJ.get(ch.norm_tf(tf), "daily").capitalize())} candles</span></div>')
    g = None
    try:
        g = _grade_cached(sym, tf, ch.data_token(sym, tf) if sym else str(len(df)), df)
    except Exception:
        g = None
    if g:
        c = grade_color(g["score"])
        H(f'<div class="grade"><div class="gletter" style="color:{c};background:{c}1F;border:1px solid {c}55">'
          f'{g["letter"]}</div><div style="min-width:0">'
          f'<div class="gact" style="color:{GRADE_TONE.get(g["tone"], NEU)}">{esc(g["action"])}</div>'
          f'<div class="gsc">{tr(g["score"], 0)} / 100 · A strongest buy, Z strongest sell</div></div></div>'
          f'<div class="gscale"><i style="left:{100 - g["score"]:.1f}%"></i></div>'
          f'<div class="gax"><span>A · buy</span><span>M–N · neutral</span><span>Z · sell</span></div>')
        rows = ""
        for grp in g["groups"]:
            gc = grade_color(grp["score"])
            rows += (f'<div class="grow"><span class="gn">{esc(grp["name"])}</span>'
                     f'<span class="gw">{grp["weight"]}%</span>'
                     f'<span class="gb"><i style="width:{max(2, grp["score"]):.0f}%;background:{gc}"></i></span>'
                     f'<span class="gv">{tr(grp["score"], 0)}</span></div>')
        H(rows)
        H(f'<div class="gtext">{_BOLD.sub(r"<b>\1</b>", esc(g["text"]))}</div>')
        with st.expander("Why this grade — what each group looked at"):
            for grp in g["groups"]:
                items = "".join(f"<div>• {esc(r)}</div>" for r in grp["reasons"]) or \
                    '<div class="muted">—</div>'
                H(f'<div style="margin-bottom:9px"><div style="font-size:12px;font-weight:700;color:{SOFT}">'
                  f'{esc(grp["name"])} <span class="muted">· {tr(grp["score"], 0)}/100 · '
                  f'{tr(grp["points"], 1)} pts contribution</span></div>'
                  f'<div class="greason">{items}</div></div>')
            if g["patterns"]:
                pr = "".join(f'<div>• {esc(p["name"])} — {esc(p.get("note") or "")} '
                             f'<span class="muted">(confidence {tr(p["conf"] * 100, 0)}%)</span></div>'
                             for p in g["patterns"])
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT}">Patterns found</div>'
                  f'<div class="greason">{pr}</div>')
            H('<div class="muted small" style="margin-top:8px">The grade is rule-based: each group is scored '
              'from real indicator values; weights are momentum 25%, pattern 20%, volume 20%, '
              'risk/reward 20%, trend 10%, volatility 5%. Not investment advice.</div>')
    else:
        H('<div class="muted" style="margin:8px 0">Not enough bars on this timeframe for a grade '
          '(at least 30 candles needed).</div>')
    try:
        t = en.indicator_board(df, ss.ch_cfg, ch.norm_tf(tf), ch.DEFAULT_CFG)
    except Exception:
        t = None
    if not t or not t["rows"]:
        H('<div class="muted small" style="margin:10px 0">Not enough bars to evaluate indicators.</div>')
        return
    n_chart = sum(1 for r in t["rows"] if r["src"] == "chart")
    n_auto = len(t["rows"]) - n_chart
    lc = UP if "Buy" in t["label"] else DOWN if "Sell" in t["label"] else NEU
    sub = (f'{n_chart} on your chart' + (f' + {n_auto} auto-picked for {en.TF_KIND_NAME[t["kind"]]}' if n_auto else ""))
    H(f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:12px 0 2px 0">'
      f'<span style="font-size:12px;font-weight:700;color:{SOFT}">Indicators <span class="muted" '
      f'style="font-weight:500">· {esc(sub)}</span></span>'
      f'<span class="badge" style="color:{lc};background:{lc}22">{esc(t["label"])}</span></div>')
    tiles = "".join(f'<div class="tile" style="align-items:center"><span class="k">{k}</span>'
                    f'<span class="v" style="font-size:17px;color:{c}">{v}</span></div>'
                    for k, v, c in [("Sell", t["sell"], DOWN), ("Neutral", t["neutral"], NEU), ("Buy", t["buy"], UP)])
    H(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 4px 0">{tiles}</div>')
    rows = ""
    for r in t["rows"]:
        v = r["sig"]
        lab, fg, bg = ("Buy", UP, UP_BG) if v > 0 else ("Sell", DOWN, DOWN_BG) if v < 0 else ("Neutral", NEU, NEU_BG)
        tag = ('<span class="chip" style="font-size:9.5px;padding:0 5px;margin-left:5px">auto</span>'
               if r["src"] == "auto" else "")
        rows += (f'<div class="stat-row ind-row"><span class="lbl">{esc(r["name"])}{tag}'
                 f'<span class="ind-note">{esc(r["note"])}</span></span>'
                 f'<span class="mono" style="font-size:12px;white-space:nowrap">{esc(r["value"])}</span>'
                 f'<span class="badge" style="color:{fg};background:{bg};width:52px;text-align:center">'
                 f'{lab}</span></div>')
    H(rows)
    hint = ("Add indicators on the chart (Indicators button) and they are evaluated here with your settings."
            if t["auto"] else "Evaluating the indicators on your chart with your settings. Remove the extras "
            "to get the auto-picked set for this timeframe again.")
    H(f'<div class="muted small" style="margin:8px 0 4px 0">{esc(hint)}</div>')


def render_sr(df, sym):
    levels, price = pivots(df)
    dec = pdec(sym, price)
    cells = "".join(f'<div class="tile"><span class="k" style="color:{fg};font-weight:800">{k}</span>'
                    f'<span class="v">{tr(v, dec)}</span><span class="mono" style="font-size:11px;color:{MUT}">'
                    f'{pct((v / price - 1) * 100)}</span></div>' for k, v, fg in levels)
    H(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px">'
      f'<span class="panel-title">Support &amp; Resistance</span>'
      f'<span class="muted small srcap">Classic pivots · daily · last price {tr(price, dec)}</span></div>'
      f'<div class="srstrip">{cells}</div>')
    try:
        gaps = en.price_gaps(df, lookback=260, max_n=6)
    except Exception:
        gaps = []
    if gaps:
        gaps = sorted(gaps, key=lambda g: -g["hi"])          # yukarıdan aşağıya: direnç → destek
        gc = ""
        for g in gaps:
            fg = DOWN if g["kind"] == "res" else UP
            role = "Resistance" if g["kind"] == "res" else "Support"
            arrow = "▲ gap up" if g["dir"] == "up" else "▼ gap down"
            when = pd.Timestamp(g["date"]).strftime("%b %d, %Y")
            gc += (f'<div class="tile gaptile" style="border-left:3px solid {fg}">'
                   f'<span class="k" style="color:{fg};font-weight:800">{role} · {arrow}</span>'
                   f'<span class="v" style="font-size:13px">{tr(g["lo"], dec)} – {tr(g["hi"], dec)}</span>'
                   f'<span class="mono" style="font-size:11px;color:{MUT}">{pct(g["dist"], 1)} · {when} · '
                   f'size {tr(g["pct"], 1)}%</span></div>')
        H(f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:12px 0 6px 0">'
          f'<span style="font-size:12px;font-weight:700;color:{SOFT}">Unfilled price gaps</span>'
          f'<span class="muted small">daily · last 12 months · a gap below price acts as support, above as '
          f'resistance · partly filled gaps shrink</span></div><div class="gapgrid">{gc}</div>')
    else:
        H('<div class="muted small" style="margin-top:10px">No unfilled price gaps in the last 12 months.</div>')
    H('<div style="height:6px"></div>')   # kutunun alt kenarına değmesin


def news_link(it):
    """Haberin kendi sayfası; Yahoo bağlantı vermediyse sembolün haber akışı."""
    u = safe_url(it.get("link"))
    if u:
        return u
    t = _SYM_RE.sub("", str(it.get("ticker") or "")).upper()[:12]
    return f"https://finance.yahoo.com/quote/{t}/news/" if t else "https://finance.yahoo.com/topic/stock-market-news/"


def news_rows(items, left=None):
    """Tamamı tıklanabilir haber satırları — kaynağın sitesine yeni sekmede açılır."""
    out = ""
    for it in items:
        sc = {"Bullish": UP, "Bearish": DOWN}.get(it.get("sentiment"), MUT)
        thumb = safe_url(it.get("thumb"))
        if left is not None:
            img = left(it, sc)
        elif thumb:
            img = f'<span class="nwi" style="background-image:url(\'{esc(thumb)}\')"></span>'
        else:
            img = f'<span class="nwi">{esc((it.get("ticker") or it.get("pair") or "•")[:5])}</span>'
        meta = " · ".join(esc(x) for x in [it.get("ticker") or it.get("pair"), it.get("source"),
                                           it.get("when")] if x)
        out += (f'<a class="nw" href="{esc(news_link(it))}" target="_blank" rel="noopener">{img}'
                f'<span class="nwb"><b>{esc(it["title"])}</b>'
                f'<span class="muted small nwm"><span style="color:{sc}">●</span> {meta}</span></span>'
                f'<span class="nwx">↗</span></a>')
    return out


def render_watchlist_compact():
    wl = list(ss.watchlist)
    q = md.get_quotes(wl)
    add = "" if ACTIVE in wl else \
        f'<a class="lnk small" target="_self" href="{link(add_wl=ACTIVE)}">＋ add {esc(ACTIVE)}</a>'
    H(f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span class="panel-title">'
      f'Watchlist</span><span class="chip">{len(wl)}</span><span class="muted small">click → chart</span>'
      f'<span style="margin-left:auto">{add}</span></div>')
    if not wl:
        H('<div class="muted small">The list is empty. Find a symbol with the search above and press “Add to watchlist”.</div>')
        return
    rows = ""
    for t in wl:
        qq = q.get(t)
        last, chp = (qq["last"], qq["change_pct"]) if qq else (float("nan"), float("nan"))
        sel = "background:#151922;" if t == ACTIVE else ""
        rows += (f'<a class="plain" target="_self" href="{link(sym=t)}"><div class="wlr" style="{sel}">'
                 f'{avatar(t, 24)}<div class="nm"><b class="mono">{esc(t)}</b><div>{esc(md.company_name(t))}</div></div>'
                 f'<div class="px"><div style="font-size:12.5px">{tr(last, pdec(t, last))}</div>'
                 f'<div style="font-size:11px;font-weight:700;color:{col(chp) if chp == chp else MUT}">{pct(chp)}'
                 f'</div></div></div></a>')
    H(f'<div class="wll">{rows}</div>')


def squarify(values, x, y, w, h):
    """Kare-yakın treemap yerleşimi (Bruls vd.). values büyükten küçüğe sıralı olmalı.
    Döner: [(x, y, w, h)] — values ile aynı sırada."""
    vals = [max(1e-9, float(v)) for v in values]
    tot = sum(vals)
    if not vals or tot <= 0 or w <= 0 or h <= 0:
        return []
    area = [v / tot * w * h for v in vals]
    out = []

    def worst(row, side):
        s_ = sum(row)
        return max(max(side * side * r / (s_ * s_), (s_ * s_) / (side * side * r)) for r in row)

    i = 0
    while i < len(area):
        side = min(w, h)
        row = [area[i]]
        j = i + 1
        while j < len(area) and worst(row + [area[j]], side) <= worst(row, side):
            row.append(area[j])
            j += 1
        s_ = sum(row)
        if w >= h:                      # dikey şerit (solda)
            cw = s_ / h
            cy = y
            for r in row:
                rh = r / cw
                out.append((x, cy, cw, rh))
                cy += rh
            x, w = x + cw, w - cw
        else:                           # yatay şerit (üstte)
            rh = s_ / w
            cx = x
            for r in row:
                rw = r / rh
                out.append((cx, y, rw, rh))
                cx += rw
            y, h = y + rh, h - rh
        i = j
    return out


def html_treemap(cons, height=560):
    """Tıklanabilir şirket ısı haritası: her kutu o şirketin grafiğini açar."""
    items = sorted([c for c in cons if (c.get("weight") or 0) > 0], key=lambda c: -c["weight"])
    if not items:
        return ""
    W, Hh = 100.0, 100.0
    rects = squarify([c["weight"] for c in items], 0, 0, W, Hh)
    boxes = ""
    for c, (x, y, w, h) in zip(items, rects):
        big_ = w * h
        fs = 15 if big_ > 260 else 13 if big_ > 120 else 11.5 if big_ > 45 else 10
        name = esc(c.get("name") or "") if big_ > 70 else ""
        boxes += (f'<a class="tmb" target="_self" href="{link(sec="Markets", sym=c["ticker"], f="chart")}" '
                  f'title="{esc(c["ticker"])} · {esc(c.get("name") or "")} · {pct(c["change_pct"])} — open chart" '
                  f'style="left:{x:.3f}%;top:{y:.3f}%;width:{w:.3f}%;height:{h:.3f}%;'
                  f'background:{heat_color(c["change_pct"], 3)}">'
                  f'<span class="tmi"><b style="font-size:{fs}px">{esc(c["ticker"])}</b>'
                  + (f'<i>{name}</i>' if name else "") +
                  f'<em style="font-size:{max(9.5, fs - 3):.1f}px">{pct(c["change_pct"])}</em></span></a>')
    return f'<div class="tmap" style="height:{int(height)}px">{boxes}</div>'


def heat_color(ch, scale=2.5):
    a = min(1.0, 0.28 + abs(ch) / scale * 0.7)
    return f'rgba({"16,122,87" if ch >= 0 else "185,45,55"},{a:.2f})'


def render_sector_block():
    anchor("sector")
    secs = md.get_sector_performance()
    srcs = {s["src"] for s in secs}
    H(f'<div class="sec-head"><h3>Sector Performance</h3><span class="muted">Today · click a sector → '
      f'company heat map</span><span style="margin-left:auto">'
      f'{src_chip("real" if srcs == {"real"} else "none" if srcs == {"none"} else "mock")}</span></div>')
    tiles = "".join(f'<a class="plain" target="_self" '
                    f'href="{link(sector=None if SECTOR == s["etf"] else s["etf"], f="sector" if SECTOR == s["etf"] else "sectormap")}">'
                    f'<div class="heat{" sel" if SECTOR == s["etf"] else ""}" style="background:{heat_color(s["change_pct"])}">'
                    f'<b>{esc(s["name"])} <span style="font-size:11px;opacity:.7;font-family:inherit">{s["etf"]}</span>'
                    f'</b><span>{pct(s["change_pct"])}</span></div></a>' for s in secs)
    H(f'<div class="heatgrid">{tiles}</div>')
    if SECTOR:
        H(f'<div class="muted small" style="margin-top:10px">The company heat map opened full-width below '
          f'— <a class="lnk" target="_self" href="{link(sector=None, f="sector")}">✕ close</a></div>')


def render_sector_map():
    """Seçili sektörün şirket ısı haritası — sayfanın tamamını kaplar."""
    if not SECTOR:
        return
    anchor("sectormap")
    sec = md.sector_by_etf(SECTOR)
    if not sec:
        return
    cons = md.get_sector_constituents(SECTOR)
    up = sum(1 for c in cons if c["change_pct"] >= 0)
    with st.container(border=True):
        H(f'<div class="sec-head" style="flex-wrap:wrap"><h3>{esc(sec[0])} · company heat map</h3>'
          f'<span class="muted">{SECTOR} constituents · box size ≈ ETF weight · {up} up / '
          f'{len(cons) - up} down · click a box → its chart opens</span>'
          f'<a class="lnk small" style="margin-left:auto" target="_self" '
          f'href="{link(sector=None, f="sector")}">✕ Close</a></div>')
        if cons:
            H(html_treemap(cons, height=520))
            cells = "".join(f'<a class="plain" target="_self" href="{link(sec="Markets", sym=c["ticker"], f="chart")}">'
                            f'<div class="heat" style="background:{heat_color(c["change_pct"], 3)}"><b>{esc(c["ticker"])}'
                            f' <span style="font-size:10px;opacity:.75;font-family:inherit">{esc(c["name"])}</span></b>'
                            f'<span>{pct(c["change_pct"])}</span></div></a>'
                            for c in sorted(cons, key=lambda c: -c["change_pct"]))
            H(f'<div class="muted small" style="margin:10px 0 6px 0">Sorted by today\'s performance — '
              f'click a company → its chart opens</div><div class="cgrid">{cells}</div>')
        else:
            H('<div class="muted">Could not load constituent data for this sector.</div>')


def render_movers():
    h1, h2 = st.columns([1.2, 1.8], vertical_alignment="center")
    with h1:
        H('<span class="panel-title">Top Movers</span>')
    with h2:
        tab = seg("List", ["Gainers", "Losers"], "w_mov", "Gainers")
    items = md.get_top_movers() if tab == "Gainers" else md.get_top_losers()
    rows = ""
    for q in items:
        c = col(q["change_pct"])
        bg = UP_BG if q["change_pct"] >= 0 else DOWN_BG
        rows += (f'<a class="plain" target="_self" href="{link(sym=q["ticker"])}"><div class="row">'
                 f'{avatar(q["ticker"], 34)}<div style="flex:1;min-width:0"><b class="mono" style="font-size:13px">'
                 f'{esc(q["ticker"])}</b><div class="muted small" style="white-space:nowrap;overflow:hidden;'
                 f'text-overflow:ellipsis">{esc(q["name"])}</div></div><div style="text-align:right">'
                 f'<div class="mono" style="font-size:13px">{tr(q["last"])}</div>'
                 f'<span class="badge mono" style="color:{c};background:{bg}">{pct(q["change_pct"])}</span>'
                 f'</div></div></a>')
    H(rows + (f'<div style="margin-top:8px">{src_chip(items[0]["src"])}</div>' if items else ""))


def render_piyasalar():
    now = pd.Timestamp.now(tz=md.TZ)
    H(f'<div class="page-title">Markets</div><div class="muted" style="margin-bottom:8px"><span class="dot-live">'
      f'</span>{md.tr_date_label(now)} {now.year} · click a card, row or sector</div>')
    health_panel()
    cols = st.columns(4)
    for c_, idx in zip(cols, md.get_index_summary()):
        cc = col(idx["change_pct"])
        act = f"border-color:{ACCENT};background:#151922;" if ACTIVE == idx["ticker"] else ""
        with c_:
            H(f'<a class="plain" target="_self" href="{link(sym=idx["ticker"])}"><div class="idx" style="{act}">'
              f'<div style="display:flex;justify-content:space-between;align-items:baseline"><b style="font-size:13px">'
              f'{idx["subtitle"]}</b><span class="chip mono">{idx["ticker"]}</span></div>'
              f'<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:10px"><div>'
              f'<div class="mono" style="font-size:18px;font-weight:600">{tr(idx["last"])}</div>'
              f'<div class="mono" style="font-size:12px;font-weight:600;color:{cc}">{pct(idx["change_pct"])}</div>'
              f'</div>{svg_spark(idx["series"], cc)}</div></div></a>')
    H("<div style='height:14px'></div>")
    left, right = st.columns([2.15, 1], gap="medium")
    with left:
        with st.container(border=True):
            daily, tf_sel, tf_df = render_chart_panel(ACTIVE)
        if daily is not None:
            with st.container(border=True):
                render_sr(daily, ACTIVE)
    with right:
        if daily is not None:
            with st.container(border=True):
                render_tech(tf_df if tf_df is not None and len(tf_df) >= 30 else daily,
                            tf_sel if tf_df is not None and len(tf_df) >= 30 else "1A", ACTIVE)
        with st.container(border=True):
            render_watchlist_compact()
    b1, b2 = st.columns([2.15, 1], gap="medium")
    with b1:
        with st.container(border=True):
            render_sector_block()
    with b2:
        with st.container(border=True):
            render_movers()
    render_sector_map()        # tam genişlik — dar sütunun altında sıkışmasın
    c1, c2 = st.columns([2.15, 1], gap="medium")
    with c1:
        with st.container(border=True):
            ipo = md.get_upcoming_ipos()
            H(f'<div class="sec-head"><h3>Upcoming IPOs</h3><span style="margin-left:auto">'
              f'{src_chip(ipo.attrs.get("src"))}</span></div>')
            table(ipo)
    with c2:
        with st.container(border=True):
            news = md.get_watchlist_news(ss.watchlist)
            H(f'<div class="sec-head"><h3>Watchlist News</h3>'
              f'<span class="muted small">click a headline → source website</span>'
              f'<span style="margin-left:auto">{src_chip(news[0]["src"] if news else "none")}</span></div>')
            H(news_rows(news[:8]) or '<div class="muted">No news found.</div>')


# ======================================================================
# BÖLÜM: DEĞER ANALİZİ
# ======================================================================
@st.cache_data(ttl=1800, show_spinner="Fetching financial statements…")
def value_bundle(sym, token, peer_ovr=()):
    """Değer analizi için gereken her şey tek yerde — hepsi gerçek veriden."""
    d = md.get_company_detail(sym)
    if not d:
        return None
    stm = md.get_statements(sym)
    f = en.financials(stm)
    px = md.get_history(sym)
    bench = md.get_history("SPY")
    an = md.get_analyst(sym)
    peers = [p for p in peer_ovr if p != sym] if peer_ovr else md.get_peers(sym, 5)
    peer_src = "Your list" if peer_ovr else md.peer_source(sym)
    vals = md.get_valuations([sym] + peers)
    r = en.fin_ratios(f, d) if f else {}
    pe_now = d.get("pe")
    if not en._ok(pe_now) and f and en._ok(f["eps"][-1]) and f["eps"][-1] > 0:
        pe_now = d["last"] / f["eps"][-1]
    band = en.pe_band(px, f, pe_now) if f else None
    fsc = en.piotroski(f) if f else None
    zsc = en.altman_z(f, d.get("market_cap")) if f else None
    cons = en.consistency(f) if f else None
    cyc = en.cyclicality(px, bench, f)
    sea = en.seasonality(px)
    pm = {}
    pv = [vals[p] for p in peers if p in vals]
    for k in ("pe", "fwd_pe", "ev_ebitda", "peg", "growth", "net_margin", "ev_sales", "rev_growth"):
        xs = [v[k] for v in pv if en._ok(v.get(k)) and v[k] > -1e6]
        pm[k] = float(np.median(xs)) if xs else float("nan")
    grade = en.value_grade(r, pm, band, fsc, zsc, cons, cyc, an, d) if f else None
    # şirket tipi + CAPM
    cls = en.classify_company(d, f, r, an, cyc, md.peer_group(sym))
    rf, rf_src = md.get_risk_free()
    cp = en.capm(d.get("beta") if en._ok(d.get("beta")) else (cyc or {}).get("beta"), rf)
    wc = en.wacc_calc(cp["ke"], d.get("market_cap"), (f["debt"][-1] if f else None),
                      (f["interest"][-1] if f else None), rf)
    px_long = md.get_history_max(sym)
    timing = en.cycle_timing(px_long, f, an)
    divst = en.dividend_stats(md.get_dividends(sym), px_long)
    wk = None
    if px_long is not None and len(px_long) > 60:
        c_ = px_long["Close"].astype(float)
        try:
            c_.index = c_.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        wk = c_.resample("W-FRI").last().dropna()
    tnx = md.get_history("^TNX")
    tnx_w = None
    if tnx is not None and len(tnx) > 60 and tnx.attrs.get("src") == "real":
        t_ = tnx["Close"].astype(float)
        try:
            t_.index = t_.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        t_ = t_.resample("W-FRI").last().dropna()
        tnx_w = t_ / 10.0 if float(t_.median()) > 20 else t_
    # model varsayılanları (kullanıcı değer patikası panelinden değiştirebilir)
    is_cyc = cls["type"] == "cyclical" or md.is_cyclical_industry(sym) or \
        bool(cyc and cyc.get("label") in ("Cyclical", "Highly cyclical"))
    # v3.8: varsayılan büyüme YoY — son analist yılının büyümesi, yoksa son raporlanan yılın EPS büyümesi
    est_ = an.get("fy") or []
    yoy_an = ((est_[-1]["avg"] / est_[-2]["avg"] - 1) * 100
              if len(est_) >= 2 and en._ok(est_[-2].get("avg")) and est_[-2]["avg"] > 0 else None)
    yoy_rep = None
    if f and len(f["eps"]) >= 2 and en._ok(f["eps"][-1]) and en._ok(f["eps"][-2]) and f["eps"][-2] > 0:
        yoy_rep = (f["eps"][-1] / f["eps"][-2] - 1) * 100
    cap_hi = 30.0 if is_cyc else 50.0
    g_lt = next((max(-5.0, min(cap_hi, x)) for x in (yoy_an, yoy_rep, an.get("growth_5y")) if en._ok(x)), 8.0)
    drop_hist = en.hist_eps_drop(f["eps"]) if f else None
    # sürücü modeli için ciro büyümesi (YoY): son analist ciro yılı, yoksa son raporlanan yıl
    rv_ = [e for e in (an.get("rev_fy") or []) if en._ok(e.get("avg"))]
    g_rev = None
    if len(rv_) >= 2 and rv_[-2]["avg"] > 0:
        g_rev = (rv_[-1]["avg"] / rv_[-2]["avg"] - 1) * 100
    elif f and len(f["revenue"]) >= 2 and en._ok(f["revenue"][-1]) and en._ok(f["revenue"][-2]) and f["revenue"][-2] > 0:
        g_rev = (f["revenue"][-1] / f["revenue"][-2] - 1) * 100
    g_rev = max(-5.0, min(cap_hi, g_rev)) if en._ok(g_rev) else 6.0
    eps_last = next((x for x in (an.get("eps_last_fy"), d.get("eps"), (f["eps"][-1] if f else None))
                     if en._ok(x)), None)
    dcfv = rdcf = None
    wacc = round(wc["wacc"], 2)
    if f and en._ok(f["fcf"][-1]) and en._ok(f["shares"][-1]) and f["fcf"][-1] > 0:
        nd_ = f["net_debt"][-1] if en._ok(f["net_debt"][-1]) else 0.0
        dcfv = en.dcf(f["fcf"][-1], f["shares"][-1], g_lt, 10, wacc, 2.5, nd_)
        rdcf = en.reverse_dcf(d["last"], f["fcf"][-1], f["shares"][-1], 10, wacc, 2.5, nd_)
    return {"d": d, "f": f, "r": r, "an": an, "peers": peers, "peer_src": peer_src, "vals": vals, "pm": pm,
            "band": band, "fsc": fsc, "zsc": zsc, "cons": cons, "cyc": cyc, "sea": sea, "grade": grade,
            "cls": cls, "rf": rf, "rf_src": rf_src, "capm": cp, "wacc": wc, "timing": timing, "divst": divst,
            "wk": wk, "tnx_w": tnx_w,
            "dcf": dcfv, "rdcf": rdcf, "g_lt": g_lt, "is_cyc": is_cyc, "drop_hist": drop_hist,
            "g_yoy_rep": yoy_rep, "g_rev": g_rev,
            "dhist": en.driver_hist(f, an, wc, rf) if f else None,
            "eps_last": eps_last, "stm_src": stm.get("src", "none"), "pe_now": pe_now,
            "px": px.tail(1300) if px is not None else None,
            "bench": bench.tail(1300) if bench is not None else None,
            "pe_ser": en.pe_series(px.tail(1300), f) if (f and px is not None) else None}


MULT_MODES = ["Today's market multiple", "Peers' forward P/E median", "Own P/E median", "Manual"]
GLT_MIN, GLT_MAX = -20.0, 150.0      # "Long-term growth" (YoY) aralığı — güçlü büyüme dönemleri için %100 üstü
PEAK_MAX = 4                         # kâr zirvesi FY0 … FY0+4 (ufuk FY0+5, zirveden sonra en az bir yıl görünsün)


def vp_state(b, sym):
    """Değer patikası ayarlarının şu anki hali (widget çizilmeden de okunabilir)."""
    an = b["an"]
    fy0 = an.get("fy0") or int(pd.Timestamp.now().year)
    est = an.get("fy") or []
    peak0 = int(np.argmax([e["avg"] for e in est])) if est else 0
    tm_ = b.get("timing") or {}
    et = tm_.get("earnings_turn") or {}
    if b["is_cyc"] and et.get("kind") == "peak" and et.get("fy"):
        peak0 = int(min(PEAK_MAX, max(0, et["fy"] - fy0)))      # döngü zamanlamasının kâr zirvesi tahmini
    dh = b.get("drop_hist")
    dhist = b.get("dhist")
    if dhist:   # sürücü modeli: düşüş = ciro düşüşü (kâr düşüşünün kabaca yarısı)
        drop0 = float(round(min(60.0, max(10.0, (dh if en._ok(dh) else 50.0) * 0.5)) / 5) * 5) if b["is_cyc"] else 25.0
    else:
        drop0 = float(round(min(80.0, max(30.0, dh if en._ok(dh) else 45.0)) / 5) * 5) if b["is_cyc"] else 45.0
    md_ = en.driver_margin_defaults(dhist, an, fy0) if dhist else {"last": 15.0, "peak": 25.0, "trough": 5.0}
    g_rev = b.get("g_rev") if en._ok(b.get("g_rev")) else 6.0
    if dhist:   # döngüselde uzun vade = dip sonrası trend büyümesi; yükseliş büyümesi = analist ivmesi
        glt0 = min(g_rev, 5.0) if b["is_cyc"] else g_rev
    else:
        glt0 = b["g_lt"]
    defaults = {"cyc": bool(b["is_cyc"]), "peak": int(min(PEAK_MAX, peak0)), "drop": drop0,
                "glt": float(round(glt0 if en._ok(glt0) else 6.0)),
                "mmode": MULT_MODES[0], "mult": float(round(b.get("pe_now") or 15.0, 1))
                if en._ok(b.get("pe_now")) else 15.0,
                "gup": float(round(min(40.0, max(g_rev, 5.0)))),
                "mtg": float(round(md_["last"], 1)), "mpk": float(round(md_["peak"], 1)),
                "mtr": float(round(md_["trough"], 1)),
                "shc": float(round(dhist["share_chg"], 1)) if dhist else 0.0,
                "cpx": float(round(dhist["capex_pct"], 1)) if dhist else 5.0,
                "lens": en.LENSES[0]}
    saved = dict(defaults)
    raw = dict((ss.get("vp_cfg") or {}).get(sym) or {})
    gov = {str(k): float(v) for k, v in (raw.pop("gov", None) or {}).items() if en._ok(v)}
    saved.update(raw)
    if saved.get("mmode") not in MULT_MODES:
        saved["mmode"] = MULT_MODES[0]
    if saved.get("lens") not in en.LENSES:
        saved["lens"] = en.LENSES[0]
    if saved.get("peak") not in range(0, PEAK_MAX + 1):
        saved["peak"] = defaults["peak"]
    saved.pop("win", None)
    for k, lo, hi in (("drop", 0.0, 90.0), ("glt", GLT_MIN, GLT_MAX), ("mult", 1.0, 80.0), ("gup", GLT_MIN, GLT_MAX),
                      ("mtg", -50.0, 80.0), ("mpk", -50.0, 80.0), ("mtr", -50.0, 80.0), ("shc", -10.0, 10.0),
                      ("cpx", 0.0, 80.0)):
        try:
            saved[k] = float(min(hi, max(lo, float(saved[k]))))
        except (TypeError, ValueError, KeyError):
            saved[k] = defaults[k]
    keys = {k: f"vp_{k}_{sym}" for k in defaults}
    cur = {k: (ss[wk] if wk in ss else saved[k]) for k, wk in keys.items()}
    return {"fy0": fy0, "keys": keys, "saved": saved, "cur": cur, "n_est": len(est), "dh": dh, "gov": gov,
            "defaults": defaults, "driver": bool(dhist)}


def vp_kwargs(b, st_):
    """Ayar sözlüğünden model argümanları (sürücü modeli; geçmiş tablo yoksa EPS tabanlı value_path)."""
    an, cur = b["an"], st_["cur"]
    mmode = cur["mmode"]
    tm = None
    if mmode == MULT_MODES[1]:
        tm = b["pm"].get("fwd_pe")
    elif mmode == MULT_MODES[2]:
        tm = (b.get("band") or {}).get("median")
    elif mmode == "Manual":
        tm = cur["mult"]
    tm = tm if en._ok(tm) and tm > 0 else None
    gy = b.get("g_yoy_rep")
    kw = {"cyclical": bool(cur["cyc"]), "peak_idx": int(cur["peak"]), "drop": float(cur["drop"]),
          "g_lt": float(cur["glt"]), "target_mult": tm, "fy0": st_["fy0"], "fy0_left": an.get("fy0_left", 0.5),
          "fy0_end": an.get("fy0_end"),
          "g_near": max(-20.0, min(100.0, gy)) if en._ok(gy) else None,
          "_mmode": mmode, "_n_est": st_["n_est"], "_driver": st_.get("driver", False)}
    if st_.get("driver"):
        dfl = st_.get("defaults") or {}

        def _chg(k):        # varsayılandan farklıysa ver, değilse model kendi hesaplasın
            v = cur.get(k)
            return float(v) if en._ok(v) and abs(float(v) - float(dfl.get(k, v))) > 1e-9 else None
        kw.update({"g_up": float(cur["gup"]), "m_target": _chg("mtg"), "m_peak": _chg("mpk"), "m_trough": _chg("mtr"),
                   "share_chg": float(cur["shc"]), "capex_pct": float(cur["cpx"]), "lens": cur["lens"],
                   "g_over": {int(k): v for k, v in (st_.get("gov") or {}).items()}})
    return kw


def build_path(b, kw, price=None):
    """Seçili modele göre değer patikası: sürücü modeli (tablolar varsa) ya da EPS modeli."""
    price = b["d"]["last"] if price is None else price
    k_ = _model_kwargs(kw)
    if kw.get("_driver") and b.get("dhist"):
        p = en.driver_path(price, b["dhist"], b["an"], years=5, **k_)
        if p:
            return p
    for k in ("g_up", "m_target", "m_peak", "m_trough", "share_chg", "capex_pct", "lens", "g_over"):
        k_.pop(k, None)
    return en.value_path(price, b["eps_last"], b["an"].get("fy") or [], years=5, **k_)


def _vg_changed(sym, fy, key):
    """Yıl yıl büyüme kutusu değişti: varsayılandan farklıysa elle girilen değer olarak sakla."""
    v = ss.get(key)
    dflt = ss.get(key + "_def")
    allc = dict(ss.get("vp_cfg") or {})
    c = dict(allc.get(sym) or {})
    gov = dict(c.get("gov") or {})
    if en._ok(v) and (dflt is None or abs(float(v) - float(dflt)) > 0.049):
        gov[str(fy)] = float(v)
    else:
        gov.pop(str(fy), None)
    c["gov"] = gov
    allc[sym] = c
    ss.vp_cfg = allc


def _vg_reset(sym):
    allc = dict(ss.get("vp_cfg") or {})
    c = dict(allc.get(sym) or {})
    c["gov"] = {}
    allc[sym] = c
    ss.vp_cfg = allc
    for k in [k for k in ss.keys() if str(k).startswith(f"vg_{sym}_")]:
        del ss[k]


G_SRC = {"analyst": "analyst estimate", "upswing": "upswing growth", "downturn": "post-peak decline",
         "recovery": "recovery (long-term growth)", "model": "long-term growth", "override": "your input"}


def value_cfg(b, sym):
    """Değer patikası ayarları — hisse başına saklanır."""
    st_ = vp_state(b, sym)
    fy0, keys, saved, dh = st_["fy0"], st_["keys"], st_["saved"], st_["dh"]
    for k, wk in keys.items():
        if wk not in ss:
            ss[wk] = saved[k]
    fy_opts = list(range(0, PEAK_MAX + 1))
    drv = st_.get("driver")
    with st.container(border=True):
        H('<div class="panel-title">Model Settings</div><div class="muted small">Defaults come from analyst '
          'estimates and the company\'s history; anything you change is saved for this stock. '
          + ('Revenue growth drives the model: revenue → operating margin → interest on net debt → tax → share '
             'count → EPS; capex sets free cash flow and net debt.' if drv else '') + '</div>')
        c = st.columns([1, 1, 1.3, 1.3, 1.6], gap="small")
        with c[0]:
            cyc = toggle("Cyclical mode", keys["cyc"], help="Earnings climb to a peak, then pull back.")
        with c[1]:
            st.selectbox("Earnings peak", fy_opts, key=keys["peak"], disabled=not cyc,
                         format_func=lambda i: f"FY{fy0 + i}",
                         help="The fiscal year in which earnings — and therefore the value path — peak.")
        with c[2]:
            st.slider("Revenue drop after peak" if drv else "Post-peak drop", 0.0, 90.0, step=5.0, key=keys["drop"],
                      disabled=not cyc, format="%.0f%%",
                      help=("Revenue decline from peak to trough over 2 years; margins shrink with it (operating "
                            "leverage), so EPS falls more. " if drv else "EPS loss from peak to trough (over 2 years). ")
                           + "EPS drop in the company's past cycles: " + (f"{tr(dh, 0)}%" if en._ok(dh) else "no data"))
        with c[3]:
            st.slider("Long-term growth (YoY)", GLT_MIN, GLT_MAX, step=1.0, key=keys["glt"], format="%.0f%%",
                      help=("Yearly revenue growth after the analyst years (cyclical: trend growth after the "
                            "trough). " if drv else "Year-over-year EPS growth after the analyst years. ")
                           + "Each year = previous year × (1 + growth). Up to 150%.")
        with c[4]:
            mmode = st.selectbox("Target multiple", MULT_MODES, key=keys["mmode"],
                                 help="Today's multiple: the stock keeps being priced the way the market prices it "
                                      "today. The others move the multiple to that value over 3 years.")
            if mmode == "Manual":
                st.number_input("P/E", 1.0, 80.0, step=0.5, key=keys["mult"])
        if drv:
            cur0 = {k: ss.get(wk) for k, wk in keys.items()}
            defs = en.driver_defaults(b["dhist"], b["an"], bool(cur0["cyc"]), int(cur0["peak"]), 5,
                                      float(cur0["glt"]), float(cur0["gup"]), float(cur0["drop"]), fy0)
            gov = st_["gov"]
            H('<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:10px">'
              '<span style="font-size:12px;font-weight:700">Revenue growth per year <span class="muted" '
              'style="font-weight:500">(YoY %, editable — defaults follow the settings above)</span></span></div>')
            gc = st.columns(len(defs) + 1, gap="small")
            for i, d in enumerate(defs):
                k = f"vg_{sym}_{d['fy']}"
                ov = gov.get(str(d["fy"]))
                g_def = float(round(min(400.0, max(-90.0, d["g"])), 1))
                if ov is None and (k not in ss or ss.get(k + "_def") != g_def):
                    ss[k] = g_def
                elif ov is not None and k not in ss:
                    ss[k] = float(min(400.0, max(-90.0, ov)))
                ss[k + "_def"] = g_def
                with gc[i]:
                    st.number_input(f"FY{d['fy']}", -90.0, 400.0, step=1.0, key=k, format="%.1f",
                                    on_change=_vg_changed, args=(sym, d["fy"], k),
                                    help=f"Default {tr(g_def, 1)}% — {G_SRC.get(d['src'], d['src'])}.")
                    src_ = "your input" if ov is not None else G_SRC.get(d["src"], d["src"])
                    H(f'<div class="muted" style="font-size:10.5px;margin-top:-6px">{esc(src_)}</div>')
            with gc[-1]:
                H('<div style="height:26px"></div>')
                st.button("Reset", key=f"vg_reset_{sym}", on_click=_vg_reset, args=(sym,),
                          help="Back to the default growth for every year.")
            d2 = st.columns([1, 1, 1, 1, 1, 1.2], gap="small")
            with d2[0]:
                st.number_input("Upswing growth", GLT_MIN, GLT_MAX, step=1.0, key=keys["gup"], format="%.0f",
                                disabled=not cyc, help="Cyclical: yearly revenue growth from the last analyst year "
                                                       "up to the peak (%).")
            with d2[1]:
                if cyc:
                    st.number_input("Peak op. margin %", -50.0, 80.0, step=0.5, key=keys["mpk"], format="%.1f",
                                    help="Operating margin at the cycle peak (default: higher of the analyst-implied "
                                         "and the company's best margin).")
                else:
                    st.number_input("Target op. margin %", -50.0, 80.0, step=0.5, key=keys["mtg"], format="%.1f",
                                    help="Operating margin the company moves to over 3 years after the analyst years "
                                         "(default: the margin implied by the last analyst estimate).")
            with d2[2]:
                st.number_input("Trough op. margin %", -50.0, 80.0, step=0.5, key=keys["mtr"], format="%.1f",
                                disabled=not cyc, help="Cyclical: operating margin at the bottom of the cycle "
                                                       "(default: 40% of the company's median margin).")
            with d2[3]:
                st.number_input("Shares / yr %", -10.0, 10.0, step=0.1, key=keys["shc"], format="%.1f",
                                help="Yearly change in the share count: negative = buybacks, positive = dilution.")
            with d2[4]:
                st.number_input("Capex % revenue", 0.0, 80.0, step=0.5, key=keys["cpx"], format="%.1f",
                                help="Capital expenditure as % of revenue (default: last 3 years). Lower capex = "
                                     "more free cash flow = faster debt reduction.")
            with d2[5]:
                st.selectbox("Valuation lens", en.LENSES, key=keys["lens"],
                             help="P/E: EPS × multiple. EV/EBIT: (EBIT × multiple − net debt) / shares — debt and "
                                  "cash count directly. Blend: average of both.")
    cur = {k: ss.get(wk) for k, wk in keys.items()}
    allc = dict(ss.get("vp_cfg") or {})
    cur["gov"] = dict(((allc.get(sym) or {}).get("gov")) or {})
    allc[sym] = cur
    ss.vp_cfg = dict(list(allc.items())[-40:])
    st_["cur"] = cur
    st_["gov"] = {k: v for k, v in cur["gov"].items()}
    return vp_kwargs(b, st_)


def _model_kwargs(cfg):
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def fin_bar_chart(f, keys, names, colors, height=240, pct=False, sel=None):
    """Yıllık kalemler için çubuk grafiği. sel: vurgulanan yıl (çeyrek sonuçları açık)."""
    fig = go.Figure()
    yrs = [str(y) for y in f["years"]]
    for k, n, c in zip(keys, names, colors):
        vals = [v / 1e9 if not pct and en._ok(v) else v for v in f[k]]
        fig.add_trace(go.Bar(x=yrs, y=vals, name=n, marker_color=c,
                             hovertemplate="%{x}: %{y:.1f}" + ("%" if pct else " bn") + "<extra>" + n +
                                           " · click for quarters</extra>"))
    if sel is not None and str(sel) in yrs:
        i = yrs.index(str(sel))
        fig.add_vrect(x0=i - 0.5, x1=i + 0.5, fillcolor=rgba(ACCENT, 0.10), line_width=0)
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.18, x=0))
    fig.update_xaxes(type="category")       # "2025" sayı sanılmasın: vurgu kutusu kategori sırasına göre
    fig.update_yaxes(ticksuffix="%" if pct else " bn")
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=26, b=4))


def rgba(hexcol, a):
    """'#RRGGBB' → 'rgba(r,g,b,a)' (Plotly'nin her sürümü kabul eder)."""
    h = str(hexcol).lstrip("#")
    if len(h) != 6:
        return hexcol
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def _clean(vals):
    return [float(v) if en._ok(v) else None for v in vals]


def bar_fig(cats, series, height=220, suffix="", barmode="group", hline=None, hl_label=None,
            legend=True, horizontal=False, text=False, dec=1):
    """Genel çubuk grafiği. series: [(ad, değerler, renk ya da renk listesi)]."""
    fig = go.Figure()
    for name, vals, color in series:
        v = _clean(vals)
        txt = [("" if x is None else tr(x, dec) + suffix) for x in v] if text else None
        kw = dict(name=name, marker_color=color,
                  hovertemplate=f"<b>%{{{'y' if horizontal else 'x'}}}</b><br>{name}: "
                                f"%{{{'x' if horizontal else 'y'}:.2f}}{suffix}<extra></extra>")
        if txt:
            kw.update(text=txt, textposition="outside")
        if horizontal:
            fig.add_trace(go.Bar(x=v, y=cats, orientation="h", **kw))
        else:
            fig.add_trace(go.Bar(x=cats, y=v, **kw))
    fig.update_layout(barmode=barmode)
    if hline is not None and en._ok(hline) and not horizontal:
        fig.add_hline(y=hline, line=dict(color=MUT, width=1, dash="dash"),
                      annotation_text=hl_label or "", annotation_position="top left",
                      annotation_font=dict(color=MUT, size=10))
    if suffix and not horizontal:
        fig.update_yaxes(ticksuffix=suffix)
    fig = _layout(fig, height, legend=legend and len(series) > 1, margin=dict(l=4, r=8, t=24, b=4))
    if horizontal:
        if suffix:
            fig.update_xaxes(ticksuffix=suffix)
        fig.update_yaxes(side="left")          # _layout ekseni sağa alıyor; kategori adları solda dursun
    return fig


def line_fig(series, height=240, suffix="", hlines=None, legend=True):
    """Genel çizgi grafiği. series: [(ad, x, y, renk, kesik?, dolgu?)]."""
    fig = go.Figure()
    for name, x, y, color, dash, fill in series:
        fig.add_trace(go.Scatter(x=list(x), y=_clean(y), mode="lines", name=name,
                                 line=dict(color=color, width=1.8 if not dash else 1.3,
                                           dash="dot" if dash else None),
                                 fill="tozeroy" if fill else None,
                                 fillcolor=rgba(color, 0.14) if fill else None,
                                 hovertemplate=f"{name}: %{{y:.2f}}{suffix}<extra></extra>"))
    for y, lab, c in (hlines or []):
        if en._ok(y):
            fig.add_hline(y=y, line=dict(color=c, width=1, dash="dash"), annotation_text=lab,
                          annotation_position="right", annotation_font=dict(color=c, size=10))
    if suffix:
        fig.update_yaxes(ticksuffix=suffix)
    return _layout(fig, height, legend=legend and len(series) > 1,
                   margin=dict(l=4, r=(70 if hlines else 8), t=24, b=4))


def eps_proj_fig(f, path, height=250):
    """Gerçekleşen EPS (çubuk) + mali yıl bazında senaryolar (analist yılları dolu nokta)."""
    fig = go.Figure()
    yrs = [f"FY{y}" for y in f["years"]]
    fig.add_trace(go.Bar(x=yrs, y=_clean(f["eps"]), name="Reported", marker_color="#4A515C",
                         hovertemplate="%{x}: %{y:.2f}<extra></extra>"))
    er = path["eps_rows"]
    fut = [r["label"] for r in er]
    last_y = yrs[-1] if yrs else None
    last_e = next((v for v in reversed(f["eps"]) if en._ok(v)), path["eps_last"])
    if last_y in fut:
        last_y = None
    for key, name, c, dash in (("bull", "Bull", "#6EE7B7", "dot"), ("base", "Base", ACCENT, None),
                               ("bear", "Bear", "#F0883E", "dot")):
        xs = ([last_y] if last_y else []) + fut
        ys = ([last_e] if last_y else []) + [r["eps"][key] for r in er]
        sym_ = (["circle"] if last_y else []) + ["circle" if r["src"] == "analyst" else "circle-open" for r in er]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=name,
                                 line=dict(color=c, width=2 if key == "base" else 1.3, dash=dash),
                                 marker=dict(size=6, symbol=sym_),
                                 hovertemplate=f"{name} %{{x}}: %{{y:.2f}}<extra></extra>"))
    pk = path.get("peak_fy")
    cats = yrs + [x for x in fut if x not in yrs]
    if path.get("cyclical") and f"FY{pk}" in cats:
        fig.add_vline(x=cats.index(f"FY{pk}"), line=dict(color=WARN, width=1, dash="dot"),
                      annotation_text="earnings peak", annotation_position="top",
                      annotation_font=dict(color=WARN, size=10))
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=24, b=4))


def peer_scatter(sym, vals, peers, height=300):
    """Büyüme / çarpan haritası — çizginin üstü büyümesine göre pahalı."""
    pts = []
    for t in [sym] + list(peers):
        v = vals.get(t)
        if not v:
            continue
        g, p, m = v.get("growth"), v.get("fwd_pe"), v.get("market_cap")
        if en._ok(g) and en._ok(p) and p > 0:
            pts.append((t, float(g), float(p), float(m) if en._ok(m) else 1e9))
    if len(pts) < 3:
        return None
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    caps = [p[3] for p in pts]
    mx = max(caps) or 1.0
    sizes = [14 + 34 * (c / mx) ** 0.5 for c in caps]
    cols = [ACCENT if p[0] == sym else "#4A515C" for p in pts]
    fig = go.Figure()
    sl, ic = en._fit(xs, ys)
    if abs(sl) > 1e-9:
        x0, x1 = min(xs) - 2, max(xs) + 3
        fig.add_trace(go.Scatter(x=[x0, x1], y=[sl * x0 + ic, sl * x1 + ic], mode="lines",
                                 line=dict(color=ACCENT, width=1.2, dash="dash"),
                                 hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=[p[0] for p in pts], textposition="middle right",
        textfont=dict(color=TXT, size=11),
        marker=dict(size=sizes, color=cols, line=dict(width=1, color="#0A0B0D")),
        customdata=[[big(p[3], "")] for p in pts], showlegend=False,
        hovertemplate="<b>%{text}</b><br>Growth %{x:.1f}%<br>Fwd P/E %{y:.1f}<br>"
                      "Market cap %{customdata[0]}<extra></extra>"))
    fig.update_xaxes(title="Fwd EPS growth", ticksuffix="%")
    fig.update_yaxes(title="Fwd P/E", ticksuffix="x")
    return _layout(fig, height, margin=dict(l=8, r=40, t=10, b=34))


def fair_path_chart(path, px, price, qp=None, sel_fy=None, sel_q=None, height=320):
    """Geçmiş fiyat + mali yıl sonlarında değer (FY değeri = o yılın EPS'i × çarpan), çeyrek noktaları,
    seçili yıl / çeyrek vurgusu ve döngüselde kâr zirvesi çizgisi."""
    fig = go.Figure()
    if px is not None and len(px) > 20:
        h = px.tail(500)
        hx = h.index
        try:
            hx = hx.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        fig.add_trace(go.Scatter(x=hx, y=h["Close"], mode="lines", name="Price",
                                 line=dict(color=SOFT, width=1.5)))
    x0 = px.index[-1] if (px is not None and len(px)) else pd.Timestamp.today()
    try:
        x0 = pd.Timestamp(x0).tz_localize(None)
    except (TypeError, AttributeError):
        x0 = pd.Timestamp(x0)
    rows = path["rows"]
    xs = [pd.Timestamp(r["end"]) for r in rows]
    allx = [x0] + xs
    labs = ["today"] + [r["label"] for r in rows]
    bear = [price] + [r["value"]["bear"] for r in rows]
    bull = [price] + [r["value"]["bull"] for r in rows]
    fig.add_trace(go.Scatter(x=allx, y=bull, mode="lines", line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=allx, y=bear, mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=rgba(ACCENT, 0.10), hoverinfo="skip", showlegend=False))
    # çeyrek noktaları (taban, TTM × çarpan) — bugünden sonrası
    if qp:
        qs = [q_ for q_ in qp["slots"] if q_.get("value") and q_["end"] > x0 and q_["fy"] >= path["fy0"]]
        if qs:
            fig.add_trace(go.Scatter(x=[q_["end"] for q_ in qs], y=[q_["value"]["base"] for q_ in qs],
                                     mode="lines+markers", name="Base · quarterly",
                                     line=dict(color=ACCENT, width=1, dash="dot"), marker=dict(size=4),
                                     customdata=[q_["label"] for q_ in qs],
                                     hovertemplate="%{customdata}: %{y:.2f}<extra></extra>"))
    for key, name, c, dash in (("bull", "Bull", "#6EE7B7", "dot"), ("base", "Base", ACCENT, None),
                               ("bear", "Bear", "#F0883E", "dot")):
        ys = [price] + [r["value"][key] for r in rows]
        fig.add_trace(go.Scatter(x=allx, y=ys, mode="lines+markers", name=name,
                                 line=dict(color=c, width=2.2 if key == "base" else 1.3, dash=dash),
                                 marker=dict(size=7 if key == "base" else 5), customdata=labs,
                                 hovertemplate=f"{name} %{{customdata}}: %{{y:.2f}}<extra></extra>"))
    if path.get("cyclical"):
        pr = next((r for r in rows if r["fy"] == path["peak_fy"]), None)
        if pr:
            # Plotly'de tarih + annotation_text birlikte hata verir → x'i epoch milisaniye olarak ver
            fig.add_vline(x=pd.Timestamp(pr["end"]).timestamp() * 1000, line=dict(color=WARN, width=1, dash="dot"),
                          annotation_text=f"earnings peak {pr['label']}", annotation_position="top",
                          annotation_font=dict(color=WARN, size=10))
    # seçili yıl / çeyrek
    if qp and sel_fy in (qp.get("fy_end") or {}):
        fe = pd.Timestamp(qp["fy_end"][sel_fy])
        fig.add_vrect(x0=fe - pd.DateOffset(years=1), x1=fe, fillcolor=rgba(ACCENT, 0.07), line_width=0)
        pt = None
        if sel_q:
            sq = next((q_ for q_ in qp["by_fy"][sel_fy] if q_["q"] == sel_q), None)
            if sq:
                y_ = (sq["value"] or {}).get("base") if not sq.get("past") else sq.get("price")
                if en._ok(y_):
                    pt = (sq["end"], y_, sq["label"])
        else:
            rr = next((r for r in rows if r["fy"] == sel_fy), None)
            if rr:
                pt = (pd.Timestamp(rr["end"]), rr["value"]["base"], rr["label"])
        if pt:
            fig.add_trace(go.Scatter(x=[pt[0]], y=[pt[1]], mode="markers+text", name=pt[2],
                                     marker=dict(size=14, symbol="diamond-open", color=WARN, line=dict(width=2)),
                                     text=[f"{pt[2]} · {tr(pt[1], 1)}"], textposition="top center",
                                     textfont=dict(color=WARN, size=11), showlegend=False,
                                     hovertemplate=f"{pt[2]}: %{{y:.2f}}<extra></extra>"))
    fig.add_hline(y=price, line=dict(color=MUT, width=1, dash="dash"),
                  annotation_text=f"today {tr(price)}", annotation_position="top left",
                  annotation_font=dict(color=MUT, size=10))
    fig.update_layout(legend=dict(orientation="h", y=1.16, x=0))
    return _layout(fig, height, legend=True, margin=dict(l=4, r=10, t=28, b=4))


Q_COL = {"reported": "#8D96A5", "analyst": None, "model": None}


def quarter_bar_fig(qp, sel_fy, sel_q, height=230):
    """Seçili yıl + önceki yıl çeyrek EPS'leri; kaynak rengi, tahminlerde kötümser–iyimser aralığı, QoQ etiketi."""
    xs = [q_ for fy in (sel_fy - 1, sel_fy) for q_ in qp["by_fy"].get(fy, [])]
    fig = go.Figure()
    for src, name, colr in (("reported", "Reported", "#8D96A5"), ("analyst", "Analyst estimate", ACCENT),
                            ("model", "Model estimate", rgba(ACCENT, 0.38))):
        pts = [q_ for q_ in xs if q_["src"] == src]
        if not pts:
            continue
        base = [q_["eps"]["base"] for q_ in pts]
        err = dict(type="data", symmetric=False, color=MUT, thickness=1, width=3,
                   array=[max(0.0, q_["eps"]["bull"] - q_["eps"]["base"]) for q_ in pts],
                   arrayminus=[max(0.0, q_["eps"]["base"] - q_["eps"]["bear"]) for q_ in pts]) \
            if src != "reported" else None
        fig.add_trace(go.Bar(
            x=[f"{q_['fy'] % 100:02d} Q{q_['q']}" for q_ in pts], y=base, name=name,
            marker=dict(color=colr, line=dict(color=[WARN if (q_["fy"] == sel_fy and q_["q"] == sel_q)
                                                     else "rgba(0,0,0,0)" for q_ in pts], width=2)),
            error_y=err,
            text=[("" if q_.get("qoq") is None else pct(q_["qoq"], 0)) for q_ in pts], textposition="outside",
            hovertemplate="FY%{x}: %{y:.2f}<extra>" + name + "</extra>"))
    fig.update_layout(barmode="overlay", legend=dict(orientation="h", y=1.2, x=0))
    fig.update_xaxes(categoryorder="array", categoryarray=[f"{q_['fy'] % 100:02d} Q{q_['q']}" for q_ in xs])
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=30, b=4))


def _src_badge(q_):
    s_ = q_["src"]
    if s_ == "reported":
        return ('<span class="badge" style="color:#C4CAD4;background:#8D96A51F">reported'
                + (" · GAAP" if q_.get("gaap") else "") + '</span>')
    if s_ == "analyst":
        n_ = q_.get("n")
        return (f'<span class="badge" style="color:#9DB8FF;background:#5B8CFF1F">analyst'
                f'{" · " + str(n_) if n_ else ""}</span>')
    return '<span class="badge" style="color:#A3ABB8;background:#6B73831A">model</span>'


def render_quarters(b, path, qp, sym, dec, sel_fy, sel_q):
    """Çeyrek çeyrek: seçili mali yılın 4 çeyreği — raporlanan / analist / model, QoQ, YoY, TTM, değer."""
    fys = qp["fy_list"]
    rows = qp["by_fy"][sel_fy]
    fe = pd.Timestamp(qp["fy_end"][sel_fy])
    yr = next((r for r in path["rows"] if r["fy"] == sel_fy), None)
    c1, c2 = st.columns([1.45, 1], gap="large")
    with c1:
        trs = ""
        for q_ in rows:
            on = sel_q == q_["q"]
            e = q_["eps"]
            rng_ = ("" if q_["src"] == "reported" else
                    f'<div class="muted" style="font-size:10.5px">{tr(e["bear"], 2)} – {tr(e["bull"], 2)}</div>')
            val = q_.get("price") if q_.get("past") else (q_.get("value") or {}).get("base")
            vlab = "price" if q_.get("past") else "value"
            rev = q_.get("rev")
            trs += (f'<tr class="{"qsel" if on else ""}"><td><b>Q{q_["q"]}</b><div class="muted" '
                    f'style="font-size:10.5px">{q_["end"].strftime("%b %Y")}</div></td>'
                    f'<td><b>{tr(e["base"], 2)}</b>{rng_}</td>'
                    f'<td style="color:{col(q_["qoq"]) if q_.get("qoq") is not None else MUT}">'
                    f'{pct(q_["qoq"], 1) if q_.get("qoq") is not None else "—"}</td>'
                    f'<td style="color:{col(q_["yoy"]) if q_.get("yoy") is not None else MUT}">'
                    f'{pct(q_["yoy"], 1) if q_.get("yoy") is not None else "—"}</td>'
                    f'<td>{big(rev) if en._ok(rev) else "—"}</td>'
                    f'<td>{tr(q_["ttm"]["base"], 2) if q_.get("ttm") else "—"}</td>'
                    f'<td title="{vlab}">{tr(val, dec) if en._ok(val) else "—"}'
                    f'{"<span class=muted style=font-size:10px> px</span>" if q_.get("past") and en._ok(val) else ""}</td>'
                    f'<td>{_src_badge(q_)}</td></tr>')
        tot = sum(q_["eps"]["base"] for q_ in rows)
        fy_eps = yr["eps"]["base"] if yr else (path["eps_last"] if sel_fy == path["fy0"] - 1 else None)
        trs += (f'<tr class="qtot"><td><b>FY{sel_fy}</b></td><td><b>{tr(tot, 2)}</b></td>'
                f'<td></td><td style="color:{col(yr["eps_yoy"]) if yr and yr.get("eps_yoy") is not None else MUT}">'
                f'{pct(yr["eps_yoy"], 1) if yr and yr.get("eps_yoy") is not None else ""}</td><td></td>'
                f'<td>{tr(fy_eps, 2) if en._ok(fy_eps) else ""}</td>'
                f'<td>{tr(yr["value"]["base"], dec) if yr else ""}</td><td class="muted small">'
                f'{"Σ Q1–Q4 = FY" if yr else "reported year"}</td></tr>')
        H(f'<table class="ptab qtab"><thead><tr><th>Quarter</th><th>EPS</th><th>QoQ</th><th>YoY</th>'
          f'<th>Revenue</th><th>TTM EPS</th><th>Value</th><th>Source</th></tr></thead><tbody>{trs}</tbody></table>')
        H(f'<div class="muted small" style="margin-top:6px">Fiscal year FY{sel_fy} ends {fe.strftime("%b %d, %Y")}. '
          f'QoQ = vs the previous quarter, YoY = vs the same quarter a year earlier. Value = TTM EPS (last four '
          f'quarters) × the multiple at that date — Q4 equals the fiscal-year value. Past quarters show the actual '
          f'share price ("px") instead.</div>')
    with c2:
        plot(quarter_bar_fig(qp, sel_fy, sel_q), key="v_qbars")
        q_ = next((x for x in rows if x["q"] == sel_q), None) if sel_q else None
        if q_ is None:
            srcs = [x["src"] for x in rows]
            parts = []
            for k_, nm in (("reported", "reported"), ("analyst", "analyst estimates"), ("model", "model estimates")):
                qs_ = [f"Q{x['q']}" for x in rows if x["src"] == k_]
                if qs_:
                    parts.append(f'{", ".join(qs_)}: {nm}')
            src_fy = (yr["src"] if yr else "reported")
            fy_txt = {"analyst": "analyst consensus for the full year", "model": "the model (YoY growth / cycle)",
                      "held": "the model — held at least at the prior year so the cycle peaks as you set it",
                      "post-peak": "the post-peak path (replaces the analyst estimate)",
                      "reported": "the reported year"}.get(src_fy, src_fy)
            H(f'<div class="gtext"><b>FY{sel_fy}</b> · {"; ".join(parts)}. The full-year EPS comes from '
              f'{esc(fy_txt)}; quarters that are not reported or covered by analysts are that total minus the known '
              f'quarters, split like the same quarters a year earlier (equal YoY growth for each).'
              + ('' if "model" not in srcs else ' <span class="muted">Pick a quarter for its details.</span>')
              + '</div>')
        else:
            e = q_["eps"]
            if q_["src"] == "reported":
                bits = [f'Reported EPS <b>{tr(e["base"], 2)}</b>']
                if en._ok(q_.get("est_then")):
                    bits.append(f'vs consensus {tr(q_["est_then"], 2)}')
                if en._ok(q_.get("surprise")):
                    bits.append(f'surprise <span style="color:{col(q_["surprise"])}">{pct(q_["surprise"], 1)}</span>')
                if en._ok(q_.get("rev")):
                    bits.append(f'revenue {big(q_["rev"])}')
                txt = " · ".join(bits) + (" (GAAP — adjusted EPS not available)" if q_.get("gaap") else "") + "."
            elif q_["src"] == "analyst":
                nd = qp.get("next_date")
                txt = (f'<b>Not reported yet — expectation.</b> Analyst consensus {tr(e["base"], 2)}'
                       f'{" from " + str(q_["n"]) + " analysts" if q_.get("n") else ""} (range {tr(e["bear"], 2)} – '
                       f'{tr(e["bull"], 2)})' + (f', revenue estimate {big(q_["rev"])}' if en._ok(q_.get("rev")) else "")
                       + (f'. Next report around {esc(nd)}' if nd else "") + '.')
            else:
                fy_e = yr["eps"]["base"] if yr else None
                sc_ = q_.get("scale")
                txt = (f'<b>Not reported yet — model expectation.</b> Analysts publish quarterly estimates only '
                       f'for the next two quarters. This one is derived from the FY{sel_fy} EPS '
                       f'({tr(fy_e, 2) if en._ok(fy_e) else "—"}, {esc((yr or {}).get("src", "model"))}) minus the '
                       f'reported / estimated quarters, split like the same quarter a year earlier'
                       + (f' (YoY {pct(sc_, 1)})' if sc_ is not None else "") +
                       f'. Bear – bull {tr(e["bear"], 2)} – {tr(e["bull"], 2)}.')
            val = q_.get("price") if q_.get("past") else (q_.get("value") or {}).get("base")
            up = (val / b["d"]["last"] - 1) * 100 if en._ok(val) and not q_.get("past") else None
            tiles = [("EPS", tr(e["base"], 2), TXT), ("QoQ", pct(q_["qoq"], 1) if q_.get("qoq") is not None else "—",
                                                       col(q_["qoq"]) if q_.get("qoq") is not None else MUT),
                     ("YoY", pct(q_["yoy"], 1) if q_.get("yoy") is not None else "—",
                      col(q_["yoy"]) if q_.get("yoy") is not None else MUT),
                     ("TTM EPS", tr(q_["ttm"]["base"], 2) if q_.get("ttm") else "—", TXT),
                     ("Price" if q_.get("past") else "Value", tr(val, dec) if en._ok(val) else "—", TXT),
                     ("vs today", pct(up) if up is not None else "—", col(up) if up is not None else MUT)]
            H(f'<div class="qtiles">' + "".join(f'<div class="tile"><span class="k">{k}</span>'
                                                 f'<span class="v" style="font-size:15px;color:{c_}">{v}</span></div>'
                                                 for k, v, c_ in tiles) + '</div>'
              f'<div class="gtext" style="margin-top:8px"><b>{q_["label"]}</b> (ends {q_["end"].strftime("%b %d, %Y")}) · '
              f'{txt}</div>')


def _cell(v, med, dec=1, lower_better=True, suffix=""):
    """Medyana göre renklenen hücre."""
    if not en._ok(v):
        return f'<td style="color:{MUT}">—</td>'
    c = TXT
    if en._ok(med) and med:
        diff = (v / med - 1) if med > 0 else 0
        good = (diff < -0.08) if lower_better else (diff > 0.08)
        bad = (diff > 0.08) if lower_better else (diff < -0.08)
        c = UP if good else DOWN if bad else TXT
    return f'<td style="color:{c}">{tr(v, dec)}{suffix}</td>'


def render_value():
    H('<div class="page-title">Valuation</div><div class="muted" style="margin-bottom:10px">'
      'Financials, multiples, fair value for the coming years, peer comparison, cyclicality and balance-sheet consistency'
      '</div>')
    sym = ACTIVE
    chips = "".join(f'<a class="crit" target="_self" style="text-decoration:none;'
                    f'{"color:#ECEEF1;border-color:" + ACCENT if t == sym else ""}" '
                    f'href="{link(sym=t)}">{esc(t)}</a>' for t in ss.watchlist[:14])
    H(f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px">'
      f'<span class="muted small">Your watchlist:</span>{chips}'
      f'<span class="muted small">· use the search above for any other symbol</span></div>')
    ovr = tuple((ss.get("peer_ovr") or {}).get(sym) or ())
    b = value_bundle(sym, md.tr_date_label(pd.Timestamp.now(tz=md.TZ)) + sym, ovr)
    if not b:
        H(f'<div class="muted">Could not load data for {esc(sym)}.</div>')
        return
    d, f, r = b["d"], b["f"], b["r"]
    render_value_head(b, sym)
    if not f:
        st.warning("No financial statements came back for this symbol (ETFs, indices and FX pairs don't publish "
                   "statements; for stocks the source may be temporarily empty). "
                   "The sections below are limited to price data.")
    if f:
        render_value_fundamentals(b)
        render_value_model(b, sym)
    render_value_peers(b, sym)
    render_value_cycle(b)
    if f:
        render_value_quality(b)


def render_value_head(b, sym):
    d, g = b["d"], b["grade"]
    cur = d.get("currency") or "USD"
    dec = pdec(sym, d["last"])
    with st.container(border=True):
        c1, c2 = st.columns([1.5, 2.2], gap="medium")
        with c1:
            H(f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">{avatar(sym, 32)}'
              f'<span class="panel-title">{esc(d["name"])}</span><span class="chip mono">{esc(sym)}</span>'
              f'{src_chip(b["stm_src"])}</div>'
              f'<div style="display:flex;align-items:baseline;gap:11px;margin-top:6px">'
              f'<span class="mono" style="font-size:28px;font-weight:600">{tr(d["last"], dec)}</span>'
              f'<span class="mono" style="color:{col(d["change_abs"])};font-weight:600;font-size:13px">'
              f'{pct(d["change_pct"])}</span><span class="muted">{esc(cur)}</span></div>'
              f'<div class="muted small" style="margin-top:4px">'
              f'{esc(" · ".join(x for x in [d.get("sector"), d.get("industry")] if x))}</div>')
            if g:
                c = grade_color(g["score"])
                H(f'<div class="grade" style="margin-top:12px"><div class="gletter" '
                  f'style="color:{c};background:{c}1F;border:1px solid {c}55">{g["letter"]}</div>'
                  f'<div style="min-width:0"><div class="gact" style="color:{GRADE_TONE.get(g["tone"], NEU)}">'
                  f'{esc(g["action"])}</div><div class="gsc">Value grade {tr(g["score"], 0)} / 100 · '
                  f'A cheap, Z expensive</div></div></div>'
                  f'<div class="gscale"><i style="left:{100 - g["score"]:.1f}%"></i></div>'
                  f'<div class="gax"><span>A · discounted</span><span>M–N · fair</span><span>Z · expensive</span>'
                  f'</div>')
                rows = ""
                for grp in g["groups"]:
                    gc = grade_color(grp["score"])
                    rows += (f'<div class="grow"><span class="gn">{esc(grp["name"])}</span>'
                             f'<span class="gw">{grp["weight"]}%</span><span class="gb">'
                             f'<i style="width:{max(2, grp["score"]):.0f}%;background:{gc}"></i></span>'
                             f'<span class="gv">{tr(grp["score"], 0)}</span></div>')
                H(rows)
                with st.expander("Why this value grade"):
                    for grp in g["groups"]:
                        items = "".join(f"<div>• {esc(x)}</div>" for x in grp["reasons"]) or \
                            '<div class="muted">—</div>'
                        H(f'<div style="margin-bottom:8px"><div style="font-size:12px;font-weight:700;'
                          f'color:{SOFT}">{esc(grp["name"])} <span class="muted">· '
                          f'{tr(grp["score"], 0)}/100 · {tr(grp["points"], 1)} pts</span></div>'
                          f'<div class="greason">{items}</div></div>')
        with c2:
            an, r = b["an"], b["r"]
            tiles = [("Market cap", big(d.get("market_cap"), cur)),
                     ("P/E", tr(b.get("pe_now"))), ("Fwd P/E", tr(d.get("fwd_pe"))),
                     ("EV/EBITDA", tr(r.get("ev_ebitda"))),
                     ("PEG", tr(b["vals"].get(sym, {}).get("peg"))),
                     ("EPS (ttm)", tr(d.get("eps"))),
                     ("Analyst EPS growth", " · ".join(
                         f'{e["label"]} {pct(e["growth"]) if e.get("growth") is not None else "—"}'
                         for e in (an.get("fy") or [])[:2]) or "—"),
                     ("Revenue growth (CAGR)", f'{tr(r.get("rev_cagr"), 1)}%'),
                     ("EPS growth (CAGR)", f'{tr(r.get("eps_cagr"), 1)}%'),
                     ("Net margin", f'{tr(r.get("net_m"), 1)}%'), ("Return on equity", f'{tr(r.get("roe"), 1)}%'),
                     ("Free cash flow yield", f'{tr(r.get("fcf_yield"), 1)}%'),
                     ("Debt / equity", tr(r.get("debt_equity"), 2))]
            H('<div class="vgrid">' + "".join(
                f'<div class="tile"><span class="k">{esc(k)}</span><span class="v">{v}</span></div>'
                for k, v in tiles) + "</div>")
            if en._ok(an.get("target_mean")):
                up = (an["target_mean"] / d["last"] - 1) * 100
                H(f'<div class="planrow" style="margin-top:10px"><span class="l">Analyst target'
                  f'{" · " + str(an["n"]) + " analysts" if an.get("n") else ""}</span>'
                  f'<span class="v">{tr(an["target_mean"], dec)} '
                  f'<span style="color:{col(up)}">({pct(up)})</span></span></div>')


def _qv(v, kind, dec=2):
    if not en._ok(v):
        return '<span class="muted">—</span>'
    if kind == "bn":
        return big(v)
    if kind == "pct":
        return f'{tr(v, 1)}%'
    if kind == "chg":
        return f'<span style="color:{col(v)}">{pct(v, 1)}</span>'
    return tr(v, dec)


def quarter_fin_fig(fq, sel_fy, height=230):
    """Seçili yıl + önceki yıl: çeyrek ciro ve net kâr (beklenen çeyrekler açık renk)."""
    xs = [(fy, q) for fy in (sel_fy - 1, sel_fy) if fy in fq for q in fq[fy]["quarters"]]
    cats = [f"{fy % 100:02d} Q{q['q']}" for fy, q in xs]
    fig = go.Figure()
    rev = [q.get("revenue") / 1e9 if en._ok(q.get("revenue")) else None for _, q in xs]
    ni = [q.get("net_income") / 1e9 if en._ok(q.get("net_income")) else None for _, q in xs]
    fig.add_trace(go.Bar(x=cats, y=rev, name="Revenue",
                         marker=dict(color=[ACCENT if q["src"] == "reported" else rgba(ACCENT, 0.35) for _, q in xs]),
                         hovertemplate="FY%{x}: %{y:.2f} bn<extra>Revenue</extra>"))
    fig.add_trace(go.Bar(x=cats, y=ni, name="Net income", marker_color=VIOLET,
                         hovertemplate="FY%{x}: %{y:.2f} bn<extra>Net income</extra>"))
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.2, x=0))
    fig.update_xaxes(categoryorder="array", categoryarray=cats)
    fig.update_yaxes(ticksuffix=" bn")
    if any(fy == sel_fy for fy, _ in xs):
        i0 = [i for i, (fy, _) in enumerate(xs) if fy == sel_fy][0]
        fig.add_vrect(x0=i0 - 0.5, x1=len(xs) - 0.5, fillcolor=rgba(ACCENT, 0.07), line_width=0)
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=30, b=4))


def render_fund_quarters(b, fq, fy_labels, k_y):
    """Fundamentals: seçili mali yılın çeyrek sonuçları (raporlanan; içinde bulunulan yılda beklenti)."""
    with st.container(border=True):
        H('<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">'
          '<span class="panel-title">Quarterly Results</span><span class="muted small">click a year in any chart '
          'above, or pick it here</span></div>')
        if not fq:
            H('<div class="muted">No quarterly statements available for this symbol.</div>')
            return
        labs = list(fy_labels.values())
        seg("Fiscal year", labs, k_y, ss.get(k_y) or labs[-1])
        sel = {v: k for k, v in fy_labels.items()}.get(ss.get(k_y), max(fq))
        y = fq[sel]
        qs = y["quarters"]
        if not any(q["src"] in ("reported", "expected") for q in qs):
            H(f'<div class="muted" style="margin:8px 0">No quarterly figures for FY{sel}. Yahoo Finance only keeps '
              f'the last ~5 quarters; older years come from SEC filings, which this company does not provide in '
              f'machine-readable form.</div>')
            return
        fa = b["f"]
        fyi = fa["years"].index(sel) if sel in fa["years"] else None

        def annual(k):
            return fa[k][fyi] if fyi is not None and k in fa else None
        head = "".join(
            f'<th>Q{q["q"]}<div class="muted" style="font-size:10.5px;font-weight:400">{q["end"].strftime("%b %Y")}'
            f'{" · expected" if q["src"] == "expected" else " · no estimate" if q["src"] == "no estimate" else ""}'
            f'</div></th>' for q in qs) + f'<th>FY{sel}</th>'
        rows_def = [("Revenue", "revenue", "bn", "revenue"), ("  QoQ", "revenue_qoq", "chg", None),
                    ("  YoY", "revenue_yoy", "chg", None), ("Gross profit", "gross", "bn", "gross"),
                    ("  Gross margin", "gross_m", "pct", "gross_m"), ("Operating income", "op_income", "bn", "op_income"),
                    ("  Operating margin", "op_m", "pct", "op_m"), ("Net income", "net_income", "bn", "net_income"),
                    ("  Net margin", "net_m", "pct", "net_m"), ("EPS (diluted)", "eps", "eps", "eps"),
                    ("  EPS YoY", "eps_yoy", "chg", None), ("Operating cash flow", "ocf", "bn", "ocf"),
                    ("Capex", "capex", "bn", "capex"), ("Free cash flow", "fcf", "bn", "fcf")]
        body = ""
        for lab, k, kind, ak in rows_def:
            if not any(en._ok(q.get(k)) for q in qs) and not (ak and en._ok(annual(ak))):
                continue
            sub = lab.startswith("  ")
            cells = ""
            for q in qs:
                v = q.get(k)
                if k == "capex" and en._ok(v):
                    v = abs(v)
                txt = _qv(v, kind)
                if q["src"] == "expected" and k == "eps" and q.get("eps_range") and en._ok(v):
                    lo, hi = q["eps_range"]
                    txt += (f'<div class="muted" style="font-size:10px">{tr(lo, 2)} – {tr(hi, 2)}'
                            f'{" · " + str(q["n"]) + " analysts" if q.get("n") else ""}</div>')
                der = " title=\"derived: full year minus the first three quarters (or year-to-date difference)\"" \
                    if k in q.get("derived", []) else ""
                cls = "qexp" if q["src"] == "expected" else ""
                cells += f'<td class="{cls}"{der}>{txt}{"<sup class=muted>Δ</sup>" if der else ""}</td>'
            av = annual(ak) if ak else None
            if ak == "capex" and en._ok(av):
                av = abs(av)
            cells += f'<td class="fytot">{_qv(av, kind) if ak else ""}</td>'
            body += (f'<tr class="{"qsub" if sub else ""}"><td>{esc(lab.strip())}</td>{cells}</tr>')
        c1, c2 = st.columns([1.6, 1], gap="large")
        with c1:
            H(f'<div style="overflow-x:auto"><table class="ptab qfin"><thead><tr><th></th>{head}</tr></thead>'
              f'<tbody>{body}</tbody></table></div>')
            notes = []
            if y.get("src"):
                notes.append(f'source: {y["src"]}')
            if any(q.get("derived") for q in qs):
                notes.append("Δ = derived (Q4 = full year minus Q1–Q3; cash flows from year-to-date figures)")
            if y["status"] == "in progress":
                notes.append("expected = analyst consensus (EPS and revenue) for quarters not reported yet")
            notes.append("QoQ vs the previous quarter, YoY vs the same quarter a year earlier")
            H(f'<div class="muted small" style="margin-top:6px">{esc(" · ".join(notes))}</div>')
        with c2:
            plot(quarter_fin_fig(fq, sel), key="v_fq")
            rq = [q for q in qs if q["src"] == "reported" and en._ok(q.get("revenue"))]
            if len(rq) >= 2:
                best = max(rq, key=lambda q: q["revenue"])
                g = rq[-1].get("revenue_yoy")
                H(f'<div class="gtext">FY{sel}: strongest quarter by revenue was <b>Q{best["q"]}</b> '
                  f'({big(best["revenue"])})' + (f'; the latest reported quarter grew <b>{pct(g, 1)}</b> year over '
                                                  f'year' if en._ok(g) else "") + '.</div>')


def render_analyst_panel(sym, b):
    """Analist notları, hedef fiyatlar, tahminler, revizyonlar ve son not değişiklikleri."""
    try:
        ad = md.get_analyst_detail(sym)
    except Exception:
        ad = {"src": "none"}
    price = b["d"]["last"]
    dec = 2
    with st.container(border=True):
        H('<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">'
          '<span class="panel-title">Analyst Ratings & Expectations</span><span class="muted small">consensus of '
          'the analysts covering the stock · Yahoo Finance</span></div>')
        if ad.get("src") != "real":
            H('<div class="muted">No analyst coverage data for this symbol.</div>')
            return
        c1, c2, c3 = st.columns([1, 1.45, 1], gap="large")
        with c1:
            dist = ad.get("dist") or {}
            tot = sum(dist.values())
            if tot:
                parts = [("Strong Buy", "strongBuy", "#16A34A"), ("Buy", "buy", "#34D399"), ("Hold", "hold", "#F5B544"),
                         ("Sell", "sell", "#F87171"), ("Strong Sell", "strongSell", "#B91C1C")]
                bar = "".join(f'<i style="width:{dist[k] / tot * 100:.1f}%;background:{c}" title="{n}: {dist[k]}"></i>'
                              for n, k, c in parts if dist.get(k))
                leg = "".join(f'<div class="stat-row"><span class="lbl"><span style="color:{c}">■</span> {n}</span>'
                              f'<span class="mono">{dist.get(k, 0)}</span>'
                              + (f'<span class="muted small" style="width:56px;text-align:right">'
                                 f'{dist.get(k, 0) - (ad.get("dist_3m") or {}).get(k, 0):+d} 3m</span>'
                                 if ad.get("dist_3m") else "") + '</div>' for n, k, c in parts)
                buyp = (dist.get("strongBuy", 0) + dist.get("buy", 0)) / tot * 100
                H(f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:4px">'
                  f'<b style="font-size:16px">{esc(ad.get("rec_key") or "—")}</b><span class="muted small">'
                  f'{tot} analysts · {tr(buyp, 0)}% buy'
                  + (f' · score {tr(ad["rec_mean"], 2)} (1 = strong buy, 5 = sell)' if en._ok(ad.get("rec_mean")) else "")
                  + f'</span></div><div class="ratebar">{bar}</div>{leg}')
            tg = ad.get("targets") or {}
            if en._ok(tg.get("low")) and en._ok(tg.get("high")) and tg["high"] > tg["low"]:
                lo, hi = min(tg["low"], price), max(tg["high"], price)
                span = hi - lo

                def xpos(v):
                    return (v - lo) / span * 100
                mean = tg.get("mean") or tg.get("median")
                up = (mean / price - 1) * 100 if en._ok(mean) else None
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin:12px 0 4px 0">Price targets '
                  f'<span class="muted" style="font-weight:500">· 12 months</span></div>'
                  f'<div class="ptrange"><span class="rng" style="left:{xpos(tg["low"]):.1f}%;width:'
                  f'{xpos(tg["high"]) - xpos(tg["low"]):.1f}%"></span>'
                  + (f'<span class="mk mean" style="left:{xpos(mean):.1f}%" title="mean {tr(mean, dec)}"></span>'
                     if en._ok(mean) else "") +
                  f'<span class="mk now" style="left:{xpos(price):.1f}%" title="price {tr(price, dec)}"></span></div>'
                  f'<div class="stat-row"><span class="lbl">Low · Mean · High</span><span class="mono">'
                  f'{tr(tg["low"], dec)} · {tr(mean, dec) if en._ok(mean) else "—"} · {tr(tg["high"], dec)}</span></div>'
                  + (f'<div class="stat-row"><span class="lbl">Upside to mean</span><span class="mono" '
                     f'style="color:{col(up)}">{pct(up)}</span></div>' if up is not None else ""))
        with c2:
            est = ad.get("est") or []
            if est:
                trs = ""
                for e in est:
                    rng_ = (f'<div class="muted" style="font-size:10.5px">{tr(e["eps_low"], 2)} – {tr(e["eps_high"], 2)}'
                            f'</div>' if en._ok(e.get("eps_low")) and en._ok(e.get("eps_high")) else "")
                    trs += (f'<tr><td>{esc(e["name"])}</td><td><b>{tr(e.get("eps"), 2) if en._ok(e.get("eps")) else "—"}'
                            f'</b>{rng_}</td><td>{_qv(e.get("growth"), "chg")}</td>'
                            f'<td>{big(e["rev"]) if en._ok(e.get("rev")) else "—"}</td>'
                            f'<td>{_qv(e.get("rev_growth"), "chg")}</td>'
                            f'<td class="muted">{int(e["n"]) if en._ok(e.get("n")) else "—"}</td></tr>')
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin:2px 0 4px 0">Expectations</div>'
                  f'<table class="ptab"><thead><tr><th>Period</th><th>EPS est.</th><th>EPS YoY</th><th>Revenue est.</th>'
                  f'<th>Rev. YoY</th><th>#</th></tr></thead><tbody>{trs}</tbody></table>')
            trd, rev = ad.get("trend") or {}, ad.get("revisions") or {}
            lines = []
            for idx, nm in (("0q", "current quarter"), ("0y", "current year"), ("+1y", "next year")):
                t_ = trd.get(idx) or {}
                if en._ok(t_.get("current")) and en._ok(t_.get("90daysAgo")) and t_["90daysAgo"]:
                    ch = (t_["current"] / t_["90daysAgo"] - 1) * 100
                    rv = rev.get(idx) or {}
                    lines.append(f'<div class="stat-row"><span class="lbl">EPS estimate, {nm}</span>'
                                 f'<span class="mono">{tr(t_["90daysAgo"], 2)} → {tr(t_["current"], 2)}</span>'
                                 f'<span class="mono" style="width:70px;text-align:right;color:{col(ch)}">{pct(ch, 1)}</span>'
                                 f'<span class="muted small" style="width:120px;text-align:right">'
                                 f'{rv.get("upLast30days", 0)}↑ {rv.get("downLast30days", 0)}↓ in 30 days</span></div>')
            if lines:
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin:12px 0 2px 0">Estimate revisions '
                  f'<span class="muted" style="font-weight:500">· last 90 days</span></div>' + "".join(lines))
        with c3:
            ch_ = ad.get("changes") or []
            H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin:2px 0 4px 0">Latest rating changes</div>')
            if ch_:
                out = ""
                for c in ch_[:7]:
                    act = c["action"].lower()
                    colr = UP if act in ("up", "init") and "sell" not in c["to"].lower() else DOWN if act == "down" else SOFT
                    pt_ = (f' · PT {tr(c["pt_prev"], 0) + " → " if en._ok(c.get("pt_prev")) and c["pt_prev"] else ""}'
                           f'{tr(c["pt"], 0)}' if en._ok(c.get("pt")) and c["pt"] else "")
                    out += (f'<div class="stat-row" style="align-items:flex-start"><span class="lbl">'
                            f'<b>{esc(c["firm"])}</b><div class="muted" style="font-size:11px;font-weight:500;line-height:1.3">'
                            f'{esc(c["date"])}{pt_}</div></span>'
                            f'<span class="small" style="color:{colr};text-align:right">'
                            f'{esc((c["from"] + " → ") if c["from"] and c["from"] != c["to"] else "")}{esc(c["to"])}'
                            f'</span></div>')
                H(out)
            else:
                H('<div class="muted small">No recent rating changes.</div>')


def render_value_fundamentals(b):
    f, r = b["f"], b["r"]
    sym = ACTIVE
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">01</span>'
      '<h3>Fundamentals</h3><span class="muted">Statements for the last ' + str(f["n"]) + ' years · click a year '
      'for its quarterly results</span></div>')
    # çeyrek sonuçları: seçili yıl (grafiğe tıklama ya da aşağıdaki seçici)
    try:
        fq = en.fiscal_quarters(f["dates"], md.get_sec_quarterly(sym), md.get_yf_quarterly_fin(sym),
                                (md.get_quarterly(sym) or {}).get("est"), cur_fy_end=(b.get("an") or {}).get("fy0_end"))
    except Exception:
        fq = {}
    k_y = f"fq_year_{sym}"
    fy_labels = {fy: (f"FY{fy} · in progress" if v["status"] == "in progress" else f"FY{fy}")
                 for fy, v in sorted(fq.items())}
    lab2fy = {v: k for k, v in fy_labels.items()}
    if fq and ss.get(k_y) not in lab2fy:
        rep_ = [fy for fy, v in fq.items() if any(q["src"] == "reported" for q in v["quarters"])
                and v["status"] == "reported"]
        ss[k_y] = fy_labels[max(rep_) if rep_ else max(fq)]
    for ck in ("v_inc", "v_marg", "v_cf", "v_bs"):        # önceki çalıştırmadaki tıklama
        x = picked_x(ss.get(ck), ck) if _HAS_SELECT else None
        if x and x.isdigit() and int(x) in fy_labels:
            ss[k_y] = fy_labels[int(x)]
    sel_fy = lab2fy.get(ss.get(k_y)) if fq else None
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        with st.container(border=True):
            H('<div class="panel-title">Income Statement</div><div class="muted small">Billions, reporting '
              'currency</div>')
            plot(fin_bar_chart(f, ["revenue", "gross", "op_income", "net_income"],
                               ["Revenue", "Gross profit", "Operating income", "Net income"],
                               [ACCENT, "#6EE7B7", WARN, VIOLET], sel=sel_fy), key="v_inc", select=True)
    with c2:
        with st.container(border=True):
            H('<div class="panel-title">Margins</div><div class="muted small">As % of revenue</div>')
            plot(fin_bar_chart(f, ["gross_m", "op_m", "net_m", "fcf_m"],
                               ["Gross", "Operating", "Net", "Free cash flow"],
                               ["#6EE7B7", WARN, VIOLET, ACCENT], pct=True, sel=sel_fy), key="v_marg", select=True)
    c3, c4 = st.columns(2, gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Cash Flow</div><div class="muted small">Operating, investing and '
              'free cash flow</div>')
            plot(fin_bar_chart(f, ["ocf", "capex", "fcf"],
                               ["Operating cash flow", "Capital expenditure", "Free cash flow"],
                               [ACCENT, DOWN, "#6EE7B7"], sel=sel_fy), key="v_cf", select=True)
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Balance Sheet</div><div class="muted small">Assets, equity and net debt</div>')
            plot(fin_bar_chart(f, ["assets", "equity", "net_debt"],
                               ["Total assets", "Equity", "Net debt"],
                               ["#4A515C", "#6EE7B7", DOWN], sel=sel_fy), key="v_bs", select=True)
    render_fund_quarters(b, fq, fy_labels, k_y)
    yrs = [str(y) for y in f["years"]]
    c5, c6, c7 = st.columns(3, gap="medium")
    with c5:
        with st.container(border=True):
            H('<div class="panel-title">Growth Rates</div><div class="muted small">Year over year</div>')
            plot(bar_fig(yrs[1:], [("Revenue", r["rev_yoy"][1:], ACCENT), ("EPS", r["eps_yoy"][1:], VIOLET)],
                         height=220, suffix="%", hline=0), key="v_growth")
    with c6:
        with st.container(border=True):
            H('<div class="panel-title">Debt and Cash</div><div class="muted small">Billions</div>')
            plot(bar_fig(yrs, [("Total debt", [v / 1e9 if en._ok(v) else None for v in f["debt"]], DOWN),
                               ("Cash", [v / 1e9 if en._ok(v) else None for v in f["cash"]], "#6EE7B7")],
                         height=220, suffix=" bn"), key="v_debt")
    with c7:
        with st.container(border=True):
            H('<div class="panel-title">Shareholder Returns</div><div class="muted small">Buybacks + dividends, '
              'billions</div>')
            plot(bar_fig(yrs, [("Buybacks", [abs(v) / 1e9 if en._ok(v) else None for v in f["buyback"]], ACCENT),
                               ("Dividends", [abs(v) / 1e9 if en._ok(v) else None for v in f["dividends_paid"]],
                                WARN)],
                         height=220, suffix=" bn", barmode="stack"), key="v_sh")
    with st.container(border=True):
        rows = [("Current ratio", tr(r.get("current_ratio"), 2), "above 1.5 is comfortable"),
                ("Net debt / EBITDA", tr(r.get("net_debt_ebitda"), 2), "above 3 is high leverage"),
                ("Interest coverage", tr(r.get("interest_cover"), 1), "EBIT / interest expense"),
                ("Return on assets", f'{tr(r.get("roa"), 1)}%', ""),
                ("Cash flow / net income", tr(r.get("accrual"), 2), "below 1 means weak earnings quality"),
                ("Share count change", f'{tr(r.get("share_chg"), 1)}%', "negative = buybacks"),
                ("Buybacks (last year)", big(abs(r.get("buyback")) if en._ok(r.get("buyback")) else float("nan"), ""), ""),
                ("Dividends (last year)", big(abs(r.get("dividends")) if en._ok(r.get("dividends")) else float("nan"), ""), "")]
        H('<div class="panel-title">Ratios and quality</div>' + "".join(
            f'<div class="stat-row"><span class="lbl">{esc(k)}</span>'
            f'<span class="mono">{v}</span>'
            f'<span class="muted small" style="width:180px;text-align:right">{esc(n)}</span></div>'
            for k, v, n in rows))
    render_revenue_mix(ACTIVE)
    render_analyst_panel(ACTIVE, b)


def fmt_count(v):
    if not en._ok(v):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:,.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:,.2f}M"
    if a >= 1e4:
        return f"{v:,.0f}"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def _fy_label(end):
    try:
        return "FY" + pd.Timestamp(end).strftime("%y")
    except Exception:
        return str(end)


def render_revenue_mix(sym):
    """Gelir kırılımı (ürün/hizmet · segment · coğrafya) + abone/müşteri gibi operasyonel göstergeler — SEC XBRL."""
    try:
        rb = md.get_revenue_breakdown(sym)
    except Exception:
        rb = {"src": "none", "why": "SEC EDGAR could not be reached right now."}
    with st.container(border=True):
        rev = rb.get("rev") or {}
        src = ""
        if rb.get("src") == "real":
            fy = pd.Timestamp(rev["ends"][0]).strftime("%b %d, %Y") if rev.get("ends") else rb.get("report") or ""
            src = (f'SEC {esc(rb.get("form"))} · fiscal year ending {esc(fy)} · filed {esc(rb.get("filed"))} · '
                   f'<a class="lnk" href="{esc(safe_url(rb.get("url")))}" target="_blank">filing ↗</a>')
        H(f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">'
          f'<span class="panel-title">Where the Revenue Comes From</span>'
          f'<span class="muted small">{src}</span></div>')
        if rb.get("src") != "real":
            H(f'<div class="muted" style="margin:8px 0 4px 0">{esc(rb.get("why") or "No segment data.")} '
              f'Revenue by business line and operating metrics are read from SEC filings (XBRL).</div>')
            return
        c1, c2 = st.columns([1.45, 1], gap="large")
        with c1:
            groups = rev.get("groups") or []
            cur = rev.get("currency") or "USD"
            if not groups:
                H('<div class="muted" style="margin-top:8px">This filing reports revenue only as one total — no '
                  'breakdown by product, segment or region is tagged.</div>')
            else:
                names = [g["name"] for g in groups]
                pick = seg("Breakdown", names, f"w_revmix_{sym}", names[0]) if len(names) > 1 else names[0]
                g = next((x for x in groups if x["name"] == pick), groups[0])
                ends = rev.get("ends") or []
                tot0 = (rev.get("total") or [None])[0]
                mx = max(r["values"][0] for r in g["rows"]) or 1
                rows = ""
                for r in g["rows"]:
                    v0 = r["values"][0]
                    yoy = r.get("yoy")
                    hist = " → ".join(f'{_fy_label(e)} {big(v, cur)}' for e, v in
                                      reversed(list(zip(ends, r["values"]))) if en._ok(v))
                    rows += (f'<div class="mixrow" title="{esc(hist)}"><span class="ml">{esc(r["label"])}</span>'
                             f'<span class="mb"><i style="width:{max(1.5, v0 / mx * 100):.1f}%"></i></span>'
                             f'<span class="mv">{big(v0, cur)}</span>'
                             f'<span class="ms">{tr(r["share"], 1) + "%" if en._ok(r.get("share")) else "—"}</span>'
                             f'<span class="my" style="color:{col(yoy) if en._ok(yoy) else MUT}">'
                             f'{pct(yoy, 1) if en._ok(yoy) else "—"}</span></div>')
                H(f'<div class="mixhead"><span class="ml">{esc(g["name"])}</span><span class="mb"></span>'
                  f'<span class="mv">{_fy_label(ends[0]) if ends else ""}</span><span class="ms">share</span>'
                  f'<span class="my">YoY</span></div>{rows}')
                notes = [f'Total revenue {big(tot0, cur)}' + (f' ({pct((tot0 / rev["total"][1] - 1) * 100, 1)} YoY)'
                                                               if len(rev.get("total") or []) > 1 and
                                                               en._ok(rev["total"][1]) and rev["total"][1] else "")]
                if g.get("overlap"):
                    notes.append("some lines overlap (a line can include another), so shares add up to more than 100%")
                notes.append("hover a line for its 3-year history")
                H(f'<div class="muted small" style="margin-top:6px">{esc(" · ".join(notes))}</div>')
                subs = [r for gg in groups for r in gg["rows"]
                        if re.search(r"subscri|recurring|membership|saas", r["label"], re.I)
                        and gg["key"] == "product"]
                if subs:
                    sv = max(subs, key=lambda r: r["values"][0])
                    H(f'<div class="gtext" style="margin-top:8px"><b>{esc(sv["label"])}</b> brings in '
                      f'<b>{tr(sv["share"], 0)}%</b> of revenue'
                      + (f', growing {pct(sv["yoy"], 1)} a year' if en._ok(sv.get("yoy")) else "")
                      + ' — the recurring part of the business.</div>')
        with c2:
            kp = rb.get("kpis") or []
            ks = rb.get("kpi_src") or {}
            H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin-top:2px">Operating metrics '
              f'<span class="muted" style="font-weight:500">· customers, subscribers, members, backlog'
              + (f' · {esc(ks.get("form"))} filed {esc(ks.get("filed"))}' if ks else "") + '</span></div>')
            if kp:
                tiles = ""
                for k in kp:
                    val = big(k["value"], k.get("currency") or "USD") if k["kind"] == "money" else fmt_count(k["value"])
                    yoy = k.get("yoy")
                    per = {"i": "as of", "q": "quarter to", "y": "year to"}.get(k["period"], "period to")
                    when = pd.Timestamp(k["end"]).strftime("%b %Y") if k.get("end") else ""
                    tiles += (f'<div class="tile kpitile"><span class="k">{esc(k["label"])}</span>'
                              f'<span class="v">{val}</span><span class="muted small">{per} {when}'
                              + (f' · <span style="color:{col(yoy)}">{pct(yoy, 1)} YoY</span>' if en._ok(yoy) else "")
                              + '</span></div>')
                H(f'<div class="kpigrid">{tiles}</div>')
            else:
                H('<div class="muted small" style="margin-top:8px">No customer, subscriber or member counts are '
                  'tagged in this company\'s filings. Many companies publish them only in earnings releases and '
                  'investor presentations — see the filing link above.</div>')
def render_longterm():
    H('<div class="page-title">Long Term</div><div class="muted" style="margin-bottom:12px">Sentiment, sectors '
      'and a value screen for long-term investing</div>')
    fg = md.get_fear_greed()
    l, r = st.columns([1.1, 1], gap="large")
    with l:
        with st.container(border=True):
            H(f'<div class="sec-head"><h3>Fear &amp; Greed Index</h3><span style="margin-left:auto">'
              f'{src_chip(fg["src"])}</span></div><div class="muted">Which emotion is driving the market right now?</div>')
            plot(gauge(fg["value"], [{"range": [0, 25], "color": DOWN}, {"range": [25, 45], "color": "#F0883E"},
                                     {"range": [45, 55], "color": "#D9C441"}, {"range": [55, 75], "color": "#56B06A"},
                                     {"range": [75, 100], "color": UP}], 240, number=True), key="fg_gauge")
            H(f'<div style="text-align:center;font-size:17px;font-weight:700;margin-top:-10px">{esc(fg["label"])}</div>'
              f'<div style="background:#12171f;border-left:3px solid {WARN};border-radius:8px;padding:12px 14px;'
              f'margin-top:12px;color:#c9d1d9;font-style:italic">“{esc(fg["quote"])}”<br><span class="muted" '
              f'style="font-style:normal">— {esc(fg["quote_author"])}</span></div>')
    with r:
        with st.container(border=True):
            H('<div class="panel-title">History</div>')
            for h in fg["history"]:
                hc = DOWN if h["value"] < 45 else ("#D9C441" if h["value"] < 55 else UP)
                H(f'<div class="stat-row"><span class="lbl">{esc(h["when"])}<br><b style="color:{TXT}">'
                  f'{esc(h["label"])}</b></span><span class="mono" style="font-size:20px;font-weight:700;color:{hc}">'
                  f'{h["value"]}</span></div>')
    with st.container(border=True):
        render_sector_block()
    render_sector_map()
    with st.container(border=True):
        vs = md.get_value_stocks()
        H(f'<div class="sec-head"><h3>Cheap Companies (PEG / Forward PE)</h3><span class="muted">Yahoo '
          f'“undervalued large caps” screen · sorted by forward PE, cheapest first</span>'
          f'<span style="margin-left:auto">{src_chip(vs.attrs.get("src"))}</span></div>')
        table(vs, column_config={"PEG": st.column_config.NumberColumn("PEG", format="%.2f"),
                                 "Forward PE": st.column_config.NumberColumn("Forward PE", format="%.1f"),
                                 "Profit Margin %": st.column_config.NumberColumn("Profit margin %", format="%.1f%%"),
                                 "EPS Growth %": st.column_config.NumberColumn("EPS growth %", format="%.1f%%")})


# ======================================================================
# BÖLÜM: SHORT TERM (Swing & Kısa Vade)
# ======================================================================
@st.cache_data(ttl=900, show_spinner="Scanning the universe…")
def run_scan(conds_json, logic, min_match, fetched_key):
    U = md.get_universe_history()
    hist = U["hist"]
    spy = hist.get("SPY")
    emap = md.get_earnings_map()
    edays = md.earnings_days(emap["map"])
    if emap["src"] == "real":  # takvimde yoksa önümüzdeki 3 haftada bilançosu yok demektir
        edays = {t: edays.get(t, en.EARN_FAR) for t in hist}
    return en.scan(hist, json.loads(conds_json), logic, min_match,
                   spy["Close"] if spy is not None else None, edays, md.NAMES)


@st.cache_data(ttl=900, show_spinner=False)
def get_regime(fetched_key):
    hist = md.get_universe_history()["hist"]
    above = [float(df["Close"].iloc[-1]) > float(en.sma(df["Close"], 50).iloc[-1])
             for t, df in hist.items() if t != "SPY" and len(df) >= 50]
    vix = md.get_quotes(["^VIX"]).get("^VIX")
    smp = md.get_sector_month_perf()
    leader = max(smp, key=lambda s: s["change_pct"])["name"] if smp else None
    return en.market_regime(hist.get("SPY"), vix["last"] if vix else None,
                            100 * sum(above) / len(above) if above else None, leader)


def _flt_reset():
    ss.flt_rows = copy.deepcopy(en.DEFAULT_FILTER)
    ss.flt_min = len(en.DEFAULT_FILTER) - 1
    ss.flt_lastN = len(en.DEFAULT_FILTER)
    ss.flt_logic = "AND"
    ss.flt_name = "Trend pullback"
    ss.flt_ver += 1


def cond_editor(rows_key, ver_key, editor_prefix):
    """Ekle / çıkar / değiştir: herhangi bir indikatör, koşul ve eşik."""
    df_in = pd.DataFrame(ss[rows_key], columns=en.COND_COLS)
    edited = st.data_editor(
        df_in, key=f"{editor_prefix}_{ss[ver_key]}", num_rows="dynamic", hide_index=True,
        **_wkw(st.data_editor),
        column_config={
            "Active": st.column_config.CheckboxColumn("Active", default=True, width="small"),
            "Indicator": st.column_config.SelectboxColumn("Indicator", options=en.IND_NAMES, required=True,
                                                         default="RSI (14)", width="medium"),
            "Condition": st.column_config.SelectboxColumn("Condition", options=en.OPS, required=True, default=">",
                                                      width="small"),
            "Compare": st.column_config.SelectboxColumn("Compare", options=en.COMPARE_OPTIONS,
                                                            required=True, default=en.NUM, width="medium",
                                                            help="Number → uses the Value column; or another indicator"),
            "Value": st.column_config.NumberColumn("Value", default=0.0, step=0.1, format="%.2f", width="small"),
        })
    rows = edited.to_dict("records")
    clean = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in rows]
    if en.normalize_conds(clean) != en.normalize_conds(ss[rows_key]) or len(clean) != len(ss[rows_key]):
        ss[rows_key] = [r for r in clean if r.get("Indicator")]
        ss[ver_key] += 1
        st.rerun()


def render_filter_editor(n_active):
    with st.container(border=True):
        H('<div class="sec-head"><h3>Edit filter</h3><span class="muted">Add a row (+), delete one (select the row → '
          'trash can), change the indicator / condition / threshold — the scan updates instantly</span></div>')
        c1, c2, c3 = st.columns([2, 1.3, 1.2], vertical_alignment="bottom")
        with c1:
            st.text_input("Filter name", key="flt_name")
        with c2:
            st.caption("Logic")
            seg("Logic", ["AND", "OR"], "flt_logic", "AND",
                fmt=lambda x: "AND (all / at least N)" if x == "AND" else "OR (any)")
        with c3:
            mx = max(1, n_active)
            ss.flt_min = int(min(max(1, int(ss.flt_min or 1)), mx))
            st.number_input("Minimum matching conditions", min_value=1, max_value=mx, step=1, key="flt_min",
                            disabled=ss.flt_logic != "AND")
        cond_editor("flt_rows", "flt_ver", "flt_ed")
        b1, b2, _ = st.columns([1, 1, 3])
        with b1:
            button("Reset to default", key="flt_reset", on_click=_flt_reset)
        with b2:
            if button("Close", key="flt_close"):
                ss.flt_edit = False
                st.rerun()
        render_saved_filters()
        with st.expander("Indicator glossary"):
            H("".join(f'<div class="stat-row"><span style="width:190px;font-weight:700">{esc(n)}</span>'
                      f'<span class="lbl small">{esc(m["desc"])}</span><span class="chip">{esc(m["group"])}</span></div>'
                      for n, m in en.INDICATORS.items()))


# ---------------------------------------------------------------- kayıtlı filtreler
def flt_snapshot():
    return {"name": (ss.get("flt_name") or "My filter").strip()[:40] or "My filter",
            "rows": copy.deepcopy(en.normalize_conds(ss.flt_rows)),
            "logic": ss.get("flt_logic") or "AND",
            "min": int(ss.get("flt_min") or 1)}


def apply_pending_filter():
    """Kayıtlı filtre yüklemesi — widget'lar çizilmeden önce uygulanır."""
    f = ss.get("flt_pending")
    if not f:
        return
    ss.flt_pending = None
    rows = f.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return
    ss.flt_rows = copy.deepcopy(rows)
    ss.flt_ver = int(ss.get("flt_ver") or 0) + 1
    n_act = sum(1 for r in rows if r.get("Active"))
    ss.flt_lastN = n_act
    for k, v in (("flt_name", str(f.get("name") or "My filter")[:40]),
                 ("flt_logic", f.get("logic") if f.get("logic") in ("AND", "OR") else "AND"),
                 ("flt_min", int(min(max(1, int(f.get("min") or 1)), max(1, n_act))))):
        ss[k] = v
        ss["_last_" + k] = v


def render_saved_filters():
    H('<div style="font-size:12px;font-weight:700;margin:14px 0 4px 0">My saved filters</div>')
    saved = ss.get("saved_filters") or []
    names = [f["name"] for f in saved]
    opts = ["—"] + names
    if ss.get("w_savedflt") not in opts:      # silinen filtre seçili kalmasın
        ss["w_savedflt"] = "—"
    s1, s2, s3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    with s1:
        pick = st.selectbox("Saved filter", opts, key="w_savedflt", label_visibility="collapsed")
    with s2:
        if button("Load", key="flt_load", disabled=pick == "—"):
            f = next((x for x in saved if x["name"] == pick), None)
            if f:
                ss.flt_pending = copy.deepcopy(f)
                st.toast(f"“{pick}” loaded")
                st.rerun()
    with s3:
        if button("Delete", key="flt_del", disabled=pick == "—"):
            ss.saved_filters = [x for x in saved if x["name"] != pick]
            st.toast(f"“{pick}” deleted")
            st.rerun()
    v1, v2 = st.columns([1, 1])
    with v1:
        if button("💾 Save this filter", key="flt_save", primary=True):
            snap = flt_snapshot()
            ss.saved_filters = [x for x in saved if x["name"] != snap["name"]] + [snap]
            del ss.saved_filters[20:]
            st.toast(f"“{snap['name']}” saved")
            st.rerun()
    with v2:
        try:
            st.download_button("⬇ Download as JSON", key="flt_export",
                               data=json.dumps(ss.get("saved_filters") or [], ensure_ascii=False, indent=1),
                               file_name="pulse_filtreler.json", mime="application/json")
        except Exception:
            pass
    if names:
        H('<div class="muted small" style="margin-top:4px">' +
          " · ".join(esc(n) for n in names) + "</div>")
    with st.expander("Restore from JSON"):
        txt = st.text_area("Filter JSON", key="flt_import_txt", height=90,
                           placeholder='[{"name": "...", "rows": [...]}]', label_visibility="collapsed")
        if button("Import", key="flt_import"):
            try:
                data = json.loads(txt or "[]")
                ok = [x for x in data if isinstance(x, dict) and x.get("rows")]
                if not ok:
                    raise ValueError("empty")
                have = {x["name"] for x in ok}
                ss.saved_filters = [x for x in (ss.get("saved_filters") or [])
                                    if x["name"] not in have] + ok
                del ss.saved_filters[20:]
                st.toast(f"{len(ok)} filters imported")
                st.rerun()
            except Exception:
                st.warning("Could not read the JSON — paste the content of the downloaded file exactly as it is.")
        H('<div class="muted small">Filters are kept for the session; if the app restarts you can '
          'restore them with this JSON.</div>')


def _seed_journal(hist):
    out = []
    for t, ago in (("MRVL", 8), ("AMD", 5), ("CRWD", 3)):
        df = hist.get(t)
        if df is None or len(df) < 30:
            continue
        a = en._last(en.atr(df))
        entry = float(df["Close"].iloc[-ago - 1])
        out.append({"t": t, "dir": "LONG", "entry": entry, "stop": entry - 1.5 * a, "target": entry + 3 * a,
                    "atr": a, "date": df.index[-ago - 1].strftime("%Y-%m-%d"), "example": True})
    return out


def opp_chart(df, o):
    d = df.tail(60)
    fig = go.Figure(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
                                   increasing_line_color=UP, decreasing_line_color=DOWN, name=o["ticker"]))
    fig.add_hrect(y0=o["entry_lo"], y1=o["entry_hi"], fillcolor="rgba(91,140,255,.14)",
                  line=dict(color="rgba(91,140,255,.5)", width=1))
    for y, c_, lbl in ((o["target"], UP, "Target"), (o["stop"], DOWN, "Stop"), (o["mid"], ACCENT, "Entry")):
        fig.add_hline(y=y, line=dict(color=c_, width=1, dash="dash" if lbl != "Entry" else "dot"),
                      annotation_text=f"{lbl} {tr(y)}", annotation_position="right",
                      annotation_font=dict(color=c_, size=10))
    lo, hi = min(float(d["Low"].min()), o["stop"]), max(float(d["High"].max()), o["target"])
    fig.update_yaxes(range=[lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06])
    fig.update_layout(xaxis_rangeslider_visible=False)
    rb = _rangebreaks(d.index)
    if rb:
        fig.update_xaxes(rangebreaks=rb)
    return _layout(fig, 230, margin=dict(l=4, r=70, t=6, b=4))


# ======================================================================
# YAPAY ZEKA TRADE FIRSATLARI
# ======================================================================
AI_STATE_STYLE = {"breakout": (UP, UP_BG, "BREAKOUT"), "retest": (ACCENT, ACC_BG, "RETEST"),
                  "forming": (WARN, WARN_BG, "FORMING")}
C15_STYLE = {"confirmed": (UP, UP_BG), "pending": (WARN, WARN_BG),
             "failed": (DOWN, DOWN_BG), "no data": (MUT, NEU_BG)}


def ai_token():
    """Önbellek anahtarı: 10 dakikalık pencere + elle yenileme sayacı."""
    now = pd.Timestamp.now(tz=md.TZ)
    return f'{now:%Y-%m-%d %H}:{now.minute // 10}|{ss.get("ai_nonce", 0)}'


@st.cache_data(ttl=600, show_spinner="Scanning the market — NASDAQ + NYSE…")
def run_ai_scan(token, cfg_json):
    """Üç aşamalı tarama. Ağır iş yalnızca eleme sonrası kalan sembollerde yapılır."""
    cfg = json.loads(cfg_json)
    snap = md.get_market_snapshot()
    cand, steps = en.ai_prefilter(snap, cfg)
    idx = md.get_daily_batch(("SPY", "QQQ"))
    regime = en.ai_regime(idx, int(cfg.get("regime_ema", 50)))
    prelim = [t for t in list(cand["ticker"].head(int(cfg.get("prelim", 60))))] if len(cand) else []
    daily = md.get_daily_batch(tuple(prelim)) if prelim else {}
    meta = cand.set_index("ticker").to_dict("index") if len(cand) else {}
    passed, ema_fail = [], 0
    for t in prelim:
        r = en.ai_evaluate(t, daily.get(t), meta=meta.get(t), cfg=cfg)
        if not r:
            continue
        if r["ema_ok"]:
            passed.append(r)
        else:
            ema_fail += 1
    passed.sort(key=lambda r: -r["volume"])
    top = passed[:int(cfg.get("top", 20))]
    if top:
        i15 = md.get_intraday_batch(tuple(r["ticker"] for r in top))
        for r in top:
            b = r["best"]
            en.ai_apply_15m(r, en.confirm_15m(i15.get(r["ticker"]), b["level"], b["kind"]) if b else None)
    top.sort(key=lambda r: -r["score"])
    for r in top:
        r["summary"] = en.ai_summary(r)
        d = daily.get(r["ticker"])
        r["df"] = d.tail(120).copy() if d is not None else None   # ayrıntı grafiği için
    return {"rows": top, "steps": steps, "regime": regime, "ema_fail": ema_fail,
            "prelim_n": len(prelim), "passed_n": len(passed),
            "src": snap.attrs.get("src", "mock") if snap is not None else "none",
            "capless": bool(steps.get("capless")),
            "at": pd.Timestamp.now(tz=md.TZ).strftime("%H:%M")}


def ai_chart(df, r, height=250):
    """Fırsatın günlük grafiği + kırılım seviyesi, stop ve hedefler."""
    d = df.tail(90)
    fig = go.Figure(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"],
                                   close=d["Close"], increasing_line_color=UP, decreasing_line_color=DOWN,
                                   name=r["ticker"]))
    lines = []
    p, b = r.get("plan"), r.get("best")
    if b:
        lines.append((b["level"], ACCENT, "Level"))
    if p:
        lines += [(p["stop"], DOWN, "Stop"), (p["tp1"], UP, "TP1 · %%%d" % round(p["part1"] * 100)),
                  (p["tp2"], "#6EE7B7", "TP2 · rest")]
    for y, c_, lbl in lines:
        fig.add_hline(y=y, line=dict(color=c_, width=1, dash="dot" if lbl == "Level" else "dash"),
                      annotation_text=f"{lbl} {tr(y)}", annotation_position="right",
                      annotation_font=dict(color=c_, size=10))
    ys = [float(d["Low"].min()), float(d["High"].max())] + [y for y, _, _ in lines]
    lo, hi = min(ys), max(ys)
    fig.update_yaxes(range=[lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06])
    fig.update_layout(xaxis_rangeslider_visible=False)
    rb = _rangebreaks(d.index)
    if rb:
        fig.update_xaxes(rangebreaks=rb)
    return _layout(fig, height, margin=dict(l=4, r=96, t=6, b=4))


def push_notes(rows):
    """Taze ve teyitli kırılımları bildirim kutusuna düşürür (aynı gün bir kez)."""
    day = pd.Timestamp.now(tz=md.TZ).strftime("%Y-%m-%d")
    have = {f'{n["ticker"]}|{n["day"]}' for n in ss.notes}
    gone = set(ss.get("notes_gone") or [])
    added = 0
    for r in rows:
        if not en.ai_fresh_breakout(r):
            continue
        k = f'{r["ticker"]}|{day}'
        if k in have or k in gone:     # aynı gün tekrar düşmesin, silinenler geri gelmesin
            continue
        b, c = r["best"], r.get("c15") or {}
        ss.notes.insert(0, {"ticker": r["ticker"], "day": day,
                            "at": pd.Timestamp.now(tz=md.TZ).strftime("%H:%M"),
                            "title": f'{r["ticker"]} · {b["name"]}',
                            "body": f'{tr(r["price"])} — {b["note"]} · 15m {c.get("state", "—")}',
                            "level": b["level"], "score": r["score"]})
        added += 1
    del ss.notes[40:]
    return added


def render_ai_opps():
    anchor("ai")
    cfg = en.ai_cfg({"tp1_part": 0.40})
    res = run_ai_scan(ai_token(), json.dumps(cfg, sort_keys=True))
    rows, reg, steps = res["rows"], res["regime"], res["steps"]
    new_n = push_notes(rows)
    if new_n:
        st.toast(f"🔔 {new_n} new breakout alerts")
        st.rerun()   # başlıktaki zil rozeti aynı anda güncellensin

    t1, t2 = st.columns([2.8, 1.6], vertical_alignment="center")
    with t1:
        H(f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
          f'<span style="font-size:20px;font-weight:800">🤖 AI Trade Opportunities</span>'
          f'{src_chip(res["src"])}</div>'
          f'<div class="muted small" style="margin-top:3px">NASDAQ + NYSE scan · last scan {res["at"]} · '
          f'top {res["prelim_n"]} candidates → {res["passed_n"]} pass the EMA gate → highest volume '
          f'{len(rows)}</div>')
    with t2:
        c1, c2 = st.columns(2)
        with c1:
            ss.ai_auto = bool(toggle("Intraday refresh", "w_aiauto",
                                     "Re-runs the scan at a set interval while the page is open."))
        with c2:
            if button("↻ Rescan", key="btn_airescan", primary=True):
                ss.ai_nonce = int(ss.get("ai_nonce", 0)) + 1
                md.get_market_snapshot.clear()
                md.get_daily_batch.clear()
                md.get_intraday_batch.clear()
                st.rerun()

    # ---- bölge (rejim) kapısı
    sp, qq = reg.get("SPY"), reg.get("QQQ")
    def _rchip(nm, v):
        if not v:
            return f'<span class="badge" style="color:{MUT};background:{NEU_BG}">{nm} —</span>'
        c_ = UP if v["ok"] else DOWN
        return (f'<span class="badge" style="color:{c_};background:{UP_BG if v["ok"] else DOWN_BG}">'
                f'{nm} {"✓" if v["ok"] else "✕"} 50 EMA {pct(v["pct"]) if v["pct"] is not None else ""}</span>')
    ok = bool(reg.get("ok"))
    H(f'<div class="critbar" style="margin-top:12px"><div style="display:flex;align-items:center;gap:8px;'
      f'flex-wrap:wrap"><span class="boxlbl">Regime filter</span>{_rchip("S&amp;P 500", sp)}{_rchip("Nasdaq", qq)}'
      f'</div><div class="muted small" style="flex:1 1 300px">The strategy only looks for longs while both indices '
      f'are above their 50-day EMA.</div></div>')
    if not ok:
        st.warning("At least one index is below its 50-day EMA — the strategy doesn't look for longs in this regime. "
                   "The list below is shown for information only.")

    H(f'<div class="funnel"><div>Universe<b>{steps.get("evren", 0)}</b></div>'
      f'<div>Price ≥ $3<b>{steps.get("price", 0)}</b></div>'
      f'<div>Daily change +<b>{steps.get("degisim", 0)}</b></div>'
      f'<div>Market cap ≥ $300M<b>'
      f'{"—" if res["capless"] else steps.get("piyasa_degeri", 0)}</b></div>'
      f'<div>Above 21 &amp; 50 EMA<b>{res["passed_n"]}</b></div>'
      f'<div>Top {cfg["top"]} by volume<b>{len(rows)}</b></div></div>')
    if res["capless"]:
        H('<div class="muted small">The Nasdaq screener did not respond — scanned a limited universe, '
          'the market-cap filter could not be applied.</div>')

    if not rows:
        H('<div class="muted" style="padding:18px 0">No stocks match the filter today.</div>')
        return

    sel = next((r for r in rows if r["ticker"] == AIP), rows[0])
    left, right = st.columns([2.25, 1], gap="medium")
    with left:
        head = ('<div class="opp-grid ai-grid opp-head"><span>Symbol</span><span>Pattern</span>'
                '<span class="r">Price</span><span class="r">Volume</span><span>15 min</span>'
                '<span class="r">Stop</span><span class="r">R/R</span><span>Score</span></div>')
        body = ""
        for r in rows:
            b, p, c = r["best"], r["plan"], r.get("c15") or {}
            sfg, sbg, slab = AI_STATE_STYLE.get((b or {}).get("state"), (MUT, NEU_BG, "—"))
            cfg_, cbg = C15_STYLE.get(c.get("state"), (MUT, NEU_BG))
            sc = UP if r["score"] >= 70 else ACCENT if r["score"] >= 55 else WARN
            body += (f'<a class="opp-grid ai-grid opp-row{" sel" if r["ticker"] == sel["ticker"] else ""}" '
                     f'target="_self" href="{link(aip=r["ticker"], f="ai")}">'
                     f'<span class="cellsym">{avatar(r["ticker"], 32)}'
                     f'<span style="min-width:0"><b style="font-size:13.5px">{esc(r["ticker"])}</b>'
                     f'<div class="nm" title="{esc(r["name"])}">{esc(r["name"])}</div></span></span>'
                     f'<span class="cellstk"><span class="aist" style="color:{sfg};background:{sbg}">'
                     f'{slab}</span><span class="sub" title="{esc((b or {}).get("name", "no pattern"))}">'
                     f'{esc((b or {}).get("name", "no pattern"))}</span></span>'
                     f'<span class="r"><div style="font-weight:600">{tr(r["price"])}</div>'
                     f'<div style="font-size:11px;font-weight:600;color:{col(r["chg"])}">{pct(r["chg"])}</div></span>'
                     f'<span class="r" style="color:{SOFT}">{big(r["volume"], "")}</span>'
                     f'<span><span class="aist" style="color:{cfg_};background:{cbg}">'
                     f'{esc(c.get("state", "—"))}</span></span>'
                     f'<span class="r" style="color:{DOWN}">{tr(p["stop"]) if p else "—"}</span>'
                     f'<span class="r" style="font-weight:700">{tr(p["rr1"], 1) if p else "—"}</span>'
                     f'<span class="cellscore"><span class="scorebar"><span style="display:block;height:6px;'
                     f'width:{r["score"]:.0f}%;background:{sc}"></span></span>'
                     f'<span class="mono" style="font-weight:600">{tr(r["score"], 0)}</span></span></a>')
        H(f'<div class="opp"><div class="opp-scroll">{head}{body}</div><div class="opp-foot">'
          f'<span>Score: pattern strength + breakout state + 15-minute confirmation + R/R + trend</span>'
          f'<span style="margin-left:auto">The top {cfg["top"]} stocks by volume are evaluated</span></div></div>')
    with right:
        render_ai_detail(sel)
    if ss.get("ai_auto"):
        components.html(_AUTO_JS % 180, height=0)
        H('<div class="muted small" style="margin-top:8px">Intraday refresh is on — the page reloads every '
          '3 minutes and re-runs the scan.</div>')


# Sayfayı belirli aralıkla yenileyip taramayı tekrarlar (yalnızca sekme açıkken).
_AUTO_JS = """<script>
(function(){ setTimeout(function(){ try{ window.parent.location.reload(); }catch(e){} }, %d*1000); })();
</script>"""


def render_ai_detail(r):
    """Seçili fırsatın grafiği, planı ve kural tabanlı açıklaması."""
    b, p, c = r["best"], r["plan"], r.get("c15") or {}
    with st.container(border=True):
        sfg, sbg, slab = AI_STATE_STYLE.get((b or {}).get("state"), (MUT, NEU_BG, "—"))
        H(f'<div style="display:flex;align-items:center;gap:11px">{avatar(r["ticker"], 38)}'
          f'<div style="flex:1;min-width:0"><a class="plain" target="_self" '
          f'href="{link(sec="Markets", sym=r["ticker"])}"><b style="font-size:17px">{esc(r["ticker"])}</b></a>'
          f'<div class="muted small">{esc(r["name"])}{" · " + esc(r["sector"]) if r["sector"] else ""}</div></div>'
          f'<span class="aist" style="color:{sfg};background:{sbg}">{slab}</span></div>')
        if r.get("df") is not None and len(r["df"]) > 10:
            plot(ai_chart(r["df"], r), key=f'aic_{r["ticker"]}')
        if b:
            H(f'<div class="muted small" style="margin-top:2px"><b style="color:{SOFT}">{esc(b["name"])}</b> — '
              f'{esc(b["note"])} · confidence {tr(b["conf"] * 100, 0)}% · volume {tr(b["vol_x"], 1)}x</div>')
        cfg_, cbg = C15_STYLE.get(c.get("state"), (MUT, NEU_BG))
        H(f'<div style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
          f'<span class="aist" style="color:{cfg_};background:{cbg}">15m · {esc(c.get("state", "—"))}</span>'
          f'<span class="muted small" style="flex:1">{esc(c.get("note", ""))}</span></div>')
        if p:
            tiles = [("Entry", tr(p["entry"]), TXT), ("Stop", tr(p["stop"]), DOWN),
                     (f'TP1 · {round(p["part1"] * 100)}%', tr(p["tp1"]), UP),
                     (f'TP2 · rest {round(p["part2"] * 100)}%', tr(p["tp2"]), "#6EE7B7")]
            H('<div class="plan">' + "".join(
                f'<div class="tile"><span class="k">{esc(k)}</span>'
                f'<span class="v" style="color:{c_}">{v}</span></div>' for k, v, c_ in tiles) + "</div>")
            H(f'<div class="planrow"><span class="l">Risk</span>'
              f'<span class="v" style="color:{DOWN}">−{tr(p["risk_pct"], 2)}%</span></div>'
              f'<div class="planrow"><span class="l">R/R · TP1 / TP2</span>'
              f'<span class="v">1 : {tr(p["rr1"], 2)}  ·  1 : {tr(p["rr2"], 2)}</span></div>'
              f'<div class="planrow"><span class="l">Stop based on</span>'
              f'<span class="v" style="font-size:12px">{esc(p["stop_src"])}</span></div>'
              f'<div class="planrow"><span class="l">TP1 based on</span>'
              f'<span class="v" style="font-size:12px">{esc(p["tp1_src"])}</span></div>')
            H(f'<div class="gtext" style="margin-top:10px">{esc(p["rule"])}</div>')
        if r.get("summary"):
            with st.expander("Why this opportunity is listed"):
                H(f'<div class="greason">{esc(r["summary"])}</div>')
        if p and button("Add to trade journal", key=f'aij_{r["ticker"]}', primary=True):
            if ss.journal is None:
                ss.journal = []
            ss.journal.append({"t": r["ticker"], "dir": "LONG", "entry": p["entry"], "stop": p["stop"],
                               "target": p["tp1"], "atr": p["atr"],
                               "date": pd.Timestamp.today().strftime("%Y-%m-%d"), "example": False})
            st.toast(f'{r["ticker"]} added to the trade journal')


AI_MODE = "🤖 AI Opportunities"


def render_short():
    """Short Term: hazır yapay zeka stratejisi ya da kullanıcının kendi filtresi."""
    now0 = pd.Timestamp.now(tz=md.TZ)
    H(f'<div class="page-title">Swing &amp; Short Term</div><div class="muted" style="margin-bottom:10px">'
      f'<span class="dot-live"></span>{md.tr_date_label(now0)} {now0.year} · a ready-made strategy or your own filter'
      f'</div>')
    mode = seg("Mode", [AI_MODE, "My Filter"], "w_aimode", AI_MODE)
    if mode == AI_MODE:
        render_ai_opps()
        render_journal(md.get_universe_history()["hist"])
        return
    render_own_filter()


def render_own_filter():
    apply_pending_filter()
    U = md.get_universe_history()
    hist = U["hist"]
    fkey = U["fetched"].isoformat()
    conds = en.normalize_conds(ss.flt_rows)
    active = [c for c in conds if c["Active"]]
    N = len(active)
    # Koşul eklenince/çıkarılınca "en az N" eşiği aynı toleransı korusun (ör. 5/6 → 6/7)
    lastN = ss.get("flt_lastN")
    if lastN is not None and int(lastN) != N:
        ss.flt_min = int(min(max(1, int(ss.flt_min or 1) + (N - int(lastN))), max(1, N)))
    ss.flt_lastN = N
    min_match = int(min(max(1, int(ss.flt_min or 1)), max(1, N)))
    opps = run_scan(json.dumps(conds, ensure_ascii=False, sort_keys=True), ss.flt_logic, min_match, fkey)
    now = pd.Timestamp.now(tz=md.TZ)

    t1, t2 = st.columns([2.6, 2], vertical_alignment="bottom")
    with t1:
        H(f'<div style="font-size:20px;font-weight:800">My Filter</div><div class="muted">'
          f'<span class="dot-live"></span>Last scan {U["fetched"].strftime("%H:%M")} · {U["n"]} stocks scanned'
          f'</div>')
    with t2:
        b0, b1, b2 = st.columns([1.1, 1.2, 1.3], vertical_alignment="center")
        with b0:
            H(f'<div style="text-align:right">{src_chip(U["src"])}</div>')
        with b1:
            if button("Close filter" if ss.flt_edit else "Edit filter", key="btn_flt_edit"):
                ss.flt_edit = not ss.flt_edit
                st.rerun()
        with b2:
            if button("↻ Refresh scan", key="btn_rescan", primary=True):
                md.get_universe_history.clear()
                run_scan.clear()
                get_regime.clear()
                st.rerun()

    chips = "".join(f'<span class="crit">{esc(en.cond_text(c))}</span>' for c in active) or \
        '<span class="muted">No active conditions — the whole universe is listed</span>'
    logic_txt = ("all" if min_match >= N else f"at least {min_match}/{N} conditions") if ss.flt_logic == "AND" \
        else "any (OR)"
    H(f'<div class="critbar" style="margin-top:12px"><div style="display:flex;align-items:center;gap:10px">'
      f'<span class="ficon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{ACCENT}" '
      f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h18l-7 8v6l-4 2v-8z"/></svg>'
      f'</span><div><div class="boxlbl">Active filter · {esc(logic_txt)}</div><div style="font-size:15px;'
      f'font-weight:800">{esc(ss.flt_name or "My filter")}</div></div></div><div style="display:flex;flex-wrap:wrap;'
      f'gap:6px;flex:1 1 400px">{chips}</div><a class="btlink" target="_self" href="{link(sec="Backtest", bt_from_flt="1")}">'
      f'Backtest this filter →</a></div>')
    if ss.flt_edit:
        render_filter_editor(N)

    reg = get_regime(fkey)
    fg_, bg_, bd_, on_ = TONE[reg["tone"]]
    checks = "".join(f'<span style="display:flex;align-items:center;gap:6px"><b style="color:{UP if c["ok"] else DOWN}">'
                     f'{"✓" if c["ok"] else "✕"}</b>{esc(c["t"])}</span>' for c in reg["checks"])
    avg_rr = float(np.mean([o["rr"] for o in opps])) if opps else float("nan")
    k0, k1, k2 = st.columns([2, 1, 1], gap="small")
    with k0:
        H(f'<div class="regime" style="border:1px solid {bd_};background:{bg_}"><div style="display:flex;'
          f'justify-content:space-between;align-items:center"><span style="font-size:13px;font-weight:700;'
          f'color:{SOFT}">Market Regime</span><span style="font-size:11px;font-weight:800;color:{on_};'
          f'background:{fg_};border-radius:999px;padding:3px 10px">{esc(reg["badge"])}</span></div>'
          f'<span style="font-size:18px;font-weight:800">{esc(reg["label"])}</span><div style="display:flex;'
          f'flex-wrap:wrap;gap:6px 16px;font-size:12px;color:{SOFT}">{checks}</div></div>')
    with k1:
        H(f'<div class="kpi"><span class="l">Matches today</span><span class="v">{len(opps)}</span>'
          f'<span class="s">{N} conditions · {U["n"]} stocks scanned</span></div>')
    with k2:
        H(f'<div class="kpi"><span class="l">Average R/R</span><span class="v">1 : {tr(avg_rr, 1)}</span>'
          f'<span class="s">With the suggested entry-stop-target</span></div>')

    counts = {s: sum(1 for o in opps if o["setup"] == s) for s in en.SETUPS}
    anchor("opps")
    h1, h2, h3 = st.columns([1.3, 2.7, 1], vertical_alignment="center")
    with h1:
        H(f'<div style="display:flex;align-items:baseline;gap:10px;margin-top:10px"><span style="font-size:20px;'
          f'font-weight:800">Swing Opportunities</span><span class="muted">{len(opps)} matches</span></div>')
    with h2:
        setup = seg("Setup", ["All"] + en.SETUPS, "w_setup", "All",
                    fmt=lambda s: f"{s} {len(opps) if s == 'All' else counts.get(s, 0)}")
    with h3:
        sort = st.selectbox("Sort", ["Score", "Risk / Reward", "Daily change"], key="w_sort",
                            label_visibility="collapsed")
    lst = [o for o in opps if setup == "All" or o["setup"] == setup]
    keyf = {"Score": lambda o: -o["score"], "Risk / Reward": lambda o: -o["rr"],
            "Daily change": lambda o: -(o["chg"] if o["chg"] == o["chg"] else -99)}[sort]
    lst.sort(key=keyf)
    sel = next((o for o in lst if o["ticker"] == OPP), lst[0] if lst else None)

    left, right = st.columns([2.25, 1], gap="medium")
    with left:
        head = ('<div class="opp-grid opp-head"><span>Symbol</span><span>Setup</span><span class="r">Price</span>'
                '<span class="r">Entry</span><span class="r">Stop</span><span class="r">Target</span>'
                '<span class="r">R/R</span><span>Score</span></div>')
        rows = ""
        for o in lst:
            sfg, sbg = SETUP_STYLE[o["setup"]]
            ed = o.get("earn_days")
            earn = (f' <span class="badge" style="color:{WARN};background:{WARN_BG};font-size:10px">EARNINGS '
                    f'{int(ed)}D</span>' if ed == ed and ed is not None and 0 <= ed <= 10 else "")
            sc = UP if o["score"] >= 75 else ACCENT if o["score"] >= 65 else WARN
            rows += (f'<a class="opp-grid opp-row{" sel" if sel and o["ticker"] == sel["ticker"] else ""}" '
                     f'target="_self" href="{link(opp=o["ticker"], f="opps")}">'
                     f'<span class="cellsym">{avatar(o["ticker"], 34)}'
                     f'<span style="min-width:0"><b style="font-size:14px">{esc(o["ticker"])}</b>{earn}'
                     f'<div class="nm" title="{esc(o["name"])}">{esc(o["name"])}</div></span></span>'
                     f'<span><span class="pill" style="color:{sfg};background:{sbg}">{esc(o["setup"])}</span></span>'
                     f'<span class="r"><div style="font-weight:600">{tr(o["price"])}</div><div style="font-size:11px;'
                     f'font-weight:600;color:{col(o["chg"])}">{pct(o["chg"])}</div></span>'
                     f'<span class="r" style="color:{SOFT}">{tr(o["entry_lo"])}–{tr(o["entry_hi"])}</span>'
                     f'<span class="r" style="color:{DOWN}">{tr(o["stop"])}</span>'
                     f'<span class="r" style="color:{UP}">{tr(o["target"])}</span>'
                     f'<span class="r" style="font-weight:700">{tr(o["rr"], 1)}</span>'
                     f'<span class="cellscore"><span class="scorebar"><span style="display:block;height:6px;'
                     f'width:{o["score"]}%;background:{sc}"></span></span><span class="mono" style="font-weight:600">'
                     f'{o["score"]}</span></span></a>')
        empty = ("" if lst else f'<div style="padding:28px 18px;text-align:center" class="muted">No matches with this filter. '
                 f'Loosen the thresholds in “Edit filter” or lower the “Minimum matching conditions”.</div>')
        H(f'<div class="opp"><div class="opp-scroll">{head}{rows}</div>{empty}<div class="opp-foot">'
          f'<span>Score: filter fit + trend strength + volume confirmation + relative strength (0–100)</span><span style="margin-left:'
          f'auto">Entry zone, stop and target are suggested from ATR(14)</span></div></div>')

    with right:
        if sel:
            sfg, sbg = SETUP_STYLE[sel["setup"]]
            with st.container(border=True):
                H(f'<div style="display:flex;align-items:center;gap:12px">{avatar(sel["ticker"], 40)}<div style="flex:1;'
                  f'min-width:0"><a class="plain" target="_self" href="{link(sec="Markets", sym=sel["ticker"])}">'
                  f'<b style="font-size:17px">{esc(sel["ticker"])}</b></a><div class="muted small">{esc(sel["name"])} · '
                  f'{esc(sel["sector"])}</div></div><span class="pill" style="color:{sfg};background:{sbg}">'
                  f'{esc(sel["setup"])}</span></div>')
                plot(opp_chart(hist[sel["ticker"]], sel), key=f"opp_{sel['ticker']}")
                risk_p = (sel["mid"] - sel["stop"]) / sel["mid"] * 100
                rew_p = (sel["target"] - sel["mid"]) / sel["mid"] * 100
                H(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">'
                  f'<div class="tile"><span class="k">Risk</span><span class="v" style="color:{DOWN}">'
                  f'−{tr(risk_p)}%</span></div><div class="tile"><span class="k">Potential</span><span class="v" '
                  f'style="color:{UP}">+{tr(rew_p)}%</span></div><div class="tile"><span class="k">R/R</span>'
                  f'<span class="v">1 : {tr(sel["rr"], 1)}</span></div></div>')
                chk = ""
                for c in sel["checks"]:
                    ic, fg, bg = ("✓", UP, UP_BG) if c["ok"] else ("–", MUT, NEU_BG) if c["ok"] is None else \
                        ("✕", DOWN, DOWN_BG)
                    chk += (f'<div class="chk"><span class="ic" style="color:{fg};background:{bg}">{ic}</span>'
                            f'<span style="flex:1;color:{SOFT}">{esc(c["text"])}</span><span class="mono small">'
                            f'{esc(c["val"])}</span></div>')
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin-top:12px;padding-bottom:4px">'
                  f'Filter checklist · {sel["passes"]}/{sel["n"]}</div>{chk}')
            with st.container(border=True):
                H(f'<div style="display:flex;justify-content:space-between;align-items:center"><span class="panel-title">'
                  f'Position Size</span><span class="muted">{esc(sel["ticker"])} · entry {tr(sel["mid"])}</span></div>')
                st.number_input("Account size ($)", min_value=0.0, step=1000.0, key="acct", format="%.0f")
                p1, p2 = st.columns([1, 1.25], vertical_alignment="center")
                with p1:
                    H('<div class="muted small">Risk per trade</div>')
                with p2:
                    risk_s = seg("Risk", ["0.5%", "1%", "2%"], "w_risk", "1%")
                rp = {"0.5%": 0.5, "1%": 1.0, "2%": 2.0}[risk_s]
                acct = float(ss.acct or 0)
                risk_amt = acct * rp / 100
                per = sel["mid"] - sel["stop"]
                qty = int(risk_amt // per) if per > 0 else 0
                pos_val = qty * sel["mid"]
                tiles = [("Amount at risk", money(risk_amt), TXT), ("Shares", tr(qty, 0), TXT),
                         ("Position value", f'{money(pos_val, dec=0)} · {tr(pos_val / acct * 100 if acct else 0, 0)}%',
                          DOWN if pos_val > acct else TXT),
                         ("Profit at target", "+" + money(qty * (sel["target"] - sel["mid"])), UP)]
                H(f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:6px 0 10px 0">'
                  + "".join(f'<div class="tile"><span class="k">{k}</span><span class="v" style="color:{c_}">{v}</span>'
                            f'</div>' for k, v, c_ in tiles) + '</div>')
                a1, a2 = st.columns(2)
                with a1:
                    if button("🔔 Set alert", key="alert"):
                        st.toast(f"Entry alert for {sel['ticker']} at {tr(sel['entry_lo'])}–{tr(sel['entry_hi'])} "
                                 f"noted (in-app only; no notification service connected)")
                with a2:
                    if button("Add to trade journal", key="add_journal", primary=True):
                        if ss.journal is None:
                            ss.journal = []
                        ss.journal.append({"t": sel["ticker"], "dir": "LONG", "entry": sel["mid"], "stop": sel["stop"],
                                           "target": sel["target"], "atr": sel["atr"],
                                           "date": pd.Timestamp.today().strftime("%Y-%m-%d"), "example": False})
                        st.toast(f"{sel['ticker']} added to the trade journal")
        else:
            with st.container(border=True):
                H('<div class="muted">No opportunity selected.</div>')

    # ---- Açık işlemlerim: swing fırsatlarının hemen altında, pozisyon büyüklüğünün yanında ----
    with left:
        render_journal(hist)


def render_journal(hist):
    anchor("journal")
    if ss.journal is None:
        ss.journal = _seed_journal(hist)
    jr = ss.journal
    q = md.get_quotes([j["t"] for j in jr]) if jr else {}
    today = pd.Timestamp.today().normalize()
    tot_r, rows = 0.0, ""
    for i, j in enumerate(jr):
        last = q.get(j["t"], {}).get("last", j["entry"])
        risk = max(j["entry"] - j["stop"], 1e-9)
        trail = max(j["stop"], last - 2 * j["atr"]) if j.get("atr") == j.get("atr") and last > j["entry"] else j["stop"]
        p_ = (last / j["entry"] - 1) * 100
        R = (last - j["entry"]) / risk
        tot_r += R
        prog = max(0.0, min(100.0, (last - j["stop"]) / max(j["target"] - j["stop"], 1e-9) * 100))
        days = int(np.busday_count(pd.Timestamp(j["date"]).date(), today.date()))
        ex = ' <span class="badge" style="color:#8D96A5;background:#1A1D23;font-size:10px">sample</span>' \
            if j.get("example") else ""
        rows += (f'<tr><td><span style="display:flex;align-items:center;gap:10px">{avatar(j["t"], 30)}<b>{esc(j["t"])}'
                 f'</b>{ex}</span></td><td style="text-align:left"><span class="badge" style="color:{UP};'
                 f'background:{UP_BG}">LONG</span></td><td style="color:{SOFT}">{tr(j["entry"])}</td>'
                 f'<td style="font-weight:600">{tr(last)}</td><td style="color:{SOFT}">{tr(trail)}</td>'
                 f'<td style="color:{MUT}">{days}d</td><td style="font-weight:600;color:{col(p_)}"><div>{pct(p_)}</div>'
                 f'<div style="font-size:11px">{chg(R, 1)}R</div></td><td style="text-align:left"><span class="prog">'
                 f'<span style="left:calc({prog:.0f}% - 7px)"></span></span></td><td><a class="lnk small" '
                 f'target="_self" href="{link(close_tr=str(i), f="journal")}">Close</a></td></tr>')
    month = today.strftime("%Y-%m")
    closed = [c for c in ss.journal_closed if str(c.get("closed", "")).startswith(month)]
    hit = (f'{len(closed)} · {tr(100 * sum(1 for c in closed if c["exit"] > c["entry"]) / len(closed), 0)}% hit rate'
           if closed else "—")
    body = (f'<div style="overflow-x:auto"><table class="jt"><thead><tr><th>Symbol</th><th style="text-align:left">'
            f'Side</th><th>Entry</th><th>Last</th><th>Trailing stop</th><th>Days</th><th>P/L</th><th style="text-align:'
            f'left">Stop → Target</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>') if jr else \
        '<div class="muted" style="padding:16px 22px">No open trades. Pick an opportunity and press “Add to trade journal”.</div>'
    H(f'<div class="opp" style="margin-top:16px"><div style="padding:18px 22px 12px;display:flex;flex-wrap:wrap;'
      f'justify-content:space-between;align-items:center;gap:12px"><div><div class="panel-title">My Open Trades</div>'
      f'<div class="muted small">Trade journal · live prices, trailing stop 2×ATR</div></div><div style="display:'
      f'flex;gap:18px;font-size:12px;color:{MUT}"><span>Open <b class="mono" style="color:{TXT}">{len(jr)}</b></span>'
      f'<span>Total <b class="mono" style="color:{col(tot_r)}">{chg(tot_r, 1)}R</b></span><span>Closed this month '
      f'<b class="mono" style="color:{TXT}">{hit}</b></span></div></div>{body}</div>')


# ======================================================================
# BÖLÜM: BACKTEST (Strateji Laboratuvarı)
# ======================================================================
QUICK = {c: s for c, s, _ in md.BT_QUICK}


def bt_symbol():
    """Arama kutusu doluysa oradan seçilen sembol, değilse hızlı seçim."""
    if (ss.get("bt_custom") or "").strip():
        if ss.get("bt_pick"):
            return ss.bt_pick
        return _SYM_RE.sub("", ss.bt_custom).upper()[:24] or QUICK.get(ss.bt_inst, "AAPL")
    return QUICK.get(ss.bt_inst, "AAPL")


def _bt_quick_pick():
    # Hızlı seçimden bir koda basılınca özel arama temizlenir
    ss.bt_custom = ""
    ss.pop("bt_pick", None)


def _data_token(sym):
    """Fiyat verisi değişince (ör. örnek → gerçek) backtest önbelleği yenilensin."""
    df = md.get_history(sym)
    if df.empty:
        return "none"
    return f'{df.attrs.get("src")}|{len(df)}|{df.index[-1]:%Y%m%d}|{float(df["Close"].iloc[-1]):.6g}'


def bt_cfg():
    return {"sym": bt_symbol(), "yrs": int(ss.bt_yrs), "ind1": ss.bt_ind1, "p1": int(ss.bt_p1), "op1": ss.bt_op1,
            "v1": float(ss.bt_v1), "logic": ss.bt_logic, "c2on": bool(ss.bt_c2on), "src2": ss.bt_src2,
            "p2": int(ss.bt_p2), "op2": ss.bt_op2, "dir": ss.bt_dir, "slMode": ss.bt_slMode,
            "slV": float(ss.bt_slV), "tpMode": ss.bt_tpMode, "tpV": float(ss.bt_tpV),
            "maxBars": int(ss.bt_maxBars), "cap": float(ss.bt_cap), "risk": float(ss.bt_risk),
            "comm": float(ss.bt_comm), "extra": en.normalize_conds(ss.bt_extra), "extra_min": _bt_xmin()}


def _bt_xmin():
    n = len([c for c in en.normalize_conds(ss.bt_extra) if c["Active"]])
    k = int(ss.get("bt_xmin") or 0)
    return k if 0 < k < n else 0


def _bt_reset():
    # Tasarımdaki gibi: ayarlar varsayılana döner ve varsayılan strateji hemen çalışır
    for k, v in BT_WIDGETS.items():
        ss[k] = copy.deepcopy(v)
    ss.pop("bt_pick", None)
    ss.bt_extra = []
    ss.bt_extra_ver += 1
    ss.bt_ran = None


def _bt_load(cfg):
    m = {"yrs": "bt_yrs", "ind1": "bt_ind1", "p1": "bt_p1", "op1": "bt_op1", "v1": "bt_v1", "logic": "bt_logic",
         "c2on": "bt_c2on", "src2": "bt_src2", "p2": "bt_p2", "op2": "bt_op2", "dir": "bt_dir",
         "slMode": "bt_slMode", "slV": "bt_slV", "tpMode": "bt_tpMode", "tpV": "bt_tpV", "maxBars": "bt_maxBars",
         "cap": "bt_cap", "risk": "bt_risk", "comm": "bt_comm", "extra_min": "bt_xmin"}
    for a, b in m.items():
        if a in cfg:
            ss[b] = copy.deepcopy(cfg[a])
    code = next((c for c, s, _ in md.BT_QUICK if s == cfg.get("sym")), None)
    ss.bt_inst, ss.bt_custom = (code, "") if code else ("AAPL", cfg.get("sym", ""))
    ss.pop("bt_pick", None)
    if not code and cfg.get("sym"):
        ss.bt_pick = cfg["sym"]
    ss.bt_extra = copy.deepcopy(cfg.get("extra", []))
    ss.bt_extra_ver += 1
    ss.bt_ran = copy.deepcopy(cfg)


@st.cache_data(ttl=1800, show_spinner="Running backtest…")
def run_backtest(cfg_json, data_token=""):
    cfg = json.loads(cfg_json)
    df = md.get_history(cfg["sym"])
    if df.empty:
        return {"ok": False, "msg": f'Could not load price data for “{cfg["sym"]}”. Check the symbol.'}
    bench = None
    if any(c["Indicator"] == "Relative strength vs SPY (3M)" or c["Compare"] == "Relative strength vs SPY (3M)"
           for c in cfg.get("extra", [])):
        bench = md.get_history("SPY")["Close"]
    res = en.backtest(df, cfg, cfg.get("extra"), bench)
    res["src"] = df.attrs.get("src", "real")
    d = md.get_company_detail(cfg["sym"]) if cfg["sym"] not in md.NAMES else None
    res["name"] = d["name"] if d else md.company_name(cfg["sym"])
    return res


def _bt_settings():
    with st.container(border=True):
        step_head(1, "Instrument")
        st.text_input("Search symbol", key="bt_custom", placeholder="🔍  Search index, stock, FX pair (e.g. tesla, GARAN.IS)",
                      label_visibility="collapsed")
        q_ = (ss.bt_custom or "").strip()
        if q_:
            found = md.search_symbols(q_)[:6]
            names = {r["ticker"]: r["name"] for r in found}
            opts = [r["ticker"] for r in found]
            raw = _SYM_RE.sub("", q_).upper()[:24]
            if raw and raw not in opts:
                opts.append(raw)
            if opts:
                H('<div class="muted small" style="margin:2px 0 4px 0">Symbols found — pick the one to test:</div>')
                seg("Symbols found", opts, "bt_pick", opts[0],
                    fmt=lambda t: f"{t} · {names[t][:18]}" if names.get(t) and names[t] != t else t)
        seg("Quick pick", list(QUICK), "bt_inst", "AAPL", on_change=_bt_quick_pick)
        if q_:
            H(f'<div class="muted small">Testing: <b class="mono">{esc(bt_symbol())}</b> · press one of the codes above '
              f'to go back to quick pick</div>')
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(2, "Period", "Daily candles")
        yrs = seg("Period", [1, 3, 5], "bt_yrs", 3, fmt=lambda v: f"{v} yr")
        dfh = md.get_history(bt_symbol())
        if len(dfh) > 60:
            want = int(round(yrs * 252))
            n_ = max(30, min(want, len(dfh) - 1))
            short = f" · only {n_} candles available" if want > len(dfh) - 1 else ""
            H(f'<div class="mono small" style="color:{DIM}">{dfh.index[-n_]:%b %d, %y} – {dfh.index[-1]:%b %d, %y}'
              f'{short}</div>')
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(3, "Entry rules")
        with st.container(border=True):
            H('<div class="boxlbl">Indicator 1</div>')
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("Indicator 1", en.IND1_OPTIONS, key="bt_ind1", label_visibility="collapsed")
            with c2:
                st.number_input("Period", min_value=2, max_value=100, step=1, key="bt_p1",
                                label_visibility="collapsed", disabled=ss.bt_ind1 == en.IND1_OFF)
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("Condition", list(en.OPS1), format_func=en.OPS1.get, key="bt_op1",
                             label_visibility="collapsed", disabled=ss.bt_ind1 == en.IND1_OFF)
            with c2:
                st.number_input("Threshold", step=1.0, key="bt_v1", label_visibility="collapsed", format="%.1f",
                                disabled=ss.bt_ind1 == en.IND1_OFF)
        seg("Logic", ["and", "or"], "bt_logic", "and", fmt=lambda x: "AND" if x == "and" else "OR")
        with st.container(border=True):
            c1, c2 = st.columns([2, 1], vertical_alignment="center")
            with c1:
                H('<div class="boxlbl">Indicator 2 · Trend filter</div>')
            with c2:
                st.checkbox("Use", key="bt_c2on")
            c1, c2 = st.columns([0.7, 2], vertical_alignment="center")
            with c1:
                H('<b style="font-size:13px;color:#C4CAD4">Price</b>')
            with c2:
                st.selectbox("Position", ["above", "below"], key="bt_op2", label_visibility="collapsed",
                             format_func={"above": "above", "below": "below"}.get, disabled=not ss.bt_c2on)
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("Average", ["sma", "ema"], key="bt_src2", label_visibility="collapsed",
                             format_func=str.upper, disabled=not ss.bt_c2on)
            with c2:
                st.number_input("Average period", min_value=2, max_value=250, step=1, key="bt_p2",
                                label_visibility="collapsed", disabled=not ss.bt_c2on)
        with st.expander(f"+ Add condition (MACD, Bollinger, Volume…){f' · {len(ss.bt_extra)} extra conditions' if ss.bt_extra else ''}",
                         expanded=bool(ss.get("bt_show_extra"))):
            cond_editor("bt_extra", "bt_extra_ver", "bt_ed")
            n_ex = len([c for c in en.normalize_conds(ss.bt_extra) if c["Active"]])
            if n_ex >= 2:
                opts = [0] + list(range(n_ex - 1, 0, -1))
                if ss.get("bt_xmin") not in opts:
                    ss.bt_xmin = 0
                st.selectbox("How many of the extra conditions must hold?", opts, key="bt_xmin",
                             format_func=lambda k: f"All ({n_ex}/{n_ex})" if k == 0 else f"At least {k}/{n_ex}")
            st.caption("Extra conditions are added to the entry signal with AND; they apply the same way to short trades.")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(4, "Side")
        seg("Side", ["long", "short", "both"], "bt_dir", "long",
            fmt={"long": "Long only", "short": "Short only", "both": "Both"}.get)
        st.caption("For short trades the conditions are mirrored (e.g. RSI < 30 → RSI > 70, price below the average).")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(5, "Exit rules")
        H(f'<span style="font-size:12px;font-weight:700;color:{DOWN}">Stop loss</span>')
        c1, c2 = st.columns([2.1, 1], vertical_alignment="center")
        with c1:
            seg("Stop type", ["pct", "atr"], "bt_slMode", "atr", fmt={"pct": "Fixed %", "atr": "ATR ×"}.get)
        with c2:
            st.number_input("Stop value", min_value=0.1, step=0.1, key="bt_slV", label_visibility="collapsed",
                            format="%.1f")
        H(f'<span style="font-size:12px;font-weight:700;color:{UP}">Take profit</span>')
        c1, c2 = st.columns([2.1, 1], vertical_alignment="center")
        with c1:
            seg("Take-profit type", ["pct", "rr", "atr"], "bt_tpMode", "rr",
                fmt={"pct": "Fixed %", "rr": "R multiple", "atr": "ATR ×"}.get)
        with c2:
            st.number_input("Take-profit value", min_value=0.1, step=0.1, key="bt_tpV", label_visibility="collapsed",
                            format="%.1f")
        st.number_input("Max. holding period (days, 0 = none)", min_value=0, step=1, key="bt_maxBars")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(6, "Capital & risk")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Capital ($)", min_value=100.0, step=1000.0, key="bt_cap", format="%.0f")
        with c2:
            st.number_input("Risk / trade %", min_value=0.1, step=0.1, key="bt_risk", format="%.1f")
        with c3:
            st.number_input("Commission %", min_value=0.0, step=0.01, key="bt_comm", format="%.2f")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        r1, r2 = st.columns([1, 2])
        with r1:
            button("Reset", key="bt_reset", on_click=_bt_reset)
        with r2:
            if button("▶  Run backtest", key="bt_run", primary=True):
                ss.bt_ran = bt_cfg()
                st.rerun()


def _kpi(label, value, sub, color=TXT):
    return (f'<div class="kpi"><span class="l">{esc(label)}</span><span class="v" style="color:{color}">{value}</span>'
            f'<span class="s">{esc(sub)}</span></div>')


def _bt_results():
    cfg_now = bt_cfg()
    if ss.bt_ran is None:
        ss.bt_ran = cfg_now
    res = run_backtest(json.dumps(ss.bt_ran, ensure_ascii=False, sort_keys=True), _data_token(ss.bt_ran["sym"]))
    dirty = json.dumps(cfg_now, sort_keys=True, ensure_ascii=False) != \
        json.dumps(ss.bt_ran, sort_keys=True, ensure_ascii=False)
    sym = ss.bt_ran["sym"]
    if not res.get("ok"):
        with st.container(border=True):
            H(f'<div class="panel-title">{esc(sym)}</div><div class="muted" style="margin-top:6px">{esc(res.get("msg"))}</div>')
        return
    k = res["kpi"]
    cur = "TRY" if sym.endswith(".IS") else "USD"
    dg = pdec(sym, float(res["price"].iloc[-1]))
    fg_, bg_, bd_, on_ = TONE[k["tone"]]
    r0, r1 = res["range"]
    dirty_chip = (f'<span class="pill" style="color:{WARN};background:{WARN_BG}">Settings changed · run to '
                  f'update the results</span>' if dirty else "")
    H(f'<div class="critbar">{avatar(sym, 40)}<div style="flex:1 1 300px;min-width:0"><div style="font-size:16px;'
      f'font-weight:800">{esc(res["name"])} <span class="mono muted" style="font-size:12px;font-weight:500">{esc(sym)} · '
      f'{r0.strftime("%b %d, %y")} – {r1.strftime("%b %d, %y")}</span></div><div class="mono small" style="color:{SOFT};'
      f'line-height:1.5">{esc(res["desc"])}</div></div>{dirty_chip}{src_chip(res["src"])}<span class="pill" '
      f'style="color:{on_};background:{fg_ if k["tone"] != "bad" else "#3A2024"}">{esc(k["verdict"])}</span></div>')
    pf = k["pf"]
    pf_s = "∞" if pf == float("inf") else tr(pf)
    n = k["n"]
    dash = "—"
    kp = [("Net income", money(k["net"], cur, 0), f'{pct(k["net_pct"])} · starting {money(k["cap"], cur, 0)}', col(k["net"])),
          ("Win rate", f'{tr(k["win_rate"], 1)}%' if n else dash, f'{k["wins"]} wins · {k["losses"]} losses',
           UP if k["win_rate"] >= 50 else NEU),
          ("Profit factor", pf_s if n else dash, "Gross profit / gross loss", UP if pf >= 1.5 else NEU if pf >= 1 else DOWN),
          ("Max. drawdown", f'−{tr(abs(k["mdd"] * 100))}%', "Deepest drawdown from peak", DOWN),
          ("Realised R/R", f'1 : {tr(k["payoff"])}' if n else dash, "Avg. win / avg. loss",
           UP if k["payoff"] >= 1.5 else NEU),
          ("Forecast", f'{chg(k["exp_r"])}R' if n else dash, "Average per trade", col(k["exp_r"])),
          ("Number of trades", str(n), f'Avg. {tr(k["avg_bars"], 1)} days in position', TXT),
          ("Sharpe", tr(k["sharpe"]), f'Buy & hold {pct(k["bh_pct"], 1)}', UP if k["sharpe"] >= 1 else NEU)]
    for row in (kp[:4], kp[4:]):
        cs = st.columns(4, gap="small")
        for c_, (a, b, s_, cl) in zip(cs, row):
            with c_:
                H(_kpi(a, b, s_, cl))
        H("<div style='height:8px'></div>")

    # Sermaye eğrisi + drawdown
    with st.container(border=True):
        H(f'<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px">'
          f'<span class="panel-title">Equity Curve</span><span class="legend"><span><i style="background:{ACCENT}">'
          f'</i>Strategy</span><span><i style="background:#6B7383"></i>Buy &amp; hold</span><span><i style="background:'
          f'rgba(248,113,113,.45);height:8px"></i>Drawdown</span></span></div>')
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.04)
        fig.add_trace(go.Scatter(x=res["bh"].index, y=res["bh"], mode="lines", name="Buy & hold",
                                 line=dict(color="#6B7383", width=1.5, dash="dash")), 1, 1)
        fig.add_trace(go.Scatter(x=res["eq"].index, y=res["eq"], mode="lines", name="Strategy", fill="tozeroy",
                                 fillcolor="rgba(91,140,255,.08)", line=dict(color=ACCENT, width=2)), 1, 1)
        fig.add_hline(y=k["cap"], line=dict(color="#3A404A", width=1, dash="dash"), row=1, col=1)
        fig.add_trace(go.Scatter(x=res["dd"].index, y=res["dd"] * 100, mode="lines", name="Drawdown %", fill="tozeroy",
                                 fillcolor="rgba(248,113,113,.4)", line=dict(color="rgba(248,113,113,.7)", width=1)), 2, 1)
        lo = min(float(res["eq"].min()), float(res["bh"].min()))
        hi = max(float(res["eq"].max()), float(res["bh"].max()))
        fig.update_yaxes(range=[lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06], row=1, col=1)
        plot(_layout(fig, 330), config=CHART_CFG, key="bt_eq")

    c1, c2 = st.columns([2, 1.1], gap="medium")
    T = res["trades"]
    with c1:
        with st.container(border=True):
            ma_lbl = (f'{ss.bt_ran["src2"].upper()}({ss.bt_ran["p2"]})' if ss.bt_ran["c2on"] else "")
            H(f'<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px">'
              f'<span class="panel-title">Price &amp; Trades</span><span class="legend"><span><i style="background:'
              f'{UP};width:9px;height:9px;border-radius:50%"></i>Long entry</span><span><i style="background:{WARN};'
              f'width:9px;height:9px;border-radius:50%"></i>Short entry</span><span><i style="background:transparent;'
              f'border:2px solid {TXT};width:9px;height:9px;border-radius:50%;box-sizing:border-box"></i>Exit</span>'
              f'<span><i style="background:{ACCENT if ma_lbl else "#3A404A"}"></i>{esc(ma_lbl or "Average off")}'
              f'</span></span></div>')
            fig = go.Figure(go.Scatter(x=res["price"].index, y=res["price"], mode="lines", name="Close",
                                       line=dict(color=SOFT, width=1.3)))
            if res["ma"] is not None:
                fig.add_trace(go.Scatter(x=res["ma"].index, y=res["ma"], mode="lines", name=ma_lbl,
                                         line=dict(color=ACCENT, width=1.4)))
            for side, color_, nm in ((True, UP, "Long entry"), (False, WARN, "Short entry")):
                tt = [t for t in T if t["long"] == side]
                if tt:
                    fig.add_trace(go.Scatter(x=[t["ed"] for t in tt], y=[t["entry"] for t in tt], mode="markers",
                                             name=nm, marker=dict(color=color_, size=8)))
            if T:
                fig.add_trace(go.Scatter(x=[t["xd"] for t in T], y=[t["exit"] for t in T], mode="markers", name="Exit",
                                         marker=dict(color=PANEL, size=7, line=dict(color=TXT, width=2))))
            plot(_layout(fig, 250), config=CHART_CFG, key="bt_px")
    with c2:
        with st.container(border=True):
            H('<div style="display:flex;justify-content:space-between;align-items:center"><span class="panel-title">'
              'Trade Results (R)</span><span class="muted small">Each bar is one trade</span></div>')
            fig = go.Figure(go.Bar(x=list(range(1, len(T) + 1)), y=[t["R"] for t in T],
                                   marker_color=[UP if t["R"] >= 0 else DOWN for t in T], name="R"))
            fig.add_hline(y=0, line=dict(color="#3A404A", width=1))
            plot(_layout(fig, 150), key="bt_r")
            mini = [("Avg. win", pct(k["avg_win_pct"]) if n else dash, UP),
                    ("Avg. loss", pct(k["avg_loss_pct"]) if n else dash, DOWN),
                    ("Best / worst", f'{pct(k["best"], 1)} / {pct(k["worst"], 1)}' if n else dash, TXT),
                    ("Losing streak (max.)", str(k["max_streak"]), WARN if k["max_streak"] >= 5 else TXT)]
            H('<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">' + "".join(
                f'<div class="tile"><span class="k">{a}</span><span class="v" style="color:{c_}">{b}</span></div>'
                for a, b, c_ in mini) + '</div>')

    with st.container(border=True):
        h1, h2, h3 = st.columns([2, 1.6, 0.9], vertical_alignment="center")
        with h1:
            H(f'<span class="panel-title">Trades</span> <span class="muted small">{n} trades · newest first</span>')
        with h2:
            tf = seg("Trade filter", ["All", "Winners", "Losers"], "w_bttf", "All")
        RS = {"TP": ("Target", UP, UP_BG), "SL": ("Stop", DOWN, DOWN_BG), "Time": ("Time exit", WARN, WARN_BG),
              "Open": ("Open", NEU, NEU_BG)}
        numbered = [(i + 1, t) for i, t in enumerate(T)]
        shown = [(no, t) for no, t in numbered if tf == "All" or (tf == "Winners") == (t["pnl"] > 0)][::-1][:150]
        with h3:
            csv = pd.DataFrame([{"#": no, "Side": "LONG" if t["long"] else "SHORT", "Entry date": t["ed"].date(),
                                 "Entry": round(t["entry"], 6), "Exit date": t["xd"].date(),
                                 "Exit": round(t["exit"], 6), "Reason": RS[t["reason"]][0], "Duration (days)": t["bars"],
                                 "Return %": round(t["ret"], 3), "R": round(t["R"], 3), "K/Z": round(t["pnl"], 2)}
                                for no, t in numbered]).to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, file_name=f"backtest_{sym}.csv", mime="text/csv", key="bt_csv",
                               **_wkw(st.download_button))
        rows = ""
        for no, t in shown:
            rs = RS[t["reason"]]
            c_ = UP if t["pnl"] > 0 else DOWN
            d_fg, d_bg = (UP, UP_BG) if t["long"] else (WARN, WARN_BG)
            rows += (f'<tr><td style="color:{MUT}">{no}</td><td style="text-align:left"><span class="badge" '
                     f'style="color:{d_fg};background:{d_bg}">{"LONG" if t["long"] else "SHORT"}</span></td>'
                     f'<td style="text-align:left;color:{SOFT}">{t["ed"].strftime("%b %d, %y")}</td><td>{tr(t["entry"], dg)}</td>'
                     f'<td style="text-align:left;color:{SOFT}">{t["xd"].strftime("%b %d, %y")}</td><td>{tr(t["exit"], dg)}</td>'
                     f'<td style="text-align:left"><span class="badge" style="color:{rs[1]};background:{rs[2]}">{rs[0]}'
                     f'</span></td><td style="color:{MUT}">{t["bars"]}d</td><td style="font-weight:600;color:{c_}">'
                     f'{pct(t["ret"])}</td><td style="color:{c_}">{chg(t["R"])}R</td><td style="font-weight:600;color:{c_}">'
                     f'{"+" if t["pnl"] >= 0 else ""}{money(t["pnl"], cur)}</td></tr>')
        empty = ("" if rows else '<div class="muted" style="padding:28px;text-align:center">No trades were generated with these '
                 'settings. Try loosening the threshold or turning off the 2nd condition.</div>')
        H(f'<div class="tt-wrap"><table class="jt" style="min-width:820px"><thead><tr><th>#</th><th style="text-align:'
          f'left">Side</th><th style="text-align:left">Entry date</th><th>Entry</th><th style="text-align:left">'
          f'Exit date</th><th>Exit</th><th style="text-align:left">Reason</th><th>Duration</th><th>Return</th><th>R</th>'
          f'<th>P/L</th></tr></thead><tbody>{rows}</tbody></table>{empty}</div><div class="muted small" '
          f'style="border-top:1px solid {LINE};padding-top:10px;margin-top:6px;line-height:1.5">Signals form on the candle '
          f'close; the trade is entered at the next candle\'s open. If stop and target are both hit in the same candle, '
          f'the stop is assumed. Past performance does not guarantee future results.</div>')


def render_backtest():
    t1, t2 = st.columns([2.2, 2.2], vertical_alignment="bottom")
    with t1:
        H('<div class="kicker">Backtest · Find your strategy</div><div class="page-title">Strategy Lab</div>'
          '<div class="muted">Combine indicators, define entry and exit rules, test on historical data.</div>')
    with t2:
        b0, b1, b2 = st.columns([1.5, 1.2, 1.2], vertical_alignment="center")
        with b0:
            src = md.get_history(bt_symbol()).attrs.get("src")
            chip = ('<span class="srcchip live">● Simulated on real price data</span>' if src == "real" else
                    '<span class="srcchip mock">Simulated on sample price data</span>' if src == "mock" else
                    '<span class="srcchip none">No price data</span>')
            H(f'<div style="text-align:right">{chip}</div>')
        with b2:  # önce kaydet → liste aynı çalıştırmada güncel olsun
            with st.popover("Save strategy", **_wkw(st.popover)):
                st.text_input("Strategy name", key="bt_save_name", placeholder="e.g. RSI dip + SMA200")
                if st.button("Save", key="bt_save_btn"):
                    ss.bt_saved.append({"name": (ss.get("bt_save_name") or f"Strategy {len(ss.bt_saved) + 1}")[:60],
                                        "cfg": bt_cfg()})
                    st.toast("Strategy saved")
        with b1:
            with st.popover("Saved strategies", **_wkw(st.popover)):
                if not ss.bt_saved:
                    st.caption("No saved strategies yet.")
                for i, s in enumerate(ss.bt_saved):
                    H(f'<div style="font-weight:800">{esc(s["name"])}</div><div class="muted small" '
                      f'style="margin-bottom:4px">{esc(s["cfg"]["sym"])} · {esc(en.describe(s["cfg"]))}</div>')
                    st.button("Load", key=f"bt_load_{i}", on_click=_bt_load, args=(copy.deepcopy(s["cfg"]),))
    H("<div style='height:10px'></div>")
    left, right = st.columns([1, 2.3], gap="medium")
    with left:
        _bt_settings()
    with right:
        _bt_results()


# ======================================================================
# BÖLÜM: FOREX & HABERLER
# ======================================================================
CAL_KEYS = [f"calccy_{c}" for c, _, _ in md.CAL_CCYS]


def _cal_sync():
    ss.cal_ccy = [c for c, _, _ in md.CAL_CCYS if ss.get(f"calccy_{c}")]


def _cal_set(codes):
    for c, _, _ in md.CAL_CCYS:
        ss[f"calccy_{c}"] = c in codes
    ss.cal_ccy = [c for c, _, _ in md.CAL_CCYS if c in codes]


def cal_currency_picker():
    """Para birimi seçimi: alt alta, bayrak + kod + ad; kendi listen kaydedilir."""
    sel = set(ss.get("cal_ccy") if ss.get("cal_ccy") is not None else [c for c, _, _ in md.CAL_CCYS])
    for c, _, _ in md.CAL_CCYS:
        k = f"calccy_{c}"
        if k not in ss:
            ss[k] = c in sel
    n = len(sel)
    lab = ("Currencies: all" if n == len(md.CAL_CCYS) else "Currencies: none" if n == 0 else
           "Currencies: " + ", ".join(c for c, _, _ in md.CAL_CCYS if c in sel) if n <= 3 else f"Currencies: {n} selected")
    with panel(lab, "cal_ccy_panel"):
        H('<div style="font-size:12px;font-weight:700;margin-bottom:2px">Show events for</div>'
          '<div class="muted small" style="margin-bottom:6px">Your choice is saved.</div>')
        b1, b2, b3 = st.columns(3)
        with b1:
            st.button("All", key="calccy_all", on_click=_cal_set, args=([c for c, _, _ in md.CAL_CCYS],),
                      **_wkw(st.button))
        with b2:
            st.button("Majors", key="calccy_maj", on_click=_cal_set, args=(md.CAL_MAJORS,), **_wkw(st.button))
        with b3:
            st.button("None", key="calccy_none", on_click=_cal_set, args=([],), **_wkw(st.button))
        for c, flag, name in md.CAL_CCYS:          # alt alta, kolay seçilsin
            st.checkbox(f"{flag}  {c} · {name}", key=f"calccy_{c}", on_change=_cal_sync)
    return [c for c, _, _ in md.CAL_CCYS if ss.get(f"calccy_{c}")]


def render_calendar():
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([1.1, 2, 1.6, 1.5], vertical_alignment="center")
        with f2:
            day = seg("Day", md.CAL_DAYS, "w_calday", "Today")
        with f3:
            imp = seg("Impact", md.CAL_IMPACTS, "w_calimp", "All")
        with f4:
            ccys = cal_currency_picker()
        rows = md.get_calendar_rows(day, imp, ccys)
        with f1:
            H(src_chip(rows[0]["src"] if rows else md._calendar_all()[0]["src"] if md._calendar_all() else "none"))
        out = ('<div class="cal-row" style="border:0;color:#8D96A5;font-size:11px;letter-spacing:.07em">'
               '<span style="width:120px">TIME</span><span style="width:70px">CCY</span><span style="width:40px">IMPACT'
               '</span><span style="flex:1">EVENT</span><span style="width:96px;text-align:right">ACTUAL</span>'
               '<span style="width:90px;text-align:right">FORECAST</span><span style="width:90px;text-align:right">'
               'PREVIOUS</span></div>')
        last_day = None
        for r in rows:
            if r["day_label"] != last_day:
                out += (f'<div style="padding:8px 6px;font-size:12px;font-weight:700;color:{SOFT};border-top:1px solid '
                        f'{LINE}">{esc(r["day_label"])}</div>')
                last_day = r["day_label"]
            ic = DOWN if r["impact"] >= 3 else WARN if r["impact"] == 2 else "#6B7383"
            dots = "".join(f'<i style="background:{ic if i < r["impact"] else "#2A2F37"}"></i>' for i in range(3))
            nxt = (f' <span class="badge" style="color:#0A0B0D;background:{ACCENT};font-size:9.5px">NEXT</span>'
                   if r["next"] else "")
            stt = r.get("state")
            if stt == "released":
                ev_ = r.get("eval")
                ac = UP if ev_ == 1 else DOWN if ev_ == -1 else TXT
                bg = UP_BG if ev_ == 1 else DOWN_BG if ev_ == -1 else "transparent"
                tip = {1: "better than forecast", -1: "worse than forecast", 0: "in line with forecast"}.get(
                    ev_, "released")
                act = (f'<span class="cal-act" title="{tip}" style="color:{ac};background:{bg}">'
                       f'{esc(r["actual"])}</span>')
            elif stt == "pending":
                act = '<span class="muted" style="font-style:italic" title="released — waiting for the value">pending…</span>'
            elif stt == "n/a":
                act = '<span class="muted" title="no value from the data source">n/a</span>'
            else:
                act = '<span class="muted">—</span>'
            flag = md.CCY_FLAG.get(r["cur"], "")
            out += (f'<div class="cal-row{" next" if r["next"] else ""}{" done" if stt == "released" else ""}">'
                    f'<span class="mono" style="width:120px">{r["time"]}{nxt}</span>'
                    f'<span style="width:70px;font-weight:700;font-size:12px">{flag} {esc(r["cur"])}</span>'
                    f'<span class="dots">{dots}</span><span style="flex:1">{esc(r["event"])}</span>'
                    f'<span class="mono" style="width:96px;text-align:right">{act}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["forecast"])}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["previous"])}</span></div>')
        if not rows:
            out += (f'<div class="muted" style="padding:18px 6px">No events with this filter'
                    f'{" — no currency selected" if not ccys else ""}.</div>')
        live = bool(rows and rows[0].get("tv_ok"))
        out += (f'<div class="muted small" style="padding-top:10px;display:flex;gap:14px;flex-wrap:wrap">'
                f'<span><span style="color:{DOWN}">■</span> High &nbsp;<span style="color:{WARN}">■</span> Medium &nbsp;'
                f'<span style="color:#6B7383">■</span> Low</span>'
                f'<span>Actual: <span class="cal-act" style="color:{UP};background:{UP_BG}">better</span> / '
                f'<span class="cal-act" style="color:{DOWN};background:{DOWN_BG}">worse</span> than forecast '
                f'(for unemployment and jobless claims lower is better)</span>'
                f'<span>{"Released values load automatically (TradingView feed, checked every 2 minutes)" if live else "Released values: source unreachable right now — retrying every 2 minutes"}</span></div>')
        H(f'<div style="overflow-x:auto"><div style="min-width:780px">{out}</div></div>')
    _save_state()       # bölüm kendi kendine yenilendiğinde para birimi seçimi de kaydedilsin


_frag = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
if _frag is not None:
    try:
        _calendar_live = _frag(run_every=120)(render_calendar)     # açıklanan değerler kendiliğinden gelsin
    except TypeError:
        _calendar_live = render_calendar
else:
    _calendar_live = render_calendar


def render_forex():
    now = pd.Timestamp.now(tz=md.TZ)
    H(f'<div class="page-title">Forex &amp; News</div><div class="muted" style="margin-bottom:8px">'
      f'<span class="dot-live"></span>{md.tr_date_label(now)} {now.year} · times in Berlin time</div>')
    health_panel()
    strip = md.get_macro_strip()
    cs = st.columns(6, gap="small")
    for c_, m in zip(cs, strip):
        cc = col(m["change_pct"])
        on = m.get("pair") == FX
        act = f"border-color:{ACCENT};background:#151922;" if on else ""
        with c_:
            # kartın tamamı bağlantı: tıklayınca aşağıdaki Forex Piyasası grafiğinde açılır
            H(f'<a class="plain" target="_self" href="{link(fx=m.get("pair") or FX, f="fx")}" '
              f'title="Open the {esc(m["name"])} chart"><div class="idx" style="padding:12px 14px;{act}">'
              f'<div style="display:flex;justify-content:space-between;'
              f'align-items:baseline"><b style="font-size:12.5px">{esc(m["name"])}</b><span class="chip mono">'
              f'{m["code"]}</span></div><div class="mono" style="font-size:19px;font-weight:600;margin-top:6px">'
              f'{tr(m["value"], m["dec"])}</div><div style="display:flex;justify-content:space-between;'
              f'align-items:flex-end"><span class="mono" style="color:{cc};font-size:12px;font-weight:600">'
              f'{pct(m["change_pct"])}</span>{svg_spark(m["series"], cc, 70, 26)}</div></div></a>')
    H(f'<div style="margin-top:6px;display:flex;align-items:center;gap:10px">'
      f'{src_chip(strip[0]["src"] if strip else "none")}'
      f'<span class="muted small">click a card or a pair on the right → the chart opens below</span></div>')

    # 01 Forex piyasası
    anchor("fx")
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">01</span><h3>Forex Market</h3></div>')
    meta = md.fx_meta(FX)
    left, right = st.columns([2.15, 1], gap="medium")
    with left:
        with st.container(border=True):
            daily = md.get_history(meta["symbol"])
            if len(daily) < 2:
                H('<div class="muted">Could not load FX pair data.</div>')
            else:
                last, prev = float(daily["Close"].iloc[-1]), float(daily["Close"].iloc[-2])
                dec = meta["dec"]
                H(f'<div style="display:flex;align-items:center;gap:9px">{avatar(meta["symbol"], 30)}'
                  f'<span class="panel-title">{esc(FX)}</span><span class="chip">{esc(meta["name"])}</span>'
                  f'{src_chip(daily.attrs.get("src"))}</div><div style="display:flex;align-items:baseline;gap:11px;'
                  f'margin-top:6px"><span class="mono" style="font-size:30px;font-weight:600">{tr(last, dec)}</span>'
                  f'<span class="mono" style="color:{col(last - prev)};font-weight:600;font-size:13px">'
                  f'{chg(last - prev, dec)} ({pct((last / prev - 1) * 100)})</span></div>')
                lb, tf = range_controls("w_fxlb", "w_fxtf")
                full, bars, intr = chart_data(meta["symbol"], tf, lb)
                d = full.tail(bars)
                note = ch.lookback_note(full, tf, lb, bars, intr)
                H(f'<div style="display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;margin:10px 0 6px 0">'
                  f'{period_stats(d, dec)}'
                  f'<span class="muted">{esc(ch.LOOKBACKS[ch.norm_lb(lb)]["name"])} · {candle_label(tf, intr)}</span>'
                  f'<span style="flex:1"></span><span class="muted small">double-click: zoom in · '
                  f'right-click: zoom out · draw with the tools on the left</span></div>'
                  + (f'<div class="muted small" style="color:{WARN};margin-bottom:6px">{esc(note)}</div>'
                     if note else ""))
                render_big_chart(meta["symbol"], tf, height=520, tf_key="w_fxtf", lb=lb)
                for a in ch.check_alerts(ss.alerts.get(meta["symbol"], []), daily):
                    st.toast(f"🔔 {FX}: {ch.alert_text(a)} — triggered")
    with right:
        with st.container(border=True):
            H('<div class="panel-title">FX Pairs</div>')
            cat = seg("Category", md.FX_CATEGORIES, "w_fxc", "All")
            rows = ""
            for p in md.get_fx_list(cat):
                act = f"background:#151922;box-shadow:inset 3px 0 0 {ACCENT};" if p["pair"] == FX else ""
                rows += (f'<a class="plain" target="_self" href="{link(fx=p["pair"], f="fx")}"><div class="row" '
                         f'style="{act}padding-left:8px;padding-right:6px">{avatar(p["symbol"], 28)}<div style="flex:1;'
                         f'min-width:0"><b style="font-size:13px">{esc(p["pair"])}</b><div class="muted" '
                         f'style="font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                         f'{esc(p["name"])}</div></div><div style="text-align:right"><div class="mono" '
                         f'style="font-size:13px">{tr(p["last"], p["dec"])}</div><div class="mono" style="font-size:11.5px;'
                         f'color:{col(p["change_pct"])};font-weight:700">{pct(p["change_pct"])}</div></div></div></a>')
            H(f'<div style="max-height:430px;overflow-y:auto">{rows}</div>')

    # 02 Ekonomik takvim
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">02</span><h3>Economic Calendar</h3></div>')
    _calendar_live()

    # 03 Piyasa haberleri
    h1, h2 = st.columns([1, 2.2], vertical_alignment="center")
    with h1:
        H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">03</span><h3>Market News</h3></div>')
    with h2:
        nc = seg("News category", md.NEWS_CATEGORIES, "w_nc", "All")
    data = md.get_forex_news(nc)
    f = data["featured"]
    sbg = {"Bullish": (UP, UP_BG), "Bearish": (DOWN, DOWN_BG)}
    if not f:
        with st.container(border=True):
            H('<div class="panel-title">Market News</div><div class="muted" style="margin-top:6px">'
              'No data is coming from the news sources right now. We don\'t show made-up headlines — try again '
              'in a few minutes.</div>')
        return
    l, r = st.columns([1, 1.15], gap="medium")
    with l:
        fs, fb = sbg.get(f["sentiment"], (NEU, NEU_BG))
        img = (f'<div class="img"><img src="{esc(f["thumb"])}" alt="" loading="lazy" '
               f'onerror="this.parentNode.style.display=\'none\'"></div>' if safe_url(f.get("thumb")) else "")
        furl = news_link(f)
        ttl = f'<a href="{esc(furl)}" target="_blank" rel="noopener">{esc(f["title"])} ↗</a>'
        tags = " ".join(f'<span class="chip mono">{esc(t)}</span>' for t in f.get("tags", []))
        H(f'<a class="plain" href="{esc(furl)}" target="_blank" rel="noopener">'
          f'<div class="feat">{img}<div style="padding:16px 18px"><div style="display:flex;'
          f'align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap"><span class="badge" style="color:{fs};'
          f'background:{fb}">{esc(f["sentiment"])}</span><span class="muted small">{esc(f["category"])} · '
          f'{esc(f["source"])} · {esc(f["when"])}</span>{src_chip(data["src"])}</div><b style="font-size:20px;'
          f'line-height:1.3;display:block">{ttl}</b><div class="muted" style="margin-top:8px;line-height:1.55">'
          f'{esc(f["summary"])}</div><div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">{tags}</div>'
          f'</div></div></a>')
    with r:
        with st.container(border=True):
            H('<div class="muted small" style="margin-bottom:2px">Click a headline → opens on the source website</div>')

            def _spark(it, sc):
                th = safe_url(it.get("thumb"))
                # haberin kendi görseli varsa üste gelir; yüklenemezse (alt="" → boş) altındaki mini grafik görünür
                img = (f'<img src="{esc(th)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if th else "")
                return (f'<span class="nwspark{" hasimg" if th else ""}">'
                        f'{svg_spark(it["spark"], sc, 76, 40)}{img}</span>')
            H(news_rows(data["items"], left=_spark) or '<div class="muted">No news in this category.</div>')
            st.caption("The Bullish/Bearish tag is derived automatically from wording in the headline.")


# ======================================================================
# AKIŞ
# ======================================================================
# ======================================================================
# GİRİŞ EKRANI (Pulse — App Entry tasarımı) · şimdilik her e-posta / şifre kabul edilir
# ======================================================================
ENTRY_ACC = "#3DDC97"
ENTRY_LOGO = ('<svg viewBox="0 0 56 56" width="{w}" height="{w}" fill="none" aria-hidden="true">'
              '<circle cx="28" cy="28" r="26" stroke="#243042" stroke-width="1.5"></circle>'
              '<path d="M11 29 H19.5 L23 19.5 L28.5 37.5 L33 25.5 L36.5 29 H45" stroke="{c}" stroke-width="2.6" '
              'stroke-linecap="round" stroke-linejoin="round"{cls}></path></svg>')
_ENTRY_BARS = "".join(f'<rect x="{24 + i * 60}" y="{y}" width="26" height="{860 - y}"></rect>' for i, y in enumerate(
    [820, 800, 828, 788, 812, 776, 818, 796, 824, 782, 806, 830, 790, 814, 772, 810, 826, 786, 804, 822, 780, 808, 768]))
_ENTRY_PATH = ("M0 700 L60 660 L120 690 L180 620 L240 640 L300 580 L360 602 L420 540 L480 575 L540 520 L600 558 "
               "L660 480 L720 505 L780 450 L840 472 L900 410 L960 440 L1020 380 L1080 418 L1140 350 L1200 374 "
               "L1260 320 L1320 344 L1380 290 L1440 268")
_ECARD = ('.st-key-entry_card', 'div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] '
          '.entry-mark)', 'div[data-testid="stVerticalBlock"]:has(> .element-container .entry-mark)')


def _ecss(rule_tail, body):
    """Giriş kartı seçicilerini (yeni / eski Streamlit DOM) her kurala uygular."""
    return ",".join(f"{c}{rule_tail}" for c in _ECARD) + "{" + body + "}"


ENTRY_CSS = ("<style>"
             "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;700&display=swap');"
             '.stApp,[data-testid="stAppViewContainer"]{background:#0A0E14 !important;background-image:none !important}'
             'header[data-testid="stHeader"]{display:none}'
             ".block-container{padding-top:0 !important;max-width:100% !important}"
             ".entry-bg{position:fixed;inset:0;z-index:0;pointer-events:none}"
             ".entry-bg svg{width:100%;height:100%;opacity:.17}"
             + _ecss("", "position:relative;z-index:2;background:rgba(15,21,30,.88);border:1px solid #1E2838;"
                         "border-radius:18px;padding:44px 40px 30px;gap:14px;margin-top:9vh;"
                         "font-family:Inter,'Helvetica Neue',Arial,sans-serif;box-shadow:0 24px 60px rgba(0,0,0,.35)")
             + ".entry-head{display:flex;flex-direction:column;align-items:center;gap:18px;margin-bottom:10px}"
             ".entry-head h1{margin:0;padding:0;font-family:'Space Grotesk',Inter,sans-serif;font-weight:700;font-size:26px;"
             "line-height:1;letter-spacing:.22em;text-transform:uppercase;color:#E6EAF0}"
             ".entry-head p{margin:0;font-size:14px;color:#94A3B8}"
             + _ecss(' [data-testid="stForm"]', "border:0;padding:0;background:transparent")
             + _ecss(' [data-testid="stWidgetLabel"] p', "font-size:13px;font-weight:500;color:#B9C4D2 !important")
             + _ecss(' [data-baseweb="input"]', "background:#0C131C !important;border-color:#243042 !important;"
                                                "border-radius:10px !important")
             + _ecss(' [data-baseweb="base-input"]', "background:#0C131C !important")
             + _ecss(" input", "height:46px;font-size:15px;color:#E6EAF0 !important;background:#0C131C !important;"
                               "font-family:Inter,sans-serif")
             + _ecss(" input::placeholder", "color:#8A99AD")
             + _ecss(' [data-testid="stCheckbox"] p', "font-size:13px;color:#B9C4D2 !important")
             + _ecss(' [data-testid="stFormSubmitButton"] button',
                     "width:100%;min-height:48px;border-radius:10px;border:0 !important;background:#3DDC97 !important;"
                     "color:#04150E !important;font-weight:600;font-size:15px;margin-top:6px")
             + _ecss(' [data-testid="stFormSubmitButton"] button p', "color:#04150E !important;font-weight:600")
             + _ecss(' [data-testid="stFormSubmitButton"] button:hover', "background:#62E6AE !important")
             + "@media (max-width:640px){" + _ecss("", "padding:32px 22px 24px !important;margin-top:3vh !important") + "}"
             + ".entry-msg{font-size:13px;border:1px solid;border-radius:10px;padding:9px 12px;margin:2px 0 4px 0;"
               "background:rgba(255,255,255,.02)}"
               ".entry-code{font-family:ui-monospace,monospace;font-size:22px;font-weight:700;letter-spacing:.12em;"
               "text-align:center;color:#E6EAF0;background:#0C131C;border:1px dashed #3DDC97;border-radius:12px;"
               "padding:16px 10px;margin:4px 0 8px 0}"
             + _ecss(' [data-testid="stBaseButton-tertiary"]', "color:#3DDC97 !important;font-size:13px;padding:0")
             + _ecss(' [data-testid="stBaseButton-tertiary"] p', "color:#3DDC97 !important;font-size:13px")
             + _ecss(' [data-testid="stBaseButton-primary"]', "width:100%;min-height:46px;border-radius:10px;border:0 "
                     "!important;background:#3DDC97 !important;color:#04150E !important;font-weight:600")
             + _ecss(' [data-testid="stBaseButton-primary"] p', "color:#04150E !important;font-weight:600")
             + _ecss(' [data-testid="stExpander"] details', "background:#0C131C !important;border-color:#243042 !important")
             + _ecss(' [data-testid="stExpander"] summary p', "color:#B9C4D2 !important;font-size:13px")
             + ".entry-foot{text-align:center;font-size:13px;color:#94A3B8;margin-top:4px}"
             ".entry-foot b{color:#3DDC97;font-weight:600}"
             "</style>")


def _entry_bg():
    grid_h = "".join(f'<line x1="0" y1="{y}" x2="1440" y2="{y}"></line>' for y in (250, 370, 490, 610, 730))
    grid_v = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="900"></line>' for x in (240, 480, 720, 960, 1200))
    return (f'<div class="entry-bg"><svg viewBox="0 0 1440 900" preserveAspectRatio="none" aria-hidden="true">'
            f'<g stroke="#3C4A5E" stroke-width="1">{grid_h}</g><g stroke="#2F3C4D" stroke-width="1">{grid_v}</g>'
            f'<g fill="#55657B">{_ENTRY_BARS}</g>'
            f'<path d="{_ENTRY_PATH} L1440 900 L0 900 Z" fill="{ENTRY_ACC}" opacity="0.14"></path>'
            f'<path d="{_ENTRY_PATH}" fill="none" stroke="{ENTRY_ACC}" stroke-width="3" stroke-linejoin="round"></path>'
            f'</svg></div>')


# ----------------------------------------------------------------------
# Kimlik doğrulama (v3.8): ilk açılışta e-posta + şifre belirlenir, sonra her açılışta giriş istenir.
# Şifre ve kurtarma kodu düz metin saklanmaz (PBKDF2-SHA256, tuzlu). Kayıt yeri:
#   1) sunucudaki .pulse_auth.json (uygulama içinden kurulur / sıfırlanır)
#   2) yoksa Streamlit Secrets → [pulse_auth] email, password_hash, recovery_hash (kalıcı)
# ----------------------------------------------------------------------
AUTH_FILE = os.environ.get("PULSE_AUTH_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                             ".pulse_auth.json")
AUTH_IDLE = 15 * 60          # bu kadar işlem yapılmazsa yeniden giriş (yeni sekme / yeni açılış zaten giriş ister)
_CODE_ABC = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _pw_hash(pw, it=240_000):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, it)
    return f"pbkdf2_sha256${it}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def _pw_check(pw, stored):
    try:
        algo, it, salt, h = str(stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), base64.b64decode(salt), int(it))
        return hmac.compare_digest(base64.b64encode(dk).decode(), h)
    except Exception:
        return False


def _norm_email(e):
    return str(e or "").strip().lower()


def _norm_code(c):
    return re.sub(r"[^A-Z0-9]", "", str(c or "").upper())


def _new_code():
    raw = "".join(secrets.choice(_CODE_ABC) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def _rec(d, role=None):
    return {"email": _norm_email(d.get("email")), "password_hash": str(d.get("password_hash") or ""),
            "recovery_hash": str(d.get("recovery_hash") or ""), "role": role or str(d.get("role") or "user"),
            "must_change": bool(d.get("must_change")), "created": str(d.get("created") or "")}


def auth_store():
    """Kayıtlı kullanıcılar: önce dosya (v2: users listesi, v1: tek kayıt → owner), yoksa Secrets
    ([[pulse_users]] listesi ya da eski [pulse_auth] tek kayıt). Hiçbiri yoksa None → ilk kurulum."""
    try:
        with open(AUTH_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        users = [_rec(u) for u in d.get("users", [])] if "users" in d else \
            ([_rec(d, "owner")] if d.get("email") else [])
        users = [u for u in users if u["email"] and u["password_hash"]]
        if users:
            if not any(u["role"] == "owner" for u in users):
                users[0]["role"] = "owner"
            return {"users": users, "where": "file"}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        sec = st.secrets if hasattr(st, "secrets") else {}
        lst = sec.get("pulse_users") if hasattr(sec, "get") else None
        users = []
        if lst:
            users = [_rec(dict(u)) for u in lst]
        elif hasattr(sec, "get") and sec.get("pulse_auth"):
            users = [_rec(dict(sec["pulse_auth"]), "owner")]
        users = [u for u in users if u["email"] and u["password_hash"]]
        if users:
            if not any(u["role"] == "owner" for u in users):
                users[0]["role"] = "owner"
            return {"users": users, "where": "secrets"}
    except Exception:
        pass
    return None


def auth_load():
    """Geriye uyumluluk: owner kaydı (yoksa None)."""
    stv = auth_store()
    if not stv:
        return None
    o = next((u for u in stv["users"] if u["role"] == "owner"), stv["users"][0])
    return {**o, "where": stv["where"]}


def auth_user(email):
    stv = auth_store()
    e = _norm_email(email)
    return next((u for u in (stv or {}).get("users", []) if hmac.compare_digest(u["email"], e)), None)


def _auth_write(users):
    tmp = AUTH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"v": 2, "users": users}, fh)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, AUTH_FILE)


def auth_upsert(email, pw, role=None, old_email=None, must_change=False, new_code=True):
    """Kullanıcı ekler / günceller. Yeni kurtarma kodunu döndürür (new_code=False ise None)."""
    stv = auth_store() or {"users": []}
    users = [dict(u) for u in stv["users"]]
    key = _norm_email(old_email or email)
    cur = next((u for u in users if u["email"] == key), None)
    code = _new_code() if new_code else None
    rec = {"email": _norm_email(email), "password_hash": _pw_hash(pw),
           "recovery_hash": _pw_hash(_norm_code(code)) if code else (cur or {}).get("recovery_hash", ""),
           "role": role or (cur or {}).get("role") or ("owner" if not users else "user"),
           "must_change": bool(must_change), "created": (cur or {}).get("created") or
           pd.Timestamp.now(tz="UTC").isoformat()}
    users = [u for u in users if u["email"] not in (key, rec["email"])]
    users.append(rec)
    users.sort(key=lambda u: (u["role"] != "owner", u["created"]))
    _auth_write(users)
    return code, rec


def auth_remove(email):
    stv = auth_store() or {"users": []}
    users = [u for u in stv["users"] if u["email"] != _norm_email(email) or u["role"] == "owner"]
    _auth_write(users)


def auth_save(email, pw):
    """İlk kurulum: owner hesabı."""
    code, rec = auth_upsert(email, pw, role="owner")
    return code, rec


def owner_key():
    """Uygulama sahibinin anahtarı (Streamlit Secrets'ta, yalnızca sahibi görür):
    [pulse_admin] key = "…"  ya da  PULSE_ADMIN_KEY = "…"."""
    try:
        sec = st.secrets if hasattr(st, "secrets") else {}
        k = None
        if hasattr(sec, "get"):
            adm = sec.get("pulse_admin")
            k = (adm.get("key") if hasattr(adm, "get") else None) or sec.get("PULSE_ADMIN_KEY")
        k = k or os.environ.get("PULSE_ADMIN_KEY")
        return str(k) if k and len(str(k)) >= 8 else None
    except Exception:
        return os.environ.get("PULSE_ADMIN_KEY") or None


def _temp_password():
    return "".join(secrets.choice(_CODE_ABC.lower() + "23456789") for _ in range(12))


def secrets_snippet(rec=None):
    """Tüm kullanıcılar için kalıcı Secrets bloğu (yalnızca karmalar)."""
    stv = auth_store() or {"users": [rec] if rec else []}
    out = []
    for u in stv["users"]:
        out.append(f'[[pulse_users]]\nemail = "{u["email"]}"\nrole = "{u["role"]}"\n'
                   f'password_hash = "{u["password_hash"]}"\nrecovery_hash = "{u["recovery_hash"]}"\n'
                   + ('must_change = true\n' if u.get("must_change") else ""))
    return "\n".join(out)


@st.cache_resource(show_spinner=False)
def _auth_guard():
    """Tüm oturumlar için ortak deneme sayacı (kaba kuvvet denemelerini yavaşlatır)."""
    return {"fails": []}


def _auth_locked():
    g = _auth_guard()
    now = time.time()
    g["fails"] = [t for t in g["fails"] if now - t < 900]
    n = len(g["fails"])
    if n < 5:
        return 0
    wait = min(900, 30 * 2 ** (n - 5)) - (now - g["fails"][-1])
    return int(max(0, wait))


def _auth_fail():
    _auth_guard()["fails"].append(time.time())


def _client_tag():
    """Oturumu tarayıcıya bağlamak için kaba bir iz (User-Agent özeti): bağlantıyı başka cihaza
    kopyalayan biri girişsiz açamasın."""
    try:
        ua = (st.context.headers or {}).get("User-Agent") or ""
    except Exception:
        ua = ""
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:16] if ua else ""


def auth_valid():
    a = ss.get("auth")
    if not isinstance(a, dict) or not a.get("user"):
        return False
    if time.time() - float(a.get("last") or 0) > AUTH_IDLE:
        ss.auth = None
        return False
    tag = _client_tag()
    if a.get("tag") and tag and a["tag"] != tag:
        ss.auth = None
        return False
    u = auth_user(a["user"]) if auth_store() else None
    if auth_store() and (u is None or u.get("must_change")):      # silindi ya da şifresi sıfırlandı
        ss.auth = None
        return False
    if u:
        a["role"] = u["role"]
    return True


def is_owner():
    return (ss.get("auth") or {}).get("role") == "owner"


def _sign_in(email):
    u = auth_user(email) or {}
    ss.auth = {"user": _norm_email(email), "at": pd.Timestamp.now(tz=md.TZ).strftime("%Y-%m-%d %H:%M"),
               "last": time.time(), "tag": _client_tag(), "role": u.get("role", "user")}
    ss["_boot"] = True            # ilk yüklemede açılış ekranı
    ss["_cred_store"] = True      # tarayıcı şifre yöneticisine kaydetmeyi önersin


# Tarayıcının otomatik doldurduğu değerler, kullanıcı "Sign in"e basana kadar sayfaya verilmez (güvenlik).
# Düğmeye basıldığı anda değerleri Streamlit'e iletir; giriş yine yalnızca düğmeyle olur.
_AUTOFILL_JS = """<script>
(function(){
  var P = window.parent, D = P.document;
  if (!P.__pulseAuthHooks) {
    P.__pulseAuthHooks = true;
    var setter = Object.getOwnPropertyDescriptor(P.HTMLInputElement.prototype, 'value').set;
    var sync = function(){
      var user = null, pass = null;
      D.querySelectorAll('input[autocomplete="username"], input[type="password"]').forEach(function(i){
        var v = i.value; if (!v) return;
        setter.call(i, v);
        i.dispatchEvent(new P.Event('input', {bubbles: true}));
        if (i.type === 'password') { if (!pass) pass = v; } else { user = v; }
      });
      if (user && pass) P.__pulsePending = {id: user, pw: pass, t: Date.now()};
    };
    D.addEventListener('pointerdown', function(e){
      if (e.target && e.target.closest && e.target.closest('[data-testid="stFormSubmitButton"]')) sync();
    }, true);
    D.addEventListener('keydown', function(e){
      if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT') sync();
    }, true);
  }
})();
</script>"""
# Başarılı girişten sonra: Chrome / Edge'de şifre yöneticisine kaydetmeyi öner (kullanıcı onaylar)
_CRED_STORE_JS = """<script>
(function(){
  var P = window.parent, c = P.__pulsePending;
  P.__pulsePending = null;
  if (!c || Date.now() - c.t > 600000) return;
  try {
    if (P.PasswordCredential && P.navigator.credentials && P.navigator.credentials.store) {
      P.navigator.credentials.store(new P.PasswordCredential({id: c.id, password: c.pw, name: 'Pulse'}));
    }
  } catch (e) {}
})();
</script>"""


def _auth_header(title, sub):
    st.markdown('<div class="entry-mark"></div><div class="entry-head">'
                + ENTRY_LOGO.format(w=72, c=ENTRY_ACC, cls="") +
                f'<div style="display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center">'
                f'<h1>{esc(title)}</h1><p>{esc(sub)}</p></div></div>', unsafe_allow_html=True)


def _auth_msg(kind, text):
    c = {"err": "#F87171", "ok": "#3DDC97", "info": "#94A3B8"}[kind]
    st.markdown(f'<div class="entry-msg" style="color:{c};border-color:{c}55">{esc(text)}</div>',
                unsafe_allow_html=True)


def _set_mode(m):
    ss["auth_mode"] = m
    ss.pop("_auth_err", None)


def _btn_link():
    return {"type": "tertiary"} if "tertiary" in str(inspect.signature(st.button)) else {}


def render_auth():
    """Giriş kapısı: ilk kurulum · giriş · şifre değiştirme (geçici şifreden sonra) · sıfırlama · kurtarma kodu."""
    st.markdown(ENTRY_CSS, unsafe_allow_html=True)
    st.markdown(_entry_bg(), unsafe_allow_html=True)
    stv = auth_store()
    mode = ss.get("auth_mode") or ("login" if stv else "setup")
    if stv and mode == "setup":
        mode = "login"
    if not stv and mode in ("login", "reset", "change"):
        mode = "setup"
    err = ss.pop("_auth_err", None)
    ok_ = ss.pop("_auth_ok", None)
    _, mid, _ = st.columns([1, 1.05, 1])
    with mid:
        try:
            card = st.container(key="entry_card")
        except TypeError:          # eski Streamlit: key yok → :has() seçicisi devreye girer
            card = st.container()
        with card:
            if mode == "code":
                _auth_code_screen()
                return
            if mode == "setup":
                _auth_header("Pulse", "First start — choose the email and password you will sign in with")
                if err:
                    _auth_msg("err", err)
                with st.form("entry_setup", border=False):
                    em = st.text_input("Email", placeholder="you@example.com", key="setup_email",
                                       autocomplete="username")
                    p1 = st.text_input("Password", type="password", placeholder="At least 8 characters",
                                       key="setup_pw", autocomplete="new-password")
                    p2 = st.text_input("Repeat password", type="password", placeholder="Same password again",
                                       key="setup_pw2", autocomplete="new-password")
                    go_ = st.form_submit_button("Create login", type="primary", **_wkw(st.form_submit_button))
                st.markdown('<div class="entry-foot">This is done once and makes you the <b>owner</b>: you can '
                            'later add friends and reset their logins. From then on Pulse asks for your email and '
                            'password every time it is opened.</div>', unsafe_allow_html=True)
                if go_:
                    e = _norm_email(em)
                    if not _EMAIL_RE.match(e):
                        ss["_auth_err"] = "Please enter a valid email address."
                    elif len(p1 or "") < 8:
                        ss["_auth_err"] = "The password needs at least 8 characters."
                    elif p1 != p2:
                        ss["_auth_err"] = "The two passwords do not match."
                    elif auth_store():
                        ss["_auth_err"] = "A login was created a moment ago — please sign in."
                        ss["auth_mode"] = "login"
                    else:
                        try:
                            code, rec = auth_save(e, p1)
                        except OSError:
                            ss["_auth_err"] = "The login could not be saved on the server (write access denied)."
                        else:
                            ss["_new_code"], ss["_new_rec"], ss["_code_next"] = code, rec, "app"
                            ss["auth_mode"] = "code"
                            _sign_in(e)
                            ss["_hold_auth"] = ss.auth      # önce kurtarma kodu gösterilir
                            ss.auth = None
                    st.rerun()
            elif mode == "change":
                who = ss.get("_chg_user") or ""
                _auth_header("New password", f"{who} — your password was reset, choose a new one")
                if err:
                    _auth_msg("err", err)
                with st.form("entry_change", border=False):
                    st.text_input("Email", value=who, key="chg_email", autocomplete="username", disabled=True)
                    p1 = st.text_input("New password", type="password", placeholder="At least 8 characters",
                                       key="chg_pw", autocomplete="new-password")
                    p2 = st.text_input("Repeat new password", type="password", key="chg_pw2",
                                       autocomplete="new-password")
                    go_ = st.form_submit_button("Save new password", type="primary", **_wkw(st.form_submit_button))
                st.button("← Back to sign in", key="chg_back", on_click=_set_mode, args=("login",), **_btn_link())
                if go_:
                    u = auth_user(who)
                    if not u or not ss.get("_chg_ok"):
                        ss["_auth_err"] = "Please sign in with the temporary password again."
                        ss["auth_mode"] = "login"
                    elif len(p1 or "") < 8:
                        ss["_auth_err"] = "The new password needs at least 8 characters."
                    elif p1 != p2:
                        ss["_auth_err"] = "The two passwords do not match."
                    else:
                        code, rec = auth_upsert(who, p1, old_email=who, must_change=False)
                        ss.pop("_chg_ok", None)
                        ss["_new_code"], ss["_new_rec"], ss["_code_next"] = code, rec, "app"
                        ss["auth_mode"] = "code"
                        _sign_in(who)
                        ss["_hold_auth"] = ss.auth
                        ss.auth = None
                    st.rerun()
            elif mode == "reset":
                _auth_header("Reset login", "Forgot your email or password? Use your recovery code")
                if err:
                    _auth_msg("err", err)
                wait = _auth_locked()
                with st.form("entry_reset", border=False):
                    rc = st.text_input("Recovery code (or owner key)", placeholder="XXXX-XXXX-XXXX-XXXX",
                                       key="reset_code", type="password", autocomplete="off")
                    em = st.text_input("New email", placeholder="you@example.com", key="reset_email",
                                       autocomplete="username")
                    p1 = st.text_input("New password", type="password", placeholder="At least 8 characters",
                                       key="reset_pw", autocomplete="new-password")
                    p2 = st.text_input("Repeat new password", type="password", key="reset_pw2",
                                       autocomplete="new-password")
                    go_ = st.form_submit_button("Reset and save", type="primary", **_wkw(st.form_submit_button))
                st.button("← Back to sign in", key="reset_back", on_click=_set_mode, args=("login",), **_btn_link())
                st.markdown('<div class="entry-foot">Use the recovery code you got when your login was created. '
                            'No code? Ask the app owner — they can reset your login in <b>Account → Users</b>. '
                            'The owner can also reset the owner login here with the owner key from the app\'s '
                            'Secrets.</div>', unsafe_allow_html=True)
                if go_:
                    e = _norm_email(em)
                    target = None
                    if wait:
                        ss["_auth_err"] = f"Too many attempts — try again in {wait} s."
                    else:
                        okey = owner_key()
                        if okey and hmac.compare_digest(str(rc or "").strip(), okey):
                            target = next((u for u in stv["users"] if u["role"] == "owner"), None)
                        else:
                            nc = _norm_code(rc)
                            target = next((u for u in stv["users"] if u.get("recovery_hash") and
                                           _pw_check(nc, u["recovery_hash"])), None) if nc else None
                        if target is None:
                            _auth_fail()
                            ss["_auth_err"] = "This recovery code (or owner key) is not correct."
                    if target is not None:
                        if not _EMAIL_RE.match(e):
                            ss["_auth_err"] = "Please enter a valid email address."
                        elif len(p1 or "") < 8:
                            ss["_auth_err"] = "The new password needs at least 8 characters."
                        elif p1 != p2:
                            ss["_auth_err"] = "The two passwords do not match."
                        elif e != target["email"] and auth_user(e):
                            ss["_auth_err"] = "Another account already uses this email."
                        else:
                            try:
                                code, rec = auth_upsert(e, p1, old_email=target["email"])
                            except OSError:
                                ss["_auth_err"] = "The new login could not be saved on the server."
                            else:
                                ss["_new_code"], ss["_new_rec"], ss["_code_next"] = code, rec, "login"
                                ss["_was_secrets"] = stv.get("where") == "secrets"
                                ss["auth_mode"] = "code"
                    st.rerun()
            else:
                _auth_header("Pulse", "Sign in to open your dashboard")
                if ok_:
                    _auth_msg("ok", ok_)
                if err:
                    _auth_msg("err", err)
                wait = _auth_locked()
                with st.form("entry_login", border=False):
                    em = st.text_input("Email", placeholder="you@example.com", key="login_email",
                                       autocomplete="username")
                    pw = st.text_input("Password", type="password", placeholder="Enter your password",
                                       key="login_pw", autocomplete="current-password")
                    go_ = st.form_submit_button("Sign in", type="primary", **_wkw(st.form_submit_button))
                st.button("Forgot email or password?", key="login_forgot", on_click=_set_mode, args=("reset",),
                          **_btn_link())
                if go_:
                    u = auth_user(em)
                    if wait:
                        ss["_auth_err"] = f"Too many attempts — try again in {wait} s."
                    elif u and _pw_check(pw, u["password_hash"]):
                        if u.get("must_change"):
                            ss["_chg_user"], ss["_chg_ok"] = u["email"], True
                            ss["auth_mode"] = "change"
                        else:
                            ss["auth_mode"] = None
                            _sign_in(u["email"])
                    else:
                        _auth_fail()
                        ss["_auth_err"] = "Email or password is not correct."
                    st.rerun()
    components.html(_AUTOFILL_JS, height=0)


def _auth_code_screen():
    code, rec = ss.get("_new_code"), ss.get("_new_rec")
    nxt = ss.get("_code_next", "login")
    if not code or not rec:
        ss["auth_mode"] = None
        st.rerun()
        return
    _auth_header("Recovery code", "Save it now — it is shown only once")
    st.markdown(f'<div class="entry-code">{esc(code)}</div>'
                '<div class="entry-foot" style="text-align:left">If you ever forget your email or password, '
                '<b>Forgot email or password?</b> on the sign-in screen lets you set new ones with this code. '
                'Keep it somewhere safe (password manager, printout).</div>', unsafe_allow_html=True)
    st.download_button("Download code (.txt)", data=f"Pulse recovery code: {code}\nLogin email: {rec['email']}\n",
                       file_name="pulse-recovery-code.txt", key="code_dl", **_wkw(st.download_button))
    if ss.get("_was_secrets"):
        st.markdown('<div class="entry-foot" style="text-align:left;color:#F5B544">Logins were stored in the '
                    'app\'s Secrets. Replace the [[pulse_users]] / [pulse_auth] block there with the lines below, '
                    'otherwise the old login returns after the next app restart.</div>', unsafe_allow_html=True)
    if rec.get("role") == "owner" or ss.get("_was_secrets"):
        with st.expander("Keep the logins after app restarts (recommended on Streamlit Cloud)"):
            st.markdown('<div class="entry-foot" style="text-align:left">On Streamlit Community Cloud the saved '
                        'login file is cleared when the app restarts or is redeployed — Pulse would then show the '
                        'first-start screen again. Paste these lines into <b>App settings → Secrets</b> to make it '
                        'permanent. They contain only salted hashes, not passwords.</div>', unsafe_allow_html=True)
            st.code(secrets_snippet(rec), language="toml")
    saved = st.checkbox("I have saved my recovery code", key="code_saved")
    if st.button("Continue to Pulse" if nxt == "app" else "Continue to sign in", key="code_go", type="primary",
                 disabled=not saved, **_wkw(st.button)):
        for k in ("_new_code", "_new_rec", "_was_secrets", "_code_next"):
            ss.pop(k, None)
        if nxt == "app" and ss.get("_hold_auth"):
            ss.auth = ss.pop("_hold_auth")
            ss.auth["last"] = time.time()
            ss["auth_mode"] = None
        else:
            ss.pop("_hold_auth", None)
            ss["auth_mode"] = "login"
            ss["_auth_ok"] = "Login updated — sign in with your new email and password."
        st.rerun()


def users_admin():
    """Owner: kullanıcı ekle, şifre sıfırla (geçici şifre), kaldır, kalıcı Secrets bloğu."""
    stv = auth_store() or {"users": [], "where": "file"}
    users = stv["users"]
    H('<div style="font-size:12px;font-weight:700;margin:14px 0 4px 0">Users <span class="muted" '
      'style="font-weight:500">· owner only</span></div>')
    rows = "".join(f'<div class="stat-row"><span class="lbl">{esc(u["email"])}</span><span class="muted small">'
                   f'{"owner" if u["role"] == "owner" else "user"}{" · must set new password" if u.get("must_change") else ""}'
                   f'</span></div>' for u in users)
    H(rows)
    res = ss.pop("_adm_result", None)
    if res:
        H(f'<div class="gtext" style="margin-top:6px">{res}</div>')
    others = [u["email"] for u in users if u["role"] != "owner"]
    if others:
        pick = st.selectbox("Account", others, key="adm_pick")
        # popover zaten sütun içinde: ikinci sütun seviyesi açılmaz, düğmeler alt alta
        if button("Reset password", key="adm_reset", help="Creates a temporary password; they choose a new "
                                                           "one at the next sign-in."):
            tmp = _temp_password()
            auth_upsert(pick, tmp, old_email=pick, must_change=True, new_code=False)
            ss["_adm_result"] = (f'Temporary password for <b>{esc(pick)}</b>: <span class="mono" '
                                 f'style="font-size:14px">{tmp}</span><br><span class="muted small">Give it to '
                                 f'them — at the next sign-in they must choose a new password. Shown only now.'
                                 f'</span>')
            st.rerun()
        if button("Remove user", key="adm_remove"):
            auth_remove(pick)
            ss["_adm_result"] = f'Removed <b>{esc(pick)}</b>.'
            st.rerun()
    with st.form("adm_add", border=False):
        ne = st.text_input("Add a user (email)", placeholder="friend@example.com", key="adm_new")
        add = st.form_submit_button("Add user", **_wkw(st.form_submit_button))
    if add:
        e = _norm_email(ne)
        if not _EMAIL_RE.match(e):
            ss["_adm_result"] = "Please enter a valid email address."
        elif auth_user(e):
            ss["_adm_result"] = f"{esc(e)} already has a login — use Reset password."
        else:
            tmp = _temp_password()
            auth_upsert(e, tmp, role="user", must_change=True, new_code=False)
            ss["_adm_result"] = (f'Added <b>{esc(e)}</b>. Temporary password: <span class="mono" style="font-size:14px">'
                                 f'{tmp}</span><br><span class="muted small">They choose their own password at the '
                                 f'first sign-in. Shown only now.</span>')
        st.rerun()
    with st.expander("Keep logins after app restarts"):
        H('<div class="muted small">On Streamlit Cloud the login file is cleared on restart / redeploy. Paste this '
          'into <b>App settings → Secrets</b> (hashes only). Optional owner key for emergencies: add '
          '<span class="mono">[pulse_admin]</span> <span class="mono">key = "…"</span> (at least 8 characters) — it '
          'resets the owner login from the sign-in screen.</div>')
        st.code(secrets_snippet(), language="toml")
    H(f'<div class="muted small">Logins stored {"on this server" if stv.get("where") == "file" else "in Secrets"} · '
      f'owner key {"set" if owner_key() else "not set"}.</div>')


LOADING_HTML = """<div class="p-load-wrap"><style>
@keyframes pulse-ring{0%{transform:scale(.92);opacity:.5}75%{transform:scale(1.4);opacity:0}100%{transform:scale(1.4);opacity:0}}
@keyframes pulse-trace{0%{stroke-dashoffset:120}55%{stroke-dashoffset:0}100%{stroke-dashoffset:-120}}
@keyframes bar-slide{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.p-load{position:fixed;inset:0;z-index:1000000;background:#0A0E14;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:44px;font-family:Inter,'Helvetica Neue',Arial,sans-serif}
.p-load .ring{position:absolute;inset:0;border-radius:999px;border:1px solid #3DDC97;animation:pulse-ring 2.4s ease-out infinite}
.p-load .trace{stroke-dasharray:120;animation:pulse-trace 2.4s linear infinite}
.p-load .bar{width:55%;height:100%;border-radius:999px;background:#3DDC97;animation:bar-slide 1.8s cubic-bezier(.4,0,.2,1) infinite}
.p-load h1{margin:0;padding:0;font-family:'Space Grotesk',Inter,sans-serif;font-weight:700;font-size:44px;line-height:1;
 letter-spacing:.24em;text-transform:uppercase;color:#E6EAF0}
</style>
<div class="p-load"><div style="display:flex;flex-direction:column;align-items:center;gap:28px">
<div style="position:relative;width:120px;height:120px;display:flex;align-items:center;justify-content:center">
<span class="ring"></span>
<svg viewBox="0 0 56 56" width="120" height="120" fill="none" aria-hidden="true">
<circle cx="28" cy="28" r="26" stroke="#243042" stroke-width="1.5"></circle>
<path d="M11 29 H19.5 L23 19.5 L28.5 37.5 L33 25.5 L36.5 29 H45" stroke="#243042" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"></path>
<path class="trace" d="M11 29 H19.5 L23 19.5 L28.5 37.5 L33 25.5 L36.5 29 H45" stroke="#3DDC97" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"></path>
</svg></div>
<div style="display:flex;flex-direction:column;align-items:center;gap:12px"><h1>Pulse</h1>
<p style="margin:0;font-size:13px;letter-spacing:.2em;text-transform:uppercase;color:#94A3B8">Market &amp; Swing Intelligence</p></div></div>
<div style="display:flex;flex-direction:column;align-items:center;gap:18px;width:min(260px,100%)">
<div style="width:100%;height:3px;border-radius:999px;background:#1B2431;overflow:hidden"><div class="bar"></div></div>
<p style="margin:0;font-size:13px;color:#94A3B8">Loading market data...</p></div></div></div>"""


def main():
    if not auth_valid():
        render_auth()
        return
    ss.auth["last"] = time.time()           # hareketsizlik süresi sıfırlanır
    if ss.pop("_cred_store", False):
        components.html(_CRED_STORE_JS, height=0)
    boot = st.empty() if ss.pop("_boot", False) else None
    if boot is not None:
        boot.markdown(LOADING_HTML, unsafe_allow_html=True)     # sayfa hesaplanırken açılış ekranı
    try:
        render_header()
        {"Markets": render_piyasalar, "Valuation": render_value, "Long Term": render_longterm,
         "Short Term": render_short, "Backtest": render_backtest,
         "Forex & News": render_forex}[SEC]()
    finally:
        if boot is not None:
            boot.empty()




VT_COLOR = {"cyclical": WARN, "defensive": UP, "growth": ACCENT, "capital": VIOLET}
STATE_ICON = {"good": ("✓", UP), "bad": ("✕", DOWN), "flat": ("•", MUT)}


def _mon(x):
    try:
        return pd.Timestamp(x).strftime("%b %Y")
    except Exception:
        return "—"


def vtype_choice(b, sym):
    """Otomatik sınıflandırma + elle değiştirme (hisse başına saklanır)."""
    auto = b["cls"]["type"]
    opts = ["auto"] + list(en.VTYPE_ORDER)
    key = f"vt_{sym}"
    saved = (ss.get("vtype_ovr") or {}).get(sym, "auto")
    if key not in ss or ss.get(key) not in opts:
        ss[key] = saved if saved in opts else "auto"
    v = st.selectbox("Valuation model", opts, key=key,
                     format_func=lambda o: f"Auto — {en.VTYPES[auto]}" if o == "auto" else en.VTYPES[o])
    ov = dict(ss.get("vtype_ovr") or {})
    if v == "auto":
        ov.pop(sym, None)
    else:
        ov[sym] = v
    ss.vtype_ovr = dict(list(ov.items())[-60:])
    return auto if v == "auto" else v


def checks_html(rows):
    out = ""
    for r_ in rows:
        ic, c_ = STATE_ICON.get(r_["state"], STATE_ICON["flat"])
        note = f'<div class="muted small">{esc(r_["note"])}</div>' if r_.get("note") else ""
        out += (f'<div class="vrow"><span class="ic" style="color:{c_};background:{c_}1F">{ic}</span>'
                f'<span class="t">{esc(r_["name"])}{note}</span>'
                f'<span class="n" style="color:{TXT};font-family:ui-monospace,monospace;text-align:right">'
                f'{esc(r_["value"])}</span></div>')
    return out or '<div class="muted">Not enough data for these checks.</div>'


def cycle_fig(wk, timing, height=300):
    """Uzun dönem fiyat (log), geçmiş tepe/dipler ve sıradaki dönüş penceresi."""
    w = wk.tail(52 * 26)
    fig = go.Figure(go.Scatter(x=w.index, y=w.values, mode="lines", line=dict(color=SOFT, width=1.4),
                               name="Price", hovertemplate="%{x|%b %Y}: %{y:.2f}<extra></extra>"))
    piv = [p_ for p_ in (timing or {}).get("pivots", []) if pd.Timestamp(p_[0]) >= w.index[0]]
    for kind, col_, sym_ in (("peak", DOWN, "triangle-down"), ("trough", UP, "triangle-up")):
        pts = [p_ for p_ in piv if p_[2] == kind]
        if pts:
            fig.add_trace(go.Scatter(x=[pd.Timestamp(p_[0]) for p_ in pts], y=[p_[1] for p_ in pts],
                                     mode="markers", name=kind.capitalize() + "s",
                                     marker=dict(size=9, color=col_, symbol=sym_),
                                     hovertemplate=kind + " %{x|%b %Y}: %{y:.2f}<extra></extra>"))
    t = timing or {}
    for wkey, col_, lab in (("window", WARN, "next " + str(t.get("next_turn", "turn"))),
                            ("window_earnings", VIOLET, "earnings-path window")):
        win = t.get(wkey)
        if not win or (wkey == "window_earnings" and t.get("window")):
            continue
        fig.add_vrect(x0=pd.Timestamp(win[0]), x1=pd.Timestamp(win[1]) + pd.Timedelta(days=20),
                      fillcolor=rgba(col_, 0.18), line_width=0)
    if not t.get("window") and t.get("window_price"):
        win = t["window_price"]
        fig.add_vrect(x0=pd.Timestamp(win[0]), x1=pd.Timestamp(win[1]) + pd.Timedelta(days=20),
                      fillcolor=rgba(WARN, 0.14), line_width=0)
    fig.update_yaxes(type="log")
    fig.update_layout(legend=dict(orientation="h", y=1.12, x=0))
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=26, b=4))


def yield_fig(divst, tnx_w, height=260):
    ys = divst["yield_series"]
    fig = go.Figure(go.Scatter(x=ys.index, y=ys.values, mode="lines", name="Dividend yield (TTM)",
                               line=dict(color=UP, width=1.8), hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>"))
    if tnx_w is not None and len(tnx_w):
        t_ = tnx_w[tnx_w.index >= ys.index[0]]
        if len(t_):
            fig.add_trace(go.Scatter(x=t_.index, y=t_.values, mode="lines", name="US 10Y yield",
                                     line=dict(color=MUT, width=1.2, dash="dot"),
                                     hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>"))
    for v, lab, c_ in ((divst["y_p75"], "cheap zone", UP), (divst["y_med"], "median", MUT),
                       (divst["y_p25"], "expensive zone", DOWN)):
        fig.add_hline(y=v, line=dict(color=c_, width=1, dash="dash"), annotation_text=f"{lab} {tr(v)}%",
                      annotation_position="top left", annotation_font=dict(color=c_, size=10))
    fig.update_yaxes(ticksuffix="%")
    fig.update_layout(legend=dict(orientation="h", y=1.14, x=0))
    return _layout(fig, height, legend=True, margin=dict(l=4, r=8, t=26, b=4))


def growth_proj_fig(rows, year0, rev0, height=260):
    yrs = [str(year0)] + [str(year0 + r_["k"]) for r_ in rows]
    revs = [rev0 / 1e9] + [r_["rev"] / 1e9 for r_ in rows]
    fig = go.Figure(go.Bar(x=yrs, y=revs, name="Revenue (bn)", marker_color=rgba(ACCENT, 0.6),
                           hovertemplate="%{x}: %{y:.1f} bn<extra></extra>"))
    fig.add_trace(go.Scatter(x=yrs[1:], y=[r_["margin"] for r_ in rows], name="FCF margin", yaxis="y2",
                             mode="lines+markers", line=dict(color=UP, width=2),
                             hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, ticksuffix="%",
                                  tickfont=dict(color=MUT, size=10)), legend=dict(orientation="h", y=1.16, x=0))
    fig = _layout(fig, height, legend=True, margin=dict(l=36, r=40, t=26, b=4))
    fig.update_layout(yaxis=dict(side="left"))
    return fig


def debt_fig(f, height=260):
    yrs = [str(y) for y in f["years"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=[v / 1e9 if en._ok(v) else None for v in f["ebitda"]], name="EBITDA (bn)",
                         marker_color=rgba(UP, 0.7)))
    fig.add_trace(go.Bar(x=yrs, y=[v / 1e9 if en._ok(v) else None for v in f["debt"]], name="Total debt (bn)",
                         marker_color=rgba(DOWN, 0.6)))
    nde = [en._d(n_, e_) for n_, e_ in zip(f["net_debt"], f["ebitda"])]
    fig.add_trace(go.Scatter(x=yrs, y=_clean(nde), name="Net debt / EBITDA", yaxis="y2", mode="lines+markers",
                             line=dict(color=WARN, width=2), hovertemplate="%{x}: %{y:.2f}x<extra></extra>"))
    fig.update_layout(barmode="group", yaxis2=dict(overlaying="y", side="right", showgrid=False, ticksuffix="x",
                                                   tickfont=dict(color=MUT, size=10)),
                      legend=dict(orientation="h", y=1.16, x=0))
    fig = _layout(fig, height, legend=True, margin=dict(l=36, r=40, t=26, b=4))
    fig.update_layout(yaxis=dict(side="left"))
    return fig


def timing_html(t):
    if not t:
        return '<div class="muted">Not enough price history to date the cycle.</div>'
    ph = t.get("phase", "—")
    pc = DOWN if ("Late" in ph or "down" in ph.lower()) else UP if ("Early up" in ph or "Bottoming" in ph) else WARN
    nxt = t.get("next_turn", "turn")
    if t.get("window"):
        w = t["window"]
        when = f'{_mon(w[0])} – {_mon(w[1])}'
        src = "price cycle and earnings path agree" if (t.get("window_price") and t.get("window_earnings")
                                                       and t.get("agree")) else \
            ("price-cycle statistics" if t.get("window_price") else "analyst earnings path")
    else:
        when, src = "no single window", "the two signals disagree"
    h = (f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><span class="panel-title">'
         f'Cycle Position &amp; Timing</span><span class="badge" style="color:{pc};background:{pc}1F">{esc(ph)}</span>'
         f'<span class="muted small" style="margin-left:auto">confidence: {esc(t.get("confidence", "low"))}</span></div>'
         f'<div class="plan" style="margin-top:10px"><div class="tile"><span class="k">Next {esc(nxt)} (price)</span>'
         f'<span class="v">{esc(when)}</span><span class="muted small">{esc(src)}</span></div>')
    et = t.get("earnings_turn")
    if et:
        h += (f'<div class="tile"><span class="k">Earnings {esc(et["kind"])} (analyst path)</span>'
              f'<span class="v">FY{et["fy"]}</span><span class="muted small">price usually turns 3–9 months '
              f'earlier</span></div>')
    h += '</div>'
    if not t.get("window") and (t.get("window_price") or t.get("window_earnings")):
        bits = []
        if t.get("window_price"):
            bits.append(f'price-cycle statistics: {_mon(t["window_price"][0])} – {_mon(t["window_price"][1])}')
        if t.get("window_earnings"):
            bits.append(f'earnings path: {_mon(t["window_earnings"][0])} – {_mon(t["window_earnings"][1])}')
        h += f'<div class="muted small">{esc(" · ".join(bits))}</div>'
    h += '<div class="greason" style="margin-top:8px">' + "".join(
        f"<div>• {esc(x)}</div>" for x in t.get("evidence", [])) + "</div>"
    h += ('<div class="muted small" style="margin-top:8px">A statistical estimate, not a forecast: cycles vary '
          'in length, so read it as a range. Upswings in the price usually end before earnings peak.</div>')
    return h


def render_value_model(b, sym):
    d, f, r, an = b["d"], b["f"], b["r"], b["an"]
    price = d["last"]
    dec = pdec(sym, price)
    cls, cp, wc = b["cls"], b["capm"], b["wacc"]
    ke, wacc = cp["ke"], wc["wacc"]
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">02</span><h3>Valuation Model</h3>'
      '<span class="muted">Methods chosen by company type · discount rate from CAPM</span></div>')
    c1, c2 = st.columns([1.55, 1], gap="medium")
    with c1:
        with st.container(border=True):
            vt = vtype_choice(b, sym)
            col_ = VT_COLOR.get(vt, ACCENT)
            auto = vt == cls["type"]
            H(f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:2px">'
              f'<span class="badge" style="color:{col_};background:{col_}1F;font-size:12.5px">{esc(en.VTYPES[vt])}</span>'
              f'<span class="muted small">{"classified from " + esc(cls["source"]) + " · confidence " + esc(cls["confidence"]) if auto else "set by you · auto would be " + esc(cls["label"])}</span></div>'
              f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">'
              + "".join(f'<span class="chip">{esc(x)}</span>' for x in cls["facts"]) + '</div>'
              + "".join(f'<div class="muted small" style="margin-top:6px">↳ {esc(x)}</div>' for x in cls["reasons"])
              + f'<div class="planrow" style="margin-top:10px"><span class="l">Cost of equity (CAPM)</span>'
              f'<span class="v">{tr(ke, 1)}% = {tr(cp["rf"], 2)}% + {tr(cp["beta"], 2)} × {tr(cp["erp"], 1)}%</span></div>'
              f'<div class="muted small">US 10Y yield{" (live)" if b.get("rf_src") == "real" else " (default — live rate unavailable)"} '
              f'+ beta × equity risk premium · WACC {tr(wacc, 1)}% '
              f'({tr(wc["we"] * 100, 0)}% equity, debt at {tr(wc["kd"], 1)}% before tax)</div>')
    # yöntemler
    st_ = vp_state(b, sym)
    kw = vp_kwargs(b, st_)
    path = None
    if en._ok(b.get("eps_last")):
        path = build_path(b, kw, price)
    extra, pbpos, ms, checks = {}, None, [], []
    if vt == "cyclical":
        ms.append(en.normalized_earnings(f, an, en._shares(f, d), ke))
        m_pb, pbpos = en.pb_roe(f, ke, price, b["px"])
        ms.append(m_pb)
        checks = en.cyclical_checks(f, r, b.get("timing"), pbpos)
    elif vt == "defensive":
        ms, checks = en.defensive_models(f, r, an, d, b.get("divst"), b["band"], ke, wacc, price)
    elif vt == "growth":
        ms, checks, extra = en.growth_models(sym, f, r, an, d, b["vals"], b["peers"], wacc, price)
    else:
        ms, checks, extra = en.capital_models(f, r, d, b["pm"], b["px"], wacc, price, an)
    ms = [m for m in ms if m]
    if path:
        r1 = path["rows"][1] if len(path["rows"]) > 1 else path["rows"][0]
        pm_ = en._method("path", f"Market-implied path ({r1['label']})", r1["value"]["bear"], r1["value"]["base"],
                         r1["value"]["bull"], f"{r1['label']} EPS × today's multiple — reference only, "
                         "not in the blend", 0.0)
        if pm_:
            ms.append(pm_)
    bl = en.blend(ms, price)
    with c2:
        with st.container(border=True):
            H('<div class="panel-title">Blended Fair Value</div>')
            if bl:
                up = bl.get("upside", 0.0)
                H(f'<div style="display:flex;align-items:baseline;gap:10px;margin-top:6px">'
                  f'<span class="mono" style="font-size:30px;font-weight:600">{tr(bl["value"], dec)}</span>'
                  f'<span class="mono" style="color:{col(up)};font-weight:700">{pct(up)}</span></div>'
                  f'<div class="muted small">range {tr(bl["low"], dec)} – {tr(bl["high"], dec)} · today {tr(price, dec)}</div>'
                  + "".join(f'<div class="planrow"><span class="l">{esc(k)}</span><span class="v">{v}%</span></div>'
                            for k, v in bl["weights"].items()))
                if en._ok(an.get("target_mean")):
                    H(f'<div class="muted small" style="margin-top:6px">Analyst mean target {tr(an["target_mean"], dec)}'
                      f' ({pct((an["target_mean"] / price - 1) * 100)})</div>')
            elif any(m.get("excluded") for m in ms):
                H('<div class="muted" style="margin-top:6px">Every method landed more than 6× away from today\'s '
                  'price, which points to unreliable inputs for this stock — no blended value is shown.</div>')
            else:
                H('<div class="muted" style="margin-top:6px">Not enough data for the methods of this type. '
                  'Try another model type above.</div>')
    c3, c4 = st.columns([1.3, 1], gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Methods</div>')
            rows = ""
            for m in ms:
                up = (m["base"] / price - 1) * 100
                rows += (f'<tr><td><b>{esc(m["name"])}</b><div class="muted small" style="white-space:normal;'
                         f'max-width:330px">{esc(m["note"])}</div></td>'
                         f'<td style="color:{SOFT}">{tr(m["low"], dec)}</td><td>{tr(m["base"], dec)}</td>'
                         f'<td style="color:{SOFT}">{tr(m["high"], dec)}</td>'
                         f'<td style="color:{col(up)}">{pct(up)}</td>'
                         f'<td style="color:{MUT}">{"excluded" if m.get("excluded") else (str(bl["weights"].get(m["name"], 0)) + "%") if (bl and m["weight"]) else "—"}</td></tr>')
            H(f'<div style="overflow-x:auto"><table class="ptab"><thead><tr><th>Method</th><th>Low</th><th>Base</th>'
              f'<th>High</th><th>vs price</th><th>Weight</th></tr></thead><tbody>{rows}</tbody></table></div>'
              if rows else '<div class="muted">No method could be calculated.</div>')
            if any(m.get("excluded") for m in ms):
                H('<div class="muted small" style="margin-top:6px">“excluded”: the result is more than 6× away '
                  'from today\'s price, which usually means a broken input — it is not used in the blend.</div>')
            if vt == "growth" and extra.get("reverse"):
                rv = extra["reverse"]
                txt = (f'Today\'s price implies starting revenue growth of <b>{tr(rv["growth"], 1)}%</b> (fading to '
                       f'{tr(en.G_TERM, 0)}% over 10 years) at a {tr(extra.get("target_margin"), 0)}% FCF margin.')
                if rv.get("capped") == "above":
                    txt = f'Today\'s price implies more than {tr(rv["growth"], 0)}% starting revenue growth.'
                elif rv.get("capped") == "below":
                    txt = "Today's price implies shrinking revenue."
                if en._ok(extra.get("g0")):
                    txt += f' Expected growth right now: {tr(extra["g0"], 1)}%.'
                H(f'<div class="gtext">{txt}</div>')
            if vt == "defensive" and not (b.get("divst") or {}).get("d0"):
                H('<div class="muted small" style="margin-top:6px">No dividend — the dividend methods are skipped.</div>')
    with c4:
        with st.container(border=True):
            title = {"cyclical": "Cycle Checks", "defensive": "Growth, Margins &amp; Dividend Safety",
                     "growth": "Growth Quality", "capital": "Debt, Profit Growth &amp; Consistency"}[vt]
            H(f'<div class="panel-title">{title}</div>' + checks_html(checks))
    # tipe özel grafik
    if vt == "cyclical":
        c5, c6 = st.columns([1, 1.35], gap="medium")
        with c5:
            with st.container(border=True):
                H(timing_html(b.get("timing")))
        with c6:
            with st.container(border=True):
                H('<div class="panel-title">Price Cycles</div><div class="muted small">Weekly closes (log scale) · '
                  'past peaks and troughs · orange band: estimated window for the next turn (purple: earnings-path '
                  'window when the two disagree)</div>')
                if b.get("wk") is not None and len(b["wk"]) > 60:
                    plot(cycle_fig(b["wk"], b.get("timing")), key="v_type")
                else:
                    H('<div class="muted">Not enough price history.</div>')
    elif vt == "defensive":
        ds = b.get("divst") or {}
        if ds.get("yield_series") is not None:
            with st.container(border=True):
                H('<div class="panel-title">Dividend Yield vs Its History</div><div class="muted small">Trailing '
                  '12-month yield · higher than usual = cheaper · dotted line: US 10Y yield</div>')
                plot(yield_fig(ds, b.get("tnx_w")), key="v_type")
    elif vt == "growth" and extra.get("path"):
        with st.container(border=True):
            H('<div class="panel-title">Target-Margin DCF Path</div><div class="muted small">Projected revenue '
              'and free-cash-flow margin used in the DCF</div>')
            plot(growth_proj_fig(extra["path"], f["years"][-1], en._last_ok(f["revenue"])), key="v_type")
    elif vt == "capital":
        with st.container(border=True):
            H('<div class="panel-title">Profits vs Debt</div><div class="muted small">EBITDA and total debt by '
              'year · line: net debt ÷ EBITDA</div>')
            plot(debt_fig(f), key="v_type")
    with st.expander("Value path (revenue · margin · debt · capex model), sensitivity & DCF",
                     expanded=(vt == "cyclical")):
        render_value_future(b)


DRV_SRC = {"analyst": "analyst", "override": "your input", "upswing": "upswing", "downturn": "post-peak",
           "recovery": "recovery", "model": "long-term", "held": "held ≥ prior", "capped": "below peak"}


def render_model_drivers(b, path, sel_fy, dec):
    """Sürücü tablosu: ciro → marj → faiz → net kâr → hisse → EPS → capex / FCF / net borç → değer."""
    dv = path["drivers"]
    base = dv["base"]
    hist = b["dhist"] or {}
    cur = b["d"].get("currency") or "USD"
    rows_fy = path["rows"]
    n = len(rows_fy)
    ac = st.session_state.get(f"vdrv_scen_{b['d'].get('ticker') or ACTIVE}") or "Base"

    def cells(vals, fmt, colorize=False):
        out = ""
        for k in range(n):
            v = vals[k] if k < len(vals) else None
            ok = en._ok(v)
            st_ = ""
            if colorize and ok:
                st_ = f' style="color:{col(v)}"'
            out += f'<td class="{"qsel" if rows_fy[k]["fy"] == sel_fy else ""}"{st_}>{fmt(v) if ok else "—"}</td>'
        return out

    with st.container(border=True):
        t1, t2 = st.columns([3, 1.2], vertical_alignment="center")
        with t1:
            H('<div class="panel-title">Model Drivers</div><div class="muted small">How each year\'s value is built. '
              'Analyst years: revenue and EPS follow consensus and the margin is the one that produces it. Later '
              'years: your growth and margin inputs. Interest = net debt × cost of debt (net cash earns the '
              'risk-free rate); FCF = net income + D&A − capex − working capital; part of FCF reduces net debt, '
              'the rest goes to dividends.</div>')
        with t2:
            seg("Scenario", ["Bear", "Base", "Bull"], f"vdrv_scen_{b['d'].get('ticker') or ACTIVE}", "Base")
        ac = st.session_state.get(f"vdrv_scen_{b['d'].get('ticker') or ACTIVE}") or "Base"
        sc = dv.get(ac.lower()) or base
        m_ = lambda x: big(x, cur)
        p1 = lambda x: f"{tr(x, 1)}%"
        head = "".join(f'<th class="{"qsel" if r["fy"] == sel_fy else ""}">{r["label"]}</th>' for r in rows_fy)
        last_rev = hist.get("rev_last")
        eps_prev = [hist.get("eps_last")] + list(sc["eps"][:-1])
        eps_yoy = [((e / p - 1) * 100) if (en._ok(p) and p > 0 and en._ok(e)) else None
                   for e, p in zip(sc["eps"], eps_prev)]
        val_key = {"Bear": "bear", "Base": "base", "Bull": "bull"}[ac]
        src_row = "".join(
            f'<td class="{"qsel" if rows_fy[k]["fy"] == sel_fy else ""}"><span class="muted" style="font-size:10.5px">'
            f'{esc(DRV_SRC.get(sc["src"][k], sc["src"][k]))}</span></td>' for k in range(n))
        lines = [
            ("Revenue", f'<td class="muted">{m_(last_rev) if en._ok(last_rev) else "—"}</td>' + cells(sc["rev"], m_)),
            ("Revenue growth (YoY)", f'<td class="muted">{p1(hist.get("g_rev_last")) if en._ok(hist.get("g_rev_last")) else "—"}</td>'
             + cells(sc["growth"], lambda x: pct(x, 1), True)),
            ("Source", '<td></td>' + src_row),
            ("Operating margin", f'<td class="muted">{p1(hist.get("op_m_last")) if en._ok(hist.get("op_m_last")) else "—"}</td>'
             + cells(sc["op_m"], p1)),
            ("EBIT", '<td></td>' + cells(sc["ebit"], m_)),
            ("Net interest (+ income / − cost)", '<td></td>' + cells([-x for x in sc["interest"]], m_, True)),
            ("Net income", '<td></td>' + cells(sc["ni"], m_)),
            ("Shares", f'<td class="muted">{big(hist.get("shares0"), "") if en._ok(hist.get("shares0")) else "—"}</td>'
             + cells(sc["shares"], lambda x: big(x, ""))),
            ("EPS", f'<td class="muted">{tr(hist.get("eps_last"), 2) if en._ok(hist.get("eps_last")) else "—"}</td>'
             + cells(sc["eps"], lambda x: tr(x, 2))),
            ("EPS growth (YoY)", '<td></td>' + cells(eps_yoy, lambda x: pct(x, 1), True)),
            ("Capex", '<td></td>' + cells(sc["capex"], m_)),
            ("Free cash flow", '<td></td>' + cells(sc["fcf"], m_)),
            ("Net debt (− = net cash)", f'<td class="muted">{m_(hist.get("net_debt0")) if en._ok(hist.get("net_debt0")) else "—"}</td>'
             + cells(sc["net_debt"], m_)),
            ("Net debt / EBITDA", '<td></td>' + cells(sc["nd_ebitda"], lambda x: f"{tr(x, 1)}x")),
            ("Value · P/E", '<td></td>' + cells(sc["value_pe"], lambda x: tr(x, dec))),
            ("Value · EV/EBIT", '<td></td>' + cells(sc["value_ev"], lambda x: tr(x, dec))),
            (f"Value ({path['lens']})", f'<td class="muted">{tr(b["d"]["last"], dec)}</td>'
             + cells([r["value"][val_key] for r in rows_fy], lambda x: f"<b>{tr(x, dec)}</b>")),
        ]
        body = "".join(f'<tr><td class="lbl">{esc(lb) if "<" not in lb else lb}</td>{cs}</tr>' for lb, cs in lines)
        H(f'<div class="dtab-wrap"><table class="ptab dtab"><thead><tr><th></th><th class="muted">Last FY · today</th>'
          f'{head}</tr></thead><tbody>{body}</tbody></table></div>')
        a = path.get("assump") or {}
        H(f'<div class="muted small" style="margin-top:6px">Assumptions: tax {tr(a.get("tax"), 1)}% · shares '
          f'{pct(a.get("share_chg"), 1)}/yr · capex {tr(a.get("capex_pct"), 1)}% and D&A {tr(a.get("da_pct"), 1)}% '
          f'of revenue · cost of debt {tr(a.get("kd"), 1)}%, cash yield {tr(a.get("rf"), 1)}% · '
          f'{tr(a.get("payout"), 0)}% of free cash flow paid out, the rest reduces net debt · working capital '
          f'5% of the revenue change.</div>')


def render_value_future(b):
    d, an = b["d"], b["an"]
    sym = d.get("ticker") or ACTIVE
    dec = pdec(sym, d["last"])
    H('<div class="muted small" style="margin-bottom:6px">' + (
        'Revenue growth → operating margin → interest on net debt → tax → share count → EPS, with capex, free '
        'cash flow and net debt rolled forward · valued on P/E and/or EV/EBIT · three scenarios. '
        if b.get("dhist") else 'Analyst EPS estimates → cycle → forward multiple · three scenarios. ')
      + 'This path assumes the market keeps pricing the stock the way it does today, so it is shown for reference '
        'and not used in the blended fair value.</div>')
    if not en._ok(b.get("eps_last")):
        H('<div class="muted">No EPS data, so a target value could not be calculated.</div>')
        return
    cfg = value_cfg(b, sym)
    est = an.get("fy") or []
    path = build_path(b, cfg)
    if not path:
        H('<div class="muted">This fiscal year\'s earnings are negative, so a multiple-based value cannot be '
          'built.</div>')
        return
    b["path"] = path
    try:
        qd = md.get_quarterly(sym)
    except Exception:
        qd = {"src": "none", "q": [], "est": {}}
    qp = en.quarter_path(path, qd, b.get("px"))
    # çeyrek seçimi (panel aşağıda; grafik bu seçimi şimdiden vurgular)
    fy_opts = [fy for fy in qp["fy_list"] if fy >= path["fy0"] or any(
        x["src"] == "reported" for x in qp["by_fy"][fy])]
    k_fy, k_q = f"vq_fy_{sym}", f"vq_q_{sym}"
    fy_lab = {fy: (f"FY{fy} · reported" if fy < path["fy0"] else f"FY{fy}") for fy in fy_opts}
    lab_fy = {v: k for k, v in fy_lab.items()}
    if ss.get(k_fy) not in lab_fy:
        ss[k_fy] = fy_lab[path["fy0"]]
    Q_OPTS = ["Full year", "Q1", "Q2", "Q3", "Q4"]
    if ss.get(k_q) not in Q_OPTS:
        ss[k_q] = "Full year"
    sel_fy = lab_fy[ss[k_fy]]
    sel_q = None if ss[k_q] == "Full year" else int(ss[k_q][1])
    c1, c2 = st.columns([1.7, 1], gap="medium")
    with c1:
        with st.container(border=True):
            n_an = an.get("n") or max([e.get("n") or 0 for e in est] or [0])
            src = (f'{", ".join(e["label"] for e in est)} analyst estimates'
                   f'{" (" + str(n_an) + " analysts)" if n_an else ""}'
                   if est else "No analyst estimates — using the last reported YoY EPS growth")
            mtxt = (f'multiple calibrated to today\'s price: <b>{tr(path["m_cal"], 1)}x</b> FY{path["fy0"]} earnings'
                    if not path["rerated"] else
                    f'multiple {tr(path["m_cal"], 1)}x → <b>{tr(path["m_target"], 1)}x</b> over 3 years'
                    + (" after the peak" if path["cyclical"] else ""))
            drv = path.get("drivers")
            if drv:
                rv_n = len([e for e in (an.get("rev_fy") or []) if en._ok(e.get("avg"))])
                src = (f'revenue: {rv_n} analyst year{"s" if rv_n != 1 else ""}, then your growth inputs · '
                       f'EPS anchored to {len(est)} analyst year{"s" if len(est) != 1 else ""}'
                       f'{" (" + str(n_an) + " analysts)" if n_an else ""}' if (rv_n or est) else
                       'no analyst estimates — revenue grows at your yearly inputs')
                ev_t = (f', EV/EBIT {tr(path["ev_cal"], 1)}x' if path.get("ev_cal") else "")
                mtxt = (f'{esc(path["lens"])} lens · calibrated to today\'s price: P/E <b>{tr(path["m_cal"], 1)}x</b>{ev_t}'
                        + (f' → P/E {tr(path["m_target"], 1)}x over 3 years' if path["rerated"] else ""))
            H(f'<div class="panel-title">Value Path</div><div class="muted small">{esc(src)} · {mtxt}'
              f'{" · earnings peak FY" + str(path["peak_fy"]) + ", then a " + tr(path["drop"], 0) + ("% revenue drop" if drv else "% drop") if path["cyclical"] else ""}'
              f'</div>')
            plot(fair_path_chart(path, b["px"], d["last"], qp, sel_fy, sel_q), key="v_path")
            sc = path["scen"]
            if drv:
                H(f'<div class="muted small">Each fiscal year is valued on <i>that year\'s</i> modelled EPS and EBIT: '
                  f'P/E value = EPS × P/E, EV/EBIT value = (EBIT × EV/EBIT − net debt) ÷ shares'
                  f'{" — the chart shows their average" if path["lens"] == "Blend" else ""}. Bear: lowest analyst '
                  f'estimates, growth lower by 3 pts or 30% of the rate (whichever is more), model margins −10%'
                  f'{", a 25% deeper revenue drop" if path["cyclical"] else ""}, multiple −15% · Bull: the '
                  f'opposite. Dotted line: quarter by quarter (TTM EPS × multiple).</div>')
            else:
                H(f'<div class="muted small">Each fiscal year is valued on <i>that year\'s</i> EPS × the multiple; '
              f'after the analyst years EPS grows year over year (base {tr(sc["base"]["g"], 0)}% YoY). '
              f'Bear: lowest analyst estimate'
              f'{", " + tr(sc["bear"]["drop"], 0) + "% post-peak drop" if path["cyclical"] else ""}, '
              f'then {tr(sc["bear"]["g"], 0)}% YoY, multiple −15% · Bull: highest estimate'
              f'{", " + tr(sc["bull"]["drop"], 0) + "% drop" if path["cyclical"] else ""}, '
              f'then {tr(sc["bull"]["g"], 0)}% YoY, multiple +15%. Dotted line: quarter by quarter (TTM EPS × '
              f'multiple).</div>')
            pk_y, pk_v = path["price_peak_year"], path["price_peak_value"]
            up = (pk_v / d["last"] - 1) * 100
            if path["cyclical"]:
                notes = []
                if path.get("overridden"):
                    ov = [y for y in path["overridden"] if y > path["peak_fy"]]
                    hd = [y for y in path["overridden"] if y <= path["peak_fy"]]
                    if ov:
                        notes.append("analyst estimates for " + ", ".join(f"FY{y}" for y in ov) +
                                     " are replaced by the post-peak path")
                    if hd:
                        notes.append(", ".join(f"FY{y}" for y in hd) + " held at least at the prior year")
                if path.get("capped"):
                    notes.append("the multiple change would have pushed " +
                                 ", ".join(f"FY{y}" for y in path["capped"]) + " above the peak, so those values "
                                 "are capped just below it")
                H(f'<div class="gtext">In the base case the value peaks in <b>FY{pk_y}</b> — the earnings-peak year '
                  f'you selected — at <b>{tr(pk_v, dec)}</b> ({pct(up)} vs today), then follows earnings down.'
                  + (f' <span class="muted">Note: {esc("; ".join(notes))}.</span>' if notes else "") + '</div>')
            else:
                H(f'<div class="gtext">The base-case value is highest in <b>FY{pk_y}</b> at <b>{tr(pk_v, dec)}</b> '
                  f'({pct(up)} vs today).</div>')
    with c2:
        with st.container(border=True):
            H('<div class="panel-title">Year by Year</div>')
            rows = ""
            for row in path["rows"]:
                up_ = row.get("upside")
                yy = row.get("yoy")
                rows += (f'<tr class="{"qsel" if row["fy"] == sel_fy else ""}"><td>{row["label"]}</td>'
                         f'<td><b>{tr(row["value"]["base"], dec)}</b><div class="muted" style="font-size:10.5px">'
                         f'{tr(row["value"]["bear"], dec)} – {tr(row["value"]["bull"], dec)}</div></td>'
                         f'<td style="color:{col(yy) if yy is not None else MUT}">{pct(yy) if yy is not None else "—"}</td>'
                         f'<td style="color:{col(up_) if up_ is not None else MUT}">'
                         f'{pct(up_) if up_ is not None else "—"}</td>'
                         f'<td style="color:{MUT}">{tr(row["mult"]["base"], 1)}x</td></tr>')
            H(f'<table class="ptab"><thead><tr><th>FY</th><th>Value <span class="muted" style="font-weight:400">'
              f'base · bear–bull</span></th><th>YoY</th><th>vs today</th><th>P/E</th></tr></thead>'
              f'<tbody>{rows}</tbody></table>')
            erows = ""
            tagmap = {"analyst": ('analyst', "#6EE7B7"), "held": ("held", "#F5B544"),
                      "post-peak": ("post-peak", "#F5B544"), "capped": ("post-peak", "#F5B544"),
                      "downturn": ("post-peak", "#F5B544"), "override": ("your growth", "#93C5FD"),
                      "upswing": ("upswing", "#93C5FD"), "recovery": ("recovery", "#93C5FD")}
            for e in path["eps_rows"]:
                g_ = e.get("growth")
                tg = tagmap.get(e["src"])
                tag = (f'<span class="badge" style="color:{tg[1]};background:{tg[1]}1F">{tg[0]}</span>' if tg
                       else '<span class="muted small">model</span>')
                erows += (f'<tr><td>{e["label"]}</td><td><b>{tr(e["eps"]["base"], 2)}</b><div class="muted" '
                          f'style="font-size:10.5px">{tr(e["eps"]["bear"], 2)} – {tr(e["eps"]["bull"], 2)}</div></td>'
                          f'<td style="color:{col(g_) if g_ is not None else MUT}">'
                          f'{pct(g_) if g_ is not None else "—"}</td><td>{tag}</td></tr>')
            H(f'<div class="panel-title" style="margin-top:12px">EPS (fiscal year)</div>'
              f'<table class="ptab"><thead><tr><th>FY</th><th>EPS <span class="muted" style="font-weight:400">'
              f'base · bear–bull</span></th><th>YoY</th><th></th></tr></thead><tbody>{erows}</tbody></table>'
              f'<div class="muted small" style="margin-top:6px">Start: last fiscal-year EPS '
              f'{tr(path["eps_last"], 2)}. YoY = change vs the previous fiscal year (first value row: vs today\'s '
              f'price). ' + (f'FY{path["fy0"]} value ≈ today\'s price, because both multiples are calibrated to it.'
                             if path.get("drivers") else
                             f'FY{path["fy0"]} value = today\'s price, because the multiple is calibrated to it.')
              + '</div>')
    if path.get("drivers"):
        render_model_drivers(b, path, sel_fy, dec)
    # çeyrek çeyrek
    with st.container(border=True):
        H(f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">'
          f'<span class="panel-title">Quarter by Quarter</span><span class="muted small">pick a fiscal year, then '
          f'a quarter · grey = reported, blue = analyst estimate, light blue = model estimate'
          f'{" · quarterly data: " + ("Yahoo Finance" if qp.get("src") == "real" else "not available — all quarters are model estimates") }'
          f'</span></div>')
        f1, f2 = st.columns([1.6, 1.1], vertical_alignment="center")
        with f1:
            seg("Fiscal year", [fy_lab[fy] for fy in fy_opts], k_fy, fy_lab[path["fy0"]])
        with f2:
            seg("Quarter", Q_OPTS, k_q, "Full year")
        sel_fy = lab_fy.get(ss.get(k_fy), path["fy0"])
        sel_q = None if ss.get(k_q, "Full year") == "Full year" else int(ss[k_q][1])
        render_quarters(b, path, qp, sym, dec, sel_fy, sel_q)
    sens = None
    try:
        key = "drop" if cfg["cyclical"] else "g_lt"
        base_v = cfg[key]
        rv = ([max(0.0, min(90.0, base_v + dlt)) for dlt in (-20, -10, 0, 10, 20)] if key == "drop"
              else [round(base_v + dlt, 1) for dlt in (-6, -3, 0, 3, 6)])
        rv = list(dict.fromkeys(rv))
        m0 = path["m_target"]
        mults = [round(m0 * k, 1) for k in (0.7, 0.85, 1.0, 1.15, 1.3)]
        kw = _model_kwargs(cfg)
        kw.pop("target_mult", None)
        if path.get("drivers"):
            sens = en.driver_sensitivity(d["last"], b["dhist"], an, kw, rv, mults, 5)
        else:
            for k in ("g_up", "m_target", "m_peak", "m_trough", "share_chg", "capex_pct", "lens", "g_over"):
                kw.pop(k, None)
            sens = en.value_sensitivity(d["last"], b["eps_last"], est, kw, rv, mults, 5)
    except Exception:
        sens = None
    b["sens"] = sens
    c3, c4 = st.columns([1.3, 1], gap="medium")
    with c3:
        with st.container(border=True):
            lab = (("revenue drop after peak" if path.get("drivers") else "post-peak drop")
                   if (sens and sens["key"] == "drop") else "long-term growth (YoY)")
            H(f'<div class="panel-title">Sensitivity</div><div class="muted small">'
              f'Base value {sens["years"] if sens else 5} years out — rows: {lab}, columns: target P/E'
              f'{" (EV/EBIT moves in the same proportion)" if path.get("drivers") else ""}</div>')
            if sens:
                head = "".join(f"<th>{tr(m, 1)}x</th>" for m in sens["multiples"])
                body = ""
                for g, row in zip(sens["rows"], sens["grid"]):
                    cells = ""
                    for v in row:
                        if not en._ok(v):
                            cells += f'<td style="color:{MUT}">—</td>'
                            continue
                        up = (v / d["last"] - 1) * 100
                        c_ = UP if up >= 25 else WARN if up >= 0 else DOWN
                        cells += f'<td style="color:{c_}">{tr(v, 0)}</td>'
                    body += f'<tr><td>{tr(g, 0)}%</td>{cells}</tr>'
                H(f'<table class="ptab"><thead><tr><th>{"Drop" if sens["key"] == "drop" else "Growth"}</th>'
                  f'{head}</tr></thead><tbody>{body}</tbody></table>')
            else:
                H('<div class="muted">Could not be calculated.</div>')
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Discounted Cash Flow</div>')
            dv, rd = b["dcf"], b["rdcf"]
            if dv:
                up = (dv["value"] / d["last"] - 1) * 100
                H(f'<div class="plan"><div class="tile"><span class="k">DCF value</span>'
                  f'<span class="v">{tr(dv["value"], dec)}</span></div>'
                  f'<div class="tile"><span class="k">Versus today</span>'
                  f'<span class="v" style="color:{col(up)}">{pct(up)}</span></div></div>'
                  f'<div class="muted small">{tr(dv["discount"], 1)}% discount · {tr(dv["terminal"], 1)}% '
                  f'terminal growth · starting growth {tr(dv["growth"], 1)}%, fading to terminal over 10 years · '
                  f'{tr(dv["terminal_share"], 0)}% of the value comes from the terminal value.</div>')
                if b.get("is_cyc"):
                    H('<div class="muted small" style="margin-top:4px">For a cyclical company the starting cash flow '
                      'depends on where it is in the cycle — read the DCF together with the path above.</div>')
            else:
                H('<div class="muted small">Free cash flow is not positive, so no DCF could be built.</div>')
            if rd:
                g0 = rd["growth"]
                cap = rd.get("capped")
                txt = (f'Today\'s price implies <b>{tr(g0, 1)}%</b> annual free cash flow growth '
                       f'over the next 10 years.')
                if cap == "above":
                    txt = (f'Today\'s price implies cash flow growth <b>above</b> {tr(g0, 0)}% '
                           f'— outside this range.')
                elif cap == "below":
                    txt = f'Today\'s price implies shrinking cash flow (below {tr(g0, 0)}%).'
                real = b["r"].get("fcf_cagr")
                if en._ok(real) and not cap:
                    fark = "above" if g0 > real else "below"
                    txt += (f' The company\'s actual free cash flow growth in recent years was '
                            f'{tr(real, 1)}% — the market expectation is {fark} that.')
                H(f'<div class="gtext">{txt}</div>')
    c5, c6 = st.columns(2, gap="medium")
    with c5:
        with st.container(border=True):
            H('<div class="panel-title">Earnings per Share: History and Projection</div>'
              '<div class="muted small">Bars are reported EPS · filled dot analyst estimate, hollow dot '
              'model</div>')
            plot(eps_proj_fig(b["f"], path), key="v_eps")
    with c6:
        with st.container(border=True):
            band, ps = b["band"], b.get("pe_ser")
            H('<div class="panel-title">Historical P/E Band</div><div class="muted small">Price ÷ that year\'s '
              'EPS — where today\'s multiple sits versus its own history</div>')
            if ps is not None and len(ps) > 20:
                hl = []
                if band:
                    hl = [(band["high"], f'90th pct · {tr(band["high"], 1)}x', DOWN),
                          (band["median"], f'median · {tr(band["median"], 1)}x', MUT),
                          (band["low"], f'10th pct · {tr(band["low"], 1)}x', UP)]
                plot(line_fig([("P/E", ps.index, ps.values, ACCENT, False, False)],
                              height=250, suffix="x", hlines=hl, legend=False), key="v_peband")
            else:
                H('<div class="muted" style="padding:20px 0">Not enough data for a P/E history.</div>')


_PEER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def parse_peers(txt, sym):
    out = []
    for t in re.split(r"[,\s;]+", str(txt or "").upper()):
        t = t.strip()
        if t and t != sym and _PEER_RE.match(t) and t not in out:
            out.append(t)
    return out[:8]


def render_peer_editor(b, sym):
    """Rakip listesi: kaynağını göster, kullanıcı değiştirebilsin."""
    ovr = (ss.get("peer_ovr") or {}).get(sym)
    names = []
    for t in b["peers"]:
        v = b["vals"].get(t) or {}
        nm = v.get("name") or md.company_name(t)
        names.append(f"{t} ({nm})" if nm and nm != t else t)
    H(f'<div class="muted small" style="margin:-4px 0 6px">Peer source: <b>{esc(b.get("peer_src") or "—")}</b>'
      f' · {esc(", ".join(names)) or "—"}</div>')
    with st.expander("Edit peers"):
        H('<div class="muted small">Separate with commas. Foreign exchanges use the Yahoo symbol: SK Hynix '
          '<span class="mono">000660.KS</span>, Samsung <span class="mono">005930.KS</span>, Nanya '
          '<span class="mono">2408.TW</span>, Kioxia <span class="mono">285A.T</span>. Market caps are '
          'converted to dollars. Companies that are not listed (e.g. CXMT) can\'t be added.</div>')
        wk = f"peer_txt_{sym}"
        if wk not in ss:
            ss[wk] = ", ".join(b["peers"])
        st.text_input("Peers", key=wk, label_visibility="collapsed")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Apply", key=f"peer_apply_{sym}", **_wkw(st.button)):
                lst = parse_peers(ss.get(wk), sym)
                po = dict(ss.get("peer_ovr") or {})
                if lst:
                    po[sym] = lst
                else:
                    po.pop(sym, None)
                ss.peer_ovr = po
                st.rerun()
        with c2:
            if st.button("Reset to default", key=f"peer_reset_{sym}", disabled=not ovr, **_wkw(st.button)):
                po = dict(ss.get("peer_ovr") or {})
                po.pop(sym, None)
                ss.peer_ovr = po
                ss.pop(wk, None)
                st.rerun()


def render_value_peers(b, sym):
    vals, peers, pm = b["vals"], b["peers"], b["pm"]
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">03</span>'
      '<h3>Versus Peers</h3><span class="muted">Above the line: expensive for its growth</span></div>')
    render_peer_editor(b, sym)
    if not peers:
        H('<div class="muted">Could not build a peer list for this symbol.</div>')
        return
    c1, c2 = st.columns([1, 1.25], gap="medium")
    with c1:
        with st.container(border=True):
            H('<div class="sec-head"><h3 style="font-size:15px">Growth / Multiple Map</h3>'
              '<span class="muted small" style="margin-left:auto">Circle size = market cap</span></div>')
            fig = peer_scatter(sym, vals, peers)
            if fig is not None:
                plot(fig, key="v_scatter")
                H('<div class="muted small">Horizontal: forward EPS growth (next fiscal-year estimate ÷ trailing 12 months) · '
                  'Vertical: forward P/E. The dashed line is the peers\' average trend.</div>')
            else:
                H('<div class="muted">Not enough peer data.</div>')
    with c2:
        with st.container(border=True):
            H('<div class="sec-head"><h3 style="font-size:15px">Multiples Comparison</h3>'
              '<span class="muted small" style="margin-left:auto">Coloured against the peer median</span>'
              '</div>')
            rows = ""
            for t in [sym] + list(peers):
                v = vals.get(t)
                if not v:
                    continue
                me = " me" if t == sym else ""
                nm = v.get("name") or ""
                nm = (nm[:16] + "…") if len(nm) > 17 else nm
                rows += (f'<tr class="{me.strip()}"><td><span style="display:flex;align-items:center;gap:9px">'
                         f'{avatar(t, 26, nm)}<span><b>{esc(t)}</b><div class="muted small">'
                         f'{esc(nm) + " · " if nm and nm != t else ""}{big(v.get("market_cap"), "USD")}</div>'
                         f'</span></span></td>'
                         + _cell(v.get("pe"), pm.get("pe"))
                         + _cell(v.get("fwd_pe"), pm.get("fwd_pe"))
                         + _cell(v.get("peg"), pm.get("peg"), 2)
                         + _cell(v.get("ev_ebitda"), pm.get("ev_ebitda"))
                         + _cell(v.get("growth"), pm.get("growth"), 0, False, "%")
                         + _cell(v.get("net_margin"), pm.get("net_margin"), 0, False, "%")
                         + "</tr>")
            med = ("<tr class='med'><td>Peer median</td>"
                   + "".join(f'<td>{tr(pm.get(k), 2 if k == "peg" else (0 if k in ("growth", "net_margin") else 1))}'
                             f'{"%" if k in ("growth", "net_margin") else ""}</td>'
                             for k in ("pe", "fwd_pe", "peg", "ev_ebitda", "growth", "net_margin"))
                   + "</tr>")
            H(f'<div style="overflow-x:auto"><table class="ptab"><thead><tr><th>Company</th><th>P/E</th>'
              f'<th>Fwd P/E</th><th>PEG</th><th>EV/EBITDA</th><th title="Analysts\' next fiscal-year EPS estimate ÷ trailing 12-month EPS">Fwd EPS growth</th><th>Net margin</th></tr></thead>'
              f'<tbody>{rows}{med}</tbody></table></div>')
            me = vals.get(sym, {})
            note = "Not enough peer multiples for a comparison."
            if en._ok(me.get("fwd_pe")) and en._ok(pm.get("fwd_pe")) and pm["fwd_pe"]:
                prem = (me["fwd_pe"] / pm["fwd_pe"] - 1) * 100
                if abs(prem) < 3:
                    note = f"{sym} trades at about the same multiple as the peer median."
                else:
                    yon = "premium" if prem > 0 else "discount"
                    note = f"{sym} trades at a {tr(abs(prem), 0)}% {yon} to the peer median."
                    if en._ok(me.get("growth")) and en._ok(pm.get("growth")):
                        daha = me["growth"] > pm["growth"]
                        note += (" The premium is partly justified — its growth is above the median." if (prem > 0 and daha)
                                 else " Its growth is below the median, so the premium points to an expensive stock."
                                 if (prem > 0 and not daha)
                                 else " It trades at a discount despite above-median growth — worth a closer look."
                                 if (prem < 0 and daha)
                                 else " The discount fits its low growth.")
            H(f'<div class="gtext">{esc(note)}</div>')
            band = b["band"]
            if band and band.get("pctile") is not None:
                H(f'<div class="planrow"><span class="l">Versus its own history</span>'
                  f'<span class="v">P/E {tr(band["current"], 1)} · {tr(band["pctile"], 0)}th percentile '
                  f'of recent years</span></div><div class="muted small">Band {tr(band["low"], 1)}x – '
                  f'{tr(band["high"], 1)}x, median {tr(band["median"], 1)}x '
                  f'({min(band["years"])}–{max(band["years"])}).</div>')
    names = [t for t in [sym] + list(peers) if vals.get(t)]
    c3, c4 = st.columns(2, gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Forward P/E Comparison</div><div class="muted small">Dashed '
              'line peer median · blue is the selected company</div>')
            order = sorted(names, key=lambda t: vals[t].get("fwd_pe") if en._ok(vals[t].get("fwd_pe")) else 1e9)
            plot(bar_fig(order, [("Fwd P/E", [vals[t].get("fwd_pe") for t in order],
                                  [ACCENT if t == sym else "#4A515C" for t in order])],
                         height=240, suffix="x", hline=pm.get("fwd_pe"), hl_label="median",
                         legend=False, text=True), key="v_pfwd")
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Growth and Net Margin</div><div class="muted small">Percent</div>')
            plot(bar_fig(names, [("Fwd EPS growth", [vals[t].get("growth") for t in names], ACCENT),
                                 ("Net margin", [vals[t].get("net_margin") for t in names], "#6EE7B7")],
                         height=240, suffix="%"), key="v_pgm")


def render_value_cycle(b):
    cyc, sea = b["cyc"], b["sea"]
    sym = b["d"].get("ticker") or ACTIVE
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">04</span>'
      '<h3>Cyclicality</h3><span class="muted">What happens when the market falls, how volatile earnings are</span>'
      '</div>')
    if not cyc:
        H('<div class="muted">Not enough price history.</div>')
        return
    px, bench = b.get("px"), b.get("bench")
    c1, c2 = st.columns([1, 1.15], gap="medium")
    with c1:
        with st.container(border=True):
            lab = cyc["label"]
            lc = DOWN if "High" in lab else WARN if lab == "Cyclical" else ACCENT if lab == "Mixed" else UP
            H(f'<div style="display:flex;align-items:center;gap:10px"><span class="panel-title">Profile</span>'
              f'<span class="badge" style="color:{lc};background:{lc}1F">{esc(lab)}</span></div>')
            tiles = [("Beta", tr(cyc.get("beta"), 2)),
                     ("Downside capture", f'{tr(cyc.get("down_capture"), 0)}%'),
                     ("Upside capture", f'{tr(cyc.get("up_capture"), 0)}%'),
                     ("Annual volatility", f'{tr(cyc.get("ann_vol"), 1)}%'),
                     ("Revenue growth volatility", f'{tr(cyc.get("rev_vol"), 1)}%'),
                     ("EPS growth volatility", f'{tr(cyc.get("eps_vol"), 1)}%'),
                     ("Max drawdown (3 yrs)", f'{tr(cyc.get("max_dd"), 1)}%'),
                     ("Years revenue shrank", str(cyc.get("rev_down_years", "—")))]
            H('<div class="vgrid">' + "".join(
                f'<div class="tile"><span class="k">{esc(k)}</span><span class="v">{v}</span></div>'
                for k, v in tiles) + "</div>")
            H('<div class="muted small" style="margin-top:8px">A downside capture above 100% means the stock '
              'falls harder than the index when the index falls. SPY is the reference.</div>')
            if cyc.get("drawdowns"):
                rows = ""
                for dd in cyc["drawdowns"][::-1]:
                    rows += (f'<div class="vrow"><span class="t">15%+ drawdown · {dd["bars"]} trading days</span>'
                             f'<span class="n" style="color:{DOWN}">{pct(dd["depth"])}</span>'
                             f'<span class="n">{"recovered" if dd["recovered"] else "ongoing"}</span></div>')
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin-top:12px">Recent drawdown '
                  f'periods</div>{rows}')
    with c2:
        with st.container(border=True):
            H(f'<div class="panel-title">{esc(sym)} and S&amp;P 500</div><div class="muted small">Last 3 years, '
              f'start = 100</div>')
            if px is not None and bench is not None and len(px) > 60 and len(bench) > 60:
                a_ = px["Close"].tail(756)
                b2 = bench["Close"].reindex(a_.index).ffill().dropna()
                a_ = a_.reindex(b2.index)
                if len(a_) > 30 and float(a_.iloc[0]) and float(b2.iloc[0]):
                    na, nb = a_ / float(a_.iloc[0]) * 100, b2 / float(b2.iloc[0]) * 100
                    plot(line_fig([(sym, na.index, na.values, ACCENT, False, False),
                                   ("S&P 500", nb.index, nb.values, "#8D96A5", True, False)],
                                  height=250, hlines=[(100, "start", "#3A404A")]), key="v_rel")
                    diff = float(na.iloc[-1] - nb.iloc[-1])
                    H(f'<div class="muted small">Over 3 years {esc(sym)} {pct(float(na.iloc[-1]) - 100)}, '
                      f'S&amp;P 500 {pct(float(nb.iloc[-1]) - 100)} — difference '
                      f'<b style="color:{col(diff)}">{tr(diff, 1)} points</b>.</div>')
            else:
                H('<div class="muted">Not enough data for a comparison.</div>')
    c3, c4 = st.columns([1.15, 1], gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Distance from Peak</div><div class="muted small">Each day, the loss versus the '
              'highest level up to that day — stock and index side by side</div>')
            if px is not None and len(px) > 60:
                ua = en.underwater(px["Close"].tail(756))
                ser = [(sym, ua.index, ua.values, DOWN, False, True)]
                if bench is not None and len(bench) > 60:
                    ub = en.underwater(bench["Close"].tail(756))
                    ser.append(("S&P 500", ub.index, ub.values, "#8D96A5", True, False))
                plot(line_fig(ser, height=230, suffix="%"), key="v_uw")
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Seasonality</div>')
            if sea:
                ms = sea["months"]
                labs = [MONTHS_TR[m["month"] - 1][:3] for m in ms]
                vals_ = [m["avg"] for m in ms]
                plot(bar_fig(labs, [("Average return", vals_,
                                     [UP if (v or 0) >= 0 else DOWN for v in vals_])],
                             height=200, suffix="%", hline=0, legend=False), key="v_season")
                best = max(ms, key=lambda m: m["avg"] if m["avg"] is not None else -99)
                worst = min(ms, key=lambda m: m["avg"] if m["avg"] is not None else 99)
                H(f'<div class="muted small">Average return by month over the last {sea["n_years"]} years</div>'
                  f'<div class="planrow" style="margin-top:8px"><span class="l">Strongest month</span>'
                  f'<span class="v" style="color:{UP}">{MONTHS_TR[best["month"] - 1]} '
                  f'{pct(best["avg"])} · {tr(best["win"], 0)}% positive</span></div>'
                  f'<div class="planrow"><span class="l">Weakest month</span>'
                  f'<span class="v" style="color:{DOWN}">{MONTHS_TR[worst["month"] - 1]} '
                  f'{pct(worst["avg"])} · {tr(worst["win"], 0)}% positive</span></div>'
                  f'<div class="muted small" style="margin-top:6px">Seasonality alone is not a signal; '
                  f'it misleads when the sample is small.</div>')
            else:
                H('<div class="muted">Not enough history.</div>')


def render_value_quality(b):
    fsc, zsc, cons = b["fsc"], b["zsc"], b["cons"]
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">05</span>'
      '<h3>Balance-Sheet Consistency</h3><span class="muted">Does it keep moving the same way over the years, can it carry its debt'
      '</span></div>')
    c1, c2 = st.columns([1, 1], gap="medium")
    with c1:
        with st.container(border=True):
            if fsc:
                fc = UP if fsc["score"] >= 7 else WARN if fsc["score"] >= 4 else DOWN
                H(f'<div style="display:flex;align-items:center;gap:10px"><span class="panel-title">'
                  f'Piotroski F-Score</span><span class="badge" style="color:{fc};background:{fc}1F">'
                  f'{fsc["score"]} / 9 · {esc(fsc["label"])}</span></div>')
                rows = ""
                for c in fsc["checks"]:
                    ic, cc, bg = ("✓", UP, UP_BG) if c["ok"] else ("✕", DOWN, DOWN_BG)
                    rows += (f'<div class="vrow"><span class="ic" style="color:{cc};background:{bg}">{ic}</span>'
                             f'<span class="t">{esc(c["t"])}</span>'
                             f'<span class="n">{esc(c["note"])}</span></div>')
                H(rows + '<div class="muted small" style="margin-top:8px">Nine checks: profitability, '
                         'leverage/liquidity and efficiency. 7+ is strong, 3 or less is weak.</div>')
            else:
                H('<div class="muted">The F-score needs statements for at least two years.</div>')
    with c2:
        with st.container(border=True):
            if zsc:
                zc = UP if zsc["zone"] == "Safe" else WARN if zsc["zone"] == "Grey zone" else DOWN
                H(f'<div style="display:flex;align-items:center;gap:10px"><span class="panel-title">'
                  f'Altman Z-Score</span><span class="badge" style="color:{zc};background:{zc}1F">'
                  f'{tr(zsc["z"], 2)} · {esc(zsc["zone"])}</span></div>'
                  f'<div class="muted small">above 2.99 safe · 1.81–2.99 grey zone · below that risky</div>'
                  + "".join(f'<div class="planrow"><span class="l">{esc(k)}</span>'
                            f'<span class="v">{tr(v, 2)}</span></div>'
                            for k, v in zsc["parts"].items()))
            if cons:
                cc = UP if cons["pct"] >= 80 else WARN if cons["pct"] >= 55 else DOWN
                H(f'<div style="display:flex;align-items:center;gap:10px;margin-top:14px">'
                  f'<span class="panel-title">Consistency</span>'
                  f'<span class="badge" style="color:{cc};background:{cc}1F">{cons["hit"]} / {cons["of"]} · '
                  f'{esc(cons["label"])}</span></div>')
                rows = ""
                for r in cons["rows"]:
                    ic, c_, bg = ("✓", UP, UP_BG) if r["ok"] else ("~", WARN, WARN_BG)
                    rows += (f'<div class="vrow"><span class="ic" style="color:{c_};background:{bg}">{ic}</span>'
                             f'<span class="t">{esc(r["t"])}</span>'
                             f'<span class="n">{r["hit"]}/{r["of"]} yrs</span></div>')
                H(rows)


try:
    main()
finally:
    _save_state()
