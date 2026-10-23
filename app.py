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

st.set_page_config(page_title="Pulse — Piyasa Paneli", layout="wide", initial_sidebar_state="collapsed")

APP_VERSION = "3.0"
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
    st.error("**" + ", ".join(_missing) + " bulunamadı.** Bu sürüm şu dosyalardan oluşuyor: `app.py`, "
             "`mock_data.py`, `engine.py`, `chart.py` ve `pulse_chart/index.html`. Eksik dosyaları "
             "GitHub'da app.py ile aynı klasöre yükleyip Streamlit'te **Reboot app** yap.")
    st.stop()

_vers = {"app.py": APP_VERSION, "mock_data.py": getattr(md, "DATA_VERSION", "eski"),
         "engine.py": getattr(en, "ENGINE_VERSION", "eski"), "chart.py": getattr(ch, "CHART_VERSION", "eski")}
if set(_vers.values()) != {APP_VERSION}:
    st.error("**Dosya sürümleri uyuşmuyor** — " +
             " · ".join(f"{k} v{v}" for k, v in _vers.items()) +
             ". Hepsinin son halini GitHub'a yükleyip **Reboot app** yap.")
    st.stop()

# ======================================================================
# Tasarım sabitleri
# ======================================================================
BG, PANEL, PANEL2, BORDER, LINE = "#0A0B0D", "#111317", "#0C0D10", "#22262D", "#1C1F25"
TXT, MUT, SOFT, DIM = "#ECEEF1", "#8D96A5", "#C4CAD4", "#A3ABB8"
UP, DOWN, NEU, WARN, ACCENT, VIOLET = "#34D399", "#F87171", "#C4CAD4", "#F5B544", "#5B8CFF", "#C4B5FD"
UP_BG, DOWN_BG, NEU_BG = "rgba(52,211,153,.12)", "rgba(248,113,113,.12)", "rgba(141,150,165,.14)"
WARN_BG, ACC_BG = "rgba(245,181,68,.13)", "rgba(91,140,255,.14)"
SETUP_STYLE = {"Pullback": ("#9DB8FF", "rgba(91,140,255,.14)"), "Kırılım": ("#6EE7B7", "rgba(52,211,153,.12)"),
               "Destekten dönüş": ("#FCD34D", "rgba(245,181,68,.13)"), "Momentum": ("#D8B4FE", "rgba(167,139,250,.14)")}
TONE = {"good": (UP, "#0F1A15", "#1F4D3A", "#0A0B0D"), "warn": (WARN, "#1A160E", "#4D3D1F", "#0A0B0D"),
        "bad": (DOWN, "#1A0F10", "#4D1F24", "#ECEEF1")}

SECTIONS = ["Piyasalar", "Long Term", "Short Term", "Backtest", "Forex & Haberler"]
TF_BARS = {"1G": 10, "1H": 22, "1A": 22, "3A": 66, "1Y": 252, "5Y": 1260}  # 1G/1H: gün içi veri yoksa
# 1G / 1H gün içi mumlarla çizilir: (yfinance periyodu, mum aralığı, gösterilecek gün sayısı)
INTRA = {"1G": ("5d", "5m", 1), "1H": ("1mo", "30m", 7)}
TF_NAME = {"1G": "Son 1 gün", "1H": "Son 1 hafta", "1A": "Son 1 ay", "3A": "Son 3 ay", "1Y": "Son 1 yıl",
           "5Y": "Son 5 yıl"}
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
WIDGET_KEYS = ["flt_logic", "flt_min", "flt_name", "acct", "w_risk", "w_tf", "w_fxtf", "w_fxc", "w_calday",
               "w_calimp", "w_nc", "w_mov", "w_setup", "w_sort", "w_bttf", "bt_inst", "bt_custom", "bt_pick",
               "bt_yrs", "bt_ind1", "bt_p1", "bt_op1", "bt_v1", "bt_logic", "bt_c2on", "bt_src2", "bt_p2",
               "bt_op2", "bt_dir", "bt_slMode", "bt_slV", "bt_tpMode", "bt_tpV", "bt_maxBars", "bt_cap",
               "bt_risk", "bt_comm", "bt_xmin"]
PERSIST = ["watchlist", "journal", "journal_closed", "flt_rows", "flt_ver", "flt_lastN", "bt_extra",
           "bt_extra_ver", "bt_ran", "bt_saved",
           "draws", "alerts", "ch_cfg", "ch_type", "ch_rev", "ch_n"] + WIDGET_KEYS


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
               "flt_rows": copy.deepcopy(en.DEFAULT_FILTER), "flt_logic": "VE",
               "flt_min": len(en.DEFAULT_FILTER) - 1, "flt_lastN": len(en.DEFAULT_FILTER),
               "flt_name": "Trend içi geri çekilme", "flt_ver": 0,
               "flt_edit": False, "bt_extra": [], "bt_extra_ver": 0, "bt_ran": None, "bt_saved": [],
               "acct": 100000.0, "draws": {}, "alerts": {}, "ch_cfg": copy.deepcopy(ch.DEFAULT_CFG),
               "ch_type": "candles", "ch_rev": 1, "ch_n": None, **BT_WIDGETS}.items():
    ss.setdefault(_k, copy.deepcopy(_v))
# Streamlit, o çalıştırmada çizilmeyen widget'ın değerini siler (ör. filtre editörü kapalıyken).
# Değeri kendine yeniden atamak bu temizliği engeller → ayarlar kaybolmaz.
for _k in WIDGET_KEYS:
    if _k in ss:
        ss[_k] = ss[_k]

_SYM_RE = re.compile(r"[^A-Za-z0-9.^=\-]")
SEC = _qp("sec", "Piyasalar")
SEC = SEC if SEC in SECTIONS else "Piyasalar"
ACTIVE = _SYM_RE.sub("", _qp("sym", "SPY")).upper()[:24] or "SPY"
FX = _qp("fx", "EUR/USD")
FX = FX if any(p == FX for p, *_ in md._FX_LIST) else "EUR/USD"
OPP = _SYM_RE.sub("", _qp("opp", "") or "").upper()[:24] or None
SECTOR = _qp("sector")
SECTOR = SECTOR if md.sector_by_etf(SECTOR or "") else None


def link(**kw):
    p = {"sid": SID, "sec": SEC, "sym": ACTIVE, "fx": FX, "opp": OPP, "sector": SECTOR}
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
        st.toast(f"{_a} izleme listesine eklendi")
_a = _consume("add_flt")
if _a in en.INDICATORS:
    ss.flt_rows.append(en.suggested_condition(_a))
    ss.flt_ver += 1
    ss.flt_edit = True
    st.toast(f"“{_a}” filtreye eklendi — değerini düzenleyebilirsin")
_a = _consume("add_bt")
if _a in en.INDICATORS:
    ss.bt_extra.append(en.suggested_condition(_a))
    ss.bt_extra_ver += 1
    ss["bt_show_extra"] = True
    st.toast(f"“{_a}” backtest koşullarına eklendi")
if _consume("bt_from_flt"):
    ss.bt_extra = [dict(r) for r in en.normalize_conds(ss.flt_rows) if r["Aktif"]]
    ss.bt_extra_ver += 1
    ss.bt_ind1, ss.bt_c2on = en.IND1_OFF, False
    _n = len(ss.bt_extra)
    _k = int(ss.get("flt_min") or _n)
    ss.bt_xmin = 1 if ss.get("flt_logic") == "VEYA" else (_k if 0 < _k < _n else 0)  # Short Term ile aynı mantık
    ss["bt_show_extra"] = True
    ss.bt_ran = None  # yeni kurallarla otomatik çalıştır
    st.toast("Short Term filtresi backtest giriş koşulu olarak yüklendi")
_a = _consume("close_tr")
if _a is not None and ss.journal:
    try:
        i = int(_a)
        tr_ = ss.journal.pop(i)
        q = md.get_quote(tr_["t"])
        tr_["exit"], tr_["closed"] = q["last"], pd.Timestamp.today().strftime("%Y-%m-%d")
        ss.journal_closed.append(tr_)
        st.toast(f"{tr_['t']} işlemi kapatıldı")
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
    return f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def pct(x, dec=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return ("+" if x >= 0 else "−") + "%" + tr(abs(x), dec)


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


def avatar(t, size=34):
    tt = str(t or "?")
    ini = re.sub(r"[^A-Z0-9]", "", tt.upper().replace("=X", "").replace("-USD", "").replace("^", ""))[:2] or "?"
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
        return '<span class="srcchip live">● canlı veri</span>'
    if src == "mock":
        return '<span class="srcchip mock">örnek veri</span>'
    return '<span class="srcchip none">veri yok</span>'


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
.srstrip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
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
.nw{display:flex;gap:12px;padding:11px 0;border-top:1px solid #1C1F25}
.nw b{font-size:13.5px;font-weight:700;line-height:1.35;display:block}
.nw a{color:#ECEEF1;text-decoration:none}.nw a:hover{color:#C3D4FF}
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
.opp-grid{display:grid;grid-template-columns:1.9fr 1.15fr .9fr 1.55fr .8fr .85fr .45fr 1.05fr;
 align-items:center;gap:0 10px;min-width:800px;padding:0 14px}
.opp-grid .r{white-space:nowrap}
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


def render_big_chart(sym, tf, height=600):
    """TradingView tarzı grafik; dosya eksikse Plotly'ye düşer."""
    if ch.missing_frontend():
        st.warning("`pulse_chart/index.html` yüklenmemiş — basit grafiğe düşüldü. GitHub'da "
                   "**pulse_chart** klasörünü ve içindeki **index.html** dosyasını da yükle.")
        full, bars, intr = chart_data(sym, tf)
        if not full.empty:
            plot(price_chart(full, bars, height - 60, intraday=intr), config=CHART_CFG, key="fallback_" + sym)
        return
    payload = ch.build_payload(sym, tf, json.dumps(ss.ch_cfg, sort_keys=True), ch.data_token(sym, tf))
    if not payload.get("ok"):
        H('<div class="muted">Bu sembol için grafik verisi alınamadı.</div>')
        return
    ev = ch.render_chart(payload, ss.draws.get(sym, []), ss.alerts.get(sym, []),
                         ss.ch_type, height=height, rev=ss.ch_rev, key="pulse_chart")
    handle_chart_event(ev)


def candle_label(tf, intraday):
    if intraday:
        return {"1G": "5 dk mumlar", "1H": "30 dk mumlar"}.get(tf, "gün içi mumlar")
    return "gün içi veri yok · günlük mumlar" if tf in INTRA else "günlük mumlar"


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
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name="Fiyat"), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=s20, mode="lines", line=dict(color=ACCENT, width=1.5), name="SMA 20"), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=s50, mode="lines", line=dict(color=WARN, width=1.5), name="SMA 50"), 1, 1)
    last = float(df["Close"].iloc[-1])
    fig.add_hline(y=last, line=dict(color=col(last - float(df["Open"].iloc[0])), width=1, dash="dot"), row=1, col=1)
    r = 2
    if has_vol:
        fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Hacim", opacity=0.45,
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
            ("Stokastik %K (14)", tr(st_k, 1), v(st_k == st_k and st_k < 20, st_k == st_k and st_k > 80)),
            ("Momentum (10)", chg(mom), 1 if mom > 0 else -1),
            ("SMA 20", tr(s20), v(s20 == s20 and price > s20, s20 == s20 and price <= s20)),
            ("SMA 50", tr(s50), v(s50 == s50 and price > s50, s50 == s50 and price <= s50))]
    score = sum(x for _, _, x in sigs)
    buy, sell = sum(1 for *_, x in sigs if x > 0), sum(1 for *_, x in sigs if x < 0)
    label = ("Güçlü Al" if score >= 3 else "Al" if score >= 1 else "Güçlü Sat" if score <= -3 else
             "Sat" if score <= -1 else "Nötr")
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
    ("Fear & Greed Index", "Long Term", "Piyasa duyarlılığı göstergesi (CNN)"),
    ("Ucuz şirketler (PEG / Forward PE)", "Long Term", "Değer taraması"),
    ("Sektör performansı · şirket ısı haritası", "Piyasalar", "Sektöre tıkla → şirketlerin günlük performansı"),
    ("Teknik özet · destek & direnç", "Piyasalar", "Seçili sembolün göstergeleri ve pivot seviyeleri"),
    ("Öne çıkanlar (yükselenler / düşenler)", "Piyasalar", "Günün en çok hareket edenleri"),
    ("Yaklaşan halka arzlar (IPO)", "Piyasalar", "IPO takvimi"),
    ("Swing fırsatları · tarama", "Short Term", "Filtrene uyan hisseler"),
    ("Filtre düzenle · kriterler", "Short Term", "RSI, MACD, hacim vb. koşulları değiştir"),
    ("Pozisyon büyüklüğü hesaplayıcı", "Short Term", "Hesap ve risk yüzdesine göre adet"),
    ("Açık işlemlerim · işlem günlüğü", "Short Term", "Takip edilen işlemler"),
    ("Strateji laboratuvarı · backtest", "Backtest", "İndikatörleri birleştir, geçmişte test et"),
    ("Stop loss · take profit · sermaye eğrisi", "Backtest", "Çıkış kuralları ve sonuçlar"),
    ("Pariteler · forex grafiği", "Forex & Haberler", "Döviz pariteleri"),
    ("Ekonomik takvim", "Forex & Haberler", "Makro veri açıklamaları"),
    ("Piyasa haberleri", "Forex & Haberler", "Forex, merkez bankaları, emtia, Türkiye"),
]


def render_search(q):
    ql = q.lower()
    syms = md.search_symbols(q)
    inds = en.find_indicators(q)
    pages = [x for x in SITE_INDEX if ql in x[0].lower() or ql in x[2].lower() or ql == x[1].lower()][:5]
    with st.container(border=True):
        H(f'<div class="muted">“{esc(q)}” için sonuçlar</div>')
        parts = []
        if syms:
            rows = ""
            for r in syms:
                t = r["ticker"]
                meta = " · ".join(x for x in [r.get("name"), r.get("type"), r.get("exchange"), r.get("sector")] if x)
                d = f'<div class="muted small" style="margin-top:2px">{esc(r["desc"])}</div>' if r.get("desc") else ""
                add = "" if t in ss.watchlist else \
                    f'<a class="sr-act" target="_self" href="{link(add_wl=t)}">☆ İzlemeye ekle</a>'
                rows += (f'<div class="sr-row"><a class="plain sr-main" target="_self" '
                         f'href="{link(sec="Piyasalar", sym=t, opp=None)}">{avatar(t, 32)}<div style="min-width:0">'
                         f'<b class="mono">{esc(t)}</b><div class="muted small">{esc(meta)}</div>{d}</div></a>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Piyasalar", sym=t, opp=None)}">'
                         f'Grafiği aç →</a>{add}</div>')
            parts.append(("sym", f'<div class="boxlbl" style="margin-top:10px">Semboller</div>{rows}'))
        if inds:
            rows = ""
            for n in inds:
                meta = en.INDICATORS[n]
                rows += (f'<div class="sr-row"><div class="sr-main"><span class="ficon">∿</span><div>'
                         f'<b>{esc(n)}</b> <span class="chip">{esc(meta["group"])}</span>'
                         f'<div class="muted small" style="margin-top:2px">{esc(meta["desc"])}</div></div></div>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Short Term", add_flt=n)}">Filtreye ekle</a>'
                         f'<a class="sr-act" target="_self" href="{link(sec="Backtest", add_bt=n)}">Backtest\'e ekle</a>'
                         f'</div>')
            parts.append(("ind", f'<div class="boxlbl" style="margin-top:10px">İndikatörler</div>{rows}'))
        # "rsi", "macd" gibi indikatör aramalarında indikatörler üstte
        if inds and (ql in en.ALIASES or any(n.lower().startswith(ql) for n in inds)):
            parts.sort(key=lambda p: p[0] != "ind")
        for _, chunk in parts:
            H(chunk)
        if pages:
            H('<div class="boxlbl" style="margin-top:10px">Sayfalar &amp; parametreler</div>' + "".join(
                f'<div class="sr-row"><a class="plain sr-main" target="_self" href="{link(sec=p)}">'
                f'<span class="ficon">↗</span><div><b>{esc(t)}</b><div class="muted small">{esc(p)} · '
                f'{esc(dsc)}</div></div></a></div>' for t, p, dsc in pages))
        raw = _SYM_RE.sub("", q).upper()[:24]
        if raw and not any(r["ticker"] == raw for r in syms):
            H(f'<div class="sr-row"><a class="plain sr-main" target="_self" '
              f'href="{link(sec="Piyasalar", sym=raw, opp=None)}"><span class="ficon">⌕</span><div>'
              f'<b class="mono">{esc(raw)}</b><div class="muted small">Bu sembolü doğrudan aç (Yahoo Finance '
              f'sembolü, ör. GARAN.IS, EURUSD=X, BTC-USD)</div></div></a></div>')
        if not (syms or inds or pages):
            H('<div class="muted" style="margin-top:6px">Sonuç bulunamadı.</div>')


def render_header():
    c1, c2, c3 = st.columns([5.6, 2.4, 0.9], vertical_alignment="center")
    with c1:
        nav = "".join(f'<a class="{"active" if s == SEC else ""}" target="_self" '
                      f'href="{link(sec=s, opp=None, sector=None)}">{esc(s)}</a>' for s in SECTIONS)
        H(f'<div class="hdr"><div class="brand">{LOGO_SVG}<span>Pulse</span></div><nav class="navbar">{nav}</nav></div>')
    with c2:
        q = st.text_input("Ara", key="q", placeholder="🔍  Sembol, parite, indikatör ara…",
                          label_visibility="collapsed")
    with c3:
        H('<div class="hdr-icons"><span class="hbtn">🔔</span><span class="hbtn">A</span></div>')
    H('<div class="hdr-line"></div>')
    if q and q.strip():
        render_search(q.strip()[:60])


def health_panel():
    h = md.get_data_health()
    ok = lambda b: "✅" if b else "⚠️"
    label = "🟢 Canlı veri" if h["yf_ok"] else "🟡 Fiyat verisi şu an örnek"
    with st.expander(f"🔎 Veri kaynakları — {label}", expanded=not h["yf_ok"]):
        H(f'<div class="small" style="line-height:1.9">{ok(h["yf_ok"])} Fiyatlar / grafikler / haberler (Yahoo): '
          f'{esc(h["yf_msg"])}<br>{ok(h["cnn_ok"])} Fear &amp; Greed (CNN)<br>{ok(h["cal_ok"])} Ekonomik takvim '
          f'(ForexFactory)</div>')
        if not h["yfinance_installed"]:
            st.warning("requirements.txt'te `yfinance>=0.2.54` satırı eksik ya da eski dosya yüklü. "
                       "Güncel requirements.txt'yi yükleyip Reboot et.")
        elif not h["yf_ok"]:
            st.info("Yahoo geçici olarak yanıt vermiyor (paylaşımlı bulut IP'si için yaygın). Veriler 1–2 dakika "
                    "içinde kendiliğinden yeniden denenir; o sırada örnek veri **etiketli** gösterilir.")


# ======================================================================
# BÖLÜM: PİYASALAR
# ======================================================================
def render_chart_panel(sym):
    """Grafik paneli. Teknik özet ve destek/direnç için günlük geçmişi döndürür."""
    d = md.get_company_detail(sym)
    daily = md.get_history(sym)
    if d is None or daily.empty:
        H(f'<div class="panel-title">{esc(sym)}</div><div class="muted" style="margin:10px 0 16px 0">Bu sembol için '
          f'veri alınamadı. Yahoo Finance sembolünü kontrol et (ör. BIST için <span class="mono">THYAO.IS</span>, '
          f'parite için <span class="mono">EURUSD=X</span>) ya da birkaç dakika sonra tekrar dene.</div>')
        return None
    cur = d.get("currency") or "USD"
    dec = pdec(sym, d["last"])
    h1, h2 = st.columns([2.3, 1.45], vertical_alignment="top")
    with h1:
        H(f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">{avatar(sym, 30)}'
          f'<span class="panel-title">{esc(d["name"])}</span><span class="chip mono">{esc(sym)}</span>'
          f'{src_chip(d.get("src"))}</div>'
          f'<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-top:6px">'
          f'<span class="mono" style="font-size:32px;font-weight:600;letter-spacing:-.03em">{tr(d["last"], dec)}</span>'
          f'<span class="mono" style="color:{col(d["change_abs"])};font-weight:600;font-size:14px">'
          f'{chg(d["change_abs"], dec)} ({pct(d["change_pct"])})</span>'
          f'<span class="muted">Günlük · {esc(cur)}</span></div>')
    with h2:
        tf = seg("Zaman aralığı", list(TF_BARS), "w_tf", "1A")
        in_wl = sym in ss.watchlist
        if button("★ İzleniyor — listeden çıkar" if in_wl else "☆ İzleme listesine ekle", key="wl_toggle"):
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
        lead = f'{d["name"]}, {d["sector"]} sektöründe yer alan bir şirket.'
    meta = " · ".join(x for x in [d.get("sector"), d.get("industry"), d.get("country")] if x)
    web = (f' · <a class="lnk" href="{esc(safe_url(d.get("website")))}" target="_blank">web sitesi ↗</a>'
           if safe_url(d.get("website")) else "")
    if lead:
        H(f'<div class="desc">{esc(lead)}</div>')
    if meta or web:
        H(f'<div class="muted small" style="margin-top:4px">{esc(meta)}{web}</div>')
    if en_sum and (d.get("desc") or len(en_sum) > 260):
        with st.expander("Şirket hakkında — ayrıntılı (Yahoo Finance)"):
            H(f'<div class="desc" style="margin:0">{esc(en_sum)}</div>')
    full, bars, intr = chart_data(sym, tf)
    df = full.tail(bars)
    H(f'<div style="display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px;margin:12px 0 6px 0">'
      f'<span class="muted">Açılış <span class="mono" style="color:{TXT}">{tr(df["Open"].iloc[0], dec)}</span></span>'
      f'<span class="muted">Yüksek <span class="mono" style="color:{TXT}">{tr(df["High"].max(), dec)}</span></span>'
      f'<span class="muted">Düşük <span class="mono" style="color:{TXT}">{tr(df["Low"].min(), dec)}</span></span>'
      f'<span class="muted">Kapanış <span class="mono" style="color:{TXT}">{tr(df["Close"].iloc[-1], dec)}</span></span>'
      f'<span class="muted">{TF_NAME[tf]} · {candle_label(tf, intr)}</span><span style="flex:1"></span>'
      f'<span class="muted small">çift tık / tekerlek: yakınlaştır · sürükle: kaydır · '
      f'soldaki araçlarla çiz</span></div>')
    render_big_chart(sym, tf, height=620)
    fired = ch.check_alerts(ss.alerts.get(sym, []), daily)
    for a in fired:
        st.toast(f"🔔 {sym}: {ch.alert_text(a)} — tetiklendi")
    with st.expander("Temel veriler"):
        g = st.columns(4)
        items = [("Piyasa değeri", big(d["market_cap"], cur)), ("F/K", tr(d["pe"])), ("İleri F/K", tr(d["fwd_pe"])),
                 ("EPS", tr(d["eps"])), ("Gelir (ttm)", big(d["revenue"], cur)), ("Net kâr", big(d["net_income"], cur)),
                 ("52h aralık", f'{tr(d["low_52w"], dec)} – {tr(d["high_52w"], dec)}'), ("Beta", tr(d["beta"])),
                 ("Temettü", f'{money(d["dividend"], cur)} ({tr(d["div_yield"])}%)' if d["dividend"] else "—"),
                 ("Analist", d["analysts"]), ("Hedef fiyat", money(d["price_target"], cur)),
                 ("Bilanço", d["earnings_date"].strftime("%d.%m.%Y") if d.get("earnings_date") is not None else "—")]
        for i, (k, v) in enumerate(items):
            with g[i % 4]:
                H(f'<div class="stat-row"><span class="lbl">{esc(k)}</span><span class="mono">{esc(v)}</span></div>')
    return daily


def render_tech(df):
    t = compute_tech(df)
    H(f'<div style="display:flex;justify-content:space-between;align-items:center">'
      f'<span class="panel-title">Teknik Özet</span><span class="muted">Günlük</span></div>')
    plot(gauge((t["score"] + 6) / 12 * 100, [{"range": [0, 40], "color": DOWN},
                                             {"range": [40, 60], "color": "#2A2F37"},
                                             {"range": [60, 100], "color": UP}], 128), key="tech_gauge")
    H(f'<div style="text-align:center;font-size:24px;font-weight:800;letter-spacing:-.02em;color:{t["color"]};'
      f'margin-top:-16px">{t["label"]}</div>')
    tiles = "".join(f'<div class="tile" style="align-items:center"><span class="k">{k}</span>'
                    f'<span class="v" style="font-size:18px;color:{c}">{v}</span></div>'
                    for k, v, c in [("Sat", t["sell"], DOWN), ("Nötr", t["neutral"], NEU), ("Al", t["buy"], UP)])
    H(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0 6px 0">{tiles}</div>')
    rows = ""
    for name, val, v in t["signals"]:
        lab, fg, bg = ("Al", UP, UP_BG) if v > 0 else ("Sat", DOWN, DOWN_BG) if v < 0 else ("Nötr", NEU, NEU_BG)
        rows += (f'<div class="stat-row"><span class="lbl">{name}</span><span class="mono" style="font-size:12px">'
                 f'{val}</span><span class="badge" style="color:{fg};background:{bg};width:44px;text-align:center">'
                 f'{lab}</span></div>')
    H(rows)


def render_sr(df, sym):
    levels, price = pivots(df)
    dec = pdec(sym, price)
    cells = "".join(f'<div class="tile"><span class="k" style="color:{fg};font-weight:800">{k}</span>'
                    f'<span class="v">{tr(v, dec)}</span><span class="mono" style="font-size:11px;color:{MUT}">'
                    f'{pct((v / price - 1) * 100)}</span></div>' for k, v, fg in levels)
    H(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px">'
      f'<span class="panel-title">Destek &amp; Direnç</span><span class="muted small">Klasik pivot · son 5 gün · '
      f'son fiyat {tr(price, dec)}</span></div><div class="srstrip">{cells}</div>')


def render_watchlist_compact():
    wl = list(ss.watchlist)
    q = md.get_quotes(wl)
    add = "" if ACTIVE in wl else \
        f'<a class="lnk small" target="_self" href="{link(add_wl=ACTIVE)}">＋ {esc(ACTIVE)} ekle</a>'
    H(f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span class="panel-title">'
      f'İzleme Listesi</span><span class="chip">{len(wl)}</span><span class="muted small">tıkla → grafik</span>'
      f'<span style="margin-left:auto">{add}</span></div>')
    if not wl:
        H('<div class="muted small">Liste boş. Üstteki aramadan bir sembol bulup “İzlemeye ekle”ye bas.</div>')
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


def treemap(cons):
    fig = go.Figure(go.Treemap(
        labels=[c["ticker"] for c in cons], parents=[""] * len(cons), values=[c["weight"] for c in cons],
        text=[f'{c["name"]}<br>{pct(c["change_pct"])}' for c in cons], textinfo="label+text",
        marker=dict(colors=[max(-4, min(4, c["change_pct"])) for c in cons], cmin=-3, cmax=3, cmid=0,
                    colorscale=[[0, "#B92D37"], [0.5, "#2A2F37"], [1, "#107A57"]], line=dict(width=2, color=BG)),
        hovertemplate="<b>%{label}</b><br>%{text}<extra></extra>", textfont=dict(color="#FFFFFF", size=13),
        tiling=dict(pad=2)))
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def heat_color(ch, scale=2.5):
    a = min(1.0, 0.28 + abs(ch) / scale * 0.7)
    return f'rgba({"16,122,87" if ch >= 0 else "185,45,55"},{a:.2f})'


def render_sector_block():
    anchor("sector")
    secs = md.get_sector_performance()
    srcs = {s["src"] for s in secs}
    H(f'<div class="sec-head"><h3>Sektör Performansı</h3><span class="muted">Günlük · bir sektöre tıkla → '
      f'şirket ısı haritası</span><span style="margin-left:auto">'
      f'{src_chip("real" if srcs == {"real"} else "none" if srcs == {"none"} else "mock")}</span></div>')
    tiles = "".join(f'<a class="plain" target="_self" '
                    f'href="{link(sector=None if SECTOR == s["etf"] else s["etf"], f="sector")}">'
                    f'<div class="heat{" sel" if SECTOR == s["etf"] else ""}" style="background:{heat_color(s["change_pct"])}">'
                    f'<b>{esc(s["name"])} <span style="font-size:11px;opacity:.7;font-family:inherit">{s["etf"]}</span>'
                    f'</b><span>{pct(s["change_pct"])}</span></div></a>' for s in secs)
    H(f'<div class="heatgrid">{tiles}</div>')
    if SECTOR:
        sec = md.sector_by_etf(SECTOR)
        cons = md.get_sector_constituents(SECTOR)
        up = sum(1 for c in cons if c["change_pct"] >= 0)
        H(f'<div class="sec-head" style="margin-top:16px;flex-wrap:wrap"><h3>{esc(sec[0])} · şirket ısı haritası</h3>'
          f'<span class="muted">{SECTOR} bileşenleri · kutu büyüklüğü ≈ ETF ağırlığı · {up} yükselen / '
          f'{len(cons) - up} düşen</span><a class="lnk small" style="margin-left:auto" target="_self" '
          f'href="{link(sector=None, f="sector")}">✕ Kapat</a></div>')
        if cons:
            plot(treemap(cons), key=f"tm_{SECTOR}")
            cells = "".join(f'<a class="plain" target="_self" href="{link(sec="Piyasalar", sym=c["ticker"])}">'
                            f'<div class="heat" style="background:{heat_color(c["change_pct"], 3)}"><b>{esc(c["ticker"])}'
                            f' <span style="font-size:10px;opacity:.75;font-family:inherit">{esc(c["name"])}</span></b>'
                            f'<span>{pct(c["change_pct"])}</span></div></a>'
                            for c in sorted(cons, key=lambda c: -c["change_pct"]))
            H(f'<div class="muted small" style="margin:10px 0 6px 0">Günlük performansa göre sıralı — '
              f'şirkete tıkla → grafiği açılır</div><div class="cgrid">{cells}</div>')


def render_movers():
    h1, h2 = st.columns([1.2, 1.8], vertical_alignment="center")
    with h1:
        H('<span class="panel-title">Öne Çıkanlar</span>')
    with h2:
        tab = seg("Liste", ["Yükselenler", "Düşenler"], "w_mov", "Yükselenler")
    items = md.get_top_movers() if tab == "Yükselenler" else md.get_top_losers()
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
    H(f'<div class="page-title">Piyasalar</div><div class="muted" style="margin-bottom:8px"><span class="dot-live">'
      f'</span>{md.tr_date_label(now)} {now.year} · bir karta, satıra veya sektöre tıkla</div>')
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
            daily = render_chart_panel(ACTIVE)
        if daily is not None:
            with st.container(border=True):
                render_sr(daily, ACTIVE)
    with right:
        if daily is not None:
            with st.container(border=True):
                render_tech(daily)
        with st.container(border=True):
            render_watchlist_compact()
    b1, b2 = st.columns([2.15, 1], gap="medium")
    with b1:
        with st.container(border=True):
            render_sector_block()
    with b2:
        with st.container(border=True):
            render_movers()
    c1, c2 = st.columns([2.15, 1], gap="medium")
    with c1:
        with st.container(border=True):
            ipo = md.get_upcoming_ipos()
            H(f'<div class="sec-head"><h3>Yaklaşan Halka Arzlar</h3><span style="margin-left:auto">'
              f'{src_chip(ipo.attrs.get("src"))}</span></div>')
            table(ipo)
    with c2:
        with st.container(border=True):
            news = md.get_watchlist_news(ss.watchlist)
            H(f'<div class="sec-head"><h3>İzleme Listesi Haberleri</h3><span style="margin-left:auto">'
              f'{src_chip(news[0]["src"] if news else "none")}</span></div>')
            rows = ""
            for it in news[:8]:
                title = (f'<a href="{esc(it["link"])}" target="_blank">{esc(it["title"])}</a>'
                         if safe_url(it.get("link"))
                         else esc(it["title"]))
                sc = {"Yükseliş": UP, "Düşüş": DOWN}.get(it["sentiment"], MUT)
                rows += (f'<div class="nw"><div style="flex:1"><b>{title}</b><div class="muted small" '
                         f'style="margin-top:3px"><span style="color:{sc}">●</span> {esc(it["ticker"])} · '
                         f'{esc(it["source"])} · {esc(it["when"])}</div></div></div>')
            H(rows or '<div class="muted">Haber bulunamadı.</div>')


# ======================================================================
# BÖLÜM: LONG TERM
# ======================================================================
def render_longterm():
    H('<div class="page-title">Long Term</div><div class="muted" style="margin-bottom:12px">Uzun vadeli '
      'yatırım için duyarlılık, sektörler ve değer taraması</div>')
    fg = md.get_fear_greed()
    l, r = st.columns([1.1, 1], gap="large")
    with l:
        with st.container(border=True):
            H(f'<div class="sec-head"><h3>Fear &amp; Greed Index</h3><span style="margin-left:auto">'
              f'{src_chip(fg["src"])}</span></div><div class="muted">Piyasayı şu an hangi duygu yönetiyor?</div>')
            plot(gauge(fg["value"], [{"range": [0, 25], "color": DOWN}, {"range": [25, 45], "color": "#F0883E"},
                                     {"range": [45, 55], "color": "#D9C441"}, {"range": [55, 75], "color": "#56B06A"},
                                     {"range": [75, 100], "color": UP}], 240, number=True), key="fg_gauge")
            H(f'<div style="text-align:center;font-size:17px;font-weight:700;margin-top:-10px">{esc(fg["label"])}</div>'
              f'<div style="background:#12171f;border-left:3px solid {WARN};border-radius:8px;padding:12px 14px;'
              f'margin-top:12px;color:#c9d1d9;font-style:italic">“{esc(fg["quote"])}”<br><span class="muted" '
              f'style="font-style:normal">— {esc(fg["quote_author"])}</span></div>')
    with r:
        with st.container(border=True):
            H('<div class="panel-title">Geçmiş</div>')
            for h in fg["history"]:
                hc = DOWN if h["value"] < 45 else ("#D9C441" if h["value"] < 55 else UP)
                H(f'<div class="stat-row"><span class="lbl">{esc(h["when"])}<br><b style="color:{TXT}">'
                  f'{esc(h["label"])}</b></span><span class="mono" style="font-size:20px;font-weight:700;color:{hc}">'
                  f'{h["value"]}</span></div>')
    with st.container(border=True):
        render_sector_block()
    with st.container(border=True):
        vs = md.get_value_stocks()
        H(f'<div class="sec-head"><h3>Ucuz Şirketler (PEG / Forward PE)</h3><span class="muted">Yahoo '
          f'“undervalued large caps” taraması · Forward PE\'ye göre ucuzdan pahalıya</span>'
          f'<span style="margin-left:auto">{src_chip(vs.attrs.get("src"))}</span></div>')
        table(vs, column_config={"PEG": st.column_config.NumberColumn("PEG", format="%.2f"),
                                 "Forward PE": st.column_config.NumberColumn("Forward PE", format="%.1f"),
                                 "Profit Margin %": st.column_config.NumberColumn("Kâr marjı %", format="%.1f%%"),
                                 "EPS Büyüme %": st.column_config.NumberColumn("EPS büyüme %", format="%.1f%%")})


# ======================================================================
# BÖLÜM: SHORT TERM (Swing & Kısa Vade)
# ======================================================================
@st.cache_data(ttl=900, show_spinner="Evren taranıyor…")
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
    ss.flt_logic = "VE"
    ss.flt_name = "Trend içi geri çekilme"
    ss.flt_ver += 1


def cond_editor(rows_key, ver_key, editor_prefix):
    """Ekle / çıkar / değiştir: herhangi bir indikatör, koşul ve eşik."""
    df_in = pd.DataFrame(ss[rows_key], columns=en.COND_COLS)
    edited = st.data_editor(
        df_in, key=f"{editor_prefix}_{ss[ver_key]}", num_rows="dynamic", hide_index=True,
        **_wkw(st.data_editor),
        column_config={
            "Aktif": st.column_config.CheckboxColumn("Aktif", default=True, width="small"),
            "Gösterge": st.column_config.SelectboxColumn("Gösterge", options=en.IND_NAMES, required=True,
                                                         default="RSI (14)", width="medium"),
            "Koşul": st.column_config.SelectboxColumn("Koşul", options=en.OPS, required=True, default=">",
                                                      width="small"),
            "Karşılaştır": st.column_config.SelectboxColumn("Karşılaştır", options=en.COMPARE_OPTIONS,
                                                            required=True, default=en.NUM, width="medium",
                                                            help="Sayı → Değer sütunu kullanılır; ya da başka bir gösterge"),
            "Değer": st.column_config.NumberColumn("Değer", default=0.0, step=0.1, format="%.2f", width="small"),
        })
    rows = edited.to_dict("records")
    clean = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in rows]
    if en.normalize_conds(clean) != en.normalize_conds(ss[rows_key]) or len(clean) != len(ss[rows_key]):
        ss[rows_key] = [r for r in clean if r.get("Gösterge")]
        ss[ver_key] += 1
        st.rerun()


def render_filter_editor(n_active):
    with st.container(border=True):
        H('<div class="sec-head"><h3>Filtreyi düzenle</h3><span class="muted">Satır ekle (+), sil (satırı seç → '
          'çöp kutusu), göstergeyi/koşulu/eşiği değiştir — tarama anında güncellenir</span></div>')
        c1, c2, c3 = st.columns([2, 1.3, 1.2], vertical_alignment="bottom")
        with c1:
            st.text_input("Filtre adı", key="flt_name")
        with c2:
            st.caption("Mantık")
            seg("Mantık", ["VE", "VEYA"], "flt_logic", "VE",
                fmt=lambda x: "VE (tümü/en az N)" if x == "VE" else "VEYA (herhangi biri)")
        with c3:
            mx = max(1, n_active)
            ss.flt_min = int(min(max(1, int(ss.flt_min or 1)), mx))
            st.number_input("En az eşleşen koşul", min_value=1, max_value=mx, step=1, key="flt_min",
                            disabled=ss.flt_logic != "VE")
        cond_editor("flt_rows", "flt_ver", "flt_ed")
        b1, b2, _ = st.columns([1, 1, 3])
        with b1:
            button("Varsayılana dön", key="flt_reset", on_click=_flt_reset)
        with b2:
            if button("Kapat", key="flt_close"):
                ss.flt_edit = False
                st.rerun()
        with st.expander("İndikatör sözlüğü"):
            H("".join(f'<div class="stat-row"><span style="width:190px;font-weight:700">{esc(n)}</span>'
                      f'<span class="lbl small">{esc(m["desc"])}</span><span class="chip">{esc(m["group"])}</span></div>'
                      for n, m in en.INDICATORS.items()))


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
    for y, c_, lbl in ((o["target"], UP, "Hedef"), (o["stop"], DOWN, "Stop"), (o["mid"], ACCENT, "Giriş")):
        fig.add_hline(y=y, line=dict(color=c_, width=1, dash="dash" if lbl != "Giriş" else "dot"),
                      annotation_text=f"{lbl} {tr(y)}", annotation_position="right",
                      annotation_font=dict(color=c_, size=10))
    lo, hi = min(float(d["Low"].min()), o["stop"]), max(float(d["High"].max()), o["target"])
    fig.update_yaxes(range=[lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06])
    fig.update_layout(xaxis_rangeslider_visible=False)
    rb = _rangebreaks(d.index)
    if rb:
        fig.update_xaxes(rangebreaks=rb)
    return _layout(fig, 230, margin=dict(l=4, r=70, t=6, b=4))


def render_short():
    U = md.get_universe_history()
    hist = U["hist"]
    fkey = U["fetched"].isoformat()
    conds = en.normalize_conds(ss.flt_rows)
    active = [c for c in conds if c["Aktif"]]
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
        H(f'<div class="page-title">Swing &amp; Kısa Vade</div><div class="muted"><span class="dot-live"></span>'
          f'Son tarama {U["fetched"].strftime("%H:%M")} · {U["n"]} hisse tarandı · {md.tr_date_label(now)} '
          f'{now.year}</div>')
    with t2:
        b0, b1, b2 = st.columns([1.1, 1.2, 1.3], vertical_alignment="center")
        with b0:
            H(f'<div style="text-align:right">{src_chip(U["src"])}</div>')
        with b1:
            if button("Filtreyi kapat" if ss.flt_edit else "Filtreyi düzenle", key="btn_flt_edit"):
                ss.flt_edit = not ss.flt_edit
                st.rerun()
        with b2:
            if button("↻ Taramayı yenile", key="btn_rescan", primary=True):
                md.get_universe_history.clear()
                run_scan.clear()
                get_regime.clear()
                st.rerun()

    chips = "".join(f'<span class="crit">{esc(en.cond_text(c))}</span>' for c in active) or \
        '<span class="muted">Aktif koşul yok — tüm evren listelenir</span>'
    logic_txt = ("tümü" if min_match >= N else f"en az {min_match}/{N} koşul") if ss.flt_logic == "VE" \
        else "herhangi biri (VEYA)"
    H(f'<div class="critbar" style="margin-top:12px"><div style="display:flex;align-items:center;gap:10px">'
      f'<span class="ficon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{ACCENT}" '
      f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h18l-7 8v6l-4 2v-8z"/></svg>'
      f'</span><div><div class="boxlbl">Aktif filtre · {esc(logic_txt)}</div><div style="font-size:15px;'
      f'font-weight:800">{esc(ss.flt_name or "Filtrem")}</div></div></div><div style="display:flex;flex-wrap:wrap;'
      f'gap:6px;flex:1 1 400px">{chips}</div><a class="btlink" target="_self" href="{link(sec="Backtest", bt_from_flt="1")}">'
      f'Bu filtreyi backtest et →</a></div>')
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
          f'color:{SOFT}">Piyasa Rejimi</span><span style="font-size:11px;font-weight:800;color:{on_};'
          f'background:{fg_};border-radius:999px;padding:3px 10px">{esc(reg["badge"])}</span></div>'
          f'<span style="font-size:18px;font-weight:800">{esc(reg["label"])}</span><div style="display:flex;'
          f'flex-wrap:wrap;gap:6px 16px;font-size:12px;color:{SOFT}">{checks}</div></div>')
    with k1:
        H(f'<div class="kpi"><span class="l">Bugün eşleşen</span><span class="v">{len(opps)}</span>'
          f'<span class="s">{N} koşul · {U["n"]} hisse tarandı</span></div>')
    with k2:
        H(f'<div class="kpi"><span class="l">Ortalama R/R</span><span class="v">1 : {tr(avg_rr, 1)}</span>'
          f'<span class="s">Önerilen giriş-stop-hedef ile</span></div>')

    counts = {s: sum(1 for o in opps if o["setup"] == s) for s in en.SETUPS}
    anchor("opps")
    h1, h2, h3 = st.columns([1.3, 2.7, 1], vertical_alignment="center")
    with h1:
        H(f'<div style="display:flex;align-items:baseline;gap:10px;margin-top:10px"><span style="font-size:20px;'
          f'font-weight:800">Swing Fırsatları</span><span class="muted">{len(opps)} eşleşme</span></div>')
    with h2:
        setup = seg("Setup", ["Tümü"] + en.SETUPS, "w_setup", "Tümü",
                    fmt=lambda s: f"{s} {len(opps) if s == 'Tümü' else counts.get(s, 0)}")
    with h3:
        sort = st.selectbox("Sırala", ["Skor", "Risk / Ödül", "Günlük değişim"], key="w_sort",
                            label_visibility="collapsed")
    lst = [o for o in opps if setup == "Tümü" or o["setup"] == setup]
    keyf = {"Skor": lambda o: -o["score"], "Risk / Ödül": lambda o: -o["rr"],
            "Günlük değişim": lambda o: -(o["chg"] if o["chg"] == o["chg"] else -99)}[sort]
    lst.sort(key=keyf)
    sel = next((o for o in lst if o["ticker"] == OPP), lst[0] if lst else None)

    left, right = st.columns([2.25, 1], gap="medium")
    with left:
        head = ('<div class="opp-grid opp-head"><span>Sembol</span><span>Setup</span><span class="r">Fiyat</span>'
                '<span class="r">Giriş</span><span class="r">Stop</span><span class="r">Hedef</span>'
                '<span class="r">R/R</span><span>Skor</span></div>')
        rows = ""
        for o in lst:
            sfg, sbg = SETUP_STYLE[o["setup"]]
            ed = o.get("earn_days")
            earn = (f' <span class="badge" style="color:{WARN};background:{WARN_BG};font-size:10px">BİLANÇO '
                    f'{int(ed)}G</span>' if ed == ed and ed is not None and 0 <= ed <= 10 else "")
            sc = UP if o["score"] >= 75 else ACCENT if o["score"] >= 65 else WARN
            rows += (f'<a class="opp-grid opp-row{" sel" if sel and o["ticker"] == sel["ticker"] else ""}" '
                     f'target="_self" href="{link(opp=o["ticker"], f="opps")}">'
                     f'<span style="display:flex;align-items:center;gap:12px">{avatar(o["ticker"], 34)}'
                     f'<span style="min-width:0"><b style="font-size:14px">{esc(o["ticker"])}</b>{earn}'
                     f'<div class="muted small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                     f'{esc(o["name"])}</div></span></span>'
                     f'<span><span class="pill" style="color:{sfg};background:{sbg}">{esc(o["setup"])}</span></span>'
                     f'<span class="r"><div style="font-weight:600">{tr(o["price"])}</div><div style="font-size:11px;'
                     f'font-weight:600;color:{col(o["chg"])}">{pct(o["chg"])}</div></span>'
                     f'<span class="r" style="color:{SOFT}">{tr(o["entry_lo"])}–{tr(o["entry_hi"])}</span>'
                     f'<span class="r" style="color:{DOWN}">{tr(o["stop"])}</span>'
                     f'<span class="r" style="color:{UP}">{tr(o["target"])}</span>'
                     f'<span class="r" style="font-weight:700">{tr(o["rr"], 1)}</span>'
                     f'<span><span class="scorebar"><span style="display:block;height:6px;width:{o["score"]}%;'
                     f'background:{sc}"></span></span><span class="mono" style="font-weight:600">{o["score"]}'
                     f'</span></span></a>')
        empty = ("" if lst else f'<div style="padding:28px 18px;text-align:center" class="muted">Bu filtreyle eşleşme '
                 f'yok. “Filtreyi düzenle”den eşikleri gevşet veya “En az eşleşen koşul” sayısını düşür.</div>')
        H(f'<div class="opp"><div class="opp-scroll">{head}{rows}</div>{empty}<div class="opp-foot">'
          f'<span>Skor: filtre uyumu + trend gücü + hacim teyidi + göreli güç (0–100)</span><span style="margin-left:'
          f'auto">Giriş bölgesi, stop ve hedef ATR(14) bazlı önerilir</span></div></div>')

    with right:
        if sel:
            sfg, sbg = SETUP_STYLE[sel["setup"]]
            with st.container(border=True):
                H(f'<div style="display:flex;align-items:center;gap:12px">{avatar(sel["ticker"], 40)}<div style="flex:1;'
                  f'min-width:0"><a class="plain" target="_self" href="{link(sec="Piyasalar", sym=sel["ticker"])}">'
                  f'<b style="font-size:17px">{esc(sel["ticker"])}</b></a><div class="muted small">{esc(sel["name"])} · '
                  f'{esc(sel["sector"])}</div></div><span class="pill" style="color:{sfg};background:{sbg}">'
                  f'{esc(sel["setup"])}</span></div>')
                plot(opp_chart(hist[sel["ticker"]], sel), key=f"opp_{sel['ticker']}")
                risk_p = (sel["mid"] - sel["stop"]) / sel["mid"] * 100
                rew_p = (sel["target"] - sel["mid"]) / sel["mid"] * 100
                H(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">'
                  f'<div class="tile"><span class="k">Risk</span><span class="v" style="color:{DOWN}">'
                  f'−%{tr(risk_p)}</span></div><div class="tile"><span class="k">Potansiyel</span><span class="v" '
                  f'style="color:{UP}">+%{tr(rew_p)}</span></div><div class="tile"><span class="k">R/R</span>'
                  f'<span class="v">1 : {tr(sel["rr"], 1)}</span></div></div>')
                chk = ""
                for c in sel["checks"]:
                    ic, fg, bg = ("✓", UP, UP_BG) if c["ok"] else ("–", MUT, NEU_BG) if c["ok"] is None else \
                        ("✕", DOWN, DOWN_BG)
                    chk += (f'<div class="chk"><span class="ic" style="color:{fg};background:{bg}">{ic}</span>'
                            f'<span style="flex:1;color:{SOFT}">{esc(c["text"])}</span><span class="mono small">'
                            f'{esc(c["val"])}</span></div>')
                H(f'<div style="font-size:12px;font-weight:700;color:{SOFT};margin-top:12px;padding-bottom:4px">'
                  f'Filtre kontrol listesi · {sel["passes"]}/{sel["n"]}</div>{chk}')
            with st.container(border=True):
                H(f'<div style="display:flex;justify-content:space-between;align-items:center"><span class="panel-title">'
                  f'Pozisyon Büyüklüğü</span><span class="muted">{esc(sel["ticker"])} · giriş {tr(sel["mid"])}</span></div>')
                st.number_input("Hesap büyüklüğü ($)", min_value=0.0, step=1000.0, key="acct", format="%.0f")
                p1, p2 = st.columns([1, 1.25], vertical_alignment="center")
                with p1:
                    H('<div class="muted small">İşlem başı risk</div>')
                with p2:
                    risk_s = seg("Risk", ["%0,5", "%1", "%2"], "w_risk", "%1")
                rp = {"%0,5": 0.5, "%1": 1.0, "%2": 2.0}[risk_s]
                acct = float(ss.acct or 0)
                risk_amt = acct * rp / 100
                per = sel["mid"] - sel["stop"]
                qty = int(risk_amt // per) if per > 0 else 0
                pos_val = qty * sel["mid"]
                tiles = [("Risk edilen tutar", money(risk_amt), TXT), ("Adet", tr(qty, 0), TXT),
                         ("Pozisyon değeri", f'{money(pos_val, dec=0)} · %{tr(pos_val / acct * 100 if acct else 0, 0)}',
                          DOWN if pos_val > acct else TXT),
                         ("Hedefte kâr", "+" + money(qty * (sel["target"] - sel["mid"])), UP)]
                H(f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:6px 0 10px 0">'
                  + "".join(f'<div class="tile"><span class="k">{k}</span><span class="v" style="color:{c_}">{v}</span>'
                            f'</div>' for k, v, c_ in tiles) + '</div>')
                a1, a2 = st.columns(2)
                with a1:
                    if button("🔔 Alarm kur", key="alarm"):
                        st.toast(f"{sel['ticker']} için {tr(sel['entry_lo'])}–{tr(sel['entry_hi'])} giriş alarmı "
                                 f"not edildi (uygulama içi; bildirim servisi bağlı değil)")
                with a2:
                    if button("İşlem günlüğüne ekle", key="add_journal", primary=True):
                        if ss.journal is None:
                            ss.journal = []
                        ss.journal.append({"t": sel["ticker"], "dir": "LONG", "entry": sel["mid"], "stop": sel["stop"],
                                           "target": sel["target"], "atr": sel["atr"],
                                           "date": pd.Timestamp.today().strftime("%Y-%m-%d"), "example": False})
                        st.toast(f"{sel['ticker']} işlem günlüğüne eklendi")
        else:
            with st.container(border=True):
                H('<div class="muted">Seçili fırsat yok.</div>')

    # ---- Açık işlemlerim ----
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
        ex = ' <span class="badge" style="color:#8D96A5;background:#1A1D23;font-size:10px">örnek</span>' \
            if j.get("example") else ""
        rows += (f'<tr><td><span style="display:flex;align-items:center;gap:10px">{avatar(j["t"], 30)}<b>{esc(j["t"])}'
                 f'</b>{ex}</span></td><td style="text-align:left"><span class="badge" style="color:{UP};'
                 f'background:{UP_BG}">LONG</span></td><td style="color:{SOFT}">{tr(j["entry"])}</td>'
                 f'<td style="font-weight:600">{tr(last)}</td><td style="color:{SOFT}">{tr(trail)}</td>'
                 f'<td style="color:{MUT}">{days}g</td><td style="font-weight:600;color:{col(p_)}"><div>{pct(p_)}</div>'
                 f'<div style="font-size:11px">{chg(R, 1)}R</div></td><td style="text-align:left"><span class="prog">'
                 f'<span style="left:calc({prog:.0f}% - 7px)"></span></span></td><td><a class="lnk small" '
                 f'target="_self" href="{link(close_tr=str(i), f="journal")}">Kapat</a></td></tr>')
    month = today.strftime("%Y-%m")
    closed = [c for c in ss.journal_closed if str(c.get("closed", "")).startswith(month)]
    hit = (f'{len(closed)} · %{tr(100 * sum(1 for c in closed if c["exit"] > c["entry"]) / len(closed), 0)} isabet'
           if closed else "—")
    body = (f'<div style="overflow-x:auto"><table class="jt"><thead><tr><th>Sembol</th><th style="text-align:left">'
            f'Yön</th><th>Giriş</th><th>Son</th><th>İz süren stop</th><th>Gün</th><th>K/Z</th><th style="text-align:'
            f'left">Stop → Hedef</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>') if jr else \
        '<div class="muted" style="padding:16px 22px">Açık işlem yok. Bir fırsat seçip “İşlem günlüğüne ekle”ye bas.</div>'
    H(f'<div class="opp" style="margin-top:16px"><div style="padding:18px 22px 12px;display:flex;flex-wrap:wrap;'
      f'justify-content:space-between;align-items:center;gap:12px"><div><div class="panel-title">Açık İşlemlerim</div>'
      f'<div class="muted small">İşlem günlüğü · fiyatlar canlı, iz süren stop 2×ATR</div></div><div style="display:'
      f'flex;gap:18px;font-size:12px;color:{MUT}"><span>Açık <b class="mono" style="color:{TXT}">{len(jr)}</b></span>'
      f'<span>Toplam <b class="mono" style="color:{col(tot_r)}">{chg(tot_r, 1)}R</b></span><span>Bu ay kapanan '
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
    n = len([c for c in en.normalize_conds(ss.bt_extra) if c["Aktif"]])
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


@st.cache_data(ttl=1800, show_spinner="Backtest çalışıyor…")
def run_backtest(cfg_json, data_token=""):
    cfg = json.loads(cfg_json)
    df = md.get_history(cfg["sym"])
    if df.empty:
        return {"ok": False, "msg": f'“{cfg["sym"]}” için fiyat verisi alınamadı. Sembolü kontrol et.'}
    bench = None
    if any(c["Gösterge"] == "Göreli güç vs SPY (3 ay)" or c["Karşılaştır"] == "Göreli güç vs SPY (3 ay)"
           for c in cfg.get("extra", [])):
        bench = md.get_history("SPY")["Close"]
    res = en.backtest(df, cfg, cfg.get("extra"), bench)
    res["src"] = df.attrs.get("src", "real")
    d = md.get_company_detail(cfg["sym"]) if cfg["sym"] not in md.NAMES else None
    res["name"] = d["name"] if d else md.company_name(cfg["sym"])
    return res


def _bt_settings():
    with st.container(border=True):
        step_head(1, "Enstrüman")
        st.text_input("Sembol ara", key="bt_custom", placeholder="🔍  Endeks, hisse, parite ara (ör. tesla, GARAN.IS)",
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
                H('<div class="muted small" style="margin:2px 0 4px 0">Bulunan semboller — test edilecek olanı seç:</div>')
                seg("Bulunan semboller", opts, "bt_pick", opts[0],
                    fmt=lambda t: f"{t} · {names[t][:18]}" if names.get(t) and names[t] != t else t)
        seg("Hızlı seçim", list(QUICK), "bt_inst", "AAPL", on_change=_bt_quick_pick)
        if q_:
            H(f'<div class="muted small">Test edilecek: <b class="mono">{esc(bt_symbol())}</b> · hızlı seçime dönmek '
              f'için yukarıdaki kodlardan birine bas</div>')
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(2, "Periyot", "Günlük mumlar")
        yrs = seg("Periyot", [1, 3, 5], "bt_yrs", 3, fmt=lambda v: f"{v} yıl")
        dfh = md.get_history(bt_symbol())
        if len(dfh) > 60:
            want = int(round(yrs * 252))
            n_ = max(30, min(want, len(dfh) - 1))
            short = f" · yalnızca {n_} mum mevcut" if want > len(dfh) - 1 else ""
            H(f'<div class="mono small" style="color:{DIM}">{dfh.index[-n_]:%d.%m.%y} – {dfh.index[-1]:%d.%m.%y}'
              f'{short}</div>')
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(3, "Giriş kuralları")
        with st.container(border=True):
            H('<div class="boxlbl">İndikatör 1</div>')
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("İndikatör 1", en.IND1_OPTIONS, key="bt_ind1", label_visibility="collapsed")
            with c2:
                st.number_input("Periyot", min_value=2, max_value=100, step=1, key="bt_p1",
                                label_visibility="collapsed", disabled=ss.bt_ind1 == en.IND1_OFF)
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("Koşul", list(en.OPS1), format_func=en.OPS1.get, key="bt_op1",
                             label_visibility="collapsed", disabled=ss.bt_ind1 == en.IND1_OFF)
            with c2:
                st.number_input("Eşik", step=1.0, key="bt_v1", label_visibility="collapsed", format="%.1f",
                                disabled=ss.bt_ind1 == en.IND1_OFF)
        seg("Mantık", ["and", "or"], "bt_logic", "and", fmt=lambda x: "VE" if x == "and" else "VEYA")
        with st.container(border=True):
            c1, c2 = st.columns([2, 1], vertical_alignment="center")
            with c1:
                H('<div class="boxlbl">İndikatör 2 · Trend filtresi</div>')
            with c2:
                st.checkbox("Kullan", key="bt_c2on")
            c1, c2 = st.columns([0.7, 2], vertical_alignment="center")
            with c1:
                H('<b style="font-size:13px;color:#C4CAD4">Fiyat</b>')
            with c2:
                st.selectbox("Konum", ["above", "below"], key="bt_op2", label_visibility="collapsed",
                             format_func={"above": "üstünde", "below": "altında"}.get, disabled=not ss.bt_c2on)
            c1, c2 = st.columns([2, 1])
            with c1:
                st.selectbox("Ortalama", ["sma", "ema"], key="bt_src2", label_visibility="collapsed",
                             format_func=str.upper, disabled=not ss.bt_c2on)
            with c2:
                st.number_input("Ortalama periyodu", min_value=2, max_value=250, step=1, key="bt_p2",
                                label_visibility="collapsed", disabled=not ss.bt_c2on)
        with st.expander(f"+ Koşul ekle (MACD, Bollinger, Hacim…){f' · {len(ss.bt_extra)} ek koşul' if ss.bt_extra else ''}",
                         expanded=bool(ss.get("bt_show_extra"))):
            cond_editor("bt_extra", "bt_extra_ver", "bt_ed")
            n_ex = len([c for c in en.normalize_conds(ss.bt_extra) if c["Aktif"]])
            if n_ex >= 2:
                opts = [0] + list(range(n_ex - 1, 0, -1))
                if ss.get("bt_xmin") not in opts:
                    ss.bt_xmin = 0
                st.selectbox("Ek koşullardan kaçı sağlansın?", opts, key="bt_xmin",
                             format_func=lambda k: f"Hepsi ({n_ex}/{n_ex})" if k == 0 else f"En az {k}/{n_ex}")
            st.caption("Ek koşullar giriş sinyaline VE ile eklenir; Short işlemlerde aynen uygulanır.")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(4, "Yön")
        seg("Yön", ["long", "short", "both"], "bt_dir", "long",
            fmt={"long": "Sadece Long", "short": "Sadece Short", "both": "İkisi"}.get)
        st.caption("Short işlemlerde koşullar aynalanır (ör. RSI < 30 → RSI > 70, fiyat ortalamanın altında).")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(5, "Çıkış kuralları")
        H(f'<span style="font-size:12px;font-weight:700;color:{DOWN}">Stop loss</span>')
        c1, c2 = st.columns([2.1, 1], vertical_alignment="center")
        with c1:
            seg("Stop türü", ["pct", "atr"], "bt_slMode", "atr", fmt={"pct": "Sabit %", "atr": "ATR ×"}.get)
        with c2:
            st.number_input("Stop değeri", min_value=0.1, step=0.1, key="bt_slV", label_visibility="collapsed",
                            format="%.1f")
        H(f'<span style="font-size:12px;font-weight:700;color:{UP}">Take profit</span>')
        c1, c2 = st.columns([2.1, 1], vertical_alignment="center")
        with c1:
            seg("Kâr al türü", ["pct", "rr", "atr"], "bt_tpMode", "rr",
                fmt={"pct": "Sabit %", "rr": "R katı", "atr": "ATR ×"}.get)
        with c2:
            st.number_input("Kâr al değeri", min_value=0.1, step=0.1, key="bt_tpV", label_visibility="collapsed",
                            format="%.1f")
        st.number_input("Maks. pozisyon süresi (gün, 0 = yok)", min_value=0, step=1, key="bt_maxBars")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        step_head(6, "Sermaye & risk")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Sermaye ($)", min_value=100.0, step=1000.0, key="bt_cap", format="%.0f")
        with c2:
            st.number_input("Risk / işlem %", min_value=0.1, step=0.1, key="bt_risk", format="%.1f")
        with c3:
            st.number_input("Komisyon %", min_value=0.0, step=0.01, key="bt_comm", format="%.2f")
        H('<div class="hdr-line" style="margin:10px 0"></div>')
        r1, r2 = st.columns([1, 2])
        with r1:
            button("Sıfırla", key="bt_reset", on_click=_bt_reset)
        with r2:
            if button("▶  Backtest'i çalıştır", key="bt_run", primary=True):
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
    dirty_chip = (f'<span class="pill" style="color:{WARN};background:{WARN_BG}">Ayarlar değişti · sonuçları '
                  f'güncellemek için çalıştır</span>' if dirty else "")
    H(f'<div class="critbar">{avatar(sym, 40)}<div style="flex:1 1 300px;min-width:0"><div style="font-size:16px;'
      f'font-weight:800">{esc(res["name"])} <span class="mono muted" style="font-size:12px;font-weight:500">{esc(sym)} · '
      f'{r0.strftime("%d.%m.%y")} – {r1.strftime("%d.%m.%y")}</span></div><div class="mono small" style="color:{SOFT};'
      f'line-height:1.5">{esc(res["desc"])}</div></div>{dirty_chip}{src_chip(res["src"])}<span class="pill" '
      f'style="color:{on_};background:{fg_ if k["tone"] != "bad" else "#3A2024"}">{esc(k["verdict"])}</span></div>')
    pf = k["pf"]
    pf_s = "∞" if pf == float("inf") else tr(pf)
    n = k["n"]
    dash = "—"
    kp = [("Net kâr", money(k["net"], cur, 0), f'{pct(k["net_pct"])} · başlangıç {money(k["cap"], cur, 0)}', col(k["net"])),
          ("Kazanma oranı", f'%{tr(k["win_rate"], 1)}' if n else dash, f'{k["wins"]} kazanç · {k["losses"]} kayıp',
           UP if k["win_rate"] >= 50 else NEU),
          ("Profit factor", pf_s if n else dash, "Brüt kâr / brüt zarar", UP if pf >= 1.5 else NEU if pf >= 1 else DOWN),
          ("Maks. drawdown", f'−%{tr(abs(k["mdd"] * 100))}', "Zirveden en derin düşüş", DOWN),
          ("Gerçekleşen R/R", f'1 : {tr(k["payoff"])}' if n else dash, "Ort. kazanç / ort. kayıp",
           UP if k["payoff"] >= 1.5 else NEU),
          ("Beklenti", f'{chg(k["exp_r"])}R' if n else dash, "İşlem başına ortalama", col(k["exp_r"])),
          ("İşlem sayısı", str(n), f'Ort. {tr(k["avg_bars"], 1)} gün pozisyonda', TXT),
          ("Sharpe", tr(k["sharpe"]), f'Al & tut {pct(k["bh_pct"], 1)}', UP if k["sharpe"] >= 1 else NEU)]
    for row in (kp[:4], kp[4:]):
        cs = st.columns(4, gap="small")
        for c_, (a, b, s_, cl) in zip(cs, row):
            with c_:
                H(_kpi(a, b, s_, cl))
        H("<div style='height:8px'></div>")

    # Sermaye eğrisi + drawdown
    with st.container(border=True):
        H(f'<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px">'
          f'<span class="panel-title">Sermaye Eğrisi</span><span class="legend"><span><i style="background:{ACCENT}">'
          f'</i>Strateji</span><span><i style="background:#6B7383"></i>Al &amp; tut</span><span><i style="background:'
          f'rgba(248,113,113,.45);height:8px"></i>Drawdown</span></span></div>')
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.04)
        fig.add_trace(go.Scatter(x=res["bh"].index, y=res["bh"], mode="lines", name="Al & tut",
                                 line=dict(color="#6B7383", width=1.5, dash="dash")), 1, 1)
        fig.add_trace(go.Scatter(x=res["eq"].index, y=res["eq"], mode="lines", name="Strateji", fill="tozeroy",
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
              f'<span class="panel-title">Fiyat &amp; İşlemler</span><span class="legend"><span><i style="background:'
              f'{UP};width:9px;height:9px;border-radius:50%"></i>Long giriş</span><span><i style="background:{WARN};'
              f'width:9px;height:9px;border-radius:50%"></i>Short giriş</span><span><i style="background:transparent;'
              f'border:2px solid {TXT};width:9px;height:9px;border-radius:50%;box-sizing:border-box"></i>Çıkış</span>'
              f'<span><i style="background:{ACCENT if ma_lbl else "#3A404A"}"></i>{esc(ma_lbl or "Ortalama kapalı")}'
              f'</span></span></div>')
            fig = go.Figure(go.Scatter(x=res["price"].index, y=res["price"], mode="lines", name="Kapanış",
                                       line=dict(color=SOFT, width=1.3)))
            if res["ma"] is not None:
                fig.add_trace(go.Scatter(x=res["ma"].index, y=res["ma"], mode="lines", name=ma_lbl,
                                         line=dict(color=ACCENT, width=1.4)))
            for side, color_, nm in ((True, UP, "Long giriş"), (False, WARN, "Short giriş")):
                tt = [t for t in T if t["long"] == side]
                if tt:
                    fig.add_trace(go.Scatter(x=[t["ed"] for t in tt], y=[t["entry"] for t in tt], mode="markers",
                                             name=nm, marker=dict(color=color_, size=8)))
            if T:
                fig.add_trace(go.Scatter(x=[t["xd"] for t in T], y=[t["exit"] for t in T], mode="markers", name="Çıkış",
                                         marker=dict(color=PANEL, size=7, line=dict(color=TXT, width=2))))
            plot(_layout(fig, 250), config=CHART_CFG, key="bt_px")
    with c2:
        with st.container(border=True):
            H('<div style="display:flex;justify-content:space-between;align-items:center"><span class="panel-title">'
              'İşlem Sonuçları (R)</span><span class="muted small">Her çubuk bir işlem</span></div>')
            fig = go.Figure(go.Bar(x=list(range(1, len(T) + 1)), y=[t["R"] for t in T],
                                   marker_color=[UP if t["R"] >= 0 else DOWN for t in T], name="R"))
            fig.add_hline(y=0, line=dict(color="#3A404A", width=1))
            plot(_layout(fig, 150), key="bt_r")
            mini = [("Ort. kazanç", pct(k["avg_win_pct"]) if n else dash, UP),
                    ("Ort. kayıp", pct(k["avg_loss_pct"]) if n else dash, DOWN),
                    ("En iyi / en kötü", f'{pct(k["best"], 1)} / {pct(k["worst"], 1)}' if n else dash, TXT),
                    ("Üst üste kayıp (maks.)", str(k["max_streak"]), WARN if k["max_streak"] >= 5 else TXT)]
            H('<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">' + "".join(
                f'<div class="tile"><span class="k">{a}</span><span class="v" style="color:{c_}">{b}</span></div>'
                for a, b, c_ in mini) + '</div>')

    with st.container(border=True):
        h1, h2, h3 = st.columns([2, 1.6, 0.9], vertical_alignment="center")
        with h1:
            H(f'<span class="panel-title">İşlemler</span> <span class="muted small">{n} işlem · en yeni üstte</span>')
        with h2:
            tf = seg("İşlem filtresi", ["Tümü", "Kazanan", "Kaybeden"], "w_bttf", "Tümü")
        RS = {"TP": ("Hedef", UP, UP_BG), "SL": ("Stop", DOWN, DOWN_BG), "Süre": ("Süre doldu", WARN, WARN_BG),
              "Açık": ("Açık", NEU, NEU_BG)}
        numbered = [(i + 1, t) for i, t in enumerate(T)]
        shown = [(no, t) for no, t in numbered if tf == "Tümü" or (tf == "Kazanan") == (t["pnl"] > 0)][::-1][:150]
        with h3:
            csv = pd.DataFrame([{"#": no, "Yön": "LONG" if t["long"] else "SHORT", "Giriş tarihi": t["ed"].date(),
                                 "Giriş": round(t["entry"], 6), "Çıkış tarihi": t["xd"].date(),
                                 "Çıkış": round(t["exit"], 6), "Sebep": RS[t["reason"]][0], "Süre (gün)": t["bars"],
                                 "Getiri %": round(t["ret"], 3), "R": round(t["R"], 3), "K/Z": round(t["pnl"], 2)}
                                for no, t in numbered]).to_csv(index=False).encode("utf-8")
            st.download_button("CSV indir", csv, file_name=f"backtest_{sym}.csv", mime="text/csv", key="bt_csv",
                               **_wkw(st.download_button))
        rows = ""
        for no, t in shown:
            rs = RS[t["reason"]]
            c_ = UP if t["pnl"] > 0 else DOWN
            d_fg, d_bg = (UP, UP_BG) if t["long"] else (WARN, WARN_BG)
            rows += (f'<tr><td style="color:{MUT}">{no}</td><td style="text-align:left"><span class="badge" '
                     f'style="color:{d_fg};background:{d_bg}">{"LONG" if t["long"] else "SHORT"}</span></td>'
                     f'<td style="text-align:left;color:{SOFT}">{t["ed"].strftime("%d.%m.%y")}</td><td>{tr(t["entry"], dg)}</td>'
                     f'<td style="text-align:left;color:{SOFT}">{t["xd"].strftime("%d.%m.%y")}</td><td>{tr(t["exit"], dg)}</td>'
                     f'<td style="text-align:left"><span class="badge" style="color:{rs[1]};background:{rs[2]}">{rs[0]}'
                     f'</span></td><td style="color:{MUT}">{t["bars"]}g</td><td style="font-weight:600;color:{c_}">'
                     f'{pct(t["ret"])}</td><td style="color:{c_}">{chg(t["R"])}R</td><td style="font-weight:600;color:{c_}">'
                     f'{"+" if t["pnl"] >= 0 else ""}{money(t["pnl"], cur)}</td></tr>')
        empty = ("" if rows else '<div class="muted" style="padding:28px;text-align:center">Bu ayarlarla hiç işlem '
                 'oluşmadı. Eşik değerini gevşetmeyi veya 2. koşulu kapatmayı dene.</div>')
        H(f'<div class="tt-wrap"><table class="jt" style="min-width:820px"><thead><tr><th>#</th><th style="text-align:'
          f'left">Yön</th><th style="text-align:left">Giriş tarihi</th><th>Giriş</th><th style="text-align:left">'
          f'Çıkış tarihi</th><th>Çıkış</th><th style="text-align:left">Sebep</th><th>Süre</th><th>Getiri</th><th>R</th>'
          f'<th>K/Z</th></tr></thead><tbody>{rows}</tbody></table>{empty}</div><div class="muted small" '
          f'style="border-top:1px solid {LINE};padding-top:10px;margin-top:6px;line-height:1.5">Sinyal mum kapanışında '
          f'oluşur, işleme bir sonraki mumun açılışında girilir. Aynı mumda hem stop hem hedef görülürse stop varsayılır. '
          f'Geçmiş performans gelecek sonuçları garanti etmez.</div>')


def render_backtest():
    t1, t2 = st.columns([2.2, 2.2], vertical_alignment="bottom")
    with t1:
        H('<div class="kicker">Backtest · Find your strategy</div><div class="page-title">Strateji Laboratuvarı</div>'
          '<div class="muted">İndikatörleri birleştir, giriş-çıkış kurallarını belirle, geçmiş veride test et.</div>')
    with t2:
        b0, b1, b2 = st.columns([1.5, 1.2, 1.2], vertical_alignment="center")
        with b0:
            src = md.get_history(bt_symbol()).attrs.get("src")
            chip = ('<span class="srcchip live">● Gerçek fiyat verisiyle simülasyon</span>' if src == "real" else
                    '<span class="srcchip mock">Örnek fiyat verisiyle simülasyon</span>' if src == "mock" else
                    '<span class="srcchip none">Fiyat verisi yok</span>')
            H(f'<div style="text-align:right">{chip}</div>')
        with b2:  # önce kaydet → liste aynı çalıştırmada güncel olsun
            with st.popover("Stratejiyi kaydet", **_wkw(st.popover)):
                st.text_input("Strateji adı", key="bt_save_name", placeholder="ör. RSI dip + SMA200")
                if st.button("Kaydet", key="bt_save_btn"):
                    ss.bt_saved.append({"name": (ss.get("bt_save_name") or f"Strateji {len(ss.bt_saved) + 1}")[:60],
                                        "cfg": bt_cfg()})
                    st.toast("Strateji kaydedildi")
        with b1:
            with st.popover("Kayıtlı stratejiler", **_wkw(st.popover)):
                if not ss.bt_saved:
                    st.caption("Henüz kayıtlı strateji yok.")
                for i, s in enumerate(ss.bt_saved):
                    H(f'<div style="font-weight:800">{esc(s["name"])}</div><div class="muted small" '
                      f'style="margin-bottom:4px">{esc(s["cfg"]["sym"])} · {esc(en.describe(s["cfg"]))}</div>')
                    st.button("Yükle", key=f"bt_load_{i}", on_click=_bt_load, args=(copy.deepcopy(s["cfg"]),))
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
    H(f'<div class="page-title">Forex &amp; Haberler</div><div class="muted" style="margin-bottom:8px">'
      f'<span class="dot-live"></span>{md.tr_date_label(now)} {now.year} · saatler Berlin saatine göre</div>')
    health_panel()
    strip = md.get_macro_strip()
    cs = st.columns(6, gap="small")
    for c_, m in zip(cs, strip):
        cc = col(m["change_pct"])
        with c_:
            H(f'<div class="idx" style="padding:12px 14px"><div style="display:flex;justify-content:space-between;'
              f'align-items:baseline"><b style="font-size:12.5px">{esc(m["name"])}</b><span class="chip mono">'
              f'{m["code"]}</span></div><div class="mono" style="font-size:19px;font-weight:600;margin-top:6px">'
              f'{tr(m["value"], m["dec"])}</div><div style="display:flex;justify-content:space-between;'
              f'align-items:flex-end"><span class="mono" style="color:{cc};font-size:12px;font-weight:600">'
              f'{pct(m["change_pct"])}</span>{svg_spark(m["series"], cc, 70, 26)}</div></div>')
    H(f'<div style="margin-top:6px">{src_chip(strip[0]["src"] if strip else "none")}</div>')

    # 01 Forex piyasası
    anchor("fx")
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">01</span><h3>Forex Piyasası</h3></div>')
    meta = md.fx_meta(FX)
    left, right = st.columns([2.15, 1], gap="medium")
    with left:
        with st.container(border=True):
            daily = md.get_history(meta["symbol"])
            if len(daily) < 2:
                H('<div class="muted">Parite verisi alınamadı.</div>')
            else:
                last, prev = float(daily["Close"].iloc[-1]), float(daily["Close"].iloc[-2])
                dec = meta["dec"]
                h1, h2 = st.columns([2, 1.5], vertical_alignment="top")
                with h1:
                    H(f'<div style="display:flex;align-items:center;gap:9px">{avatar(meta["symbol"], 30)}'
                      f'<span class="panel-title">{esc(FX)}</span><span class="chip">{esc(meta["name"])}</span>'
                      f'{src_chip(daily.attrs.get("src"))}</div><div style="display:flex;align-items:baseline;gap:11px;'
                      f'margin-top:6px"><span class="mono" style="font-size:30px;font-weight:600">{tr(last, dec)}</span>'
                      f'<span class="mono" style="color:{col(last - prev)};font-weight:600;font-size:13px">'
                      f'{chg(last - prev, dec)} ({pct((last / prev - 1) * 100)})</span></div>')
                with h2:
                    tf = seg("Zaman", list(TF_BARS), "w_fxtf", "1A")
                full, bars, intr = chart_data(meta["symbol"], tf)
                d = full.tail(bars)
                H(f'<div style="display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;margin:10px 0 6px 0">'
                  f'<span class="muted">Yüksek <span class="mono" style="color:{TXT}">{tr(d["High"].max(), dec)}</span>'
                  f'</span><span class="muted">Düşük <span class="mono" style="color:{TXT}">{tr(d["Low"].min(), dec)}'
                  f'</span></span><span class="muted">{TF_NAME[tf]} · {candle_label(tf, intr)}</span>'
                  f'<span style="flex:1"></span><span class="muted small">çift tık: yakınlaştır · '
                  f'soldaki araçlarla çiz</span></div>')
                render_big_chart(meta["symbol"], tf, height=520)
                for a in ch.check_alerts(ss.alerts.get(meta["symbol"], []), daily):
                    st.toast(f"🔔 {FX}: {ch.alert_text(a)} — tetiklendi")
    with right:
        with st.container(border=True):
            H('<div class="panel-title">Pariteler</div>')
            cat = seg("Kategori", md.FX_CATEGORIES, "w_fxc", "Tümü")
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
    H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">02</span><h3>Ekonomik Takvim</h3></div>')
    with st.container(border=True):
        f1, f2, f3 = st.columns([1.4, 2, 1.6], vertical_alignment="center")
        with f2:
            day = seg("Gün", md.CAL_DAYS, "w_calday", "Bugün")
        with f3:
            imp = seg("Etki", md.CAL_IMPACTS, "w_calimp", "Tümü")
        rows = md.get_calendar_rows(day, imp)
        with f1:
            H(src_chip(rows[0]["src"] if rows else md._calendar_all()[0]["src"] if md._calendar_all() else "none"))
        out = ('<div class="cal-row" style="border:0;color:#8D96A5;font-size:11px;letter-spacing:.07em">'
               '<span style="width:120px">SAAT</span><span style="width:52px">DÖVİZ</span><span style="width:40px">ETKİ'
               '</span><span style="flex:1">ETKİNLİK</span><span style="width:90px;text-align:right">AÇIKLANAN</span>'
               '<span style="width:90px;text-align:right">BEKLENTİ</span><span style="width:90px;text-align:right">'
               'ÖNCEKİ</span></div>')
        last_day = None
        for r in rows:
            if r["day_label"] != last_day:
                out += (f'<div style="padding:8px 6px;font-size:12px;font-weight:700;color:{SOFT};border-top:1px solid '
                        f'{LINE}">{esc(r["day_label"])}</div>')
                last_day = r["day_label"]
            ic = DOWN if r["impact"] >= 3 else WARN if r["impact"] == 2 else "#6B7383"
            dots = "".join(f'<i style="background:{ic if i < r["impact"] else "#2A2F37"}"></i>' for i in range(3))
            nxt = (f' <span class="badge" style="color:#0A0B0D;background:{ACCENT};font-size:9.5px">SIRADAKİ</span>'
                   if r["next"] else "")
            out += (f'<div class="cal-row{" next" if r["next"] else ""}"><span class="mono" style="width:120px">'
                    f'{r["time"]}{nxt}</span><span style="width:52px;font-weight:700;font-size:12px">{esc(r["cur"])}</span>'
                    f'<span class="dots">{dots}</span><span style="flex:1">{esc(r["event"])}</span>'
                    f'<span class="mono" style="width:90px;text-align:right">{esc(r["actual"])}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["forecast"])}</span>'
                    f'<span class="mono muted" style="width:90px;text-align:right">{esc(r["previous"])}</span></div>')
        if not rows:
            out += f'<div class="muted" style="padding:18px 6px">Bu filtreyle etkinlik yok.</div>'
        out += (f'<div class="muted small" style="padding-top:10px"><span style="color:{DOWN}">■</span> Yüksek &nbsp;'
                f'<span style="color:{WARN}">■</span> Orta &nbsp;<span style="color:#6B7383">■</span> Düşük</div>')
        H(f'<div style="overflow-x:auto"><div style="min-width:760px">{out}</div></div>')

    # 03 Piyasa haberleri
    h1, h2 = st.columns([1, 2.2], vertical_alignment="center")
    with h1:
        H('<div class="sec-head" style="margin-top:18px"><span class="sec-no">03</span><h3>Piyasa Haberleri</h3></div>')
    with h2:
        nc = seg("Haber kategorisi", md.NEWS_CATEGORIES, "w_nc", "Tümü")
    data = md.get_forex_news(nc)
    f = data["featured"]
    l, r = st.columns([1, 1.15], gap="medium")
    sbg = {"Yükseliş": (UP, UP_BG), "Düşüş": (DOWN, DOWN_BG)}
    with l:
        fs, fb = sbg.get(f["sentiment"], (NEU, NEU_BG))
        img = (f'<img src="{esc(f["thumb"])}" alt="">' if safe_url(f.get("thumb")) else "[HABER GÖRSELİ]")
        ttl = (f'<a href="{esc(f["link"])}" target="_blank">{esc(f["title"])}</a>' if safe_url(f.get("link"))
               else esc(f["title"]))
        tags = " ".join(f'<span class="chip mono">{esc(t)}</span>' for t in f.get("tags", []))
        H(f'<div class="feat"><div class="img">{img}</div><div style="padding:16px 18px"><div style="display:flex;'
          f'align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap"><span class="badge" style="color:{fs};'
          f'background:{fb}">{esc(f["sentiment"])}</span><span class="muted small">{esc(f["category"])} · '
          f'{esc(f["source"])} · {esc(f["when"])}</span>{src_chip(data["src"])}</div><b style="font-size:20px;'
          f'line-height:1.3;display:block">{ttl}</b><div class="muted" style="margin-top:8px;line-height:1.55">'
          f'{esc(f["summary"])}</div><div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">{tags}</div>'
          f'</div></div>')
    with r:
        with st.container(border=True):
            rows = ""
            for it in data["items"]:
                sc, sb = sbg.get(it["sentiment"], (NEU, NEU_BG))
                ttl = (f'<a href="{esc(it["link"])}" target="_blank">{esc(it["title"])}</a>'
                       if safe_url(it.get("link"))
                       else esc(it["title"]))
                rows += (f'<div class="nw"><div style="width:84px;flex:none;display:flex;align-items:center;'
                         f'background:#0C0D10;border-radius:10px;padding:4px">{svg_spark(it["spark"], sc, 76, 40)}</div>'
                         f'<div style="flex:1;min-width:0"><b>{ttl}</b><div style="margin-top:5px;display:flex;'
                         f'align-items:center;gap:7px;flex-wrap:wrap"><span class="badge" style="color:{sc};'
                         f'background:{sb}">{esc(it["sentiment"])}</span><span class="muted mono small">'
                         f'{esc(it["pair"])}</span><span class="muted small">{esc(it["source"])}</span><span '
                         f'class="muted small">{esc(it["when"])}</span></div></div></div>')
            H(rows or '<div class="muted">Bu kategoride haber yok.</div>')
            st.caption("Yükseliş/Düşüş etiketi başlıktaki ifadelerden otomatik çıkarılır.")


# ======================================================================
# AKIŞ
# ======================================================================
def main():
    render_header()
    {"Piyasalar": render_piyasalar, "Long Term": render_longterm, "Short Term": render_short,
     "Backtest": render_backtest, "Forex & Haberler": render_forex}[SEC]()


try:
    main()
finally:
    _save_state()
