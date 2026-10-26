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

import copy
import html
import inspect
import json
import re
import secrets
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

st.set_page_config(page_title="Pulse — Market Dashboard", layout="wide", initial_sidebar_state="collapsed")

APP_VERSION = "3.6"
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


def plot(fig, config=None, key=None):
    st.plotly_chart(fig, config=config if config is not None else {"displayModeBar": False}, key=key,
                    **_wkw(st.plotly_chart))


def table(df, **kw):
    st.dataframe(df, hide_index=True, **_wkw(st.dataframe), **kw)


def button(label, key, primary=False, **kw):
    return st.button(label, key=key, type="primary" if primary else "secondary", **_wkw(st.button), **kw)


def toggle(label, key, help=None):
    """st.toggle eski Streamlit sürümlerinde yok — checkbox'a düşer."""
    fn = getattr(st, "toggle", None) or st.checkbox
    return fn(label, key=key, help=help)


def H(s):
    # Her zaman <div> ile başlat → Markdown bunu HTML bloğu olarak geçirir
    # (aksi halde metindeki $, *, _ karakterleri biçimlendirmeye dönüşebilir).
    head = s.lstrip()[:6]
    s = s if head.startswith(("<div", "<style")) else f"<div>{s}</div>"
    st.markdown(s, unsafe_allow_html=True)


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
           "vp_cfg", "peer_ovr", "vtype_ovr"] + WIDGET_KEYS


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
.srstrip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;padding-bottom:4px}
.srstrip .tile{padding:9px 10px;line-height:1.3}
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
                         ss.ch_type, height=height, rev=ss.ch_rev, key="pulse_chart")
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
}


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
    H('<div style="font-size:12px;font-weight:700;margin:12px 0 4px 0">Background theme</div>')
    names = [THEMES[k]["name"] for k in THEMES]
    cur = THEMES.get(ss.get("theme") or "gece", THEMES["gece"])["name"]
    picked = seg("Theme", names, "w_theme", cur)
    key = next((k for k, v in THEMES.items() if v["name"] == picked), "gece")
    if key != ss.get("theme"):
        ss.theme = key
        st.rerun()
    sw = "".join(f'<span title="{esc(v["name"])}" style="width:26px;height:26px;border-radius:8px;'
                 f'display:inline-block;border:2px solid {"#ECEEF1" if k == ss.theme else "transparent"};'
                 f'background:{v["bg"]};box-shadow:inset 0 0 0 1px {v["border"]}"></span>'
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
    lb, tf = range_controls("w_lb", "w_tf")
    full, bars, intr = chart_data(sym, tf, lb)
    df = full.tail(bars)
    note = ch.lookback_note(full, tf, lb, bars, intr)
    H(f'<div style="display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px;margin:10px 0 6px 0">'
      f'{period_stats(df, dec)}'
      f'<span class="muted">{esc(ch.LOOKBACKS[ch.norm_lb(lb)]["name"])} · {candle_label(tf, intr)}</span>'
      f'<span style="flex:1"></span>'
      f'<span class="muted small">wheel / double-click: zoom in · right-click or ＋− buttons: zoom out · '
      f'drag: pan · click a drawing: colour · “Fullscreen”</span></div>'
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
    t = compute_tech(df)
    H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin:12px 0 2px 0">Indicators</div>')
    tiles = "".join(f'<div class="tile" style="align-items:center"><span class="k">{k}</span>'
                    f'<span class="v" style="font-size:17px;color:{c}">{v}</span></div>'
                    for k, v, c in [("Sell", t["sell"], DOWN), ("Neutral", t["neutral"], NEU), ("Buy", t["buy"], UP)])
    H(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 4px 0">{tiles}</div>')
    rows = ""
    for name, val, v in t["signals"]:
        lab, fg, bg = ("Buy", UP, UP_BG) if v > 0 else ("Sell", DOWN, DOWN_BG) if v < 0 else ("Neutral", NEU, NEU_BG)
        rows += (f'<div class="stat-row"><span class="lbl">{name}</span><span class="mono" style="font-size:12px">'
                 f'{val}</span><span class="badge" style="color:{fg};background:{bg};width:44px;text-align:center">'
                 f'{lab}</span></div>')
    H(rows)
    H('<div style="height:4px"></div>')


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


def treemap(cons, height=380):
    fig = go.Figure(go.Treemap(
        labels=[c["ticker"] for c in cons], parents=[""] * len(cons), values=[c["weight"] for c in cons],
        text=[f'{c["name"]}<br>{pct(c["change_pct"])}' for c in cons], textinfo="label+text",
        marker=dict(colors=[max(-4, min(4, c["change_pct"])) for c in cons], cmin=-3, cmax=3, cmid=0,
                    colorscale=[[0, "#B92D37"], [0.5, "#2A2F37"], [1, "#107A57"]], line=dict(width=2, color=BG)),
        hovertemplate="<b>%{label}</b><br>%{text}<extra></extra>", textfont=dict(color="#FFFFFF", size=13),
        tiling=dict(pad=2)))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)")
    return fig


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
                    f'href="{link(sector=None if SECTOR == s["etf"] else s["etf"], f="sector")}">'
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
          f'{len(cons) - up} down · ⛶ at the top right of the map for fullscreen</span>'
          f'<a class="lnk small" style="margin-left:auto" target="_self" '
          f'href="{link(sector=None, f="sector")}">✕ Close</a></div>')
        if cons:
            plot(treemap(cons, height=560), key=f"tm_{SECTOR}")
            cells = "".join(f'<a class="plain" target="_self" href="{link(sec="Markets", sym=c["ticker"])}">'
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
    cap_hi = 20.0 if is_cyc else 25.0
    g_lt = next((max(-5.0, min(cap_hi, x)) for x in (an.get("growth_5y"), r.get("eps_cagr"), r.get("rev_cagr"))
                 if en._ok(x)), 8.0)
    drop_hist = en.hist_eps_drop(f["eps"]) if f else None
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
            "eps_last": eps_last, "stm_src": stm.get("src", "none"), "pe_now": pe_now,
            "px": px.tail(1300) if px is not None else None,
            "bench": bench.tail(1300) if bench is not None else None,
            "pe_ser": en.pe_series(px.tail(1300), f) if (f and px is not None) else None}


MULT_MODES = ["Today's market multiple", "Peers' forward P/E median", "Own P/E median", "Manual"]


def vp_state(b, sym):
    """Değer patikası ayarlarının şu anki hali (widget çizilmeden de okunabilir)."""
    an = b["an"]
    fy0 = an.get("fy0") or int(pd.Timestamp.now().year)
    est = an.get("fy") or []
    peak0 = int(np.argmax([e["avg"] for e in est])) if est else 0
    tm_ = b.get("timing") or {}
    et = tm_.get("earnings_turn") or {}
    if b["is_cyc"] and et.get("kind") == "peak" and et.get("fy"):
        peak0 = int(min(3, max(0, et["fy"] - fy0)))      # döngü zamanlamasının kâr zirvesi tahmini
    dh = b.get("drop_hist")
    drop0 = float(round(min(80.0, max(30.0, dh if en._ok(dh) else 45.0)) / 5) * 5) if b["is_cyc"] else 45.0
    defaults = {"cyc": bool(b["is_cyc"]), "peak": peak0, "drop": drop0, "glt": float(round(b["g_lt"])),
                "mmode": MULT_MODES[0], "mult": float(round(b.get("pe_now") or 15.0, 1))
                if en._ok(b.get("pe_now")) else 15.0, "win": 1}
    saved = dict(defaults)
    saved.update((ss.get("vp_cfg") or {}).get(sym) or {})
    if saved.get("mmode") not in MULT_MODES:
        saved["mmode"] = MULT_MODES[0]
    if saved.get("peak") not in range(0, 4):
        saved["peak"] = defaults["peak"]
    if saved.get("win") not in (1, 2):
        saved["win"] = 1
    for k, lo, hi in (("drop", 0.0, 90.0), ("glt", -5.0, 30.0), ("mult", 1.0, 80.0)):
        try:
            saved[k] = float(min(hi, max(lo, float(saved[k]))))
        except (TypeError, ValueError):
            saved[k] = defaults[k]
    keys = {k: f"vp_{k}_{sym}" for k in defaults}
    cur = {k: (ss[wk] if wk in ss else saved[k]) for k, wk in keys.items()}
    return {"fy0": fy0, "keys": keys, "saved": saved, "cur": cur, "n_est": len(est), "dh": dh}


def vp_kwargs(b, st_):
    """Ayar sözlüğünden value_path argümanları."""
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
    return {"cyclical": bool(cur["cyc"]), "peak_idx": int(cur["peak"]), "drop": float(cur["drop"]),
            "g_lt": float(cur["glt"]), "target_mult": tm, "fy0": st_["fy0"], "fy0_left": an.get("fy0_left", 0.5),
            "window": int(cur["win"]),
            "g_near": max(-10.0, min(40.0, b["r"]["eps_cagr"])) if en._ok(b["r"].get("eps_cagr")) else None,
            "_mmode": mmode, "_n_est": st_["n_est"]}


def value_cfg(b, sym):
    """Değer patikası ayarları — hisse başına saklanır."""
    st_ = vp_state(b, sym)
    fy0, keys, saved, dh = st_["fy0"], st_["keys"], st_["saved"], st_["dh"]
    for k, wk in keys.items():
        if wk not in ss:
            ss[wk] = saved[k]
    fy_opts = list(range(0, 4))
    with st.container(border=True):
        H('<div class="panel-title">Model Settings</div><div class="muted small">Defaults come from analyst '
          'estimates and the company\'s history; anything you change is saved for this stock.</div>')
        c = st.columns([1, 1, 1.25, 1.25, 1.5, 1], gap="small")
        with c[0]:
            cyc = toggle("Cyclical mode", keys["cyc"], help="Earnings climb to a peak, then pull back.")
        with c[1]:
            st.selectbox("Earnings peak", fy_opts, key=keys["peak"], disabled=not cyc,
                         format_func=lambda i: f"FY{fy0 + i}",
                         help="The fiscal year in which the cycle peaks in earnings.")
        with c[2]:
            st.slider("Post-peak drop", 0.0, 90.0, step=5.0, key=keys["drop"], disabled=not cyc,
                      format="%.0f%%",
                      help="EPS loss from peak to trough (over 2 years). In the company's past cycles: "
                           + (f"{tr(dh, 0)}%" if en._ok(dh) else "no data"))
        with c[3]:
            st.slider("Long-term growth", -5.0, 30.0, step=1.0, key=keys["glt"], format="%.0f%%",
                      help="Annual EPS growth for the years after analyst estimates end.")
        with c[4]:
            mmode = st.selectbox("Target multiple", MULT_MODES, key=keys["mmode"],
                                 help="Today's multiple: the stock keeps being priced the way the market prices it "
                                      "today. The others move the multiple to that value over 3 years.")
            if mmode == "Manual":
                st.number_input("Fwd P/E", 1.0, 80.0, step=0.5, key=keys["mult"])
        with c[5]:
            st.selectbox("Market's horizon", [1, 2], key=keys["win"], format_func=lambda x: f"{x} yr",
                         help="How many years of earnings the price reflects. With 2 years, "
                              "the cycle turn shows up in the price earlier.")
    cur = {k: ss.get(wk) for k, wk in keys.items()}
    allc = dict(ss.get("vp_cfg") or {})
    allc[sym] = cur
    ss.vp_cfg = dict(list(allc.items())[-40:])
    st_["cur"] = cur
    return vp_kwargs(b, st_)


def _model_kwargs(cfg):
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def fin_bar_chart(f, keys, names, colors, height=240, pct=False):
    """Yıllık kalemler için çubuk grafiği."""
    fig = go.Figure()
    for k, n, c in zip(keys, names, colors):
        vals = [v / 1e9 if not pct and en._ok(v) else v for v in f[k]]
        fig.add_trace(go.Bar(x=[str(y) for y in f["years"]], y=vals, name=n, marker_color=c))
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.18, x=0))
    fig.update_yaxes(ticksuffix="%" if pct else " mr")
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


def fair_path_chart(path, px, price, height=300):
    """Geçmiş fiyat + önümüzdeki yılların değer bandı (aralık dolgulu)."""
    fig = go.Figure()
    if px is not None and len(px) > 20:
        h = px.tail(500)
        fig.add_trace(go.Scatter(x=h.index, y=h["Close"], mode="lines", name="Price",
                                 line=dict(color=SOFT, width=1.5)))
    x0 = px.index[-1] if (px is not None and len(px)) else pd.Timestamp.today()
    try:
        x0 = pd.Timestamp(x0).tz_localize(None)
    except (TypeError, AttributeError):
        x0 = pd.Timestamp(x0)
    xs = [x0 + pd.DateOffset(years=r["k"]) for r in path["rows"]]
    td = path["today"]["value"]
    allx = [x0] + xs
    bear = [td["bear"]] + [r["value"]["bear"] for r in path["rows"]]
    bull = [td["bull"]] + [r["value"]["bull"] for r in path["rows"]]
    fig.add_trace(go.Scatter(x=allx, y=bull, mode="lines", line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=allx, y=bear, mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=rgba(ACCENT, 0.10), hoverinfo="skip", showlegend=False))
    for key, name, c, dash in (("bull", "Bull", "#6EE7B7", "dot"), ("base", "Base", ACCENT, None),
                               ("bear", "Bear", "#F0883E", "dot")):
        ys = [price if key == "base" else td[key]] + [r["value"][key] for r in path["rows"]]
        fig.add_trace(go.Scatter(x=allx, y=ys, mode="lines+markers", name=name,
                                 line=dict(color=c, width=2.2 if key == "base" else 1.3, dash=dash),
                                 marker=dict(size=5),
                                 hovertemplate=f"{name} %{{x|%b %Y}}: %{{y:.2f}}<extra></extra>"))
    fig.add_hline(y=price, line=dict(color=MUT, width=1, dash="dash"),
                  annotation_text=f"today {tr(price)}", annotation_position="top left",
                  annotation_font=dict(color=MUT, size=10))
    fig.update_layout(legend=dict(orientation="h", y=1.16, x=0))
    return _layout(fig, height, legend=True, margin=dict(l=4, r=10, t=28, b=4))


def path_mult_fig(path, height=220):
    """Her yıl kullanılan ileri kâr ve çarpan — patikanın nereden geldiği."""
    yrs = [str(path["today"]["year"])] + [str(r["year"]) for r in path["rows"]]
    rows = [path["today"]] + path["rows"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=[r["fwd_eps"]["base"] for r in rows], name="Next-12-month EPS (base)",
                         marker_color=rgba(ACCENT, 0.55), hovertemplate="%{x}: %{y:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=yrs, y=[r["mult"]["base"] for r in rows], name="Multiple", yaxis="y2",
                             mode="lines+markers", line=dict(color=WARN, width=2),
                             hovertemplate="%{x}: %{y:.1f}x<extra></extra>"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, ticksuffix="x",
                                  tickfont=dict(color=MUT, size=10)),
                      legend=dict(orientation="h", y=1.2, x=0))
    fig = _layout(fig, height, legend=True, margin=dict(l=36, r=36, t=26, b=4))
    fig.update_layout(yaxis=dict(side="left"))
    return fig


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


def render_value_fundamentals(b):
    f, r = b["f"], b["r"]
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">01</span>'
      '<h3>Fundamentals</h3><span class="muted">Statements for the last ' + str(f["n"]) + ' years</span></div>')
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        with st.container(border=True):
            H('<div class="panel-title">Income Statement</div><div class="muted small">Billions, reporting '
              'currency</div>')
            plot(fin_bar_chart(f, ["revenue", "gross", "op_income", "net_income"],
                               ["Revenue", "Gross profit", "Operating income", "Net income"],
                               [ACCENT, "#6EE7B7", WARN, VIOLET]), key="v_inc")
    with c2:
        with st.container(border=True):
            H('<div class="panel-title">Margins</div><div class="muted small">As % of revenue</div>')
            plot(fin_bar_chart(f, ["gross_m", "op_m", "net_m", "fcf_m"],
                               ["Gross", "Operating", "Net", "Free cash flow"],
                               ["#6EE7B7", WARN, VIOLET, ACCENT], pct=True), key="v_marg")
    c3, c4 = st.columns(2, gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Cash Flow</div><div class="muted small">Operating, investing and '
              'free cash flow</div>')
            plot(fin_bar_chart(f, ["ocf", "capex", "fcf"],
                               ["Operating cash flow", "Capital expenditure", "Free cash flow"],
                               [ACCENT, DOWN, "#6EE7B7"]), key="v_cf")
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Balance Sheet</div><div class="muted small">Assets, equity and net debt</div>')
            plot(fin_bar_chart(f, ["assets", "equity", "net_debt"],
                               ["Total assets", "Equity", "Net debt"],
                               ["#4A515C", "#6EE7B7", DOWN]), key="v_bs")
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
                         height=220, suffix=" mr"), key="v_debt")
    with c7:
        with st.container(border=True):
            H('<div class="panel-title">Shareholder Returns</div><div class="muted small">Buybacks + dividends, '
              'billions</div>')
            plot(bar_fig(yrs, [("Buybacks", [abs(v) / 1e9 if en._ok(v) else None for v in f["buyback"]], ACCENT),
                               ("Dividends", [abs(v) / 1e9 if en._ok(v) else None for v in f["dividends_paid"]],
                                WARN)],
                         height=220, suffix=" mr", barmode="stack"), key="v_sh")
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
    with st.container(border=True):
        f1, f2, f3 = st.columns([1.4, 2, 1.6], vertical_alignment="center")
        with f2:
            day = seg("Day", md.CAL_DAYS, "w_calday", "Today")
        with f3:
            imp = seg("Impact", md.CAL_IMPACTS, "w_calimp", "All")
        rows = md.get_calendar_rows(day, imp)
        with f1:
            H(src_chip(rows[0]["src"] if rows else md._calendar_all()[0]["src"] if md._calendar_all() else "none"))
        out = ('<div class="cal-row" style="border:0;color:#8D96A5;font-size:11px;letter-spacing:.07em">'
               '<span style="width:120px">TIME</span><span style="width:52px">CCY</span><span style="width:40px">IMPACT'
               '</span><span style="flex:1">EVENT</span><span style="width:90px;text-align:right">ACTUAL</span>'
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
            out += (f'<div class="cal-row{" next" if r["next"] else ""}"><span class="mono" style="width:120px">'
                    f'{r["time"]}{nxt}</span><span style="width:52px;font-weight:700;font-size:12px">{esc(r["cur"])}</span>'
                    f'<span class="dots">{dots}</span><span style="flex:1">{esc(r["event"])}</span>'
                    f'<span class="mono" style="width:90px;text-align:right">{esc(r["actual"])}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["forecast"])}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["previous"])}</span></div>')
        if not rows:
            out += f'<div class="muted" style="padding:18px 6px">No events with this filter.</div>'
        out += (f'<div class="muted small" style="padding-top:10px"><span style="color:{DOWN}">■</span> High &nbsp;'
                f'<span style="color:{WARN}">■</span> Medium &nbsp;<span style="color:#6B7383">■</span> Low</div>')
        H(f'<div style="overflow-x:auto"><div style="min-width:760px">{out}</div></div>')

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
        img = (f'<img src="{esc(f["thumb"])}" alt="">' if safe_url(f.get("thumb")) else "[NEWS IMAGE]")
        furl = news_link(f)
        ttl = f'<a href="{esc(furl)}" target="_blank" rel="noopener">{esc(f["title"])} ↗</a>'
        tags = " ".join(f'<span class="chip mono">{esc(t)}</span>' for t in f.get("tags", []))
        H(f'<a class="plain" href="{esc(furl)}" target="_blank" rel="noopener">'
          f'<div class="feat"><div class="img">{img}</div><div style="padding:16px 18px"><div style="display:flex;'
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
                return (f'<span style="width:84px;flex:none;display:flex;align-items:center;'
                        f'background:#0C0D10;border-radius:10px;padding:4px">'
                        f'{svg_spark(it["spark"], sc, 76, 40)}</span>')
            H(news_rows(data["items"], left=_spark) or '<div class="muted">No news in this category.</div>')
            st.caption("The Bullish/Bearish tag is derived automatically from wording in the headline.")


# ======================================================================
# AKIŞ
# ======================================================================
def main():
    render_header()
    {"Markets": render_piyasalar, "Valuation": render_value, "Long Term": render_longterm,
     "Short Term": render_short, "Backtest": render_backtest,
     "Forex & News": render_forex}[SEC]()




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


def football_fig(ms, price, bl, height=None):
    """Her yöntemin değer aralığı (çubuk), taban değeri (elmas), bugünkü fiyat ve harman değer."""
    fig = go.Figure()
    names = [m["name"] for m in ms]
    for m in ms:
        c_ = ACCENT if (m["weight"] > 0 and not m.get("excluded")) else MUT
        fig.add_trace(go.Scatter(x=[m["low"], m["high"]], y=[m["name"], m["name"]], mode="lines",
                                 line=dict(color=rgba(c_, 0.55), width=16), showlegend=False,
                                 hovertemplate=f"{esc(m['name'])}: {tr(m['low'])} – {tr(m['high'])}<extra></extra>"))
    fig.add_trace(go.Scatter(x=[m["base"] for m in ms], y=names, mode="markers", showlegend=False,
                             marker=dict(size=11, color=TXT, symbol="diamond", line=dict(width=1, color="#0A0B0D")),
                             hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
    fig.add_vline(x=price, line=dict(color=TXT, width=1.4, dash="dot"),
                  annotation_text=f"price {tr(price)}", annotation_position="top",
                  annotation_font=dict(color=SOFT, size=10))
    if bl:
        fig.add_vline(x=bl["value"], line=dict(color=UP if bl["value"] >= price else DOWN, width=2, dash="dash"),
                      annotation_text=f"blended {tr(bl['value'])}", annotation_position="bottom",
                      annotation_font=dict(color=SOFT, size=10))
    fig = _layout(fig, height or (90 + 46 * len(ms)), margin=dict(l=8, r=16, t=26, b=24))
    fig.update_yaxes(side="left", categoryorder="array", categoryarray=names[::-1], showgrid=False)
    fig.update_layout(hovermode="closest")
    return fig


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
        path = en.value_path(price, b["eps_last"], an.get("fy") or [], years=5, **_model_kwargs(kw))
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
        r1 = path["rows"][0]
        pm_ = en._method("path", "Market-implied path (12 mo)", r1["value"]["bear"], r1["value"]["base"],
                         r1["value"]["bull"], "Analyst EPS × today's forward multiple — reference only, "
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
    if ms:
        with st.container(border=True):
            H('<div class="panel-title">Valuation Range by Method</div><div class="muted small">Bar = low–high, '
              'diamond = base case · dotted line today\'s price, dashed line blended fair value · grey methods '
              'are shown for reference only</div>')
            plot(football_fig(ms, price, bl), key="v_ff")
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
    with st.expander("Analyst-estimate value path, sensitivity & DCF", expanded=(vt == "cyclical")):
        render_value_future(b)


def render_value_future(b):
    d, an = b["d"], b["an"]
    sym = d.get("ticker") or ACTIVE
    dec = pdec(sym, d["last"])
    H('<div class="muted small" style="margin-bottom:6px">Analyst EPS estimates → cycle → forward multiple · '
      'three scenarios. This path assumes the market keeps pricing the stock the way it does today, so it is '
      'shown for reference and not used in the blended fair value.</div>')
    if not en._ok(b.get("eps_last")):
        H('<div class="muted">No EPS data, so a target value could not be calculated.</div>')
        return
    cfg = value_cfg(b, sym)
    est = an.get("fy") or []
    path = en.value_path(d["last"], b["eps_last"], est, years=5, **_model_kwargs(cfg))
    if not path:
        H('<div class="muted">Forward earnings are negative, so a multiple-based value cannot be built.</div>')
        return
    b["path"] = path
    c1, c2 = st.columns([1.7, 1], gap="medium")
    with c1:
        with st.container(border=True):
            n_an = an.get("n") or max([e.get("n") or 0 for e in est] or [0])
            src = (f'{", ".join(e["label"] for e in est)} analyst estimates'
                   f'{" (" + str(n_an) + " analysts)" if n_an else ""}'
                   if est else "No analyst estimates — using historical EPS growth")
            mtxt = (f'multiple calibrated to today\'s price: <b>{tr(path["m_cal"], 1)}x</b> forward earnings'
                    if not path["rerated"] else
                    f'multiple {tr(path["m_cal"], 1)}x → <b>{tr(path["m_target"], 1)}x</b> over 3 years')
            H(f'<div class="panel-title">Value Path</div><div class="muted small">{esc(src)} · {mtxt}'
              f'{" · earnings peak FY" + str(path["peak_fy"]) + ", then a " + tr(path["drop"], 0) + "% drop" if path["cyclical"] else ""}'
              f'</div>')
            plot(fair_path_chart(path, b["px"], d["last"]), key="v_path")
            sc = path["scen"]
            H(f'<div class="muted small">Bear: lowest analyst estimate'
              f'{", " + tr(sc["bear"]["drop"], 0) + "% post-peak drop" if path["cyclical"] else ""}, '
              f'then {tr(sc["bear"]["g"], 0)}% growth, multiple −15% · Bull: highest estimate'
              f'{", " + tr(sc["bull"]["drop"], 0) + "% drop" if path["cyclical"] else ""}, '
              f'then {tr(sc["bull"]["g"], 0)}% growth, multiple +15%. At every point the price reflects '
              f'earnings for <i>the next 12 months</i>.</div>')
            # tek cümlelik okuma
            pk_y, pk_v = path["price_peak_year"], path["price_peak_value"]
            if path["cyclical"] and pk_y > path["today"]["year"]:
                up = (pk_v / d["last"] - 1) * 100
                H(f'<div class="gtext">In the base case the price peaks around <b>{pk_y}</b> '
                  f'(<b>{tr(pk_v, dec)}</b>, {pct(up)}); earnings peak in FY{path["peak_fy"]}. For cyclicals '
                  f'the market prices the turn in advance, so the price tops out before earnings do.</div>')
            elif path["cyclical"]:
                H('<div class="gtext">In the base case the price is in its peak zone today: forward earnings start to fall '
                  'as earnings approach their peak. Try changing the peak year or the drop rate.</div>')
    with c2:
        with st.container(border=True):
            H('<div class="panel-title">Year by Year</div>')
            rows = ""
            for row in path["rows"]:
                up = row.get("upside")
                rows += (f'<tr><td>{row["year"]}</td>'
                         f'<td style="color:{SOFT}">{tr(row["value"]["bear"], dec)}</td>'
                         f'<td style="color:{TXT}">{tr(row["value"]["base"], dec)}</td>'
                         f'<td style="color:{SOFT}">{tr(row["value"]["bull"], dec)}</td>'
                         f'<td style="color:{col(up) if up is not None else MUT}">'
                         f'{pct(up) if up is not None else "—"}</td>'
                         f'<td style="color:{MUT}">{tr(row["mult"]["base"], 1)}x</td></tr>')
            H(f'<table class="ptab"><thead><tr><th>Year</th><th>Bear</th><th>Base</th><th>Bull</th>'
              f'<th>Return</th><th>Multiple</th></tr></thead><tbody>{rows}</tbody></table>')
            erows = ""
            for e in path["eps_rows"]:
                g_ = e.get("growth")
                tag = ('<span class="badge" style="color:#6EE7B7;background:#6EE7B71F">analyst</span>'
                       if e["src"] == "analyst" else '<span class="muted small">model</span>')
                erows += (f'<tr><td>{e["label"]}</td><td style="color:{SOFT}">{tr(e["eps"]["bear"], 2)}</td>'
                          f'<td>{tr(e["eps"]["base"], 2)}</td><td style="color:{SOFT}">{tr(e["eps"]["bull"], 2)}</td>'
                          f'<td style="color:{col(g_) if g_ is not None else MUT}">'
                          f'{pct(g_) if g_ is not None else "—"}</td><td>{tag}</td></tr>')
            H(f'<div class="panel-title" style="margin-top:12px">EPS (fiscal year)</div>'
              f'<table class="ptab"><thead><tr><th>Year</th><th>Bear</th><th>Base</th><th>Bull</th>'
              f'<th>Growth</th><th></th></tr></thead><tbody>{erows}</tbody></table>'
              f'<div class="muted small" style="margin-top:6px">Start: last fiscal-year EPS '
              f'{tr(path["eps_last"], 2)}. Return is the base case\'s potential versus today\'s price.</div>')
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
        sens = en.value_sensitivity(d["last"], b["eps_last"], est, kw, rv, mults, 5)
    except Exception:
        sens = None
    b["sens"] = sens
    c3, c4 = st.columns([1.3, 1], gap="medium")
    with c3:
        with st.container(border=True):
            lab = "post-peak drop" if (sens and sens["key"] == "drop") else "long-term growth"
            H(f'<div class="panel-title">Sensitivity</div><div class="muted small">'
              f'Base value {sens["years"] if sens else 5} years out — rows: {lab}, columns: target multiple</div>')
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
            H('<div class="panel-title" style="margin-top:10px">Building Blocks of the Path</div>'
              '<div class="muted small">Each year: next-12-month EPS × that year\'s multiple = value</div>')
            plot(path_mult_fig(path), key="v_pmult")
    with c6:
        with st.container(border=True):
            band, ps = b["band"], b.get("pe_ser")
            H('<div class="panel-title">Historical P/E Band</div><div class="muted small">Price ÷ that year\'s '
              'EPS — where today\'s multiple sits versus its own history</div>')
            if ps is not None and len(ps) > 20:
                hl = []
                if band:
                    hl = [(band["high"], f'top 90% · {tr(band["high"], 1)}x', DOWN),
                          (band["median"], f'median · {tr(band["median"], 1)}x', MUT),
                          (band["low"], f'alt %10 · {tr(band["low"], 1)}x', UP)]
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
    f = b["f"]
    yrs = [str(y) for y in f["years"]]
    c3, c4 = st.columns([1.2, 1], gap="medium")
    with c3:
        with st.container(border=True):
            H('<div class="panel-title">Profitability Trend</div><div class="muted small">Return on equity and on '
              'assets, net margin — can it hold the same level over the years</div>')
            plot(line_fig([("Return on equity", yrs, f["roe"], ACCENT, False, False),
                           ("Return on assets", yrs, f["roa"], "#6EE7B7", False, False),
                           ("Net margin", yrs, f["net_m"], VIOLET, True, False)],
                          height=240, suffix="%"), key="v_prof")
    with c4:
        with st.container(border=True):
            H('<div class="panel-title">Altman Z — Component Contributions</div><div class="muted small">Weighted '
              'contribution; they add up to the Z-score</div>')
            parts = en.altman_contrib(zsc)
            if parts:
                plot(bar_fig([k for k, _ in parts], [("Contribution", [v for _, v in parts],
                                                      [UP if v >= 0 else DOWN for _, v in parts])],
                             height=240, legend=False, horizontal=True, text=True, dec=2), key="v_altman")
            else:
                H('<div class="muted" style="padding:20px 0">Could not be calculated.</div>')


try:
    main()
finally:
    _save_state()
