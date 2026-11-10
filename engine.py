"""
========================================================================
 HESAPLAMA MOTORU  (engine.py)  —  v3
========================================================================
İndikatörler, düzenlenebilir filtre motoru (swing tarayıcı), piyasa
rejimi ve backtest. Ağ erişimi ve Streamlit İÇERMEZ — saf hesaplama.

Filtre koşulu (dict) — Short Term filtresi ve Backtest ek koşulları
aynı yapıyı kullanır:
    {"Aktif": True, "Gösterge": "RSI (14)", "Koşul": "≥",
     "Karşılaştır": "Sayı" | <başka gösterge adı>, "Değer": 40.0}

Yeni bir indikatör eklemek için INDICATORS sözlüğüne bir satır ekle;
filtre editörü, arama ve backtest onu otomatik olarak tanır.
========================================================================
"""

import numpy as np
import pandas as pd

ENGINE_VERSION = "4.0"
NAN = float("nan")


# ======================================================================
# Biçim yardımcısı (Türkçe sayı)
# ======================================================================
def fmt_num(v, dec=None):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if v != v:
        return "—"
    if dec is None:
        if abs(v - round(v)) < 1e-9:
            dec = 0
        elif abs(v * 10 - round(v * 10)) < 1e-9:
            dec = 1
        else:
            dec = 2
    return f"{v:,.{dec}f}"


def _last(s):
    try:
        v = s.iloc[-1]
        return float(v) if pd.notna(v) else NAN
    except Exception:
        return NAN


def _ok(x):
    return x == x and x is not None


# ======================================================================
# Temel indikatör serileri
# ======================================================================
def sma(s, n):
    n = int(n)
    return s.rolling(n, min_periods=n).mean()


def ema(s, n):
    n = int(n)
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close, n=14):
    n = int(n)
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(~((dn == 0) & up.notna()), 100.0)


def stoch_k(df, n=14):
    n = int(n)
    hh = df["High"].rolling(n, min_periods=n).max()
    ll = df["Low"].rolling(n, min_periods=n).min()
    return (df["Close"] - ll) / (hh - ll).replace(0, np.nan) * 100


def williams_r(df, n=14):
    n = int(n)
    hh = df["High"].rolling(n, min_periods=n).max()
    ll = df["Low"].rolling(n, min_periods=n).min()
    return (hh - df["Close"]) / (hh - ll).replace(0, np.nan) * -100


def cci(df, n=20):
    n = int(n)
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    ma = tp.rolling(n, min_periods=n).mean()
    md = tp.rolling(n, min_periods=n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def mfi(df, n=14):
    n = int(n)
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    mf = tp * df["Volume"].astype(float)
    up = mf.where(tp > tp.shift(), 0.0)
    dn = mf.where(tp < tp.shift(), 0.0)
    r = up.rolling(n, min_periods=n).sum() / dn.rolling(n, min_periods=n).sum().replace(0, np.nan)
    return 100 - 100 / (1 + r)


def macd(close, f=12, s=26, sig=9):
    line = close.ewm(span=f, adjust=False).mean() - close.ewm(span=s, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def atr(df, n=14):
    n = int(n)
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def boll_pctb(close, n=20, k=2.0):
    m = sma(close, n)
    sd = close.rolling(int(n), min_periods=int(n)).std()
    up, lo = m + k * sd, m - k * sd
    return (close - lo) / (up - lo).replace(0, np.nan)


def relvol(df, n=20):
    v = df["Volume"].astype(float)
    return v / v.rolling(int(n), min_periods=int(n)).mean().replace(0, np.nan)


def pct_ret(close, n):
    return (close / close.shift(int(n)) - 1) * 100


def _bench_rs(df, ctx, n=63):
    b = ctx.get("bench") if ctx else None
    if b is None or len(b) == 0:
        return pd.Series(np.nan, index=df.index)
    b = b.reindex(df.index.union(b.index)).ffill().reindex(df.index)
    return pct_ret(df["Close"], n) - pct_ret(b, n)


def _const(df, v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = NAN
    return pd.Series(v, index=df.index, dtype=float)


# ======================================================================
# İNDİKATÖR KATALOĞU — filtre editörü, arama ve backtest buradan okur
#   kind: price | osc | pct | ratio | days  (değer biçimlendirme için)
# ======================================================================
INDICATORS = {
    "Price": {"fn": lambda df, ctx: df["Close"], "group": "Price", "kind": "price",
              "desc": "Last closing price."},
    "SMA 20": {"fn": lambda df, ctx: sma(df["Close"], 20), "group": "Trend", "kind": "price",
               "desc": "20-day simple moving average — short-term trend."},
    "SMA 50": {"fn": lambda df, ctx: sma(df["Close"], 50), "group": "Trend", "kind": "price",
               "desc": "50-day simple moving average — the medium-term trend swing traders watch most."},
    "SMA 200": {"fn": lambda df, ctx: sma(df["Close"], 200), "group": "Trend", "kind": "price",
                "desc": "200-day average — price above it is considered a long-term bull regime."},
    "EMA 20": {"fn": lambda df, ctx: ema(df["Close"], 20), "group": "Trend", "kind": "price",
               "desc": "20-day exponential average — gives more weight to recent prices."},
    "EMA 50": {"fn": lambda df, ctx: ema(df["Close"], 50), "group": "Trend", "kind": "price",
               "desc": "50-day exponential average."},
    "RSI (14)": {"fn": lambda df, ctx: rsi(df["Close"], 14), "group": "Momentum", "kind": "osc",
                 "desc": "Relative Strength Index (0–100). Above 70 overbought, below 30 oversold; "
                         "the 40–60 band points to a pullback within a trend."},
    "Stochastic %K (14)": {"fn": lambda df, ctx: stoch_k(df, 14), "group": "Momentum", "kind": "osc",
                          "desc": "Where the close sits in the last 14-day range (0–100). Above 80 overbought, "
                                  "below 20 oversold."},
    "Williams %R (14)": {"fn": lambda df, ctx: williams_r(df, 14), "group": "Momentum", "kind": "osc",
                         "desc": "Between −100 and 0. Above −20 overbought, below −80 oversold."},
    "CCI (20)": {"fn": lambda df, ctx: cci(df, 20), "group": "Momentum", "kind": "osc",
                 "desc": "Commodity Channel Index. Above +100 strong uptrend, below −100 strong downtrend."},
    "MFI (14)": {"fn": lambda df, ctx: mfi(df, 14), "group": "Volume", "kind": "osc",
                 "desc": "Money Flow Index — volume-weighted RSI (0–100). Above 80 overbought, below 20 oversold."},
    "MACD line": {"fn": lambda df, ctx: macd(df["Close"])[0], "group": "Momentum", "kind": "price",
                     "desc": "EMA 12 − EMA 26. Above zero is upward momentum."},
    "MACD signal": {"fn": lambda df, ctx: macd(df["Close"])[1], "group": "Momentum", "kind": "price",
                    "desc": "9-day exponential average of the MACD line."},
    "MACD histogram": {"fn": lambda df, ctx: macd(df["Close"])[2], "group": "Momentum", "kind": "price",
                       "desc": "MACD − signal. Crossing above zero shows buying momentum starting."},
    "Bollinger %B (20,2)": {"fn": lambda df, ctx: boll_pctb(df["Close"]), "group": "Volatility", "kind": "ratio",
                            "desc": "Where price sits inside the Bollinger band: 0 lower band, 1 upper band. "
                                    "Below 0 oversold, above 1 overbought."},
    "ATR % (14)": {"fn": lambda df, ctx: atr(df, 14) / df["Close"] * 100, "group": "Volatility", "kind": "pct",
                   "desc": "Average true range as a share of price — a measure of daily volatility."},
    "Relative volume (20d)": {"fn": lambda df, ctx: relvol(df, 20), "group": "Volume", "kind": "ratio",
                           "desc": "Today's volume / 20-day average volume. Above 1.5 means strong interest."},
    "Daily change %": {"fn": lambda df, ctx: pct_ret(df["Close"], 1), "group": "Returns", "kind": "pct",
                         "desc": "Percent change on the last day."},
    "1W return %": {"fn": lambda df, ctx: pct_ret(df["Close"], 5), "group": "Returns", "kind": "pct",
                         "desc": "Return over the last 5 trading days."},
    "1M return %": {"fn": lambda df, ctx: pct_ret(df["Close"], 21), "group": "Returns", "kind": "pct",
                      "desc": "Return over the last 21 trading days (momentum)."},
    "3M return %": {"fn": lambda df, ctx: pct_ret(df["Close"], 63), "group": "Returns", "kind": "pct",
                      "desc": "Return over the last 63 trading days."},
    "Distance to 52W high %": {"fn": lambda df, ctx: (df["Close"] / df["High"].rolling(252, min_periods=20).max() - 1) * 100,
                              "group": "Trend", "kind": "pct",
                              "desc": "Distance from the 52-week high in percent (0 = at the high, −10 = 10% below it)."},
    "Relative strength vs SPY (3M)": {"fn": lambda df, ctx: _bench_rs(df, ctx, 63), "group": "Relative strength", "kind": "pct",
                                 "desc": "Stock return over the last 3 months − S&P 500 (SPY) return (points). "
                                         "Positive means stronger than the index."},
    "Days to earnings": {"fn": lambda df, ctx: _const(df, (ctx or {}).get("earn_days", NAN)),
                            "group": "Calendar", "kind": "days",
                            "desc": "Days until the next earnings report (empty if no data)."},
}
IND_NAMES = list(INDICATORS)

ALIASES = {
    "rsi": "RSI (14)", "macd": "MACD histogram", "stoch": "Stochastic %K (14)",
    "stochastic": "Stochastic %K (14)", "bollinger": "Bollinger %B (20,2)", "boll": "Bollinger %B (20,2)",
    "atr": "ATR % (14)", "volatility": "ATR % (14)", "volatility": "ATR % (14)",
    "volume": "Relative volume (20d)", "volume": "Relative volume (20d)", "sma": "SMA 50", "ema": "EMA 20",
    "average": "SMA 50", "moving average": "SMA 50", "cci": "CCI (20)", "mfi": "MFI (14)",
    "williams": "Williams %R (14)", "momentum": "1M return %", "return": "1M return %",
    "balance sheet": "Days to earnings", "bilanco": "Days to earnings", "earnings": "Days to earnings",
    "relative strength": "Relative strength vs SPY (3M)", "relative strength": "Relative strength vs SPY (3M)",
    "rs": "Relative strength vs SPY (3M)", "peak": "Distance to 52W high %", "52": "Distance to 52W high %",
    "price": "Price", "price": "Price",
}


def find_indicators(q):
    """İsim eşleşmeleri önce, sonra takma adlar, en son grup eşleşmeleri."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    out = []

    def add(n):
        if n not in out:
            out.append(n)

    for n in IND_NAMES:
        if q in n.lower():
            add(n)
    for k, v in ALIASES.items():
        if q in k or (len(k) >= 3 and k in q):
            add(v)
    for n in IND_NAMES:
        if q in INDICATORS[n]["group"].lower():
            add(n)
    return out[:8]


# Bilanço takvimi gerçek veriyle geldiğinde, pencerede (3 hafta) bilançosu
# olmayan hisseler bu değeri alır → "Bilançoya kalan gün > 10" koşulunu geçer.
EARN_FAR = 99.0


def fmt_ind_value(name, v):
    if v is None or v != v:
        return "no data"
    kind = INDICATORS.get(name, {}).get("kind", "price")
    if kind == "osc":
        return fmt_num(v, 1)
    if kind == "pct":
        return ("+" if v >= 0 else "−") + fmt_num(abs(v), 1) + "%"
    if kind == "ratio":
        return fmt_num(v, 2) + ("×" if "volume" in name.lower() else "")
    if kind == "days":
        return "3+ weeks" if v >= EARN_FAR else f"{int(round(v))} days"
    return fmt_num(v, 2)


# ======================================================================
# KOŞUL MOTORU
# ======================================================================
OPS = ["<", ">", "≤", "≥", "crosses above", "crosses below"]
NUM = "Number"
COMPARE_OPTIONS = [NUM] + IND_NAMES
COND_COLS = ["Active", "Indicator", "Condition", "Compare", "Value"]

DEFAULT_FILTER = [
    {"Active": True, "Indicator": "Price", "Condition": ">", "Compare": "SMA 50", "Value": 0.0},
    {"Active": True, "Indicator": "SMA 50", "Condition": ">", "Compare": "SMA 200", "Value": 0.0},
    {"Active": True, "Indicator": "RSI (14)", "Condition": "≥", "Compare": NUM, "Value": 40.0},
    {"Active": True, "Indicator": "RSI (14)", "Condition": "≤", "Compare": NUM, "Value": 60.0},
    {"Active": True, "Indicator": "Relative volume (20d)", "Condition": ">", "Compare": NUM, "Value": 1.5},
    {"Active": True, "Indicator": "Relative strength vs SPY (3M)", "Condition": ">", "Compare": NUM, "Value": 0.0},
]

# Bir indikatör filtreye/backtest'e eklendiğinde mantıklı varsayılan koşul
SUGGESTED = {
    "RSI (14)": (">", NUM, 50.0), "Stochastic %K (14)": ("<", NUM, 20.0),
    "Williams %R (14)": ("<", NUM, -80.0), "CCI (20)": (">", NUM, 100.0), "MFI (14)": ("<", NUM, 20.0),
    "MACD histogram": ("crosses above", NUM, 0.0), "MACD line": (">", "MACD signal", 0.0),
    "MACD signal": ("<", "MACD line", 0.0), "Bollinger %B (20,2)": ("<", NUM, 0.0),
    "ATR % (14)": ("<", NUM, 4.0), "Relative volume (20d)": (">", NUM, 1.5),
    "Daily change %": (">", NUM, 0.0), "1W return %": (">", NUM, 0.0),
    "1M return %": (">", NUM, 5.0), "3M return %": (">", NUM, 10.0),
    "Distance to 52W high %": (">", NUM, -10.0), "Relative strength vs SPY (3M)": (">", NUM, 0.0),
    "Days to earnings": (">", NUM, 10.0), "Price": (">", "SMA 50", 0.0),
    "SMA 20": ("<", "Price", 0.0), "SMA 50": (">", "SMA 200", 0.0), "SMA 200": ("<", "Price", 0.0),
    "EMA 20": ("<", "Price", 0.0), "EMA 50": ("<", "Price", 0.0),
}


def suggested_condition(name):
    op, cmp_, val = SUGGESTED.get(name, (">", NUM, 0.0))
    return {"Active": True, "Indicator": name, "Condition": op, "Compare": cmp_, "Value": float(val)}


def normalize_conds(rows):
    out = []
    for r in rows or []:
        try:
            if not isinstance(r, dict):
                continue
            g, k = r.get("Indicator"), r.get("Condition")
            c = r.get("Compare") or NUM
            if g not in INDICATORS or k not in OPS or (c != NUM and c not in INDICATORS):
                continue
            v = r.get("Value")
            try:
                v = float(v)
                if v != v:
                    v = 0.0
            except (TypeError, ValueError):
                v = 0.0
            a = r.get("Active")
            a = True if a is None or a != a else bool(a)
            out.append({"Active": a, "Indicator": g, "Condition": k, "Compare": c, "Value": v})
        except Exception:
            continue
    return out


def cond_text(c):
    rhs = c["Compare"] if c["Compare"] != NUM else fmt_num(c["Value"])
    return f'{c["Indicator"]} {c["Condition"]} {rhs}'


def needed(conds):
    s = set()
    for c in conds:
        s.add(c["Indicator"])
        if c["Compare"] != NUM:
            s.add(c["Compare"])
    return s


def compute_series(df, names, ctx=None):
    ctx = ctx or {}
    out = {}
    for n in names:
        if n in out or n not in INDICATORS:
            continue
        try:
            out[n] = INDICATORS[n]["fn"](df, ctx).astype(float)
        except Exception:
            out[n] = pd.Series(np.nan, index=df.index)
    return out


def _rhs(c, S, index):
    if c["Compare"] == NUM:
        return pd.Series(float(c["Value"]), index=index)
    return S[c["Compare"]]


def eval_series(c, S):
    """Koşulun her bar için doğru/yanlış serisi (backtest)."""
    L = S[c["Indicator"]]
    R = _rhs(c, S, L.index)
    op = c["Condition"]
    if op == "<":
        m = L < R
    elif op == ">":
        m = L > R
    elif op == "≤":
        m = L <= R
    elif op == "≥":
        m = L >= R
    elif op == "crosses above":
        m = (L.shift() < R.shift()) & (L >= R)
    else:
        m = (L.shift() > R.shift()) & (L <= R)
    valid = L.notna() & R.notna()
    if op in ("crosses above", "crosses below"):
        valid &= L.shift().notna() & R.shift().notna()
    return (m & valid).fillna(False).astype(bool)


def eval_last(c, S):
    """Son bar için (durum, sol değer, sağ değer). Veri yoksa durum None."""
    L = S[c["Indicator"]]
    R = _rhs(c, S, L.index)
    if len(L) < 2:
        return None, NAN, NAN
    l1, r1, l0, r0 = L.iloc[-1], R.iloc[-1], L.iloc[-2], R.iloc[-2]
    if pd.isna(l1) or pd.isna(r1):
        return None, float(l1) if pd.notna(l1) else NAN, float(r1) if pd.notna(r1) else NAN
    op = c["Condition"]
    if op == "<":
        ok = l1 < r1
    elif op == ">":
        ok = l1 > r1
    elif op == "≤":
        ok = l1 <= r1
    elif op == "≥":
        ok = l1 >= r1
    else:
        if pd.isna(l0) or pd.isna(r0):
            return None, float(l1), float(r1)
        ok = (l0 < r0 and l1 >= r1) if op == "crosses above" else (l0 > r0 and l1 <= r1)
    return bool(ok), float(l1), float(r1)


# ======================================================================
# SWING TARAYICI
# ======================================================================
SETUPS = ["Pullback", "Breakout", "Support bounce", "Momentum"]
BASE_NEEDS = ["Price", "SMA 50", "SMA 200", "EMA 20", "RSI (14)", "Relative volume (20d)",
              "1M return %", "Relative strength vs SPY (3M)", "Daily change %"]


def classify_setup(df, S):
    c = _last(S["Price"])
    o = float(df["Open"].iloc[-1])
    hi20 = float(df["High"].iloc[-21:-1].max()) if len(df) > 21 else NAN
    lo60 = float(df["Low"].iloc[-60:].min())
    rv, r = _last(S["Relative volume (20d)"]), _last(S["RSI (14)"])
    m1, e20, s50 = _last(S["1M return %"]), _last(S["EMA 20"]), _last(S["SMA 50"])
    if _ok(hi20) and c >= hi20 * 0.995 and (not _ok(rv) or rv >= 1.2):
        return "Breakout"
    if _ok(r) and _ok(m1) and r >= 60 and m1 >= 8:
        return "Momentum"
    if c <= lo60 * 1.06 and c > o:
        return "Support bounce"
    if _ok(s50) and _ok(e20) and c > s50 and abs(c / e20 - 1) <= 0.03:
        return "Pullback"
    return "Momentum" if (_ok(r) and r >= 55) else "Pullback"


def trade_levels(setup, df, S, a):
    """ATR(14) bazlı giriş bölgesi, stop ve hedef önerisi."""
    c = _last(S["Price"])
    if not _ok(a) or a <= 0:
        a = c * 0.02
    e20 = _last(S["EMA 20"])
    e20 = e20 if _ok(e20) else c
    lo20 = float(df["Low"].tail(20).min())
    if setup == "Breakout":
        lo, hi = c - 0.2 * a, c + 0.2 * a
        mid = (lo + hi) / 2
        stop, tgt = mid - 1.5 * a, mid + 3.5 * a
    elif setup == "Pullback":
        base = min(c, e20)
        lo, hi = base - 0.2 * a, base + 0.3 * a
        mid = (lo + hi) / 2
        stop, tgt = lo - 1.2 * a, mid + 3.0 * a
    elif setup == "Support bounce":
        lo, hi = c - 0.3 * a, c + 0.1 * a
        mid = (lo + hi) / 2
        stop, tgt = min(lo20 - 0.3 * a, mid - 1.0 * a), mid + 2.5 * a
    else:  # Momentum
        lo, hi = c - 0.4 * a, c
        mid = (lo + hi) / 2
        stop, tgt = mid - 1.6 * a, mid + 3.2 * a
    rr = (tgt - mid) / max(mid - stop, 1e-9)
    return {"entry_lo": lo, "entry_hi": hi, "mid": mid, "stop": stop, "target": tgt, "rr": rr, "atr": a}


def _score(fit, S):
    c, s50, s200 = _last(S["Price"]), _last(S["SMA 50"]), _last(S["SMA 200"])
    trend = 0.5 * (1 if _ok(s50) and c > s50 else 0) + 0.5 * (1 if _ok(s50) and _ok(s200) and s50 > s200 else 0)
    rv = _last(S["Relative volume (20d)"])
    vol = min(max((rv - 0.6) / 1.4, 0), 1) if _ok(rv) else 0.3
    rs = _last(S["Relative strength vs SPY (3M)"])
    rsc = min(max((rs + 10) / 20, 0), 1) if _ok(rs) else 0.5
    return int(round(100 * (0.5 * fit + 0.25 * trend + 0.15 * vol + 0.10 * rsc)))


def scan(hist, conds, logic="AND", min_match=None, bench=None, earn_days=None, names=None):
    """Evren üzerinde filtreyi çalıştırır, eşleşenleri setup/seviye/skorla döndürür.
    hist: {ticker: OHLCV DataFrame}; conds: koşul listesi (normalize edilir)."""
    names = names or {}
    earn_days = earn_days or {}
    active = [c for c in normalize_conds(conds) if c["Active"]]
    N = len(active)
    need = set(BASE_NEEDS) | needed(active)
    need_min = N if not min_match else max(1, min(int(min_match), N))
    out = []
    for t, df in hist.items():
        if t == "SPY" or df is None or len(df) < 60:
            continue
        ctx = {"bench": bench, "earn_days": earn_days.get(t, NAN)}
        S = compute_series(df, need, ctx)
        checks, passes = [], 0
        for c in active:
            st_, lv, _rv = eval_last(c, S)
            checks.append({"text": cond_text(c), "ok": st_, "val": fmt_ind_value(c["Indicator"], lv)})
            passes += 1 if st_ else 0
        if N:
            ok = passes >= 1 if logic == "OR" else passes >= need_min
            if not ok:
                continue
        a = _last(atr(df, 14))
        setup = classify_setup(df, S)
        lv = trade_levels(setup, df, S, a)
        fit = passes / N if N else 1.0
        nm, sec = names.get(t, (t, ""))
        out.append({
            "ticker": t, "name": nm, "sector": sec, "setup": setup,
            "price": _last(S["Price"]), "chg": _last(S["Daily change %"]),
            **lv, "score": _score(fit, S), "passes": passes, "n": N, "checks": checks,
            "rsi": _last(S["RSI (14)"]), "relvol": _last(S["Relative volume (20d)"]),
            "rs": _last(S["Relative strength vs SPY (3M)"]), "earn_days": earn_days.get(t, NAN),
            "src": df.attrs.get("src", "real"),
        })
    out.sort(key=lambda x: -x["score"])
    return out


# ======================================================================
# PİYASA REJİMİ
# ======================================================================
def market_regime(spy_df=None, vix=None, pct_above50=None, leader=None):
    checks, above, low = [], None, None
    if spy_df is not None and len(spy_df) >= 200:
        c = float(spy_df["Close"].iloc[-1])
        s200 = float(sma(spy_df["Close"], 200).iloc[-1])
        above = c > s200
        checks.append({"t": "SPX > SMA 200" if above else "SPX < SMA 200", "ok": above})
    if vix is not None and _ok(vix):
        low = vix < 20
        checks.append({"t": f"VIX {fmt_num(vix, 1)} · {'below' if low else 'above'} 20", "ok": low})
    if pct_above50 is not None and _ok(pct_above50):
        checks.append({"t": f"Share of stocks above SMA 50: {fmt_num(pct_above50, 0)}%",
                       "ok": pct_above50 >= 50})
    if leader:
        checks.append({"t": f"Leading sector: {leader}", "ok": True})
    if above and low is not False:
        label, badge, tone = "Uptrend · low volatility", "GOOD FOR SWING", "good"
    elif above:
        label, badge, tone = "Uptrend · high volatility", "CAUTIOUS", "warn"
    elif above is False and low:
        label, badge, tone = "Weak trend · low volatility", "BE SELECTIVE", "warn"
    elif above is False:
        label, badge, tone = "Downtrend · high volatility", "DEFENSIVE", "bad"
    else:
        label, badge, tone = "No regime data", "—", "warn"
    return {"label": label, "badge": badge, "tone": tone, "checks": checks}


# ======================================================================
# BACKTEST — tasarımdaki Strateji Laboratuvarı'nın birebir portu
# Sinyal mum kapanışında oluşur, giriş bir sonraki mumun açılışında.
# Aynı mumda stop ve hedef görülürse stop varsayılır.
# ======================================================================
IND1 = {
    "RSI": {"fn": lambda df, p: rsi(df["Close"], p), "mirror": lambda v: 100 - v},
    "Stochastic %K": {"fn": lambda df, p: stoch_k(df, p), "mirror": lambda v: 100 - v},
    "MFI": {"fn": lambda df, p: mfi(df, p), "mirror": lambda v: 100 - v},
    "Williams %R": {"fn": lambda df, p: williams_r(df, p), "mirror": lambda v: -100 - v},
    "CCI": {"fn": lambda df, p: cci(df, p), "mirror": lambda v: -v},
}
IND1_OFF = "— (none)"
IND1_OPTIONS = list(IND1) + [IND1_OFF]
OPS1 = {"lt": "below (<)", "gt": "above (>)", "xup": "crosses above", "xdn": "crosses below"}
OPS1_SHORT = {"lt": "<", "gt": ">", "xup": "↗ crosses", "xdn": "↘ crosses"}
_MIR = {"lt": "gt", "gt": "lt", "xup": "xdn", "xdn": "xup"}

BT_DEFAULTS = {"yrs": 3, "ind1": "RSI", "p1": 14, "op1": "lt", "v1": 30.0, "logic": "and",
               "c2on": True, "src2": "sma", "p2": 200, "op2": "above", "dir": "long",
               "slMode": "atr", "slV": 2.0, "tpMode": "rr", "tpV": 2.0, "maxBars": 0,
               "cap": 10000.0, "risk": 1.0, "comm": 0.1, "extra_min": 0}


def _extra_need(cfg, n):
    """Ek koşullardan en az kaçı sağlanmalı (0/boş = hepsi)."""
    try:
        k = int(cfg.get("extra_min") or 0)
    except (TypeError, ValueError):
        k = 0
    return n if k <= 0 or k >= n else k


def describe(cfg):
    cfg = {**BT_DEFAULTS, **(cfg or {})}
    parts = []
    if cfg["ind1"] in IND1:
        parts.append(f'{cfg["ind1"]}({int(cfg["p1"])}) {OPS1_SHORT.get(cfg["op1"], "<")} {fmt_num(cfg["v1"])}')
    if cfg["c2on"]:
        parts.append(f'Price {">" if cfg["op2"] == "above" else "<"} {str(cfg["src2"]).upper()}({int(cfg["p2"])})')
    s = (" AND " if cfg["logic"] == "and" else " OR ").join(parts)
    ex = [cond_text(c) for c in normalize_conds(cfg.get("extra")) if c["Active"]]
    if ex:
        k = _extra_need(cfg, len(ex))
        joined = " AND ".join(ex) if k == len(ex) else f"[at least {k}/{len(ex)}: " + " · ".join(ex) + "]"
        s = (s + " AND " if s else "") + joined
    s = s or "No conditions"
    s += " · " + {"long": "Long", "short": "Short", "both": "Long + Short"}.get(cfg["dir"], "Long")
    s += " · SL " + (f'{fmt_num(cfg["slV"], 1)}%' if cfg["slMode"] == "pct" else f'{fmt_num(cfg["slV"], 1)}×ATR')
    if cfg["tpMode"] == "pct":
        s += f' · TP {fmt_num(cfg["tpV"], 1)}%'
    elif cfg["tpMode"] == "rr":
        s += f' · TP {fmt_num(cfg["tpV"], 1)}R'
    else:
        s += f' · TP {fmt_num(cfg["tpV"], 1)}×ATR'
    if int(cfg["maxBars"]) > 0:
        s += f' · max. {int(cfg["maxBars"])}d'
    return s


def backtest(df, cfg, extra=None, bench=None):
    cfg = {**BT_DEFAULTS, **(cfg or {})}
    if extra is None:
        extra = cfg.get("extra")
    cfg["extra"] = normalize_conds(extra)
    if df is None or len(df) == 0:
        return {"ok": False, "msg": "No price data."}
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    total = len(df)
    if total < 60:
        return {"ok": False, "msg": "Not enough price data (at least 60 candles needed)."}
    N = int(round(float(cfg["yrs"]) * 252))
    N = max(30, min(N, total - 1))
    start = total - N
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    dates = df.index
    p1, p2 = max(2, int(cfg["p1"])), max(2, int(cfg["p2"]))
    use1 = cfg["ind1"] in IND1
    ind1 = IND1[cfg["ind1"]]["fn"](df, p1).to_numpy(dtype=float) if use1 else None
    ma = (ema if cfg["src2"] == "ema" else sma)(df["Close"], p2).to_numpy(dtype=float)
    av = atr(df, 14).to_numpy(dtype=float)
    extra_c = [x for x in normalize_conds(extra) if x["Active"]]
    emask = None
    if extra_c:
        S = compute_series(df, needed(extra_c), {"bench": bench})
        cnt = np.zeros(total, dtype=int)
        for x in extra_c:
            cnt += eval_series(x, S).to_numpy().astype(int)
        emask = cnt >= _extra_need(cfg, len(extra_c))
    has_any = use1 or bool(cfg["c2on"]) or bool(extra_c)
    thr1 = float(cfg["v1"])
    thr1_s = IND1[cfg["ind1"]]["mirror"](thr1) if use1 else NAN

    def test(op, v, pv, t):
        if v != v or t != t:
            return False
        if op == "lt":
            return v < t
        if op == "gt":
            return v > t
        if pv != pv:
            return False
        if op == "xup":
            return pv < t <= v
        return pv > t >= v

    def signal(i, long):
        if not has_any:
            return False
        parts = []
        if use1:
            op = cfg["op1"] if long else _MIR.get(cfg["op1"], "gt")
            parts.append(test(op, ind1[i], ind1[i - 1], thr1 if long else thr1_s))
        if cfg["c2on"]:
            if ma[i] != ma[i]:
                parts.append(False)
            else:
                above, want = c[i] > ma[i], cfg["op2"] == "above"
                parts.append(above == want if long else above != want)
        main = (all(parts) if cfg["logic"] == "and" else any(parts)) if parts else True
        if emask is not None:
            main = main and bool(emask[i])
        return main

    cap = max(100.0, float(cfg["cap"]))
    risk_pct = max(0.01, float(cfg["risk"])) / 100
    comm = max(0.0, float(cfg["comm"])) / 100
    max_bars = int(cfg["maxBars"])
    cash, pos, trades = cap, None, []
    eq = np.full(total, cap, dtype=float)

    def close_pos(i, px, reason):
        nonlocal cash, pos
        sg = 1 if pos["long"] else -1
        gross = sg * (px - pos["entry"]) * pos["qty"]
        fees = comm * (pos["entry"] + px) * pos["qty"]
        pnl = gross - fees
        cash += pnl
        trades.append({"long": pos["long"], "ei": pos["ei"], "xi": i, "entry": pos["entry"], "exit": px,
                       "reason": reason, "pnl": pnl,
                       "ret": (sg * (px - pos["entry"]) / pos["entry"] - comm * (pos["entry"] + px) / pos["entry"]) * 100,
                       "R": pnl / pos["risk_amt"] if pos["risk_amt"] else 0.0, "bars": i - pos["ei"] + 1})
        pos = None

    for i in range(max(start, 1), total):
        if pos is not None and i >= pos["ei"]:
            if pos["long"]:
                if l[i] <= pos["sl"]:
                    close_pos(i, min(o[i], pos["sl"]), "SL")
                elif h[i] >= pos["tp"]:
                    close_pos(i, max(o[i], pos["tp"]), "TP")
            else:
                if h[i] >= pos["sl"]:
                    close_pos(i, max(o[i], pos["sl"]), "SL")
                elif l[i] <= pos["tp"]:
                    close_pos(i, min(o[i], pos["tp"]), "TP")
            if pos is not None and max_bars > 0 and i - pos["ei"] + 1 >= max_bars:
                close_pos(i, c[i], "Time")
        eq[i] = cash + ((1 if pos["long"] else -1) * (c[i] - pos["entry"]) * pos["qty"] if pos else 0.0)
        if pos is None and i < total - 1:
            side = None
            if cfg["dir"] != "short" and signal(i, True):
                side = True
            elif cfg["dir"] != "long" and signal(i, False):
                side = False
            if side is not None:
                px = o[i + 1]
                a = av[i] if av[i] == av[i] else px * 0.02
                sd = px * max(0.05, float(cfg["slV"])) / 100 if cfg["slMode"] == "pct" else a * max(0.1, float(cfg["slV"]))
                if cfg["tpMode"] == "pct":
                    td = px * max(0.05, float(cfg["tpV"])) / 100
                elif cfg["tpMode"] == "rr":
                    td = sd * max(0.1, float(cfg["tpV"]))
                else:
                    td = a * max(0.1, float(cfg["tpV"]))
                qty = min(cash * risk_pct / sd, cash / px) if sd > 0 and px > 0 else 0
                if qty > 0:
                    pos = {"long": side, "ei": i + 1, "entry": px, "qty": qty, "risk_amt": qty * sd,
                           "sl": px - sd if side else px + sd, "tp": px + td if side else px - td}
    if pos is not None:
        close_pos(total - 1, c[total - 1], "Open")
    eq[total - 1] = cash

    # ---- sonuçlar ----
    idx = dates[start:]
    eq_s = pd.Series(eq[start:], index=idx)
    bh_s = pd.Series(cap * c[start:] / c[start], index=idx)
    dd_s = eq_s / eq_s.cummax() - 1
    for t in trades:
        t["ed"], t["xd"] = dates[t["ei"]], dates[t["xi"]]
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = sum(t["pnl"] for t in losses)
    final = float(eq_s.iloc[-1])
    rets = eq_s.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 2 and rets.std() > 0 else 0.0
    avg = lambda arr, f: (sum(f(t) for t in arr) / len(arr)) if arr else 0.0
    pf = (gw / -gl) if gl < 0 else (float("inf") if gw > 0 else 0.0)
    avg_win, avg_loss = avg(wins, lambda t: t["pnl"]), avg(losses, lambda t: t["pnl"])
    payoff = (avg_win / -avg_loss) if avg_loss < 0 else 0.0
    exp_r = avg(trades, lambda t: t["R"])
    streak = max_streak = 0
    for t in trades:
        streak = streak + 1 if t["pnl"] <= 0 else 0
        max_streak = max(max_streak, streak)
    good = n >= 10 and pf >= 1.3 and exp_r > 0
    okish = n >= 5 and pf >= 1
    verdict = "Too few samples" if n < 5 else "Promising" if good else "Borderline" if okish else "Weak"
    tone = "warn" if n < 5 else "good" if good else "warn" if okish else "bad"
    kpi = {
        "cap": cap, "final": final, "net": final - cap, "net_pct": (final / cap - 1) * 100,
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / n * 100 if n else 0.0, "pf": pf,
        "mdd": float(dd_s.min()) if len(dd_s) else 0.0, "payoff": payoff, "exp_r": exp_r,
        "avg_bars": avg(trades, lambda t: t["bars"]), "sharpe": sharpe,
        "bh_pct": (c[-1] / c[start] - 1) * 100,
        "avg_win_pct": avg(wins, lambda t: t["ret"]), "avg_loss_pct": avg(losses, lambda t: t["ret"]),
        "best": max((t["ret"] for t in trades), default=0.0),
        "worst": min((t["ret"] for t in trades), default=0.0),
        "max_streak": max_streak, "verdict": verdict, "tone": tone,
    }
    return {"ok": True, "trades": trades, "eq": eq_s, "bh": bh_s, "dd": dd_s,
            "price": pd.Series(c[start:], index=idx),
            "ma": pd.Series(ma[start:], index=idx) if cfg["c2on"] else None,
            "kpi": kpi, "range": (idx[0], idx[-1]), "desc": describe(cfg), "cfg": cfg}


# ======================================================================
# GRAFİK İNDİKATÖRLERİ
# Hepsi gerçek OHLCV üzerinde çalışır; ayarlar arayüzden değiştirilebilir.
# ======================================================================
def wavetrend(df, n1=10, n2=21, sig=4):
    """LazyBear WaveTrend: wt1 (hızlı), wt2 (sinyal). Aşırı alım +60, aşırı satım −60."""
    ap = (df["High"] + df["Low"] + df["Close"]) / 3
    esa = ema(ap, n1)
    d = ema((ap - esa).abs(), n1)
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, n2)
    return wt1, sma(wt1, max(2, int(sig)))


def nadaraya_watson(close, h=8.0, mult=3.0, window=500):
    """Nadaraya-Watson tahmincisi (Gauss çekirdeği) + ortalama mutlak hata bandı."""
    s = pd.to_numeric(close, errors="coerce").dropna()
    n = min(int(window), len(s))
    empty = pd.Series(np.nan, index=close.index)
    if n < 20:
        return empty, empty.copy(), empty.copy()
    y = s.to_numpy(float)[-n:]
    i = np.arange(n, dtype=float)
    h = max(0.5, float(h))
    w = np.exp(-((i[:, None] - i[None, :]) ** 2) / (2 * h * h))
    mid = (w * y).sum(1) / w.sum(1)
    mae = float(np.mean(np.abs(y - mid))) * max(0.1, float(mult))
    idx = s.index[-n:]
    up = pd.Series(mid + mae, index=idx).reindex(close.index)
    lo = pd.Series(mid - mae, index=idx).reindex(close.index)
    md = pd.Series(mid, index=idx).reindex(close.index)
    return up, lo, md


def pivot_points(s, left=5, right=5):
    """(tepe indeksleri, dip indeksleri) — her iki yanında da uç değer olan barlar."""
    v = pd.to_numeric(s, errors="coerce").to_numpy(float)
    n = len(v)
    left, right = max(1, int(left)), max(1, int(right))
    hi, lo = [], []
    for i in range(left, n - right):
        x = v[i]
        if x != x:
            continue
        w = v[i - left:i + right + 1]
        if np.all(np.isnan(w)):
            continue
        if x >= np.nanmax(w):
            hi.append(i)
        if x <= np.nanmin(w):
            lo.append(i)
    return hi, lo


DIV_KINDS = {"reg_bull": ("Bullish divergence", "bull"), "hid_bull": ("Hidden bullish", "bull"),
             "reg_bear": ("Bearish divergence", "bear"), "hid_bear": ("Hidden bearish", "bear")}


def divergences(df, osc, left=5, right=5, min_gap=5, max_gap=60, hidden=True, limit=14):
    """Fiyat ile osilatör arasındaki klasik ve gizli uyumsuzluklar.
    Pivotlar osilatörden alınır, fiyat aynı barlardan okunur."""
    osc = pd.to_numeric(osc, errors="coerce")
    hi, lo = pivot_points(osc, left, right)
    hv, lv = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    ov = osc.to_numpy(float)
    out = []

    def add(i1, i2, kind, py1, py2):
        out.append({"i1": int(i1), "i2": int(i2), "p1": float(py1), "p2": float(py2),
                    "o1": float(ov[i1]), "o2": float(ov[i2]), "kind": kind})

    for seq, is_low in ((lo, True), (hi, False)):
        for a, b in zip(seq, seq[1:]):
            gap = b - a
            if not (min_gap <= gap <= max_gap):
                continue
            if ov[a] != ov[a] or ov[b] != ov[b]:
                continue
            if is_low:
                p1, p2 = lv[a], lv[b]
                if p2 < p1 and ov[b] > ov[a]:
                    add(a, b, "reg_bull", p1, p2)
                elif hidden and p2 > p1 and ov[b] < ov[a]:
                    add(a, b, "hid_bull", p1, p2)
            else:
                p1, p2 = hv[a], hv[b]
                if p2 > p1 and ov[b] < ov[a]:
                    add(a, b, "reg_bear", p1, p2)
                elif hidden and p2 < p1 and ov[b] > ov[a]:
                    add(a, b, "hid_bear", p1, p2)
    out.sort(key=lambda d: -d["i2"])
    return out[:int(limit)]


def ranked_sr_zones(df, lookback=300, left=8, right=8, merge_pct=0.6, max_zones=8,
                    weak_below=35.0):
    """Destek/direnç bantları: pivotları fiyata göre kümeler, her kümeyi temas sayısı,
    hacim ve yakınlık ile puanlar; en güçlü bant %100 olacak şekilde normalize eder."""
    d = df.tail(int(lookback))
    n = len(d)
    if n < 40:
        return []
    hi, lo = pivot_points(d["High"], left, right)
    pl_hi, pl_lo = pivot_points(d["Low"], left, right)
    hv, lv = d["High"].to_numpy(float), d["Low"].to_numpy(float)
    vol = pd.to_numeric(d["Volume"], errors="coerce").fillna(0.0).to_numpy(float)
    pts = [(i, hv[i], vol[i]) for i in hi] + [(i, lv[i], vol[i]) for i in pl_lo]
    if not pts:
        return []
    pts.sort(key=lambda x: x[1])
    close = float(d["Close"].iloc[-1])
    tol = max(1e-9, close * float(merge_pct) / 100)
    groups, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[1] - cur[-1][1] <= tol:
            cur.append(p)
        else:
            groups.append(cur)
            cur = [p]
    groups.append(cur)
    vol_max = max(1.0, float(np.nanmax(vol)) if len(vol) else 1.0)
    raw = []
    for g in groups:
        idxs = [x[0] for x in g]
        prices = [x[1] for x in g]
        touches = len(g)
        vsum = sum(x[2] for x in g) / (vol_max * touches)
        recency = (max(idxs) + 1) / n
        score = touches * 1.0 + vsum * 1.2 + recency * 1.5
        raw.append({"lo": min(prices), "hi": max(prices), "touches": touches,
                    "start": min(idxs), "last": max(idxs), "score": score})
    top = max(r["score"] for r in raw) or 1.0
    out = []
    for r in raw:
        pct = round(r["score"] / top * 100)
        mid = (r["lo"] + r["hi"]) / 2
        pad = max(tol * 0.5, (r["hi"] - r["lo"]) * 0.15)
        kind = "res" if mid > close else "sup"
        weak = pct < float(weak_below)
        base = "Resistance" if kind == "res" else "Support"
        out.append({"lo": r["lo"] - pad, "hi": r["hi"] + pad, "pct": int(pct), "kind": kind,
                    "weak": bool(weak), "touches": r["touches"],
                    "start": int(r["start"]) + (len(df) - n), "last": int(r["last"]) + (len(df) - n),
                    "label": ("Weak " + base) if weak else base})
    out.sort(key=lambda z: -z["pct"])
    return out[:int(max_zones)]


# ======================================================================
# v3.1 — ek göstergeler (Supertrend, VIDYA, Bollinger, Volatility Stop,
#        Stokastik, ADX) · tamamı gerçek OHLCV üzerinden hesaplanır
# ======================================================================
def bollinger(close, n=20, k=2.0):
    """Bollinger bantları: (üst, orta, alt)."""
    n, k = int(n), float(k)
    m = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    return m + k * sd, m, m - k * sd


def stoch(df, k=14, d=3, smooth=3):
    """Stokastik osilatör: (%K yumuşatılmış, %D)."""
    k, d, smooth = int(k), int(d), int(smooth)
    lo = df["Low"].rolling(k, min_periods=k).min()
    hi = df["High"].rolling(k, min_periods=k).max()
    raw = (df["Close"] - lo) / (hi - lo).replace(0, np.nan) * 100
    kk = raw.rolling(smooth, min_periods=smooth).mean() if smooth > 1 else raw
    return kk, kk.rolling(d, min_periods=d).mean()


def adx(df, n=14):
    """Wilder ADX: (adx, +DI, −DI). Trendin gücü — yönü değil."""
    n = int(n)
    up = df["High"].diff()
    dn = -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a.replace(0, np.nan)
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), pdi, mdi


def supertrend(df, n=10, mult=3.0):
    """Supertrend: (çizgi, yön). Yön +1 yükseliş (çizgi altta), −1 düşüş."""
    n, mult = int(n), float(mult)
    a = atr(df, n).to_numpy(float)
    hl2 = ((df["High"] + df["Low"]) / 2).to_numpy(float)
    c = df["Close"].to_numpy(float)
    up, lo = hl2 + mult * a, hl2 - mult * a
    line = np.full(len(c), np.nan)
    dirn = np.ones(len(c), dtype=int)
    fu, fl = np.nan, np.nan
    for i in range(len(c)):
        if not np.isfinite(a[i]):
            continue
        pc = c[i - 1] if i else c[i]
        fu = up[i] if not np.isfinite(fu) or up[i] < fu or pc > fu else fu
        fl = lo[i] if not np.isfinite(fl) or lo[i] > fl or pc < fl else fl
        prev = dirn[i - 1] if i else 1
        if prev == 1:
            dirn[i] = -1 if c[i] < fl else 1
        else:
            dirn[i] = 1 if c[i] > fu else -1
        if dirn[i] != prev:
            fu, fl = up[i], lo[i]
        line[i] = fl if dirn[i] == 1 else fu
    return pd.Series(line, index=df.index), pd.Series(dirn, index=df.index)


def vidya(df, length=10, mom=20, mult=2.0):
    """Volumatic VIDYA — Chande değişken ortalaması + trend dönüşünde sabitlenen ATR bandı.
    Döner: (vidya, üst bant, alt bant, yön, dönüş noktaları)."""
    length, mom, mult = int(length), int(mom), float(mult)
    close = df["Close"]
    d = close.diff()
    gain = d.clip(lower=0).rolling(mom, min_periods=mom).sum()
    loss = (-d.clip(upper=0)).rolling(mom, min_periods=mom).sum()
    cmo = ((gain - loss) / (gain + loss).replace(0, np.nan)).abs()
    c = close.to_numpy(float)
    k = cmo.to_numpy(float)
    a = atr(df, 14).to_numpy(float)
    alpha = 2.0 / (length + 1)
    v = np.full(len(c), np.nan)
    ub = np.full(len(c), np.nan)
    lb = np.full(len(c), np.nan)
    dirn = np.zeros(len(c), dtype=int)
    flips = []
    prev = np.nan
    cur_dir = 0
    for i in range(len(c)):
        if not np.isfinite(k[i]):
            continue
        prev = c[i] if not np.isfinite(prev) else c[i] * alpha * k[i] + prev * (1 - alpha * k[i])
        v[i] = prev
        nd = 1 if c[i] > prev else -1
        if cur_dir == 0:
            cur_dir = nd
        elif nd != cur_dir:
            cur_dir = nd
            band = a[i] if np.isfinite(a[i]) else abs(c[i]) * 0.02
            ub[i], lb[i] = prev + mult * band, prev - mult * band
            flips.append({"i": int(i), "dir": int(nd), "p": float(prev)})
        dirn[i] = cur_dir
        if i and not np.isfinite(ub[i]):
            ub[i], lb[i] = ub[i - 1], lb[i - 1]
    idx = close.index
    return (pd.Series(v, index=idx), pd.Series(ub, index=idx), pd.Series(lb, index=idx),
            pd.Series(dirn, index=idx), flips[-40:])


def volatility_stop(df, n=20, mult=2.0):
    """ATR iz süren stop: (stop çizgisi, yön). Yön +1 long, −1 short."""
    n, mult = int(n), float(mult)
    a = atr(df, n).to_numpy(float)
    c = df["Close"].to_numpy(float)
    stop = np.full(len(c), np.nan)
    dirn = np.ones(len(c), dtype=int)
    cur, d0 = np.nan, 1
    for i in range(len(c)):
        if not np.isfinite(a[i]):
            continue
        off = mult * a[i]
        if not np.isfinite(cur):
            cur, d0 = c[i] - off, 1
        elif d0 == 1:
            if c[i] < cur:
                d0, cur = -1, c[i] + off
            else:
                cur = max(cur, c[i] - off)
        else:
            if c[i] > cur:
                d0, cur = 1, c[i] - off
            else:
                cur = min(cur, c[i] + off)
        stop[i], dirn[i] = cur, d0
    return pd.Series(stop, index=df.index), pd.Series(dirn, index=df.index)


def obv(df):
    """On-Balance Volume."""
    sign = np.sign(df["Close"].diff().fillna(0.0))
    return (sign * df["Volume"].astype(float)).cumsum()


# ======================================================================
# Formasyon tespiti — klasik grafik formasyonları
# ======================================================================
def _slope(xs, ys):
    if len(xs) < 2:
        return 0.0
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    den = ((x - x.mean()) ** 2).sum()
    return float(((x - x.mean()) * (y - y.mean())).sum() / den) if den else 0.0


def chart_patterns(df, left=4, right=4, lookback=180, tol=0.035, limit=4):
    """Son barlarda klasik formasyonlar: çift dip/tepe, OBO, ters OBO, üçgen, bayrak.
    Döner: [{"name","kind","conf","i","note"}] — kind: bull | bear | neutral."""
    if df is None or len(df) < 40:
        return []
    d = df.tail(int(lookback))
    n = len(d)
    hi_i, _ = pivot_points(d["High"], left, right)
    _, lo_i = pivot_points(d["Low"], left, right)
    H = d["High"].to_numpy(float)
    L = d["Low"].to_numpy(float)
    C = d["Close"].to_numpy(float)
    px = float(C[-1])
    out = []

    def rel(a, b):
        return abs(a - b) / max(abs(b), 1e-9)

    # ---- çift dip / çift tepe
    if len(lo_i) >= 2:
        i1, i2 = lo_i[-2], lo_i[-1]
        gap = i2 - i1
        if 5 <= gap <= 90 and rel(L[i1], L[i2]) <= tol:
            mid = [j for j in hi_i if i1 < j < i2]
            neck = float(H[max(mid, key=lambda j: H[j])]) if mid else float(H[i1:i2 + 1].max())
            if neck > max(L[i1], L[i2]):
                conf = 0.55 + 0.25 * (1 - rel(L[i1], L[i2]) / tol) + (0.2 if px > neck else 0.0)
                out.append({"name": "Double bottom", "kind": "bull", "conf": float(round(min(1.0, conf), 2)),
                            "i": int(i2) + (len(df) - n),
                            "note": "neckline %s%s" % (fmt_num(neck, 2), " broken" if px > neck else " not broken yet")})
    if len(hi_i) >= 2:
        i1, i2 = hi_i[-2], hi_i[-1]
        gap = i2 - i1
        if 5 <= gap <= 90 and rel(H[i1], H[i2]) <= tol:
            mid = [j for j in lo_i if i1 < j < i2]
            neck = float(L[min(mid, key=lambda j: L[j])]) if mid else float(L[i1:i2 + 1].min())
            if neck < min(H[i1], H[i2]):
                conf = 0.55 + 0.25 * (1 - rel(H[i1], H[i2]) / tol) + (0.2 if px < neck else 0.0)
                out.append({"name": "Double top", "kind": "bear", "conf": float(round(min(1.0, conf), 2)),
                            "i": int(i2) + (len(df) - n),
                            "note": "neckline %s%s" % (fmt_num(neck, 2), " broken" if px < neck else " not broken yet")})
    # ---- omuz-baş-omuz / ters OBO
    if len(hi_i) >= 3:
        a, b, c = hi_i[-3], hi_i[-2], hi_i[-1]
        if H[b] > H[a] and H[b] > H[c] and rel(H[a], H[c]) <= tol * 1.8 and (c - a) <= 140:
            mids = [j for j in lo_i if a < j < c]
            neck = float(np.mean([L[j] for j in mids])) if mids else float(L[a:c + 1].min())
            out.append({"name": "Head and shoulders", "kind": "bear", "conf": 0.72,
                        "i": int(c) + (len(df) - n),
                        "note": "neckline %s%s" % (fmt_num(neck, 2), " broken" if px < neck else "")})
    if len(lo_i) >= 3:
        a, b, c = lo_i[-3], lo_i[-2], lo_i[-1]
        if L[b] < L[a] and L[b] < L[c] and rel(L[a], L[c]) <= tol * 1.8 and (c - a) <= 140:
            mids = [j for j in hi_i if a < j < c]
            neck = float(np.mean([H[j] for j in mids])) if mids else float(H[a:c + 1].max())
            out.append({"name": "Inverse head and shoulders", "kind": "bull", "conf": 0.72,
                        "i": int(c) + (len(df) - n),
                        "note": "neckline %s%s" % (fmt_num(neck, 2), " broken" if px > neck else "")})
    # ---- üçgen (son 3 tepe / 3 dip eğimi)
    if len(hi_i) >= 3 and len(lo_i) >= 3:
        hs = _slope(hi_i[-3:], [H[j] for j in hi_i[-3:]]) / max(px, 1e-9) * 100
        ls = _slope(lo_i[-3:], [L[j] for j in lo_i[-3:]]) / max(px, 1e-9) * 100
        flat = 0.035
        if hs < -flat and ls > flat:
            out.append({"name": "Symmetrical triangle", "kind": "neutral", "conf": 0.6,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n), "note": "squeeze — breakout pending"})
        elif abs(hs) <= flat and ls > flat:
            out.append({"name": "Ascending triangle", "kind": "bull", "conf": 0.68,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n),
                        "note": "horizontal resistance %s" % fmt_num(float(np.mean([H[j] for j in hi_i[-3:]])), 2)})
        elif hs < -flat and abs(ls) <= flat:
            out.append({"name": "Descending triangle", "kind": "bear", "conf": 0.68,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n),
                        "note": "horizontal support %s" % fmt_num(float(np.mean([L[j] for j in lo_i[-3:]])), 2)})
    # ---- bayrak / flama (sert hareket + sıkışma)
    if n >= 45:
        imp = (C[-20] / C[-40] - 1) * 100 if C[-40] else 0.0
        rng = (H[-15:].max() - L[-15:].min()) / max(px, 1e-9) * 100
        if abs(imp) >= 8 and rng <= max(4.0, abs(imp) * 0.45):
            out.append({"name": "Bull flag" if imp > 0 else "Bear flag",
                        "kind": "bull" if imp > 0 else "bear", "conf": 0.6,
                        "i": len(df) - 1,
                        "note": "%s%% move followed by a squeeze in a %s%% band"
                                % (fmt_num(abs(imp), 1), fmt_num(rng, 1))})
    out.sort(key=lambda p: (-p["conf"], -p["i"]))
    return out[:int(limit)]


# ======================================================================
# A–Z notu — altı grup, kural tabanlı puanlama ve Türkçe yorum
#   A = en güçlü alım · M/N = nötr · Z = en güçlü satım
# ======================================================================
GRADE_GROUPS = [("mom", "Momentum", 25), ("form", "Pattern & divergence", 20),
                ("vol", "Volume", 20), ("rr", "Risk / Reward", 20),
                ("trend", "Trend & averages", 10), ("volat", "Volatility & position", 5)]
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _f(v, dec=2):
    return fmt_num(v, dec)


def _g_momentum(df):
    close = df["Close"]
    why, parts = [], []
    r_s = rsi(close, 14)
    r, r5 = _last(r_s), _last(r_s.shift(5))
    if _ok(r):
        dr = (r - r5) if _ok(r5) else 0.0
        if r >= 70:
            s, t = 68, "RSI %s — strong but overbought, risk of a pullback" % _f(r, 1)
        elif r >= 58:
            s, t = 90, "RSI %s — buyers have the momentum" % _f(r, 1)
        elif r >= 50:
            s, t = 66, "RSI %s — slightly above 50" % _f(r, 1)
        elif r >= 42:
            s, t = 40, "RSI %s — below 50, momentum weak" % _f(r, 1)
        elif r > 30:
            s, t = 24, "RSI %s — sellers dominate" % _f(r, 1)
        else:
            s, t = 38, "RSI %s — oversold, a relief bounce is possible" % _f(r, 1)
        s = min(100, max(0, s + (6 if dr > 4 else -6 if dr < -4 else 0)))
        parts.append((s, 1.1))
        why.append(t + (" and rising over the last 5 bars" if dr > 4 else " and weakening over the last 5 bars" if dr < -4 else ""))
    line, sig, hist = macd(close)
    h, hp = _last(hist), _last(hist.shift(1))
    if _ok(h):
        rising = _ok(hp) and h > hp
        hv = hist.to_numpy(float)
        cross = next((k for k in range(1, min(40, len(hv))) if _ok(hv[-k]) and _ok(hv[-k - 1])
                      and np.sign(hv[-k]) != np.sign(hv[-k - 1])), None)
        if h > 0:
            s = 92 if rising else 68
            t = "MACD histogram positive and %s" % ("widening" if rising else "narrowing")
        else:
            s = 34 if rising else 10
            t = "MACD histogram negative and %s" % ("recovering" if rising else "deepening")
        if cross is not None and cross <= 5:
            t += " · turned %d bars ago" % cross
            s = min(100, s + 6) if h > 0 else max(0, s - 6)
        parts.append((s, 1.2))
        why.append(t)
    k_s, d_s = stoch(df)
    kk, dd = _last(k_s), _last(d_s)
    if _ok(kk) and _ok(dd):
        if kk > 80:
            s, t = 48, "Stochastic %s — overbought" % _f(kk, 0)
        elif kk < 20:
            s, t = 52, "Stochastic %s — oversold" % _f(kk, 0)
        elif kk > dd:
            s, t = 82, "Stochastic %s, above its signal" % _f(kk, 0)
        else:
            s, t = 28, "Stochastic %s, below its signal" % _f(kk, 0)
        parts.append((s, 0.8))
        why.append(t)
    if not parts:
        return 50.0, ["Not enough bars for momentum"]
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def _g_form(df, patterns=None, div_list=None):
    pats = chart_patterns(df) if patterns is None else patterns
    if div_list is None:
        div_list = divergences(df, rsi(df["Close"], 14), limit=6)
    n = len(df)
    bull = bear = 0.0
    why = []
    for p in pats:
        w = float(p.get("conf", 0.6))
        if p["kind"] == "bull":
            bull += w
        elif p["kind"] == "bear":
            bear += w
        why.append("%s (%s)" % (p["name"], p.get("note", "")) if p.get("note") else p["name"])
    fresh = [d for d in div_list if n - 1 - int(d.get("i2", 0)) <= 12]
    for d in fresh:
        kind = DIV_KINDS.get(d.get("kind"), ("", ""))[1]
        label = DIV_KINDS.get(d.get("kind"), ("Divergence", ""))[0]
        if kind == "bull":
            bull += 0.55
        elif kind == "bear":
            bear += 0.55
        why.append("%s — RSI and price are diverging" % label)
    if not pats and not fresh:
        return 50.0, ["No clear pattern or divergence"]
    net = (bull - bear) / max(1.0, bull + bear)
    return 50 + net * 46, why


def _g_volume(df):
    why, parts = [], []
    rv, frac = vol_ratio(df, 20)
    up = _last(df["Close"].diff()) or 0.0
    pace = (" — on pace, the bar is %s%% complete" % _f(frac * 100, 0)) if frac < 0.97 else ""
    if _ok(rv):
        if rv >= 1.5:
            s = 90 if up >= 0 else 14
            why.append("Volume %sx above average, %s bar%s" % (_f(rv, 1), "up" if up >= 0 else "down", pace))
        elif rv >= 1.0:
            s = 68 if up >= 0 else 34
            why.append("Volume slightly above average (%sx%s)" % (_f(rv, 1), pace))
        elif rv >= 0.8:
            s = 54 if up >= 0 else 42
            why.append("Volume around average (%sx%s)" % (_f(rv, 2), pace))
        else:
            s = 44
            why.append("Volume below average (%sx%s) — weak confirmation of the move" % (_f(rv, 1), pace))
        parts.append((s, 1.2))
    m = _last(mfi(df, 14))
    if _ok(m):
        s = 88 if m >= 60 else 68 if m >= 50 else 34 if m >= 40 else 16
        parts.append((s, 1.0))
        why.append("Money flow (MFI) %s" % _f(m, 0))
    o = obv(df)
    if len(o) > 25:
        ov = o.to_numpy(float)[-21:]
        sl = _slope(range(len(ov)), ov)
        base = abs(float(df["Volume"].tail(21).mean())) or 1.0
        rr = sl / base
        s = 86 if rr > 0.25 else 64 if rr > 0.02 else 36 if rr > -0.25 else 14
        parts.append((s, 0.9))
        why.append("OBV %s over the last 20 bars" % ("rising" if rr > 0.02 else "falling" if rr < -0.02 else "flat"))
    if not parts:
        return 50.0, ["No volume data"]
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def _g_rr(df, zones=None):
    px = float(df["Close"].iloc[-1])
    a = _last(atr(df, 14)) or px * 0.02
    if zones is None:
        zones = ranked_sr_zones(df)
    levels_up, levels_dn = [], []
    for z in zones or []:
        mid = (z["lo"] + z["hi"]) / 2
        (levels_up if mid > px else levels_dn).append((mid, z.get("pct", 50), z.get("label", "band")))
    for p in (50, 200):
        v = _last(sma(df["Close"], p))
        if _ok(v):
            (levels_up if v > px else levels_dn).append((v, 55, "SMA %d" % p))
    why, notes = [], []
    if not levels_up:
        hh = float(df["High"].tail(252).max())
        if hh > px * 1.004:
            levels_up.append((hh, 50, "52-week high"))
            notes.append("No pivot band left above; target is the 52-week high")
        else:
            levels_up.append((px + 2.5 * a, 50, "ATR target"))
            notes.append("Price at its high, no resistance above — target 2.5×ATR")
    if not levels_dn:
        levels_dn.append((px - 2.0 * a, 50, "ATR stop"))
        notes.append("No recorded support below — stop 2×ATR")
    res = min(levels_up, key=lambda x: x[0])
    sup = max(levels_dn, key=lambda x: x[0])
    rew = max(0.0, (res[0] - px) / px * 100)
    raw_risk = max(0.0, (px - sup[0]) / px * 100)
    atr_pct = a / px * 100
    # Stop 0,5×ATR'den dar olamaz: gürültü stopu düşürmesin, R/R şişmesin
    risk = max(raw_risk, 0.5 * atr_pct)
    rr = min(10.0, rew / risk) if risk > 0.02 else 0.0
    why.append("Nearest resistance: %s %s (+%s%%), nearest support: %s %s (−%s%%)"
               % (res[2], _f(res[0]), _f(rew, 1), sup[2], _f(sup[0]), _f(raw_risk, 1)))
    if risk > raw_risk + 0.01:
        notes.append("Support is %s%% away; the stop was pulled to a 0.5×ATR (%s%%) floor so noise doesn't trigger it"
                     % (_f(raw_risk, 1), _f(risk, 1)))
    if rr >= 2.5:
        s = 95
    elif rr >= 2:
        s = 86
    elif rr >= 1.5:
        s = 72
    elif rr >= 1:
        s = 55
    elif rr >= 0.6:
        s = 34
    else:
        s = 14
    why.append("Risk/reward 1 : %s%s" % (_f(rr, 2), "+" if rr >= 10 else ""))
    return float(s), why + notes


def _g_trend(df):
    close = df["Close"]
    px = float(close.iloc[-1])
    why, parts = [], []
    ms = {p: _last(sma(close, p)) for p in (20, 50, 100, 200)}
    have = [p for p in (20, 50, 100, 200) if _ok(ms[p])]
    if have:
        above = sum(1 for p in have if px > ms[p])
        s = above / len(have) * 100
        order = all(ms[have[i]] >= ms[have[i + 1]] for i in range(len(have) - 1))
        rev = all(ms[have[i]] <= ms[have[i + 1]] for i in range(len(have) - 1))
        if order and len(have) >= 3:
            s = min(100, s + 12)
            why.append("Averages in perfect alignment (20>50>100>200)")
        elif rev and len(have) >= 3:
            s = max(0, s - 12)
            why.append("Averages in downtrend alignment (20<50<100<200)")
        why.append("Price above %d/%d moving averages" % (above, len(have)))
        parts.append((s, 1.3))
    try:
        _, sd = supertrend(df, 10, 3.0)
        v = int(sd.iloc[-1])
        parts.append((84 if v > 0 else 16, 1.0))
        why.append("Supertrend %s" % ("up" if v > 0 else "down"))
    except Exception:
        pass
    ax, pdi, mdi = adx(df, 14)
    av = _last(ax)
    if _ok(av):
        why.append("ADX %s — trend %s" % (_f(av, 0), "strong" if av >= 25 else "weak/flat"))
        if av < 18 and parts:
            parts = [(50 + (s - 50) * 0.55, w) for s, w in parts]
    if not parts:
        return 50.0, ["Not enough bars for trend"]
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def _g_volat(df):
    close = df["Close"]
    px = float(close.iloc[-1])
    why, parts = [], []
    b = _last(boll_pctb(close, 20, 2.0))
    if _ok(b):
        if b > 1:
            s, t = 38, "Outside the upper Bollinger band — overextended"
        elif b >= 0.55:
            s, t = 82, "In the upper half of the Bollinger band (%%B %s)" % _f(b * 100, 0)
        elif b >= 0.45:
            s, t = 58, "Mid Bollinger"
        elif b >= 0:
            s, t = 34, "In the lower half of the Bollinger band (%%B %s)" % _f(b * 100, 0)
        else:
            s, t = 46, "Outside the lower Bollinger band — a bounce may come"
        parts.append((s, 1.0))
        why.append(t)
    a = _last(atr(df, 14))
    s20 = _last(sma(close, 20))
    if _ok(a) and _ok(s20) and a > 0:
        ext = (px - s20) / a
        if abs(ext) > 3:
            parts.append((40 if ext > 0 else 50, 0.8))
            why.append("Price is %s ATR away from its 20-day average — a pullback is likely" % _f(abs(ext), 1))
        else:
            parts.append((70 if ext > 0 else 46, 0.8))
    if len(df) > 60:
        lo, hi = float(df["Low"].tail(252).min()), float(df["High"].tail(252).max())
        if hi > lo:
            pos = (px - lo) / (hi - lo) * 100
            why.append("At %s%% of its 1-year range" % _f(pos, 0))
            parts.append((min(100, max(0, pos * 0.8 + 10)), 0.7))
    if not parts:
        return 50.0, []
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def grade(df, zones=None, tf_name="daily"):
    """Altı grubu puanlar, 0–100 skoru A–Z harfine çevirir ve Türkçe yorum üretir."""
    if df is None or len(df) < 30:
        return None
    pats = chart_patterns(df)
    divs = divergences(df, rsi(df["Close"], 14), limit=6)
    fns = {"mom": lambda: _g_momentum(df), "form": lambda: _g_form(df, pats, divs),
           "vol": lambda: _g_volume(df), "rr": lambda: _g_rr(df, zones),
           "trend": lambda: _g_trend(df), "volat": lambda: _g_volat(df)}
    groups, total = [], 0.0
    for key, name, w in GRADE_GROUPS:
        try:
            s, why = fns[key]()
        except Exception:
            s, why = 50.0, []
        s = float(min(100.0, max(0.0, s)))
        total += s * w / 100.0
        groups.append({"key": key, "name": name, "weight": w, "score": round(s, 1),
                       "points": round(s * w / 100.0, 1), "reasons": why})
    score = float(min(100.0, max(0.0, total)))
    li = int(round((100 - score) / 4.0))
    li = min(25, max(0, li))
    letter = LETTERS[li]
    if li <= 3:
        action, tone = "Strong Buy", "bull"
    elif li <= 8:
        action, tone = "Buy", "bull"
    elif li <= 11:
        action, tone = "Weak Buy", "bull"
    elif li <= 14:
        action, tone = "Neutral", "flat"
    elif li <= 17:
        action, tone = "Weak Sell", "bear"
    elif li <= 22:
        action, tone = "Sell", "bear"
    else:
        action, tone = "Strong Sell", "bear"
    return {"score": round(score, 1), "letter": letter, "action": action, "tone": tone,
            "groups": groups, "patterns": pats, "tf": tf_name,
            "text": _grade_text(df, groups, letter, action, score, tf_name, pats)}


def _grade_text(df, groups, letter, action, score, tf_name, pats):
    """Puanlardan doğal dilde Türkçe yorum kurar — uydurma yok, hepsi hesaplanan değerlerden."""
    gd = {g["key"]: g for g in groups}
    px = float(df["Close"].iloc[-1])
    out = []
    top = max(groups, key=lambda g: g["score"])
    bot = min(groups, key=lambda g: g["score"])
    out.append("On the %s timeframe, with %s points, I rate it **%s** — %s."
               % (tf_name, _f(score, 0), letter, action.lower()))
    mom, trend = gd["mom"], gd["trend"]
    lead = []
    if mom["reasons"]:
        lead.append(mom["reasons"][0])
    if trend["reasons"]:
        lead.append(trend["reasons"][-1] if len(trend["reasons"]) > 1 else trend["reasons"][0])
    if lead:
        out.append("What drives the picture: " + "; ".join(lead) + ".")
    if gd["form"]["reasons"] and pats:
        bits = [p["name"].lower() + ((" (" + p["note"] + ")") if p.get("note") else "") for p in pats[:2]]
        out.append("Patterns: " + ", ".join(bits) + ".")
    elif gd["form"]["reasons"]:
        out.append(gd["form"]["reasons"][0] + ".")
    if gd["vol"]["reasons"]:
        out.append(gd["vol"]["reasons"][0] + ".")
    if gd["rr"]["reasons"]:
        out.append(" ".join(r.rstrip(".") + "." for r in gd["rr"]["reasons"][:2]))
    out.append("Strongest side %s (%s/100), weakest side %s (%s/100). Last price %s."
               % (top["name"].lower(), _f(top["score"], 0), bot["name"].lower(), _f(bot["score"], 0), _f(px)))
    if gd["volat"]["reasons"]:
        out.append("Risk note: " + gd["volat"]["reasons"][0] + ".")
    return " ".join(out)


# ======================================================================
# v3.2 — Kurulum formasyonları (günlük): üçgen · dikdörtgen · merdiven · kırılım
#   Hepsi pivot noktaları üzerinden çalışır; her biri kırılacak SEVİYEYİ döndürür,
#   böylece 15 dakikalık teyit ve stop/hedef planı aynı seviyeyi kullanabilir.
# ======================================================================
SETUP_NAMES = {"triangle_sym": "Symmetrical triangle", "triangle_asc": "Ascending triangle",
               "triangle_desc": "Descending triangle", "rectangle": "Rectangle (horizontal channel)",
               "ladder": "Staircase (higher highs/lows)", "breakout": "Breakout",
               "breakdown": "Breakdown"}


def _fit(xs, ys):
    """En küçük kareler doğrusu: (eğim, sabit)."""
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    if len(x) < 2:
        return 0.0, float(y[0]) if len(y) else 0.0
    den = ((x - x.mean()) ** 2).sum()
    if den <= 0:
        return 0.0, float(y.mean())
    m = float(((x - x.mean()) * (y - y.mean())).sum() / den)
    return m, float(y.mean() - m * x.mean())


def _state(close, level, a, side):
    """Fiyatın seviyeye göre durumu: kırılım / geri test / oluşum."""
    if a <= 0:
        a = max(abs(close) * 0.01, 1e-6)
    d = (close - level) / a if side == "bull" else (level - close) / a
    if d >= 0.25:
        return "breakout"
    if d >= -0.35:
        return "retest"
    return "forming"


def _vol_x(df, n=20):
    v = df["Volume"].astype(float)
    base = v.iloc[-n - 1:-1].mean()
    return float(v.iloc[-1] / base) if base and base == base and base > 0 else 1.0


def _close_pos(df):
    """Kapanışın günün aralığındaki yeri (1 = en tepe)."""
    h, lo, c = float(df["High"].iloc[-1]), float(df["Low"].iloc[-1]), float(df["Close"].iloc[-1])
    return (c - lo) / (h - lo) if h > lo else 0.5


def setup_patterns(df, lookback=140, left=3, right=3, limit=4):
    """Günlük grafikte kurulum formasyonları. Döner: [{key,name,kind,level,lower,state,
    bars_since,conf,vol_x,note,start}]  — en güçlüden zayıfa."""
    if df is None or len(df) < 45:
        return []
    d = df.tail(int(lookback))
    n = len(d)
    H = d["High"].to_numpy(float)
    L = d["Low"].to_numpy(float)
    C = d["Close"].to_numpy(float)
    px = float(C[-1])
    a = _last(atr(d, 14)) or px * 0.02
    hi_i, _ = pivot_points(d["High"], left, right)
    _, lo_i = pivot_points(d["Low"], left, right)
    vx = _vol_x(d)
    cpos = _close_pos(d)
    out = []

    # ---------------- 1) ÜÇGEN -------------------------------------------------
    # Son 3 tepeye ve son 3 dibe doğru uydurulur; bantların daralması aranır.
    if len(hi_i) >= 3 and len(lo_i) >= 3:
        hx, hy = hi_i[-3:], [H[j] for j in hi_i[-3:]]
        lx, ly = lo_i[-3:], [L[j] for j in lo_i[-3:]]
        span = max(hx[-1], lx[-1]) - min(hx[0], lx[0])
        if 15 <= span <= 130:
            sh, bh = _fit(hx, hy)
            sl, bl = _fit(lx, ly)
            x0 = min(hx[0], lx[0])
            w0 = (sh * x0 + bh) - (sl * x0 + bl)
            w1 = (sh * (n - 1) + bh) - (sl * (n - 1) + bl)
            shp, slp = sh / px * 100, sl / px * 100      # %/bar
            flat = 0.045
            key = None
            if w0 > 0 and w1 > 0:
                if shp < -flat and slp > flat and w1 < w0 * 0.78:
                    key, kind = "triangle_sym", "bull" if C[-1] > (C[-20] if n > 20 else C[0]) else "bear"
                elif abs(shp) <= flat and slp > flat and w1 < w0 * 0.88:
                    key, kind = "triangle_asc", "bull"
                elif shp < -flat and abs(slp) <= flat and w1 < w0 * 0.88:
                    key, kind = "triangle_desc", "bear"
            if key:
                up_line = sh * (n - 1) + bh
                dn_line = sl * (n - 1) + bl
                level = up_line if kind == "bull" else dn_line
                st_ = _state(px, level, a, kind)
                conf = 0.55 + (0.18 if w1 < w0 * 0.6 else 0.08) + (0.12 if st_ == "breakout" else 0.0)
                out.append({"key": key, "name": SETUP_NAMES[key], "kind": kind,
                            "level": float(level), "lower": float(dn_line if kind == "bull" else up_line),
                            "state": st_, "bars_since": 0, "conf": round(min(1.0, conf), 2),
                            "vol_x": round(vx, 2), "start": int(min(hx[0], lx[0])) + (len(df) - n),
                            "note": "band narrowed %s%%" % fmt_num((1 - w1 / w0) * 100, 0)})

    # ---------------- 2) DİKDÖRTGEN -------------------------------------------
    # Son tepeler birbirine, son dipler birbirine yakın → yatay sıkışma.
    if len(hi_i) >= 2 and len(lo_i) >= 2:
        hs = [H[j] for j in hi_i[-3:]]
        ls = [L[j] for j in lo_i[-3:]]
        top, bot = float(np.mean(hs)), float(np.mean(ls))
        tol = 0.028
        span = max(hi_i[-1], lo_i[-1]) - min(hi_i[-len(hs)], lo_i[-len(ls)])
        flat_top = all(abs(v - top) / max(top, 1e-9) <= tol for v in hs)
        flat_bot = all(abs(v - bot) / max(bot, 1e-9) <= tol for v in ls)
        height = (top - bot) / max(px, 1e-9)
        if flat_top and flat_bot and 0.025 <= height <= 0.30 and span >= 15:
            kind = "bull" if px >= (top + bot) / 2 else "bear"
            level = top if kind == "bull" else bot
            st_ = _state(px, level, a, kind)
            conf = 0.58 + (0.14 if len(hs) >= 3 and len(ls) >= 3 else 0.0) + \
                (0.14 if st_ == "breakout" else 0.0)
            out.append({"key": "rectangle", "name": SETUP_NAMES["rectangle"], "kind": kind,
                        "level": float(level), "lower": float(bot if kind == "bull" else top),
                        "state": st_, "bars_since": 0, "conf": round(min(1.0, conf), 2),
                        "vol_x": round(vx, 2),
                        "start": int(min(hi_i[-len(hs)], lo_i[-len(ls)])) + (len(df) - n),
                        "note": "%s – %s band, height %s%%"
                                % (fmt_num(bot, 2), fmt_num(top, 2), fmt_num(height * 100, 1))})

    # ---------------- 3) MERDİVEN ---------------------------------------------
    # Üst üste yükselen zirveler VE yükselen dipler (ya da tersi).
    if len(hi_i) >= 3 and len(lo_i) >= 3:
        hs = [H[j] for j in hi_i[-3:]]
        ls = [L[j] for j in lo_i[-3:]]
        step = 0.01
        up_h = all(hs[i + 1] > hs[i] * (1 + step) for i in range(2))
        up_l = all(ls[i + 1] > ls[i] * (1 + step) for i in range(2))
        dn_h = all(hs[i + 1] < hs[i] * (1 - step) for i in range(2))
        dn_l = all(ls[i + 1] < ls[i] * (1 - step) for i in range(2))
        kind = "bull" if (up_h and up_l) else "bear" if (dn_h and dn_l) else None
        if kind:
            level = float(hs[-1] if kind == "bull" else ls[-1])
            st_ = _state(px, level, a, kind)
            legs = (hs[-1] / hs[0] - 1) * 100 if kind == "bull" else (1 - ls[-1] / ls[0]) * 100
            conf = 0.56 + min(0.2, abs(legs) / 100) + (0.12 if st_ == "breakout" else 0.0)
            out.append({"key": "ladder", "name": SETUP_NAMES["ladder"], "kind": kind,
                        "level": level, "lower": float(ls[-1] if kind == "bull" else hs[-1]),
                        "state": st_, "bars_since": 0, "conf": round(min(1.0, conf), 2),
                        "vol_x": round(vx, 2), "start": int(min(hi_i[-3], lo_i[-3])) + (len(df) - n),
                        "note": "in three steps %s%%" % fmt_num(abs(legs), 1)})

    # ---------------- 4) KIRILIM ----------------------------------------------
    # N barlık zirvenin ATR payıyla üstünde kapanış + hacim teyidi + güçlü kapanış yeri.
    for N, tag in ((20, "20-day"), (55, "55-day")):
        if n < N + 6:
            continue
        prior_h = float(np.nanmax(H[-N - 1:-1]))
        prior_l = float(np.nanmin(L[-N - 1:-1]))
        if px > prior_h + 0.25 * a:
            since = 0
            for k in range(1, min(12, n - N)):
                ref = float(np.nanmax(H[-N - 1 - k:-1 - k]))
                if C[-1 - k] > ref + 0.25 * a:
                    since = k
                else:
                    break
            rng10 = (np.nanmax(H[-12:-1]) - np.nanmin(L[-12:-1])) / max(a, 1e-9)
            conf = 0.5 + (0.18 if vx >= 1.5 else 0.06 if vx >= 1.1 else -0.08) \
                + (0.12 if cpos >= 0.65 else 0.0) + (0.1 if rng10 <= 4.5 else 0.0) \
                + (0.08 if N == 55 else 0.0)
            out.append({"key": "breakout", "name": "%s high breakout" % tag, "kind": "bull",
                        "level": prior_h, "lower": prior_l, "state": "breakout",
                        "bars_since": int(since), "conf": round(min(1.0, max(0.15, conf)), 2),
                        "vol_x": round(vx, 2), "start": int(n - N - 1) + (len(df) - n),
                        "note": "%s high %s cleared · volume %sx%s"
                                % (tag, fmt_num(prior_h, 2), fmt_num(vx, 1),
                                   " · from a tight squeeze" if rng10 <= 4.5 else "")})
            break
        if px < prior_l - 0.25 * a:
            out.append({"key": "breakdown", "name": "%s low breakdown" % tag, "kind": "bear",
                        "level": prior_l, "lower": prior_h, "state": "breakout", "bars_since": 0,
                        "conf": 0.55, "vol_x": round(vx, 2), "start": int(n - N - 1) + (len(df) - n),
                        "note": "%s low %s broken" % (tag, fmt_num(prior_l, 2))})
            break

    out.sort(key=lambda p: (-(p["state"] == "breakout"), -p["conf"]))
    return out[:int(limit)]


def confirm_15m(df15, level, kind="bull", vol_n=20, window=26):
    """Günlük kırılımın 15 dakikalık grafikte tutup tutmadığı.
    teyitli = seviyenin üstünde + hacimli kesiş + EMA9>EMA21 · bekleniyor = zayıf · bozuldu = altına döndü."""
    out = {"state": "no data", "ok": False, "vol_x": None, "bars_since": None,
           "note": "Could not load 15-minute data", "last": None}
    if df15 is None or len(df15) < 12 or level is None or not _ok(level):
        return out
    c = df15["Close"].to_numpy(float)
    v = df15["Volume"].astype(float).to_numpy()
    px = float(c[-1])
    out["last"] = px
    e9, e21 = _last(ema(df15["Close"], 9)), _last(ema(df15["Close"], 21))
    aligned = _ok(e9) and _ok(e21) and ((e9 > e21) if kind == "bull" else (e9 < e21))
    above = px > level if kind == "bull" else px < level
    cross = None
    lo = max(1, len(c) - int(window))
    for i in range(len(c) - 1, lo - 1, -1):
        prev, cur = c[i - 1], c[i]
        if kind == "bull" and prev <= level < cur:
            cross = i
            break
        if kind == "bear" and prev >= level > cur:
            cross = i
            break
    vx = None
    if cross is not None:
        base = v[max(0, cross - vol_n):cross]
        m = float(base.mean()) if len(base) else 0.0
        vx = round(float(v[cross]) / m, 2) if m > 0 else None
        out["bars_since"] = int(len(c) - 1 - cross)
    last_vx = None
    base = v[-vol_n - 1:-1]
    if len(base) and base.mean() > 0:
        last_vx = round(float(v[-1]) / float(base.mean()), 2)
    out["vol_x"] = vx if vx is not None else last_vx
    strong = (vx is not None and vx >= 1.3) or (last_vx is not None and last_vx >= 1.3)
    if not above:
        out["state"] = "failed"
        out["note"] = "15m price turned back through the %s level (%s)" % (fmt_num(level, 2),
                                                              "below" if kind == "bull" else "above")
        return out
    if strong and aligned:
        out["state"], out["ok"] = "confirmed", True
        out["note"] = "15m holding above %s · volume %sx · EMA9>EMA21" \
            % (fmt_num(level, 2), fmt_num(out["vol_x"] or 1, 1))
    else:
        out["state"] = "pending"
        eksik = []
        if not strong:
            eksik.append("volume weak")
        if not aligned:
            eksik.append("EMA alignment has not turned yet")
        out["note"] = "15m above the level but " + " and ".join(eksik)
    return out


def swing_plan(df, zones, level=None, kind="bull", tp1_part=0.40):
    """Stop / hedef planı: stop son günlük mumun ya da destek bandının altı,
    TP1 bir sonraki S/R bandı (burada %40 satılır), kalan %60 trendi takip eder;
    TP1'e ulaşınca kalanın stopu TP1 seviyesine çekilir."""
    if df is None or len(df) < 20:
        return None
    px = float(df["Close"].iloc[-1])
    a = _last(atr(df, 14)) or px * 0.02
    last_low = float(df["Low"].iloc[-1])
    last_high = float(df["High"].iloc[-1])
    zones = zones or []
    sup = [z for z in zones if (z["lo"] + z["hi"]) / 2 < px]
    res = [z for z in zones if (z["lo"] + z["hi"]) / 2 > px]
    sup.sort(key=lambda z: -(z["lo"] + z["hi"]) / 2)
    res.sort(key=lambda z: (z["lo"] + z["hi"]) / 2)
    if kind == "bull":
        cands = [("last daily candle", last_low - 0.08 * a)]
        if sup:
            cands.append(("support band", float(sup[0]["lo"]) - 0.08 * a))
        if level is not None and _ok(level):
            cands.append(("breakout level", float(level) - 0.5 * a))
        name, stop = min(cands, key=lambda x: x[1])
        if px - stop > 3.2 * a:                       # çok geniş stop → ATR'ye çek
            name, stop = "2×ATR (bands too far)", px - 2.0 * a
        risk = max(px - stop, 0.15 * a)
        t1_src = "resistance band"
        tp1 = float(res[0]["lo"]) if res else px + 2.0 * risk
        if not res:
            t1_src = "2R target"
        if tp1 <= px + 0.35 * risk:                   # bant çok yakınsa bir sonrakine geç
            if len(res) > 1:
                tp1 = float(res[1]["lo"])
            else:
                tp1, t1_src = px + 2.0 * risk, "2R target"
        t2_src = "the second band above"
        nxt = [z for z in res if float(z["lo"]) > tp1 * 1.001]
        tp2 = float(nxt[0]["lo"]) if nxt else px + 3.5 * risk
        if not nxt:
            t2_src = "3.5R target"
    else:
        cands = [("last daily candle", last_high + 0.08 * a)]
        if res:
            cands.append(("resistance band", float(res[0]["hi"]) + 0.08 * a))
        name, stop = max(cands, key=lambda x: x[1])
        if stop - px > 3.2 * a:
            name, stop = "2×ATR (bands too far)", px + 2.0 * a
        risk = max(stop - px, 0.15 * a)
        tp1 = float(sup[0]["hi"]) if sup else px - 2.0 * risk
        t1_src = "support band" if sup else "2R target"
        nxt = [z for z in sup if float(z["hi"]) < tp1 * 0.999]
        tp2 = float(nxt[0]["hi"]) if nxt else px - 3.5 * risk
        t2_src = "the second band below" if nxt else "3.5R target"
    rr1 = abs(tp1 - px) / risk if risk > 0 else 0.0
    rr2 = abs(tp2 - px) / risk if risk > 0 else 0.0
    part = float(min(0.9, max(0.1, tp1_part)))
    return {"entry": round(px, 4), "stop": round(stop, 4), "tp1": round(tp1, 4), "tp2": round(tp2, 4),
            "risk": round(risk, 4), "risk_pct": round(risk / px * 100, 2),
            "rr1": round(rr1, 2), "rr2": round(rr2, 2), "atr": round(float(a), 4),
            "stop_src": name, "tp1_src": t1_src, "tp2_src": t2_src,
            "part1": part, "part2": round(1 - part, 2),
            "rule": ("Sell %d%% at TP1 and let the remaining %d%% ride the trend; once TP1 is hit "
                     "the stop on the rest moves up to TP1 (%s)."
                     % (round(part * 100), round((1 - part) * 100), fmt_num(tp1, 2)))}


# ======================================================================
# v3.2 — "Yapay Zeka Trade Fırsatları" taraması
#   1) Ucuz filtreler (fiyat, günlük değişim, piyasa değeri) → hacme göre sırala
#   2) İlk N adayın günlük verisinde EMA21 / EMA50 kapısı
#   3) Kalanların ilk 20'sinde formasyon + 15 dakikalık teyit + stop/hedef planı
# ======================================================================
AI_FILTER = {
    "min_price": 3.0,        # fiyat ≥ 3 $
    "min_change": 0.01,      # günlük değişim > %0,01 (pozitif yönde)
    "min_cap": 300e6,        # piyasa değeri ≥ 300 M$
    "ema_fast": 21,          # fiyat 21 EMA üstünde
    "ema_slow": 50,          # fiyat 50 EMA üstünde
    "regime_ema": 50,        # SPY ve QQQ 50 günlük EMA üstünde
    "prelim": 60,            # günlük veri çekilecek aday sayısı
    "top": 20,               # nihai liste
    "tp1_part": 0.40,        # TP1'de satılacak oran
}
AI_STATE_PTS = {"breakout": 20.0, "retest": 12.0, "forming": 5.0}
AI_C15_PTS = {"confirmed": 20.0, "pending": 8.0, "no data": 6.0, "failed": 0.0}


def ai_cfg(over=None):
    c = dict(AI_FILTER)
    for k, v in (over or {}).items():
        if k in c:
            try:
                c[k] = type(AI_FILTER[k])(v)
            except (TypeError, ValueError):
                pass
    return c


def ai_regime(idx, n=50):
    """SPY / QQQ 50 günlük EMA'nın üstünde mi? Filtrenin bölge kapısı."""
    out, ok = {}, True
    for k, df in (idx or {}).items():
        if df is None or len(df) < n + 5:
            out[k] = None
            ok = False
            continue
        px = float(df["Close"].iloc[-1])
        e = _last(ema(df["Close"], n))
        good = bool(_ok(e) and px > e)
        out[k] = {"price": px, "ema": float(e) if _ok(e) else None, "ok": good,
                  "pct": ((px / e - 1) * 100) if (_ok(e) and e) else None}
        ok = ok and good
    out["ok"] = bool(ok and idx)
    return out


def ai_prefilter(snap, cfg=None):
    """Anlık görüntüde ucuz filtreler; hacme göre azalan sırada döndürür."""
    c = ai_cfg(cfg)
    steps = {"evren": 0, "price": 0, "degisim": 0, "piyasa_degeri": 0, "capless": True}
    if snap is None or len(snap) == 0:
        return snap, steps
    capless = bool((getattr(snap, "attrs", None) or {}).get("capless"))
    d = snap.copy()
    steps["evren"] = len(d)
    d = d[d["last"].astype(float) >= c["min_price"]]
    steps["price"] = len(d)
    d = d[d["change_pct"].astype(float) > c["min_change"]]
    steps["degisim"] = len(d)
    if not capless:
        cap = pd.to_numeric(d["market_cap"], errors="coerce")
        d = d[cap >= c["min_cap"]]
    steps["piyasa_degeri"] = len(d)
    steps["capless"] = capless
    d = d.sort_values("volume", ascending=False, na_position="last").reset_index(drop=True)
    return d, steps


def ai_evaluate(ticker, df, df15=None, zones=None, cfg=None, meta=None):
    """Tek sembol: EMA kapısı, formasyon, 15dk teyidi ve işlem planı."""
    c = ai_cfg(cfg)
    if df is None or len(df) < 60:
        return None
    close = df["Close"]
    px = float(close.iloc[-1])
    ef, es = _last(ema(close, c["ema_fast"])), _last(ema(close, c["ema_slow"]))
    if not (_ok(ef) and _ok(es)):
        return None
    ema_ok = bool(px > ef and px > es)
    zones = ranked_sr_zones(df) if zones is None else zones
    pats = setup_patterns(df)
    best = pats[0] if pats else None
    plan = swing_plan(df, zones, level=(best or {}).get("level"),
                      kind=(best or {}).get("kind", "bull"), tp1_part=c["tp1_part"])
    c15 = confirm_15m(df15, best["level"], best["kind"]) if (df15 is not None and best) else None
    score = 0.0
    if best:
        score += 40.0 * float(best["conf"])
        score += AI_STATE_PTS.get(best["state"], 0.0)
        if best["vol_x"] and best["vol_x"] >= 1.5:
            score += 5.0
    if c15:
        score += AI_C15_PTS.get(c15["state"], 0.0)
    if plan:
        score += 12.0 * min(1.0, plan["rr1"] / 3.0)
    if ema_ok:
        score += 8.0
    m = meta or {}
    return {"ticker": ticker, "name": m.get("name") or ticker, "price": px,
            "chg": float(m.get("change_pct") or 0.0), "volume": float(m.get("volume") or 0.0),
            "market_cap": m.get("market_cap"), "sector": m.get("sector") or "",
            "ema_ok": ema_ok, "ema_fast": float(ef), "ema_slow": float(es),
            "patterns": pats, "best": best, "plan": plan, "c15": c15,
            "zones": (zones or [])[:6], "score": round(min(100.0, max(0.0, score)), 1)}


def ai_fresh_breakout(r, max_bars=1):
    """Bildirime düşecek kadar taze ve teyitli bir kırılım mı?"""
    b, c15 = r.get("best"), r.get("c15")
    if not b or b["state"] != "breakout" or b["kind"] != "bull":
        return False
    if int(b.get("bars_since") or 0) > max_bars:
        return False
    return bool(r.get("ema_ok")) and bool(c15 and c15.get("state") in ("confirmed", "pending"))


def ai_apply_15m(r, c15):
    """15 dakikalık teyit sonucunu sonuca ve skora işler."""
    if not r:
        return r
    r["c15"] = c15
    if c15:
        r["score"] = round(min(100.0, r["score"] + AI_C15_PTS.get(c15.get("state"), 0.0)), 1)
    return r


def ai_summary(r):
    """Sonucu tek cümlede özetler (kural tabanlı)."""
    if not r:
        return ""
    b, p, c = r.get("best"), r.get("plan"), r.get("c15")
    bits = []
    if b:
        durum = {"breakout": "breakout happened", "retest": "retesting the level",
                 "forming": "still forming"}.get(b["state"], b["state"])
        bits.append("%s — %s (%s)" % (b["name"], durum, b["note"]))
    else:
        bits.append("No clear pattern, it only passed the trend and volume conditions")
    if c:
        bits.append("15-minute confirmation: %s — %s" % (c["state"], c["note"]))
    if p:
        bits.append("Entry %s · stop %s (%s, −%s%%) · TP1 %s (%s, R/R 1:%s)"
                    % (fmt_num(p["entry"], 2), fmt_num(p["stop"], 2), p["stop_src"],
                       fmt_num(p["risk_pct"], 1), fmt_num(p["tp1"], 2), p["tp1_src"],
                       fmt_num(p["rr1"], 2)))
        bits.append(p["rule"])
    return " ".join(bits)


# ======================================================================
# v3.3 — DEĞER ANALİZİ
#   Finansal tablolardan seri çıkarma, oranlar, kalite skorları,
#   adil değer patikası, DCF / ters DCF, döngüsellik ve değer notu.
# ======================================================================
NAN = float("nan")
INC_ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue", "Revenue"),
    "gross": ("Gross Profit",),
    "op_income": ("Operating Income", "EBIT"),
    "net_income": ("Net Income Common Stockholders", "Net Income"),
    "ebitda": ("Normalized EBITDA", "EBITDA"),
    "interest": ("Interest Expense",),
    "pretax": ("Pretax Income",),
    "shares": ("Diluted Average Shares", "Basic Average Shares"),
    "eps": ("Diluted EPS", "Basic EPS"),
    "rnd": ("Research And Development", "Research Development"),
    "da_inc": ("Reconciled Depreciation", "Depreciation And Amortization In Income Statement",
               "Depreciation Amortization Depletion Income Statement"),
    "tax_rate": ("Tax Rate For Calcs",),
}
BAL_ROWS = {
    "assets": ("Total Assets",),
    "cur_assets": ("Current Assets", "Total Current Assets"),
    "cur_liab": ("Current Liabilities", "Total Current Liabilities"),
    "liab": ("Total Liabilities Net Minority Interest", "Total Liabilities"),
    "equity": ("Stockholders Equity", "Total Stockholder Equity"),
    "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
    "debt": ("Total Debt", "Long Term Debt"),
    "retained": ("Retained Earnings",),
    "working_cap": ("Working Capital",),
    "deferred_rev": ("Current Deferred Revenue", "Deferred Revenue Current", "Deferred Revenue"),
    "deferred_rev_nc": ("Non Current Deferred Revenue", "Non Current Deferred Liabilities"),
    "shares_out": ("Ordinary Shares Number", "Share Issued"),
}
CF_ROWS = {
    "ocf": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure",),
    "fcf_rep": ("Free Cash Flow",),
    "buyback": ("Repurchase Of Capital Stock",),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
    "da_cf": ("Depreciation And Amortization", "Depreciation Amortization Depletion"),
    "sbc": ("Stock Based Compensation",),
}


def _row(df, *names):
    if df is None or getattr(df, "empty", True):
        return None
    idx = {str(i).strip().lower(): i for i in df.index}
    for n in names:
        k = n.strip().lower()
        if k in idx:
            return df.loc[idx[k]]
    for n in names:                      # tam eşleşme yoksa içerik araması
        k = n.strip().lower()
        for low, orig in idx.items():
            if k in low:
                return df.loc[orig]
    return None


def _vals(s, n):
    out = []
    if s is not None:
        for v in list(s)[-n:]:
            try:
                f = float(v)
            except (TypeError, ValueError):
                f = NAN
            out.append(f)
    while len(out) < n:
        out.insert(0, NAN)
    return out


def _d(a, b):
    """Güvenli bölme."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return NAN
    if b == 0 or b != b or a != a:
        return NAN
    return a / b


def financials(stmts, years=5):
    """Tablolardan yıl yıl hizalanmış seriler. Döner: dict ya da None."""
    if not stmts:
        return None
    inc = stmts.get("income")
    if inc is None or getattr(inc, "empty", True):
        return None
    cols = list(inc.columns)[-years:]
    n = len(cols)
    if n < 2:
        return None
    f = {"n": n, "years": [int(pd.Timestamp(c).year) for c in cols], "dates": [pd.Timestamp(c) for c in cols]}
    for k, names in INC_ROWS.items():
        f[k] = _vals(_row(inc, *names), n)
    for k, names in BAL_ROWS.items():
        f[k] = _vals(_row(stmts.get("balance"), *names), n)
    for k, names in CF_ROWS.items():
        f[k] = _vals(_row(stmts.get("cashflow"), *names), n)
    # türetilenler
    f["fcf"] = [r if r == r else (o + c if (o == o and c == c) else NAN)
                for r, o, c in zip(f["fcf_rep"], f["ocf"], f["capex"])]
    f["net_debt"] = [(dd - cc) if (dd == dd and cc == cc) else NAN
                     for dd, cc in zip(f["debt"], f["cash"])]
    f["gross_m"] = [_d(g, r) * 100 for g, r in zip(f["gross"], f["revenue"])]
    f["op_m"] = [_d(o, r) * 100 for o, r in zip(f["op_income"], f["revenue"])]
    f["net_m"] = [_d(x, r) * 100 for x, r in zip(f["net_income"], f["revenue"])]
    f["fcf_m"] = [_d(x, r) * 100 for x, r in zip(f["fcf"], f["revenue"])]
    f["roe"] = [_d(x, e) * 100 for x, e in zip(f["net_income"], f["equity"])]
    f["roa"] = [_d(x, a) * 100 for x, a in zip(f["net_income"], f["assets"])]
    if not any(v == v for v in f["eps"]):       # EPS yoksa net kâr / hisse adedi
        f["eps"] = [_d(x, s) for x, s in zip(f["net_income"], f["shares"])]
    # amortisman: önce nakit akışı tablosu, yoksa gelir tablosu, o da yoksa FAVÖK − FVÖK
    f["da"] = [a if a == a else (b if b == b else ((e - o) if (e == e and o == o and e > o) else NAN))
               for a, b, e, o in zip(f["da_cf"], f["da_inc"], f["ebitda"], f["op_income"])]
    f["shares"] = [s_ if s_ == s_ else so for s_, so in zip(f["shares"], f["shares_out"])]
    return f


def cagr(series, years=None):
    """Bileşik yıllık büyüme (%); negatiften pozitife geçişlerde anlamsız olacağı için NaN."""
    v = [x for x in (series or []) if x == x]
    if len(v) < 2:
        return NAN
    a, b = v[0], v[-1]
    k = (years if years is not None else len(v) - 1)
    if k <= 0 or a is None or a <= 0 or b <= 0:
        return NAN
    return ((b / a) ** (1.0 / k) - 1) * 100


def yoy(series):
    out = [NAN]
    for i in range(1, len(series or [])):
        a, b = series[i - 1], series[i]
        out.append(((b / a - 1) * 100) if (a == a and b == b and a > 0) else NAN)
    return out


def fin_ratios(f, detail=None):
    """Son yılın oranları + tarihsel eğilim."""
    if not f:
        return {}
    d = detail or {}
    i = f["n"] - 1
    rev, ni = f["revenue"][i], f["net_income"][i]
    ebit, ebitda = f["op_income"][i], f["ebitda"][i]
    mcap = d.get("market_cap", NAN)
    nd = f["net_debt"][i]
    ev = (mcap + nd) if (mcap == mcap and nd == nd) else NAN
    return {
        "revenue": rev, "net_income": ni, "ebitda": ebitda, "fcf": f["fcf"][i],
        "gross_m": f["gross_m"][i], "op_m": f["op_m"][i], "net_m": f["net_m"][i], "fcf_m": f["fcf_m"][i],
        "roe": f["roe"][i], "roa": f["roa"][i],
        "debt_equity": _d(f["debt"][i], f["equity"][i]),
        "net_debt_ebitda": _d(nd, ebitda),
        "current_ratio": _d(f["cur_assets"][i], f["cur_liab"][i]),
        "interest_cover": _d(ebit, abs(f["interest"][i])) if f["interest"][i] == f["interest"][i] else NAN,
        "ev": ev, "ev_ebitda": _d(ev, ebitda), "ev_sales": _d(ev, rev),
        "fcf_yield": _d(f["fcf"][i], mcap) * 100,
        "accrual": (_d(f["fcf"][i], ni) if ni == ni and ni > 0 else NAN),
        "rev_cagr": cagr(f["revenue"]), "eps_cagr": cagr(f["eps"]), "fcf_cagr": cagr(f["fcf"]),
        "rev_yoy": yoy(f["revenue"]), "eps_yoy": yoy(f["eps"]),
        "share_chg": ((f["shares"][i] / f["shares"][0] - 1) * 100)
                     if (f["shares"][0] == f["shares"][0] and f["shares"][0] > 0
                         and f["shares"][i] == f["shares"][i]) else NAN,
        "buyback": f["buyback"][i], "dividends": f["dividends_paid"][i],
    }


# ---------------------------------------------------------------- kalite skorları
def piotroski(f):
    """Piotroski F-skoru (0–9): kârlılık, kaldıraç/likidite ve verimlilik kontrolleri."""
    if not f or f["n"] < 2:
        return None
    i, j = f["n"] - 1, f["n"] - 2
    roa_now, roa_prev = _d(f["net_income"][i], f["assets"][i]), _d(f["net_income"][j], f["assets"][j])
    lev_now, lev_prev = _d(f["debt"][i], f["assets"][i]), _d(f["debt"][j], f["assets"][j])
    cur_now, cur_prev = _d(f["cur_assets"][i], f["cur_liab"][i]), _d(f["cur_assets"][j], f["cur_liab"][j])
    turn_now, turn_prev = _d(f["revenue"][i], f["assets"][i]), _d(f["revenue"][j], f["assets"][j])
    checks = [
        ("Net income positive", roa_now == roa_now and roa_now > 0, "Return on assets %s" % fmt_num(roa_now * 100, 1)),
        ("Operating cash flow positive", f["ocf"][i] == f["ocf"][i] and f["ocf"][i] > 0, ""),
        ("Return on assets rising", roa_now == roa_now and roa_prev == roa_prev and roa_now > roa_prev, ""),
        ("Cash flow above earnings", (f["ocf"][i] == f["ocf"][i] and f["net_income"][i] == f["net_income"][i]
                                      and f["ocf"][i] > f["net_income"][i]), "earnings quality"),
        ("Debt/assets falling", lev_now == lev_now and lev_prev == lev_prev and lev_now <= lev_prev, ""),
        ("Current ratio rising", cur_now == cur_now and cur_prev == cur_prev and cur_now > cur_prev,
         "Current ratio %s" % fmt_num(cur_now, 2)),
        ("Share count not rising", (f["shares"][i] == f["shares"][i] and f["shares"][j] == f["shares"][j]
                                  and f["shares"][i] <= f["shares"][j] * 1.002),
         ("%s%% annual" % fmt_num(_d(f["shares"][i], f["shares"][j]) * 100 - 100, 1))
         if (f["shares"][i] == f["shares"][i] and f["shares"][j] == f["shares"][j]) else "no data"),
        ("Gross margin rising", (f["gross_m"][i] == f["gross_m"][i] and f["gross_m"][j] == f["gross_m"][j]
                               and f["gross_m"][i] > f["gross_m"][j]), ""),
        ("Asset turnover rising", turn_now == turn_now and turn_prev == turn_prev and turn_now > turn_prev, ""),
    ]
    score = sum(1 for _, ok, _ in checks if ok)
    label = "Strong" if score >= 7 else "Moderate" if score >= 4 else "Weak"
    return {"score": score, "max": 9, "label": label,
            "checks": [{"t": t, "ok": bool(ok), "note": nt} for t, ok, nt in checks]}


def altman_z(f, market_cap):
    """Altman Z-skoru — iflas riski. >2,99 güvenli · 1,81–2,99 gri · <1,81 riskli."""
    if not f or f["n"] < 1:
        return None
    i = f["n"] - 1
    A = f["assets"][i]
    if A != A or A <= 0:
        return None
    wc = f["working_cap"][i]
    if wc != wc:
        ca, cl = f["cur_assets"][i], f["cur_liab"][i]
        wc = (ca - cl) if (ca == ca and cl == cl) else NAN
    x1, x2 = _d(wc, A), _d(f["retained"][i], A)
    x3 = _d(f["op_income"][i], A)
    x4 = _d(market_cap, f["liab"][i])
    x5 = _d(f["revenue"][i], A)
    parts = [x1, x2, x3, x4, x5]
    if sum(1 for p in parts if p == p) < 4:
        return None
    z = (1.2 * (x1 if x1 == x1 else 0) + 1.4 * (x2 if x2 == x2 else 0) + 3.3 * (x3 if x3 == x3 else 0)
         + 0.6 * (x4 if x4 == x4 else 0) + 1.0 * (x5 if x5 == x5 else 0))
    zone = "Safe" if z >= 2.99 else "Grey zone" if z >= 1.81 else "Risky"
    return {"z": round(float(z), 2), "zone": zone,
            "parts": {"Working capital/Assets": x1, "Retained earnings/Assets": x2,
                      "EBIT/Assets": x3, "Market cap/Debt": x4, "Sales/Assets": x5}}


def consistency(f):
    """Bilanço sürekliliği: yıl yıl aynı yönde mi gidiyor?"""
    if not f or f["n"] < 3:
        return None
    def _up(key, tol=0.0):
        v = [x for x in f[key] if x == x]
        if len(v) < 3:
            return None
        return sum(1 for a, b in zip(v, v[1:]) if b >= a * (1 - tol)), len(v) - 1
    rows = []
    for key, name, tol in (("revenue", "Revenue grew every year", 0.0), ("net_income", "Net income grew every year", 0.0),
                           ("fcf", "Free cash flow grew every year", 0.0),
                           ("gross_m", "Gross margin held", 0.05), ("equity", "Equity grew", 0.0)):
        r = _up(key, tol)
        if r:
            rows.append({"t": name, "hit": r[0], "of": r[1], "ok": r[0] == r[1]})
    pos_fcf = sum(1 for x in f["fcf"] if x == x and x > 0)
    n_fcf = sum(1 for x in f["fcf"] if x == x)
    if n_fcf:
        rows.append({"t": "Free cash flow always positive", "hit": pos_fcf, "of": n_fcf,
                     "ok": pos_fcf == n_fcf})
    pos_ni = sum(1 for x in f["net_income"] if x == x and x > 0)
    n_ni = sum(1 for x in f["net_income"] if x == x)
    if n_ni:
        rows.append({"t": "Net income always positive", "hit": pos_ni, "of": n_ni, "ok": pos_ni == n_ni})
    hit = sum(r["hit"] for r in rows)
    of = sum(r["of"] for r in rows)
    pct = _d(hit, of) * 100
    return {"rows": rows, "hit": hit, "of": of, "pct": pct,
            "label": "Very stable" if pct >= 85 else "Stable" if pct >= 65
            else "Choppy" if pct >= 45 else "Irregular"}


# ---------------------------------------------------------------- değerleme
def hist_eps_drop(eps):
    """Geçmiş yıllık EPS'te en sert zirve → sonraki dip düşüşü (%). Döngü derinliği için."""
    xs = [float(v) for v in (eps or []) if _ok(v)]
    best = None
    for i, a in enumerate(xs):
        if a <= 0:
            continue
        lo = min(xs[i + 1:], default=a)
        d = (1 - lo / a) * 100
        if best is None or d > best:
            best = d
    return best


SCEN_KEYS = ("bear", "base", "bull")


def value_path(price, eps_last, est=None, g_lt=8.0, years=5, cyclical=False, peak_idx=None,
               drop=45.0, down_years=2, target_mult=None, rerate_years=3, fy0=None, fy0_left=0.5,
               window=None, g_near=None, fy0_end=None):
    """Mali yıl bazında değer patikası (v3.8): Değer_FY = EPS_FY × çarpan_FY — kâr ve çarpan aynı yıla ait.

    * EPS yıl yıl, YoY büyümeyle kurulur: önce analist tahminleri (taban = ortalama, kötümser = en düşük,
      iyimser = en yüksek), sonra her yıl `g_lt` (YoY). Çok yıllık ortalama / pencere yok (`window` yok sayılır).
    * Döngüsel modda kâr TAM OLARAK seçilen mali yılda (`peak_idx`) zirve yapar: zirveye kadar azalmaz,
      zirveden sonra `down_years` yılda `drop` % geriler ve ufuk içinde zirvenin altında kalır. Zirveden
      sonraki yıllarda analist tahmini varsa da düşüş modeli geçerlidir (işaretlenir).
    * Çarpan bugünkü fiyata, içinde bulunulan mali yılın (FY0) EPS'ine kalibre edilir: FY0 değeri = bugünkü
      fiyat. `target_mult` verilirse çarpan `rerate_years` içinde o değere kayar (döngüselde zirveden sonra).
    * Döngüselde her senaryonun en yüksek değeri seçilen zirve yılındadır; çarpan değişimi bunu bozarsa o
      yılın değeri zirvenin hemen altına çekilir ve `capped` ile bildirilir.
    """
    if not _ok(eps_last):
        return None
    est = [e for e in (est or []) if _ok(e.get("avg"))]
    years = int(years)
    H = years + 1                                  # FY0 … FY0+years
    g_lt = float(g_lt if _ok(g_lt) else 8.0)
    if not _ok(g_near):
        g_near = g_lt
    this_year = int(pd.Timestamp.now().year)
    fy0 = int(fy0 or this_year)
    try:
        end0 = pd.Timestamp(fy0_end) if fy0_end else pd.Timestamp(year=fy0, month=12, day=31)
    except Exception:
        end0 = pd.Timestamp(year=fy0, month=12, day=31)
    ends = [end0 + pd.DateOffset(years=k) for k in range(H)]
    if peak_idx is None:
        peak_idx = int(np.argmax([e["avg"] for e in est])) if est else 0
    peak_idx = int(min(H - 1, max(0, peak_idx)))
    drop = float(min(95.0, max(0.0, drop if _ok(drop) else 45.0)))
    down_years = int(max(1, down_years))
    sp = {"bear": {"est": "low", "g": g_lt * 0.5 - 1.0, "drop": min(95.0, drop * 1.35), "m": 0.85},
          "base": {"est": "avg", "g": g_lt, "drop": drop, "m": 1.0},
          "bull": {"est": "high", "g": g_lt * 1.5 + 1.0, "drop": drop * 0.6, "m": 1.15}}
    eps, srcs = {}, {}
    for key, p in sp.items():
        gl = p["g"] / 100.0
        e, src = [], []
        for i in range(H):
            post = cyclical and i > peak_idx
            if i < len(est) and not post:
                v = float(est[i].get(p["est"], est[i]["avg"]))
                if not _ok(v):
                    v = float(est[i]["avg"])
                sc = "analyst"
            elif i == 0:
                v = float(eps_last) * (1 + g_near / 100.0)
                sc = "model"
            elif post:
                pk = e[peak_idx]
                if i <= peak_idx + down_years:
                    v = pk * (1 - p["drop"] / 100.0 * (i - peak_idx) / down_years)
                else:
                    # dipten toparlanma: YoY büyüme (yılda en fazla %25), ufuk içinde zirvenin altında
                    v = e[-1] * (1 + min(0.25, max(gl, 0.0)))
                v = min(v, pk * 0.97) if pk > 0 else v
                sc = "post-peak" if i < len(est) else "model"
            else:
                prev = e[-1]
                if cyclical and i <= peak_idx:
                    # analist tahmini bitti ama zirve daha ileride: son YoY büyümenin yarısıyla devam
                    last_g = (e[-1] / e[-2] - 1) if (len(e) > 1 and e[-2] > 0) else gl
                    v = prev * (1 + min(0.40, max(gl, last_g * 0.5)))
                else:
                    v = prev * (1 + gl)
                sc = "model"
            if cyclical and 0 < i <= peak_idx and e and e[-1] > 0 and v < e[-1] * 1.01:
                v = e[-1] * 1.01                     # zirve seçilen yılda olsun: öncesi azalmaz
                sc = "held"
            e.append(float(v))
            src.append(sc)
        eps[key], srcs[key] = e, src

    e0 = eps["base"][0]
    if max(eps["base"]) <= 0:
        return None
    if _ok(price) and price > 0 and e0 > 0:
        m_cal = float(price) / e0
    else:
        m_cal = float(target_mult) if _ok(target_mult) and target_mult > 0 else 15.0
    m_cal = float(min(80.0, max(1.0, m_cal)))
    m_tgt = float(target_mult) if (_ok(target_mult) and target_mult > 0) else m_cal
    start = peak_idx if cyclical else 0

    def mult(k, key):
        t = min(1.0, max(0.0, (k - start) / float(max(1, rerate_years))))
        ts = min(1.0, k / float(max(1, rerate_years)))
        m = m_cal + (m_tgt - m_cal) * t
        return m * (1 + (sp[key]["m"] - 1) * ts)

    vals, mults, capped = {}, {}, []
    for key in SCEN_KEYS:
        vs = [max(0.0, eps[key][k] * mult(k, key)) for k in range(H)]
        ms = [mult(k, key) for k in range(H)]
        if cyclical and vs[peak_idx] > 0:
            top = vs[peak_idx]
            for k in range(H):
                if k != peak_idx and vs[k] >= top:
                    vs[k] = top * 0.99
                    ms[k] = vs[k] / eps[key][k] if eps[key][k] > 0 else ms[k]
                    if key == "base":
                        capped.append(fy0 + k)
        vals[key], mults[key] = vs, ms
    rows = []
    for k in range(H):
        prev_v = vals["base"][k - 1] if k else (float(price) if _ok(price) and price > 0 else None)
        prev_e = eps["base"][k - 1] if k else float(eps_last)
        row = {"year": fy0 + k, "fy": fy0 + k, "label": f"FY{fy0 + k}", "k": k, "end": ends[k],
               "value": {key: round(vals[key][k], 2) for key in SCEN_KEYS},
               "eps": {key: round(eps[key][k], 3) for key in SCEN_KEYS},
               "mult": {key: round(mults[key][k], 2) for key in SCEN_KEYS},
               "src": srcs["base"][k],
               "eps_yoy": round((eps["base"][k] / prev_e - 1) * 100, 1) if prev_e and prev_e > 0 else None,
               "yoy": round((vals["base"][k] / prev_v - 1) * 100, 1) if prev_v and prev_v > 0 else None}
        if _ok(price) and price > 0:
            row["upside"] = round((vals["base"][k] / price - 1) * 100, 1)
        rows.append(row)
    eps_rows = [{"fy": r["fy"], "label": r["label"], "src": r["src"], "eps": r["eps"], "growth": r["eps_yoy"]}
                for r in rows]
    base_vals = vals["base"]
    pk_k = peak_idx if cyclical else int(np.argmax(base_vals))
    today = {"year": this_year, "k": -1, "value": {key: float(price) if _ok(price) else base_vals[0]
                                                   for key in SCEN_KEYS}}
    return {"rows": rows, "today": today, "eps_rows": eps_rows, "eps_last": float(eps_last),
            "m_cal": round(m_cal, 2), "m_target": round(m_tgt, 2), "window": 1, "cyclical": bool(cyclical),
            "peak_fy": fy0 + peak_idx, "peak_idx": peak_idx, "drop": drop, "down_years": down_years,
            "g_lt": g_lt, "fy0": fy0, "n_est": len(est), "price_peak_year": fy0 + pk_k,
            "price_peak_value": base_vals[pk_k], "rerated": m_tgt != m_cal, "capped": capped,
            "ends": ends, "fy0_end": end0, "eps_series": eps, "mult_series": mults,
            "overridden": [fy0 + k for k in range(H) if srcs["base"][k] in ("post-peak", "held")],
            "scen": {k: {"g": round(v["g"], 1), "drop": round(v["drop"], 0), "m": v["m"], "est": v["est"]}
                     for k, v in sp.items()}}


def value_sensitivity(price, eps_last, est, cfg, rows_vals, mults, years=5):
    """Duyarlılık: satır = döngüselde zirve sonrası düşüş, değilse uzun vade büyümesi; sütun = hedef çarpan."""
    key = "drop" if cfg.get("cyclical") else "g_lt"
    grid = []
    for rv in rows_vals:
        line = []
        for m in mults:
            c = dict(cfg)
            c[key] = rv
            c["target_mult"] = m
            p = value_path(price, eps_last, est, years=years, **c)
            line.append(p["rows"][-1]["value"]["base"] if p else float("nan"))
        grid.append(line)
    return {"key": key, "rows": list(rows_vals), "multiples": list(mults), "grid": grid, "years": years}


def dcf(fcf0, shares, growth_pct, years=10, discount=9.0, terminal=2.5, net_debt=0.0):
    """İndirgenmiş nakit akışı: büyüme uç değere doğru azalarak gider."""
    if not (_ok(fcf0) and _ok(shares)) or shares <= 0 or fcf0 <= 0:
        return None
    r, t = discount / 100.0, terminal / 100.0
    if r <= t:
        r = t + 0.02
    g0 = max(-0.1, min(0.5, (growth_pct if _ok(growth_pct) else 5.0) / 100.0))
    pv, fcf = 0.0, float(fcf0)
    for k in range(1, int(years) + 1):
        gk = g0 + (t - g0) * (k - 1) / max(1, years - 1)     # büyüme kademeli olarak uç değere iner
        fcf *= (1 + gk)
        pv += fcf / ((1 + r) ** k)
    tv = fcf * (1 + t) / (r - t)
    pv += tv / ((1 + r) ** years)
    eq = pv - (net_debt if _ok(net_debt) else 0.0)
    return {"value": round(eq / shares, 2), "pv": pv, "terminal_share": round(tv / ((1 + r) ** years) / pv * 100, 1),
            "discount": discount, "terminal": terminal, "growth": g0 * 100, "years": years}


def reverse_dcf(price, fcf0, shares, years=10, discount=9.0, terminal=2.5, net_debt=0.0):
    """Bugünkü fiyat hangi büyümeyi fiyatlıyor? (ikiye bölerek çözülür)"""
    if not (_ok(price) and _ok(fcf0) and _ok(shares)) or price <= 0 or fcf0 <= 0 or shares <= 0:
        return None
    lo, hi = -20.0, 45.0
    f = lambda g: (dcf(fcf0, shares, g, years, discount, terminal, net_debt) or {}).get("value", NAN)
    vlo, vhi = f(lo), f(hi)
    if not (_ok(vlo) and _ok(vhi)):
        return None
    if price > vhi:        # fiyat arama aralığının üstünde kalıyor
        return {"growth": hi, "capped": "above"}
    if price < vlo:
        return {"growth": lo, "capped": "below"}
    for _ in range(50):
        mid = (lo + hi) / 2
        if f(mid) < price:
            lo = mid
        else:
            hi = mid
    return {"growth": round((lo + hi) / 2, 1), "capped": None}


def pe_band(px, f, pe_now=None):
    """Hissenin kendi tarihsel P/E aralığı ve bugünkü konumu (yüzdelik dilim)."""
    if px is None or len(px) < 200 or not f:
        return None
    close = px["Close"] if "Close" in getattr(px, "columns", []) else px
    samples = []
    for yr, eps in zip(f["years"], f["eps"]):
        if not _ok(eps) or eps <= 0:
            continue
        try:
            sel = close[[pd.Timestamp(d).year == yr for d in close.index]]
        except Exception:
            continue
        for v in sel.to_numpy(float)[::5]:
            if v == v:
                samples.append(v / eps)
    if len(samples) < 20:
        return None
    a = np.array(samples, float)
    lo, med, hi = float(np.percentile(a, 10)), float(np.median(a)), float(np.percentile(a, 90))
    cur = pe_now if _ok(pe_now) else NAN
    pct = float((a < cur).mean() * 100) if _ok(cur) else NAN
    return {"low": round(lo, 1), "median": round(med, 1), "high": round(hi, 1),
            "current": round(float(cur), 1) if _ok(cur) else None,
            "pctile": round(pct, 0) if pct == pct else None, "n": len(samples),
            "years": [y for y, e in zip(f["years"], f["eps"]) if _ok(e) and e > 0]}


# ---------------------------------------------------------------- döngüsellik
def _drawdowns(close, min_pct=10.0):
    """Zirveden en az %min_pct düşen dönemler: [(başlangıç, dip, düşüş%, toparlanma barı)]"""
    v = np.asarray(close, float)
    out, peak, pi = [], v[0], 0
    i = 0
    while i < len(v):
        if v[i] > peak:
            peak, pi = v[i], i
        dd = (v[i] / peak - 1) * 100
        if dd <= -min_pct:
            j, trough, ti = i, v[i], i
            while j < len(v) and v[j] < peak:
                if v[j] < trough:
                    trough, ti = v[j], j
                j += 1
            out.append({"start": pi, "trough": ti, "end": min(j, len(v) - 1),
                        "depth": round((trough / peak - 1) * 100, 1),
                        "bars": int(min(j, len(v) - 1) - pi),
                        "recovered": bool(j < len(v))})
            peak, pi, i = v[min(j, len(v) - 1)], min(j, len(v) - 1), min(j, len(v) - 1) + 1
            continue
        i += 1
    return out


def cyclicality(px, bench=None, f=None, days=756):
    """Hissenin döngüselliği: beta, düşüşte davranış, büyüme oynaklığı, dip-tepe kayıpları."""
    if px is None or len(px) < 120:
        return None
    close = px["Close"].tail(days)
    r = close.pct_change().dropna()
    out = {"n": len(r), "ann_vol": round(float(r.std() * np.sqrt(252) * 100), 1)}
    if bench is not None and len(bench) > 120:
        b = bench["Close"] if "Close" in getattr(bench, "columns", []) else bench
        br = b.pct_change().dropna()
        j = r.index.intersection(br.index)
        if len(j) > 100:
            x, y = br.loc[j].to_numpy(float), r.loc[j].to_numpy(float)
            var = float(np.var(x))
            out["beta"] = round(float(np.cov(y, x)[0, 1] / var), 2) if var > 0 else None
            dn = x < 0
            up = x > 0
            if dn.sum() > 10 and float(x[dn].mean()) != 0:
                out["down_capture"] = round(float(y[dn].mean() / x[dn].mean()) * 100, 0)
            if up.sum() > 10 and float(x[up].mean()) != 0:
                out["up_capture"] = round(float(y[up].mean() / x[up].mean()) * 100, 0)
            out["corr"] = round(float(np.corrcoef(y, x)[0, 1]), 2)
    dds = _drawdowns(close.to_numpy(float), 15.0)
    out["drawdowns"] = dds[-4:]
    out["max_dd"] = round(min([d["depth"] for d in dds], default=0.0), 1)
    if f:
        gv = [g for g in yoy(f["revenue"]) if g == g]
        ev = [g for g in yoy(f["eps"]) if g == g]
        out["rev_vol"] = round(float(np.std(gv)), 1) if len(gv) >= 2 else None
        out["eps_vol"] = round(float(np.std(ev)), 1) if len(ev) >= 2 else None
        out["rev_down_years"] = sum(1 for g in gv if g < 0)
    b, dc = out.get("beta"), out.get("down_capture")
    ev = out.get("eps_vol")
    pts = 0
    pts += 2 if (b is not None and b >= 1.3) else 1 if (b is not None and b >= 1.0) else 0
    pts += 2 if (dc is not None and dc >= 120) else 1 if (dc is not None and dc >= 95) else 0
    pts += 2 if (ev is not None and ev >= 45) else 1 if (ev is not None and ev >= 22) else 0
    pts += 1 if out.get("rev_down_years", 0) >= 1 else 0
    out["score"] = pts
    out["label"] = "Highly cyclical" if pts >= 5 else "Cyclical" if pts >= 3 else \
        "Mixed" if pts >= 2 else "Defensive"
    return out


def seasonality(px, years=10):
    """Takvim ayına göre ortalama getiri (%) ve pozitif ay oranı."""
    if px is None or len(px) < 300:
        return None
    close = px["Close"].tail(int(years * 252))
    try:
        m = close.resample("ME").last()
    except ValueError:
        m = close.resample("M").last()
    r = (m.pct_change() * 100).dropna()
    if len(r) < 24:
        return None
    out = []
    for mon in range(1, 13):
        sel = r[[pd.Timestamp(d).month == mon for d in r.index]]
        a = sel.to_numpy(float)
        out.append({"month": mon, "avg": round(float(a.mean()), 2) if len(a) else None,
                    "win": round(float((a > 0).mean() * 100), 0) if len(a) else None, "n": int(len(a))})
    return {"months": out, "n_years": int(len(r) / 12)}


# ---------------------------------------------------------------- değer notu
VALUE_GROUPS = [("peer", "Multiples vs peers", 25), ("own", "Versus own history", 15),
                ("growth", "Growth", 20), ("quality", "Balance sheet & quality", 20),
                ("cash", "Cash generation", 20)]


def _score_band(v, bands, default=50.0):
    """bands: [(eşik, puan)] — v eşikten küçük/eşitse o puan."""
    if not _ok(v):
        return default
    for th, s in bands:
        if v <= th:
            return s
    return bands[-1][1]


def value_grade(ratios, peers_med, band, fscore, zs, cons, cyc, analyst=None, detail=None):
    """Değerleme notu (A–Z): çarpanlar, büyüme, bilanço kalitesi ve nakit üretimi."""
    d = detail or {}
    g, why = {}, {}
    # 1) rakiplere göre
    w, prem_txt = [], []
    for key, label in (("pe", "P/E"), ("fwd_pe", "Fwd P/E"), ("ev_ebitda", "EV/EBITDA")):
        mine = d.get(key) if key in ("pe", "fwd_pe") else ratios.get("ev_ebitda")
        med = (peers_med or {}).get(key)
        if _ok(mine) and _ok(med) and med > 0 and mine > 0:
            prem = (mine / med - 1) * 100
            w.append(_score_band(prem, [(-30, 95), (-15, 85), (0, 72), (15, 55), (35, 35), (60, 20), (1e9, 8)]))
            prem_txt.append("%s %s (%s vs %s)" % (
                label, ("%s%% premium" % fmt_num(prem, 0)) if prem >= 0 else ("%s%% discount" % fmt_num(-prem, 0)),
                fmt_num(mine, 1), fmt_num(med, 1)))
    g["peer"] = float(np.mean(w)) if w else 50.0
    why["peer"] = prem_txt or ["Peer multiples could not be calculated"]
    # 2) kendi geçmişi
    if band and band.get("pctile") is not None:
        p = band["pctile"]
        g["own"] = _score_band(p, [(10, 95), (25, 85), (45, 70), (60, 55), (75, 38), (90, 20), (1e9, 8)])
        why["own"] = ["At the %sth percentile of its recent P/E distribution (median %s)" %
                      (fmt_num(p, 0), fmt_num(band["median"], 1))]
    else:
        g["own"], why["own"] = 50.0, ["Historical P/E band could not be calculated"]
    # 3) büyüme
    gr = []
    for v, lbl in ((ratios.get("rev_cagr"), "Revenue"), (ratios.get("eps_cagr"), "EPS")):
        if _ok(v):
            gr.append(_score_band(v, [(0, 12), (5, 35), (10, 58), (18, 78), (30, 92), (1e9, 96)]))
    fg = (analyst or {}).get("growth_next_y")
    if _ok(fg):
        gr.append(_score_band(fg, [(0, 15), (5, 38), (12, 62), (22, 82), (1e9, 93)]))
    g["growth"] = float(np.mean(gr)) if gr else 50.0
    why["growth"] = ["Revenue %s annual %s%%, EPS %s%%" %
                     ("compound", fmt_num(ratios.get("rev_cagr"), 1), fmt_num(ratios.get("eps_cagr"), 1))]
    # 4) kalite
    q = []
    if fscore:
        q.append(fscore["score"] / 9 * 100)
        why.setdefault("quality", []).append("Piotroski %d/9" % fscore["score"])
    if zs:
        q.append(_score_band(-zs["z"], [(-4, 95), (-2.99, 80), (-1.81, 50), (1e9, 20)]))
        why.setdefault("quality", []).append("Altman Z %s (%s)" % (fmt_num(zs["z"], 2), zs["zone"]))
    if cons:
        q.append(cons["pct"])
        why.setdefault("quality", []).append("Consistency %s/%s checks" % (cons["hit"], cons["of"]))
    de = ratios.get("debt_equity")
    if _ok(de):
        q.append(_score_band(de, [(0.3, 92), (0.8, 75), (1.5, 55), (2.5, 35), (1e9, 15)]))
    g["quality"] = float(np.mean(q)) if q else 50.0
    why.setdefault("quality", ["Not enough balance-sheet data"])
    # 5) nakit üretimi
    c = []
    fy = ratios.get("fcf_yield")
    if _ok(fy):
        c.append(_score_band(-fy, [(-8, 95), (-5, 85), (-3, 70), (-1.5, 52), (0, 32), (1e9, 12)]))
        why.setdefault("cash", []).append("Free cash flow yield %s%%" % fmt_num(fy, 1))
    ac = ratios.get("accrual")
    if _ok(ac):
        c.append(_score_band(-ac, [(-1.2, 92), (-0.9, 78), (-0.6, 58), (-0.3, 35), (1e9, 15)]))
        why.setdefault("cash", []).append("Cash flow/net income %s" % fmt_num(ac, 2))
    sc = ratios.get("share_chg")
    if _ok(sc):
        c.append(_score_band(sc, [(-5, 92), (-1, 78), (1, 60), (4, 38), (1e9, 18)]))
        why.setdefault("cash", []).append(
            "Share count changed %s%% across the statements (%s)"
            % (fmt_num(abs(sc), 1), "rose — dilution" if sc > 0 else "fell — buybacks"))
    g["cash"] = float(np.mean(c)) if c else 50.0
    why.setdefault("cash", ["No cash-flow data"])

    groups, total = [], 0.0
    for key, name, wgt in VALUE_GROUPS:
        s = float(min(100.0, max(0.0, g.get(key, 50.0))))
        total += s * wgt / 100.0
        groups.append({"key": key, "name": name, "weight": wgt, "score": round(s, 1),
                       "points": round(s * wgt / 100.0, 1), "reasons": why.get(key, [])})
    score = float(min(100.0, max(0.0, total)))
    li = min(25, max(0, int(round((100 - score) / 4.0))))
    letter = LETTERS[li]
    if li <= 3:
        action, tone = "Clearly discounted", "bull"
    elif li <= 8:
        action, tone = "Reasonably priced", "bull"
    elif li <= 14:
        action, tone = "Fairly valued", "flat"
    elif li <= 19:
        action, tone = "Premium", "bear"
    else:
        action, tone = "Clearly expensive", "bear"
    return {"score": round(score, 1), "letter": letter, "action": action, "tone": tone, "groups": groups}


# ---------------------------------------------------------------- grafik serileri
def pe_series(px, f, step=3):
    """Zaman içinde P/E: her günün fiyatı, o mali yılın EPS'ine bölünür."""
    if px is None or not f or len(px) < 60:
        return None
    eps = {y: e for y, e in zip(f["years"], f["eps"]) if _ok(e) and e > 0}
    if not eps:
        return None
    last_y = max(eps)
    close = px["Close"]
    xs, ys = [], []
    for d, v in zip(close.index[::step], close.to_numpy(float)[::step]):
        y = pd.Timestamp(d).year
        e = eps.get(y) or (eps[last_y] if y > last_y else None)
        if e and v == v:
            xs.append(d)
            ys.append(v / e)
    if len(xs) < 20:
        return None
    return pd.Series(ys, index=pd.DatetimeIndex(xs))


def underwater(close):
    """Zirveden uzaklık (%) — 0 zirvede, negatif düşüşte."""
    c = pd.Series(close).astype(float)
    return (c / c.cummax() - 1) * 100


def altman_contrib(zs):
    """Altman Z'nin bileşen katkıları (ağırlıklı)."""
    if not zs:
        return []
    w = {"Working capital/Assets": 1.2, "Retained earnings/Assets": 1.4, "EBIT/Assets": 3.3,
         "Market cap/Debt": 0.6, "Sales/Assets": 1.0}
    return [(k, round(w[k] * v, 3)) for k, v in zs["parts"].items() if _ok(v)]


# ======================================================================
# v3.6 — ŞİRKET TİPİNE GÖRE DEĞERLEME
#   Döngüsel & emtia · Defansif · Büyüme teknolojisi · Sermaye yoğun & donanım
#   Sınıflandırma: elle derlenmiş rakip grubu → Yahoo endüstrisi → finansal ölçütler.
#   İskonto oranı CAPM: risksiz faiz (ABD 10Y) + beta × hisse risk primi.
# ======================================================================
VTYPES = {"cyclical": "Cyclical & Commodity", "defensive": "Defensive",
          "growth": "Growth Tech", "capital": "Capital Intensive & Hardware"}
VTYPE_ORDER = ["cyclical", "defensive", "growth", "capital"]
ERP = 5.0          # hisse senedi risk primi (%)
G_TERM = 3.0       # uzun vade nominal büyüme (%)

_IND_TYPE = {
    # döngüsel & emtia
    "steel": "cyclical", "aluminum": "cyclical", "copper": "cyclical", "other industrial metals & mining": "cyclical",
    "gold": "cyclical", "silver": "cyclical", "other precious metals & mining": "cyclical", "coking coal": "cyclical",
    "thermal coal": "cyclical", "uranium": "cyclical", "chemicals": "cyclical", "specialty chemicals": "cyclical",
    "agricultural inputs": "cyclical", "airlines": "cyclical", "marine shipping": "cyclical", "trucking": "cyclical",
    "building materials": "cyclical", "residential construction": "cyclical", "paper & paper products": "cyclical",
    "lumber & wood production": "cyclical", "farm & heavy construction machinery": "cyclical",
    "recreational vehicles": "cyclical", "auto manufacturers": "cyclical", "auto parts": "cyclical",
    "auto & truck dealerships": "cyclical", "oil & gas e&p": "cyclical", "oil & gas integrated": "cyclical",
    "oil & gas refining & marketing": "cyclical", "oil & gas equipment & services": "cyclical",
    "oil & gas drilling": "cyclical", "banks - diversified": "cyclical", "banks - regional": "cyclical",
    "metal fabrication": "cyclical", "resorts & casinos": "cyclical", "lodging": "cyclical",
    "travel services": "cyclical", "leisure": "cyclical", "engineering & construction": "cyclical",
    # defansif
    "household & personal products": "defensive", "beverages - non-alcoholic": "defensive",
    "beverages - brewers": "defensive", "beverages - wineries & distilleries": "defensive",
    "packaged foods": "defensive", "confectioners": "defensive", "tobacco": "defensive",
    "discount stores": "defensive", "grocery stores": "defensive", "food distribution": "defensive",
    "drug manufacturers - general": "defensive", "drug manufacturers - specialty & generic": "defensive",
    "healthcare plans": "defensive", "medical distribution": "defensive",
    "medical instruments & supplies": "defensive", "pharmaceutical retailers": "defensive",
    "waste management": "defensive", "oil & gas midstream": "defensive",
    "financial data & stock exchanges": "defensive", "credit services": "defensive",
    # büyüme teknolojisi
    "software - application": "growth", "software - infrastructure": "growth",
    "internet content & information": "growth", "internet retail": "growth",
    "electronic gaming & multimedia": "growth", "biotechnology": "growth", "health information services": "growth",
    "information technology services": "growth",
    # sermaye yoğun & donanım
    "semiconductors": "capital", "semiconductor equipment & materials": "capital",
    "communication equipment": "capital", "computer hardware": "capital", "consumer electronics": "capital",
    "electronic components": "capital", "scientific & technical instruments": "capital",
    "telecom services": "capital", "aerospace & defense": "capital", "electrical equipment & parts": "capital",
    "specialty industrial machinery": "capital", "solar": "capital",
}
_IND_PREFIX = [("utilities", "defensive"), ("reit", "defensive"), ("insurance", "defensive"),
               ("beverages", "defensive"), ("drug manufacturers", "defensive"), ("oil & gas", "cyclical"),
               ("banks", "cyclical"), ("software", "growth"), ("semiconductor", "capital"), ("auto", "cyclical")]
_TARGET_FCF_M = {"software - application": 28.0, "software - infrastructure": 28.0,
                 "internet content & information": 25.0, "electronic gaming & multimedia": 22.0,
                 "biotechnology": 25.0, "health information services": 20.0, "internet retail": 12.0,
                 "credit services": 30.0, "information technology services": 15.0}


def _med(xs):
    v = [float(x) for x in xs if _ok(x)]
    return float(np.median(v)) if v else NAN


def _pctl(xs, q):
    v = [float(x) for x in xs if _ok(x)]
    return float(np.percentile(v, q)) if v else NAN


def _last_ok(xs):
    for x in reversed(list(xs or [])):
        if _ok(x):
            return float(x)
    return NAN


def _industry_type(industry, sector=""):
    ind = str(industry or "").strip().lower()
    if ind in _IND_TYPE:
        return _IND_TYPE[ind]
    for pre, t in _IND_PREFIX:
        if ind.startswith(pre):
            return t
    sec = str(sector or "").strip().lower()
    if sec in ("utilities", "consumer defensive"):
        return "defensive"
    if sec in ("energy", "basic materials"):
        return "cyclical"
    return None


def class_metrics(f, r, an, d, cyc):
    """Sınıflandırmada kullanılan ölçütler (yüzde)."""
    m = {}
    rev = f["revenue"] if f else []
    yo = (r or {}).get("rev_yoy") or []
    g_last = _last_ok(yo)
    g_fwd = (an or {}).get("rev_growth_0y", NAN)
    m["growth"] = g_fwd if _ok(g_fwd) else (g_last if _ok(g_last) else (r or {}).get("rev_cagr", NAN))
    m["growth_hist"] = (r or {}).get("rev_cagr", NAN)
    if f:
        cx = [abs(c) / v * 100 for c, v in zip(f["capex"], rev) if _ok(c) and _ok(v) and v > 0]
        rd = [x / v * 100 for x, v in zip(f["rnd"], rev) if _ok(x) and _ok(v) and v > 0]
        om = [x for x in f["op_m"] if _ok(x)]
        m["capex_int"] = float(np.mean(cx)) if cx else NAN
        m["rnd_int"] = float(np.mean(rd)) if rd else 0.0
        m["margin_swing"] = (max(om) - min(om)) if len(om) >= 2 else NAN
        m["eps_neg_years"] = sum(1 for e in f["eps"] if _ok(e) and e < 0)
        m["rev_down_years"] = sum(1 for x in yo if _ok(x) and x < -2)
    else:
        m.update(capex_int=NAN, rnd_int=0.0, margin_swing=NAN, eps_neg_years=0, rev_down_years=0)
    b = (d or {}).get("beta")
    m["beta"] = float(b) if _ok(b) else (cyc or {}).get("beta", NAN)
    dy = (d or {}).get("div_yield")
    m["div_yield"] = float(dy) if _ok(dy) else 0.0
    m["cyc_label"] = (cyc or {}).get("label", "")
    return m


def _metric_scores(m, sector=""):
    sec = str(sector or "").lower()
    s = {k: 0.0 for k in VTYPE_ORDER}
    g, cx, rd = m.get("growth"), m.get("capex_int"), m.get("rnd_int", 0.0)
    if _ok(g):
        s["growth"] += 3 if g >= 20 else 1 if g >= 12 else 0
    s["growth"] += 1 if rd >= 12 else 0
    if _ok(cx):
        s["capital"] += 2 if cx >= 10 else 1 if cx >= 6 else 0
    s["capital"] += 1 if sec in ("technology", "communication services", "industrials") else 0
    s["cyclical"] += 1 if m.get("rev_down_years", 0) >= 1 else 0
    s["cyclical"] += 1 if (_ok(m.get("margin_swing")) and m["margin_swing"] >= 12) else 0
    s["cyclical"] += 1 if m.get("eps_neg_years", 0) >= 1 else 0
    s["cyclical"] += 1 if (_ok(m.get("beta")) and m["beta"] >= 1.3) else 0
    s["cyclical"] += 2 if m.get("cyc_label") in ("Cyclical", "Highly cyclical") else 0
    s["defensive"] += 1 if (_ok(m.get("beta")) and m["beta"] < 0.85) else 0
    s["defensive"] += 1 if m.get("div_yield", 0) >= 1.5 else 0
    s["defensive"] += 2 if (m.get("rev_down_years", 0) == 0 and _ok(m.get("margin_swing"))
                            and m["margin_swing"] < 6) else 0
    s["defensive"] += 2 if sec in ("consumer defensive", "utilities", "healthcare") else 0
    return s


def classify_company(d, f, r, an, cyc, group=None):
    """Değerleme tipi + gerekçe. group: md.peer_group() sonucu (elle derlenmiş, 'vtype' içerebilir)."""
    d = d or {}
    m = class_metrics(f, r, an, d, cyc)
    scores = _metric_scores(m, d.get("sector"))
    reasons, src, t = [], None, None
    if group and group.get("vtype"):
        t, src = group["vtype"], 'peer group "%s"' % group["name"]
    if t is None:
        t = _industry_type(d.get("industry"), d.get("sector"))
        if t:
            src = 'industry "%s"' % (d.get("industry") or d.get("sector"))
    prior = t
    if t == "defensive" and _ok(m["growth"]) and m["growth"] >= 25 and m["rnd_int"] >= 10:
        t = "growth"
        reasons.append("Revenue growth %s%% with R&D at %s%% of revenue — valued as growth, not as a "
                       "defensive dividend payer" % (fmt_num(m["growth"], 0), fmt_num(m["rnd_int"], 0)))
    if t == "defensive" and src and not src.startswith("peer group") and _ok(m["beta"]) and m["beta"] >= 1.5:
        alt = max(VTYPE_ORDER, key=lambda k: (scores[k], -VTYPE_ORDER.index(k)))
        if alt != "defensive" and scores[alt] >= 2:
            reasons.append("Beta %s is too high for a defensive stock — classified by its financials as %s"
                           % (fmt_num(m["beta"], 2), VTYPES[alt].lower()))
            t = alt
    if t == "growth" and _ok(m["growth"]) and m["growth"] < 10 and m["rnd_int"] < 8:
        alt = "defensive" if (m["div_yield"] >= 1.0 and (not _ok(m["beta"]) or m["beta"] < 1.1)) else \
            "capital" if (_ok(m["capex_int"]) and m["capex_int"] >= 10) else \
            max(VTYPE_ORDER, key=lambda k: (scores[k] if k != "growth" else -1, -VTYPE_ORDER.index(k)))
        if alt not in ("defensive", "capital") and scores.get(alt, 0) < 2:
            alt = "growth"
        if alt != "growth":
            reasons.append("Growth below 10%% with little R&D — closer to %s" % VTYPES[alt].lower())
            t = alt
    if t == "cyclical" and src and src.startswith("industry") and m["rnd_int"] >= 10 and _ok(m["growth"]) \
            and m["growth"] >= 10:
        t = "growth"
        reasons.append("A technology platform in a cyclical industry (R&D %s%% of revenue, growth %s%%)"
                       % (fmt_num(m["rnd_int"], 0), fmt_num(m["growth"], 0)))
    if t is None:
        tie = ["growth", "capital", "cyclical", "defensive"]      # eşitlikte öncelik
        t = max(VTYPE_ORDER, key=lambda k: (scores[k], -tie.index(k)))
        src = "financial metrics"
    best = max(scores.values())
    if src and src.startswith("peer group"):
        conf = "high"
    elif prior and t == prior:
        conf = "high" if scores[t] >= best - 1 else "medium"
    else:
        conf = "medium" if scores[t] - sorted(scores.values())[-2] >= 2 else "low"
    facts = []
    if d.get("industry"):
        facts.append("Industry: %s" % d["industry"])
    if _ok(m["growth"]):
        facts.append("Revenue growth %s%%" % fmt_num(m["growth"], 1))
    if _ok(m["capex_int"]):
        facts.append("Capex %s%% of revenue" % fmt_num(m["capex_int"], 1))
    if m["rnd_int"]:
        facts.append("R&D %s%% of revenue" % fmt_num(m["rnd_int"], 1))
    if _ok(m["beta"]):
        facts.append("Beta %s" % fmt_num(m["beta"], 2))
    if m["div_yield"]:
        facts.append("Dividend yield %s%%" % fmt_num(m["div_yield"], 2))
    if _ok(m["margin_swing"]):
        facts.append("Operating margin range %s pts" % fmt_num(m["margin_swing"], 1))
    if m["rev_down_years"]:
        facts.append("Revenue fell in %d of the last years" % m["rev_down_years"])
    return {"type": t, "label": VTYPES[t], "source": src or "financial metrics", "confidence": conf,
            "reasons": reasons, "facts": facts, "scores": scores, "metrics": m}


# ---------------------------------------------------------------- iskonto oranı
def capm(beta, rf):
    b = float(min(2.2, max(0.6, beta))) if _ok(beta) else 1.0
    rf = float(rf) if _ok(rf) else 4.3
    return {"rf": rf, "beta": b, "erp": ERP, "ke": rf + b * ERP}


def wacc_calc(ke, mcap, debt, interest, rf=4.3, tax=21.0):
    E = float(mcap) if _ok(mcap) and mcap > 0 else NAN
    D = float(debt) if _ok(debt) and debt > 0 else 0.0
    kd = abs(float(interest)) / D * 100 if (_ok(interest) and D > 0) else rf + 1.5
    kd = float(min(rf + 6.0, max(rf + 0.5, kd)))
    we = E / (E + D) if _ok(E) else 0.8
    return {"kd": kd, "we": we, "wacc": we * ke + (1 - we) * kd * (1 - tax / 100.0), "tax": tax}


def _shares(f, d):
    s = _last_ok(f["shares"]) if f else NAN
    if not _ok(s) and _ok((d or {}).get("market_cap")) and _ok((d or {}).get("last")) and d["last"] > 0:
        s = d["market_cap"] / d["last"]
    return s


def _method(key, name, low, base, high, note, weight):
    if not (_ok(base) and base > 0):
        return None
    lo = low if _ok(low) and low > 0 else base
    hi = high if _ok(high) and high > 0 else base
    lo, hi = min(lo, base, hi), max(lo, base, hi)
    return {"key": key, "name": name, "low": round(float(lo), 2), "base": round(float(base), 2),
            "high": round(float(hi), 2), "note": note, "weight": weight}


def blend(methods, price=None, band=6.0):
    """Ağırlıklı ortalama. Taban değeri fiyatın 1/band – band katı dışında kalan yöntem bozuk girdiye
    işaret ettiği için harmana katılmaz (tabloda 'excluded' görünür)."""
    for x in methods:
        if x and _ok(price) and price > 0 and x.get("weight", 0) > 0:
            x["excluded"] = not (price / band <= x["base"] <= price * band)
    ms = [x for x in methods if x and x.get("weight", 0) > 0 and not x.get("excluded")]
    if not ms:
        return None
    w = sum(x["weight"] for x in ms)
    val = sum(x["base"] * x["weight"] for x in ms) / w
    lo = sum(x["low"] * x["weight"] for x in ms) / w
    hi = sum(x["high"] * x["weight"] for x in ms) / w
    out = {"value": round(val, 2), "low": round(lo, 2), "high": round(hi, 2),
           "weights": {x["name"]: round(x["weight"] / w * 100) for x in ms}}
    if _ok(price) and price > 0:
        out["upside"] = round((val / price - 1) * 100, 1)
    return out


def _year_end_price(px, date):
    """Verilen tarihteki (ya da öncesindeki son) kapanış."""
    if px is None or not len(px):
        return NAN
    c = px["Close"] if "Close" in getattr(px, "columns", []) else px
    idx = pd.DatetimeIndex(c.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    dt = pd.Timestamp(date)
    if dt.tzinfo is not None:
        dt = dt.tz_localize(None)
    v = c.to_numpy(float)[idx <= dt]
    return float(v[-1]) if len(v) and idx[0] <= dt else NAN


# ---------------------------------------------------------------- 1) döngüsel & emtia
def normalized_earnings(f, an, shares, ke):
    """Döngü ortası kâr: elde olan yılların medyan net marjı × trend ciro × döngü ortası P/E.
    Trend ciro, ciro serisine (geçmiş + analist tahmini) oturtulan log-doğrusal eğrinin bu mali yıldaki
    değeridir — döngünün tepesini ve dibini düzler, yapısal büyümeyi korur."""
    if not f or not _ok(shares) or shares <= 0:
        return None
    pts = [(i, x) for i, x in enumerate(f["revenue"]) if _ok(x) and x > 0]
    mar = [x for x in f["net_m"] if _ok(x)]
    est = []
    for k, (e, rv) in enumerate(zip((an or {}).get("fy") or [], (an or {}).get("rev_fy") or [])):
        if _ok(e.get("avg")) and _ok(rv.get("avg")) and rv["avg"] > 0:
            mm = e["avg"] * shares / rv["avg"] * 100
            if -60 <= mm <= 80:
                mar.append(mm)
                est.append(e["label"])
            pts.append((f["n"] + k, rv["avg"]))
    if len(mar) < 3 or len(pts) < 2:
        return None
    xs = np.array([p_[0] for p_ in pts], float)
    ys = np.log(np.array([p_[1] for p_ in pts], float))
    b1, b0 = np.polyfit(xs, ys, 1)
    t_now = f["n"] if (an or {}).get("rev_fy") else f["n"] - 1
    rev_tr = float(np.exp(b0 + b1 * t_now))
    pe_mid = float(min(20.0, max(8.0, 100.0 / max(1.0, ke - G_TERM))))
    eps_of = lambda mm: mm / 100.0 * rev_tr / shares   # noqa: E731
    base = eps_of(_med(mar)) * pe_mid
    low = eps_of(_pctl(mar, 25)) * pe_mid * 0.85
    high = eps_of(_pctl(mar, 75)) * pe_mid * 1.15
    note = ("Median net margin %s%% over %d years%s × trend revenue %s (log-linear fit, %s%%/yr) → mid-cycle "
            "EPS %s × %sx" % (fmt_num(_med(mar), 1), len(mar), (" (incl. %s estimates)" % ", ".join(est)) if est
                               else "", _bn(rev_tr), fmt_num((np.exp(b1) - 1) * 100, 1),
                               fmt_num(eps_of(_med(mar)), 2), fmt_num(pe_mid, 1)))
    return _method("norm", "Mid-cycle earnings", low, base, high, note, 0.35)


def pb_roe(f, ke, price=None, px=None):
    """Döngü ortası özkaynak kârlılığına göre hak edilen P/B × defter değeri; geçmiş P/B konumu."""
    if not f:
        return None, None
    eq, sh = _last_ok(f["equity"]), _last_ok(f["shares"])
    if not (_ok(eq) and _ok(sh)) or eq <= 0 or sh <= 0:
        return None, None
    bvps = eq / sh
    roes = [x for x in f["roe"] if _ok(x)]
    if len(roes) < 2:
        return None, None
    jpb = lambda roe: float(min(8.0, max(0.3, (roe - G_TERM) / max(1.0, ke - G_TERM))))   # noqa: E731
    roe_mid = _med(roes)
    m = _method("pb", "P/B vs mid-cycle ROE", bvps * jpb(_pctl(roes, 25)), bvps * jpb(roe_mid),
                bvps * jpb(_pctl(roes, 75)),
                "Book value %s/share × justified P/B %sx (median ROE %s%%, cost of equity %s%%)" % (
                    fmt_num(bvps, 2), fmt_num(jpb(roe_mid), 2), fmt_num(roe_mid, 1), fmt_num(ke, 1)), 0.25)
    hist = []
    for dt, e, s_ in zip(f["dates"], f["equity"], f["shares"]):
        p = _year_end_price(px, dt)
        if _ok(p) and _ok(e) and _ok(s_) and e > 0 and s_ > 0:
            hist.append(p / (e / s_))
    pos = None
    if _ok(price) and price > 0:
        cur = price / bvps
        pos = {"current": round(cur, 2), "hist": [round(x, 2) for x in hist],
               "pctile": round(float(np.mean([x < cur for x in hist]) * 100), 0) if len(hist) >= 3 else None,
               "bvps": round(bvps, 2)}
    return m, pos


def zigzag(close, thr):
    """Fiyatın en az `thr` (oran) dönüş yaptığı onaylı tepe/dipler: [(tarih, fiyat, 'peak'|'trough')]."""
    v = close.to_numpy(float)
    idx = close.index
    piv, mode = [], None
    lo_i = hi_i = ext = 0
    for i in range(1, len(v)):
        if mode is None:
            if v[i] < v[lo_i]:
                lo_i = i
            if v[i] > v[hi_i]:
                hi_i = i
            if v[i] >= v[lo_i] * (1 + thr):
                piv.append((lo_i, "trough"))
                mode, ext = "up", i
            elif v[i] <= v[hi_i] * (1 - thr):
                piv.append((hi_i, "peak"))
                mode, ext = "down", i
        elif mode == "up":
            if v[i] > v[ext]:
                ext = i
            elif v[i] <= v[ext] * (1 - thr):
                piv.append((ext, "peak"))
                mode, ext = "down", i
        else:
            if v[i] < v[ext]:
                ext = i
            elif v[i] >= v[ext] * (1 + thr):
                piv.append((ext, "trough"))
                mode, ext = "up", i
    return [(idx[i], float(v[i]), k) for i, k in piv]


def _fy_end(an, fy):
    """Mali yıl sonu tarihi (yaklaşık): analistin FY0 sonu + yıl farkı."""
    end0 = (an or {}).get("fy0_end")
    fy0 = (an or {}).get("fy0")
    try:
        if end0 and fy0:
            return pd.Timestamp(end0) + pd.DateOffset(years=int(fy) - int(fy0))
    except Exception:
        pass
    return pd.Timestamp(year=int(fy), month=12, day=31)


def cycle_timing(px_long, f, an, today=None):
    """Döngünün neresindeyiz, sıradaki tepe/dip ne zaman olabilir.

    İki bağımsız tahmin birleştirilir:
      1) Fiyat döngüsü — uzun geçmişteki tepe/dip aralarının medyan süresi (zigzag).
      2) Kâr döngüsü — analist EPS büyüme patikası, marjın kendi aralığındaki yeri ve tahmin revizyonları.
    Fiyat genelde kâr dönüşünden 3–9 ay önce döner.
    """
    if px_long is None or len(px_long) < 400:
        return None
    c = px_long["Close"].astype(float)
    try:
        c.index = c.index.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    w = c.resample("W-FRI").last().dropna()
    if len(w) < 104:
        return None
    today = pd.Timestamp(today or w.index[-1])
    vol = float(w.pct_change().std() * np.sqrt(52))
    thr = float(min(0.45, max(0.25, 1.1 * vol)))
    piv = zigzag(w, thr)
    out = {"thr": round(thr * 100), "pivots": [(str(pd.Timestamp(t).date()), round(p, 2), k) for t, p, k in piv],
           "evidence": []}
    ups = [(piv[i + 1][0] - piv[i][0]).days for i in range(len(piv) - 1)
           if piv[i][2] == "trough" and piv[i + 1][2] == "peak"]
    downs = [(piv[i + 1][0] - piv[i][0]).days for i in range(len(piv) - 1)
             if piv[i][2] == "peak" and piv[i + 1][2] == "trough"]
    out["n_cycles"] = min(len(ups), len(downs))
    out["med_up_days"] = int(np.median(ups)) if ups else None
    out["med_down_days"] = int(np.median(downs)) if downs else None
    # şu anki bacak
    leg, last = None, None
    if piv:
        last = piv[-1]
        leg = "up" if last[2] == "trough" else "down"
        out["last_pivot"] = {"date": str(pd.Timestamp(last[0]).date()), "price": round(last[1], 2), "kind": last[2]}
        out["elapsed_days"] = int((today - pd.Timestamp(last[0])).days)
    out["leg"] = leg
    durs = ups if leg == "up" else downs
    win_px = None
    if last is not None and durs:
        med = float(np.median(durs))
        lo, hi = (float(np.percentile(durs, 25)), float(np.percentile(durs, 75))) if len(durs) >= 3 \
            else (med * 0.7, med * 1.3)
        if hi - lo < 90:
            half = max(45.0, 0.15 * med)
            lo, hi = med - half, med + half
        t0 = pd.Timestamp(last[0])
        a, b = t0 + pd.Timedelta(days=lo), t0 + pd.Timedelta(days=hi)
        if b < today:          # ortalamayı aşmış: önümüzdeki aylarda
            a, b = today, today + pd.Timedelta(days=max(90, (hi - lo) / 2))
        elif a < today:
            a = today
        win_px = (a, b)
        out["progress"] = round(out["elapsed_days"] / med, 2) if med else None
        out["evidence"].append(
            "Price cycle: %s leg since %s (%d weeks). Past %s legs lasted a median %d weeks (%d cycles found, "
            "swings of %d%%+)." % ("up" if leg == "up" else "down", out["last_pivot"]["date"],
                                   out["elapsed_days"] // 7, "up" if leg == "up" else "down", int(med // 7),
                                   len(durs), out["thr"]))
    # kâr döngüsü
    fys = (an or {}).get("fy") or []
    g0 = fys[0].get("growth") if fys else None
    g1 = fys[1].get("growth") if len(fys) > 1 else None
    fy0 = fys[0]["fy"] if fys else None
    e_turn = None
    if g0 is not None and fy0:
        if g0 > 0 and g1 is not None and g1 <= 0:
            e_turn = ("peak", fy0)
        elif g0 > 0 and g1 is not None and g1 < g0:
            e_turn = ("peak", fy0 + 1 if g1 < max(15.0, g0 / 2) else fy0 + 2)
        elif g0 > 0:
            e_turn = ("peak", fy0 + 2)
        elif g1 is not None and g1 > 0:
            e_turn = ("trough", fy0)
        else:
            e_turn = ("trough", fy0 + 1)
        out["evidence"].append("Analyst EPS growth: FY%s %s%s." % (
            fy0, ("+" if g0 >= 0 else "") + fmt_num(g0, 0) + "%",
            (", FY%s %s" % (fy0 + 1, ("+" if g1 >= 0 else "") + fmt_num(g1, 0) + "%")) if g1 is not None else ""))
    om = [x for x in (f or {}).get("op_m", []) if _ok(x)]
    mpos = None
    if len(om) >= 3:
        lo_m, hi_m = min(om), max(om)
        mpos = (om[-1] - lo_m) / (hi_m - lo_m) * 100 if hi_m > lo_m else 50.0
        out["margin_pos"] = round(mpos)
        out["evidence"].append("Operating margin %s%% is at %d%% of its %d-year range (%s%% – %s%%)." % (
            fmt_num(om[-1], 1), round(mpos), len(om), fmt_num(lo_m, 1), fmt_num(hi_m, 1)))
    rv = (an or {}).get("revisions") or {}
    r1 = rv.get("+1y", rv.get("0y"))
    if _ok(r1):
        out["revision_90d"] = round(r1, 1)
        out["evidence"].append("Next-year EPS estimate revised %s%s%% over 90 days." % (
            "+" if r1 >= 0 else "−", fmt_num(abs(r1), 1)))
    win_e = None
    if e_turn:
        end = _fy_end(an, e_turn[1])
        win_e = (end - pd.DateOffset(months=9), end - pd.DateOffset(months=3))
        if win_e[1] < today:
            win_e = (today, today + pd.DateOffset(months=6))
        elif win_e[0] < today:
            win_e = (today, win_e[1])
        out["earnings_turn"] = {"kind": e_turn[0], "fy": int(e_turn[1])}
    # aşama
    prog = out.get("progress")
    e_rising = g0 is not None and g0 > 0 and (g1 is None or g1 > 0)
    late = (mpos is not None and mpos >= 80) or (g0 is not None and g1 is not None and 0 < g1 < g0 / 2) \
        or (_ok(r1) and r1 < -5 and (g0 or 0) > 0) or (prog is not None and prog >= 0.85)
    if leg == "up" or (leg is None and (g0 or 0) > 0):
        phase = "Late upswing" if late else ("Early upswing" if (prog is not None and prog < 0.4 and
                                                                   (mpos is None or mpos < 50)) else "Mid upswing")
        nxt = "peak"
    elif e_rising and (prog is None or prog < 0.5):
        phase = "Early downswing — price leading earnings"
        nxt = "trough"
        out["evidence"].append("The price has turned down while analysts still expect earnings growth — "
                               "markets usually start pricing an earnings peak 6–12 months ahead.")
    else:
        phase = "Bottoming" if ((prog is not None and prog >= 0.6) or (g1 is not None and g1 > 0)) else "Downswing"
        nxt = "trough"
    out["phase"], out["next_turn"] = phase, nxt
    # pencereleri birleştir (fiyat penceresi kâr dönüşüyle aynı türdeyse)
    wins = [w_ for w_ in (win_px, win_e if (e_turn and e_turn[0] == nxt) else None) if w_]
    if wins:
        if len(wins) == 2:
            a, b = max(wins[0][0], wins[1][0]), min(wins[0][1], wins[1][1])
            out["agree"] = a <= b
        else:
            a, b = wins[0]
        if out.get("agree", True):     # örtüşmüyorsa tek tarih uydurmuyoruz — iki pencere ayrı gösterilir
            out["window"] = (str(pd.Timestamp(a).date()), str(pd.Timestamp(b).date()))
    out["window_price"] = tuple(str(pd.Timestamp(x).date()) for x in win_px) if win_px else None
    out["window_earnings"] = tuple(str(pd.Timestamp(x).date()) for x in win_e) if win_e else None
    n_sig = sum(1 for x in (win_px, win_e) if x) + (1 if mpos is not None else 0) + (1 if _ok(r1) else 0)
    out["confidence"] = "medium" if (n_sig >= 3 and out.get("agree", True) and out["n_cycles"] >= 2) else "low"
    return out


# ---------------------------------------------------------------- 2) defansif
def dividend_stats(divs, px, today=None):
    """Hisse başı temettü geçmişi: son 12 ay, yıllık büyüme, art arda artış, verim bandı."""
    if divs is None or len(divs) == 0:
        return None
    s = pd.Series(divs).astype(float)
    try:
        s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    except (TypeError, AttributeError):
        s.index = pd.DatetimeIndex(s.index)
    s = s[s > 0]
    if s.empty:
        return None
    today = pd.Timestamp(today or pd.Timestamp.today().normalize())
    d0 = float(s[s.index > today - pd.Timedelta(days=365)].sum())
    annual = s.groupby(s.index.year).sum()
    annual = annual[annual.index < today.year]
    cagr5 = NAN
    if len(annual) >= 3:
        a = annual.tail(6)
        k = len(a) - 1
        if a.iloc[0] > 0 and k > 0:
            cagr5 = ((a.iloc[-1] / a.iloc[0]) ** (1 / k) - 1) * 100
    raises = int(sum(1 for i in range(1, len(annual)) if annual.iloc[i] > annual.iloc[i - 1] * 1.001))
    out = {"d0": round(d0, 4), "cagr5": round(cagr5, 2) if _ok(cagr5) else NAN, "years": int(len(annual)),
           "raises": raises, "annual": {int(k): round(float(v), 4) for k, v in annual.tail(10).items()}}
    if px is not None and len(px) > 300:
        c = px["Close"].astype(float)
        try:
            c.index = c.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        w = c.resample("W-FRI").last().dropna()
        cum = s.cumsum()
        ttm = []
        for t, p in w.items():
            got = cum[cum.index <= t]
            old = cum[cum.index <= t - pd.Timedelta(days=365)]
            dd = (got.iloc[-1] if len(got) else 0.0) - (old.iloc[-1] if len(old) else 0.0)
            ttm.append(dd / p * 100 if p > 0 else NAN)
        ys = pd.Series(ttm, index=w.index)
        ys = ys[ys.index >= ys.index[0] + pd.Timedelta(days=365)]
        ys = ys[ys > 0]
        if len(ys) > 52:
            out["yield_series"] = ys
            out["y_now"] = round(float(ys.iloc[-1]), 2)
            out["y_med"] = round(float(ys.median()), 2)
            out["y_p25"] = round(float(ys.quantile(0.25)), 2)
            out["y_p75"] = round(float(ys.quantile(0.75)), 2)
    return out


def ddm_two_stage(d0, g1, ke, years=5, g2=G_TERM):
    if not (_ok(d0) and d0 > 0 and _ok(ke)):
        return NAN
    k = max(ke, g2 + 1.5) / 100.0
    g1_, g2_ = g1 / 100.0, g2 / 100.0
    pv, dv = 0.0, d0
    for t in range(1, years + 1):
        dv *= 1 + g1_
        pv += dv / (1 + k) ** t
    tv = dv * (1 + g2_) / (k - g2_)
    return pv + tv / (1 + k) ** years


def _trend(xs, n=2):
    """Son n yılın ortalaması − önceki n yılın ortalaması."""
    v = [x for x in xs if _ok(x)]
    if len(v) < 3:
        return NAN
    n = min(n, len(v) // 2) or 1
    return float(np.mean(v[-n:]) - np.mean(v[-2 * n:-n]))


def _row_check(name, value, state, note=""):
    return {"name": name, "value": value, "state": state, "note": note}


def defensive_models(f, r, an, d, divst, band, ke, wacc, price):
    ms, checks = [], []
    sh = _shares(f, d)
    eps_g = (an or {}).get("growth_0y", NAN)
    if not _ok(eps_g):
        eps_g = (r or {}).get("eps_cagr", NAN)
    if divst and _ok(divst.get("d0")) and divst["d0"] > 0:
        dg = divst.get("cagr5")
        parts = [x for x in (dg, eps_g) if _ok(x)]
        g1 = float(min(10.0, max(0.0, np.mean(parts)))) if parts else 4.0
        d0 = divst["d0"]
        ms.append(_method("ddm", "Dividend discount (2-stage)", ddm_two_stage(d0, g1, ke + 1.0),
                          ddm_two_stage(d0, g1, ke), ddm_two_stage(d0, g1, ke - 1.0),
                          "Dividend %s/share growing %s%%/yr for 5 years, then %s%%; cost of equity %s%% (±1 pt)"
                          % (fmt_num(d0, 2), fmt_num(g1, 1), fmt_num(G_TERM, 1), fmt_num(ke, 1)), 0.30))
        if divst.get("y_med"):
            ms.append(_method("yield", "Dividend yield vs own history", d0 / (divst["y_p75"] / 100),
                              d0 / (divst["y_med"] / 100), d0 / (divst["y_p25"] / 100),
                              "Price at which today's dividend would yield its historical median %s%% "
                              "(range %s%% – %s%%)" % (fmt_num(divst["y_med"], 2), fmt_num(divst["y_p25"], 2),
                                                       fmt_num(divst["y_p75"], 2)), 0.20))
    fe = NAN
    fys = (an or {}).get("fy") or []
    if fys and _ok(fys[0].get("avg")):
        fe = fys[0]["avg"]
    elif _ok((d or {}).get("eps")):
        fe = d["eps"]
    if band and _ok(fe) and fe > 0:
        ms.append(_method("pe_hist", "P/E vs own history", fe * band["low"], fe * band["median"], fe * band["high"],
                          "Forward EPS %s × historical P/E %sx (10th–90th pct %sx – %sx)" % (
                              fmt_num(fe, 2), fmt_num(band["median"], 1), fmt_num(band["low"], 1),
                              fmt_num(band["high"], 1)), 0.25))
    if f:
        fcf, nd = _last_ok(f["fcf"]), _last_ok(f["net_debt"])
        g = (r or {}).get("rev_cagr", NAN)
        g = float(min(8.0, max(0.0, g))) if _ok(g) else 3.0
        if _ok(fcf) and fcf > 0 and _ok(sh):
            v = [(dcf(fcf, sh, g, 10, w, G_TERM, nd if _ok(nd) else 0.0) or {}).get("value", NAN)
                 for w in (wacc + 1, wacc, wacc - 1)]
            ms.append(_method("dcf", "Free-cash-flow DCF", v[0], v[1], v[2],
                              "FCF %s growing %s%% fading to %s%%, WACC %s%% (±1 pt)" % (
                                  _bn(fcf), fmt_num(g, 1), fmt_num(G_TERM, 1), fmt_num(wacc, 1)), 0.25))
    # kontroller: temettünün yanında büyüme, marj ve kâr
    if f:
        ry = (r or {}).get("rev_yoy") or []
        rt = _trend(ry)
        last_g = _last_ok(ry)
        checks.append(_row_check("Revenue growth", "%s%% last yr" % fmt_num(last_g, 1) if _ok(last_g) else "—",
                                 "good" if (_ok(rt) and rt > 0.5) else "bad" if (_ok(rt) and rt < -2) else "flat",
                                 ("accelerating (%s pts)" % fmt_num(rt, 1)) if (_ok(rt) and rt > 0.5) else
                                 ("slowing (%s pts)" % fmt_num(rt, 1)) if (_ok(rt) and rt < -0.5) else "steady"))
        ey = (r or {}).get("eps_yoy") or []
        et = _trend(ey)
        checks.append(_row_check("EPS growth", "%s%% last yr" % fmt_num(_last_ok(ey), 1) if _ok(_last_ok(ey)) else "—",
                                 "good" if (_ok(et) and et > 0.5) else "bad" if (_ok(et) and et < -3) else "flat",
                                 (("analysts expect %s%% this year" % fmt_num(eps_g, 1)) if _ok(eps_g) else "")))
        for key, lab in (("gross_m", "Gross margin"), ("op_m", "Operating margin"), ("net_m", "Net margin")):
            v = [x for x in f[key] if _ok(x)]
            if len(v) >= 2:
                ch = v[-1] - v[0]
                checks.append(_row_check(lab, "%s%%" % fmt_num(v[-1], 1),
                                         "good" if ch > 0.5 else "bad" if ch < -1.5 else "flat",
                                         "%s%s pts over %d yrs" % ("+" if ch >= 0 else "−", fmt_num(abs(ch), 1),
                                                                   len(v) - 1)))
        ni = [x for x in f["net_income"] if _ok(x)]
        if len(ni) >= 3:
            up = sum(1 for i in range(1, len(ni)) if ni[i] >= ni[i - 1])
            checks.append(_row_check("Earnings consistency", "%d/%d yrs up" % (up, len(ni) - 1),
                                     "good" if up >= len(ni) - 2 else "bad" if up <= (len(ni) - 1) / 2 else "flat",
                                     "net income rose year over year"))
        dp, nil, fcfl = _last_ok(f["dividends_paid"]), _last_ok(f["net_income"]), _last_ok(f["fcf"])
        if _ok(dp) and dp != 0 and _ok(nil) and nil > 0:
            pr = abs(dp) / nil * 100
            checks.append(_row_check("Payout ratio", "%s%%" % fmt_num(pr, 0),
                                     "good" if pr <= 65 else "bad" if pr > 90 else "flat",
                                     "dividends ÷ net income"))
            if _ok(fcfl) and fcfl > 0:
                cv = fcfl / abs(dp)
                checks.append(_row_check("Dividend cover (FCF)", "%sx" % fmt_num(cv, 2),
                                         "good" if cv >= 1.3 else "bad" if cv < 1 else "flat",
                                         "free cash flow ÷ dividends"))
        nde = (r or {}).get("net_debt_ebitda", NAN)
        if _ok(nde):
            checks.append(_row_check("Net debt / EBITDA", "%sx" % fmt_num(nde, 2),
                                     "good" if nde < 2 else "bad" if nde > 3.5 else "flat", ""))
    if divst:
        if _ok(divst.get("cagr5")):
            checks.append(_row_check("Dividend growth", "%s%%/yr" % fmt_num(divst["cagr5"], 1),
                                     "good" if divst["cagr5"] >= 4 else "bad" if divst["cagr5"] < 0 else "flat",
                                     "raised in %d of %d years" % (divst["raises"], max(1, divst["years"] - 1))))
    return ms, checks


def _bn(x):
    if not _ok(x):
        return "—"
    a = abs(x)
    for dv, s_ in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if a >= dv:
            return ("−" if x < 0 else "") + fmt_num(a / dv, 1) + s_
    return fmt_num(x, 0)


# ---------------------------------------------------------------- 3) büyüme teknolojisi
def target_margin_dcf(rev0, g0, m0, m_t, wacc, shares, net_debt=0.0, years=10, g_term=G_TERM, m_year=7, dil=0.0):
    """Ciro azalan hızla büyür, serbest nakit akışı marjı hedef marja yaklaşır, WACC ile iskonto edilir."""
    if not (_ok(rev0) and rev0 > 0 and _ok(shares) and shares > 0 and _ok(wacc)):
        return None
    w = max(wacc, g_term + 2.0) / 100.0
    g0 = float(min(100.0, max(-20.0, g0 if _ok(g0) else 10.0)))
    m0 = float(min(60.0, max(-80.0, m0 if _ok(m0) else 0.0)))
    rev, pv, rows, fcf = float(rev0), 0.0, [], 0.0
    for k in range(1, years + 1):
        gk = g0 + (g_term - g0) * (k - 1) / max(1, years - 1)
        rev *= 1 + gk / 100.0
        mk = m0 + (m_t - m0) * min(1.0, k / float(m_year))
        fcf = rev * mk / 100.0
        pv += fcf / (1 + w) ** k
        rows.append({"k": k, "rev": rev, "growth": gk, "margin": mk, "fcf": fcf})
    tv = fcf * (1 + g_term / 100.0) / (w - g_term / 100.0) if fcf > 0 else 0.0
    pv += tv / (1 + w) ** years
    eq = pv - (net_debt if _ok(net_debt) else 0.0)
    sh = shares * (1 + max(0.0, dil) / 100.0) ** 5
    return {"value": eq / sh, "rows": rows, "tv_share": (tv / (1 + w) ** years) / pv * 100 if pv > 0 else NAN}


def reverse_target_dcf(price, rev0, m0, m_t, wacc, shares, net_debt=0.0, dil=0.0):
    if not (_ok(price) and price > 0):
        return None
    fn = lambda g: (target_margin_dcf(rev0, g, m0, m_t, wacc, shares, net_debt, dil=dil) or {}).get("value", NAN)  # noqa
    lo, hi = -15.0, 100.0
    vlo, vhi = fn(lo), fn(hi)
    if not (_ok(vlo) and _ok(vhi)):
        return None
    if price >= vhi:
        return {"growth": hi, "capped": "above"}
    if price <= vlo:
        return {"growth": lo, "capped": "below"}
    for _ in range(60):
        mid = (lo + hi) / 2
        if fn(mid) < price:
            lo = mid
        else:
            hi = mid
    return {"growth": round((lo + hi) / 2, 1), "capped": None}


def ev_sales_regression(sym, vals, peers, rev0, net_debt, shares):
    """Rakiplerde EV/Satış ~ ciro büyümesi doğrusu; bu şirketin büyümesine düşen çarpan."""
    pts = []
    for t in peers:
        v = (vals or {}).get(t) or {}
        if _ok(v.get("ev_sales")) and _ok(v.get("rev_growth")) and 0 < v["ev_sales"] < 80:
            pts.append((float(v["rev_growth"]), float(v["ev_sales"])))
    me = (vals or {}).get(sym) or {}
    g = me.get("rev_growth")
    if len(pts) < 3 or not _ok(g) or not (_ok(rev0) and rev0 > 0 and _ok(shares) and shares > 0):
        return None
    xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    if np.ptp(xs) < 1e-6:
        return None
    b, a = np.polyfit(xs, ys, 1)
    resid = float(np.std(ys - (a + b * xs)))
    evs = max(0.3, a + b * g)
    nd = net_debt if _ok(net_debt) else 0.0
    px = lambda m: (m * rev0 - nd) / shares   # noqa: E731
    return {"ev_sales": round(evs, 2), "slope": round(b, 3), "n": len(pts), "growth": round(g, 1),
            "method": _method("evs", "EV/Sales vs growth (peers)", px(max(0.2, evs - resid)), px(evs),
                              px(evs + resid),
                              "Peer line: EV/Sales = %s + %s × growth (%d peers) → %sx at %s%% growth" % (
                                  fmt_num(a, 2), fmt_num(b, 3), len(pts), fmt_num(evs, 2), fmt_num(g, 1)), 0.30)}


def growth_models(sym, f, r, an, d, vals, peers, wacc, price):
    ms, checks, extra = [], [], {}
    if not f:
        return ms, checks, extra
    sh = _shares(f, d)
    rev0, nd = _last_ok(f["revenue"]), _last_ok(f["net_debt"])
    m0 = _last_ok(f["fcf_m"])
    g0 = (an or {}).get("rev_growth_0y", NAN)
    if not _ok(g0):
        g0 = _last_ok((r or {}).get("rev_yoy") or [])
    if not _ok(g0):
        g0 = (r or {}).get("rev_cagr", NAN)
    ind = str((d or {}).get("industry") or "").lower()
    m_t = _TARGET_FCF_M.get(ind, 20.0)
    if _ok(m0) and m0 > m_t:
        m_t = float(min(40.0, m0))
    sc = (r or {}).get("share_chg", NAN)
    dil = float(min(4.0, max(0.0, sc / max(1, f["n"] - 1)))) if _ok(sc) else 0.0
    if _ok(rev0) and _ok(sh):
        base = target_margin_dcf(rev0, g0, m0, m_t, wacc, sh, nd, dil=dil)
        lo = target_margin_dcf(rev0, (g0 if _ok(g0) else 10) * 0.7, m0, m_t - 6, wacc, sh, nd, dil=dil)
        hi = target_margin_dcf(rev0, (g0 if _ok(g0) else 10) * 1.3, m0, m_t + 6, wacc, sh, nd, dil=dil)
        if base:
            extra["path"] = base["rows"]
            extra["target_margin"] = m_t
            extra["g0"] = g0
            ms.append(_method("tdcf", "Target-margin DCF", lo["value"] if lo else NAN, base["value"],
                              hi["value"] if hi else NAN,
                              "Revenue %s growing %s%% fading to %s%% over 10 yrs; FCF margin %s%% → %s%% by "
                              "year 7; WACC %s%%%s" % (_bn(rev0), fmt_num(g0, 1), fmt_num(G_TERM, 0),
                                                       fmt_num(m0, 1), fmt_num(m_t, 0), fmt_num(wacc, 1),
                                                       ("; dilution %s%%/yr" % fmt_num(dil, 1)) if dil else ""),
                              0.50))
            extra["reverse"] = reverse_target_dcf(price, rev0, m0, m_t, wacc, sh, nd, dil)
        reg = ev_sales_regression(sym, vals, peers, rev0, nd, sh)
        if reg and reg["method"]:
            ms.append(reg["method"])
            extra["evs"] = reg
    # kontroller
    gl = _last_ok((r or {}).get("rev_yoy") or [])
    r40 = (gl if _ok(gl) else 0) + (m0 if _ok(m0) else 0)
    if _ok(gl) and _ok(m0):
        checks.append(_row_check("Rule of 40", fmt_num(r40, 0), "good" if r40 >= 40 else "bad" if r40 < 25 else "flat",
                                 "revenue growth %s%% (last FY) + FCF margin %s%%" % (fmt_num(gl, 1), fmt_num(m0, 1))))
    rt = _trend((r or {}).get("rev_yoy") or [])
    if _ok(rt):
        checks.append(_row_check("Growth trend", "%s%s pts" % ("+" if rt >= 0 else "−", fmt_num(abs(rt), 1)),
                                 "good" if rt > 0 else "bad" if rt < -8 else "flat", "recent vs earlier revenue growth"))
    gm = [x for x in f["gross_m"] if _ok(x)]
    if gm:
        checks.append(_row_check("Gross margin", "%s%%" % fmt_num(gm[-1], 1),
                                 "good" if gm[-1] >= 60 else "bad" if gm[-1] < 35 else "flat",
                                 "high gross margin leaves room for scale"))
    rd = [x / v * 100 for x, v in zip(f["rnd"], f["revenue"]) if _ok(x) and _ok(v) and v > 0]
    if rd:
        checks.append(_row_check("R&D intensity", "%s%%" % fmt_num(rd[-1], 1), "flat", "of revenue"))
    sbc = [x / v * 100 for x, v in zip(f["sbc"], f["revenue"]) if _ok(x) and _ok(v) and v > 0]
    if sbc:
        checks.append(_row_check("Stock comp", "%s%%" % fmt_num(sbc[-1], 1),
                                 "good" if sbc[-1] < 8 else "bad" if sbc[-1] > 20 else "flat", "of revenue"))
    if dil:
        checks.append(_row_check("Share dilution", "%s%%/yr" % fmt_num(dil, 1), "bad" if dil > 2 else "flat", ""))
    cash = _last_ok(f["cash"])
    fcf = _last_ok(f["fcf"])
    if _ok(fcf) and fcf < 0 and _ok(cash):
        run = cash / -fcf
        checks.append(_row_check("Cash runway", "%s yrs" % fmt_num(run, 1), "good" if run >= 3 else "bad" if run < 1.5
                                 else "flat", "cash ÷ annual cash burn"))
    checks += recurring_checks(f)
    return ms, checks, extra


def recurring_checks(f):
    """Abonelik/tekrarlayan gelir göstergesi: ertelenmiş gelir (peşin tahsil edilen abonelik ve bakım)."""
    out = []
    if not f:
        return out
    dr = [((a if _ok(a) else 0.0) + (b if _ok(b) else 0.0)) if (_ok(a) or _ok(b)) else NAN
          for a, b in zip(f["deferred_rev"], f["deferred_rev_nc"])]
    ratio = [x / v * 100 for x, v in zip(dr, f["revenue"]) if _ok(x) and _ok(v) and v > 0]
    if ratio:
        g = cagr([x for x in dr if _ok(x)])
        rg = cagr(f["revenue"])
        note = "deferred revenue %s" % _bn(_last_ok(dr))
        if _ok(g):
            note += ", growing %s%%/yr%s" % (fmt_num(g, 1), (" vs revenue %s%%" % fmt_num(rg, 1)) if _ok(rg) else "")
        out.append(_row_check("Recurring revenue (proxy)", "%s%% of revenue" % fmt_num(ratio[-1], 1),
                              "good" if ratio[-1] >= 15 else "flat", note))
    return out


# ---------------------------------------------------------------- 4) sermaye yoğun & donanım
def roic_series(f, tax=21.0):
    out = []
    for oi, e, dbt, c in zip(f["op_income"], f["equity"], f["debt"], f["cash"]):
        ic = (e if _ok(e) else NAN) + (dbt if _ok(dbt) else 0.0) - (c if _ok(c) else 0.0)
        out.append(oi * (1 - tax / 100) / ic * 100 if (_ok(oi) and _ok(ic) and ic > 0) else NAN)
    return out


def eva_value(ic, roic, wacc, growth, years=10, keep=0.0):
    """Değer = yatırılmış sermaye + ekonomik kârın (ROIC − WACC) bugünkü değeri.
    keep: 10. yılda kalan fark payı (0 = tamamen erir)."""
    if not (_ok(ic) and ic > 0 and _ok(roic) and _ok(wacc)):
        return NAN
    w = wacc / 100.0
    spread0 = (roic - wacc) / 100.0
    g = max(-0.05, min(0.25, (growth if _ok(growth) else 3.0) / 100.0))
    cap, pv = float(ic), 0.0
    for t in range(1, years + 1):
        sp = spread0 * (1 - (1 - keep) * (t - 1) / max(1, years - 1))
        pv += sp * cap / (1 + w) ** t
        gt = g + (G_TERM / 100.0 - g) * (t - 1) / max(1, years - 1)
        cap *= 1 + gt
    if keep > 0:
        sp_end = spread0 * keep
        pv += sp_end * cap / max(1e-6, w - G_TERM / 100.0) / (1 + w) ** years
    return ic + pv


def hist_ev_ebitda(f, px):
    out = []
    for dt, s_, nd, eb in zip(f["dates"], f["shares"], f["net_debt"], f["ebitda"]):
        p = _year_end_price(px, dt)
        if _ok(p) and _ok(s_) and _ok(eb) and eb > 0:
            out.append((p * s_ + (nd if _ok(nd) else 0.0)) / eb)
    return out


def capital_models(f, r, d, pm, px, wacc, price, an=None):
    ms, checks, extra = [], [], {}
    if not f:
        return ms, checks, extra
    sh = _shares(f, d)
    nd = _last_ok(f["net_debt"])
    nd0 = nd if _ok(nd) else 0.0
    eb = _last_ok(f["ebitda"])
    # 1) FD/FAVÖK — rakip medyanı ve kendi geçmişi
    hist = hist_ev_ebitda(f, px)
    extra["hist_ev_ebitda"] = hist
    peer_m = (pm or {}).get("ev_ebitda", NAN)
    own_m = _med(hist) if len(hist) >= 2 else NAN
    cands = [x for x in (peer_m, own_m) if _ok(x) and 2 < x < 150]
    if _ok(eb) and eb > 0 and _ok(sh) and cands:
        mid = float(np.mean(cands))
        lo, hi = min(cands + [mid * 0.85]), max(cands + [mid * 1.15])
        ev2px = lambda m: (m * eb - nd0) / sh   # noqa: E731
        ms.append(_method("eveb", "EV/EBITDA (peers + own history)", ev2px(lo), ev2px(mid), ev2px(hi),
                          "EBITDA %s × %sx (peer median %s, own median %s)" % (
                              _bn(eb), fmt_num(mid, 1), (fmt_num(peer_m, 1) + "x") if _ok(peer_m) else "—",
                              (fmt_num(own_m, 1) + "x") if _ok(own_m) else "—"), 0.35))
    # 2) ROIC − WACC (ekonomik kâr)
    roics = roic_series(f)
    extra["roic"] = roics
    ro = _med(roics[-3:]) if any(_ok(x) for x in roics) else NAN
    eq, dbt, c = _last_ok(f["equity"]), _last_ok(f["debt"]), _last_ok(f["cash"])
    ic = (eq if _ok(eq) else NAN) + (dbt if _ok(dbt) else 0.0) - (c if _ok(c) else 0.0)
    g = (an or {}).get("rev_growth_0y", NAN)
    if not _ok(g):
        g = (r or {}).get("rev_cagr", NAN)
    g = float(min(40.0, max(-10.0, g))) if _ok(g) else NAN
    if _ok(ic) and ic > 0 and _ok(ro) and _ok(sh):
        to_px = lambda v: (v - nd0) / sh if _ok(v) else NAN   # noqa: E731
        ms.append(_method("eva", "ROIC vs WACC (economic profit)",
                          to_px(eva_value(ic, ro, wacc, g)), to_px(eva_value(ic, ro, wacc, g, keep=0.25)),
                          to_px(eva_value(ic, ro, wacc, g, keep=0.5)),
                          "Invested capital %s growing %s%%, ROIC %s%% vs WACC %s%%; a quarter of the excess "
                          "return persists after 10 yrs (low: none, high: half)" % (
                              _bn(ic), fmt_num(g if _ok(g) else 3.0, 1), fmt_num(ro, 1), fmt_num(wacc, 1)), 0.25))
        extra["ic"], extra["roic_now"] = ic, ro
    # 3) Sahip kazancı DCF (bakım yatırımı ≈ amortisman)
    ocf, cx, da = _last_ok(f["ocf"]), _last_ok(f["capex"]), _last_ok(f["da"])
    if _ok(ocf) and _ok(cx):
        maint = min(abs(cx), da) if _ok(da) else abs(cx)
        oe = ocf - maint
        extra["owner"] = {"ocf": ocf, "maint": maint, "growth_capex": abs(cx) - maint, "oe": oe}
        gg = float(min(40.0, max(0.0, g))) if _ok(g) else 4.0
        if oe > 0 and _ok(sh):
            v = [(dcf(oe, sh, gx, 10, wx, G_TERM, nd0) or {}).get("value", NAN)
                 for gx, wx in ((gg * 0.6, wacc + 1), (gg, wacc), (gg * 1.3, wacc - 1))]
            ms.append(_method("owner", "Owner-earnings DCF", v[0], v[1], v[2],
                              "Operating cash flow %s − maintenance capex %s (≈ depreciation) = %s; growth %s%%, "
                              "WACC %s%%" % (_bn(ocf), _bn(maint), _bn(oe), fmt_num(gg, 1), fmt_num(wacc, 1)), 0.25))
    # kontroller — borç, kâr/borç büyümesi, süreklilik
    nde = [_d(n_, e_) for n_, e_ in zip(f["net_debt"], f["ebitda"])]
    nde_ok = [x for x in nde if _ok(x)]
    if nde_ok:
        tr_ = nde_ok[-1] - nde_ok[0] if len(nde_ok) >= 2 else 0
        checks.append(_row_check("Net debt / EBITDA", "%sx" % fmt_num(nde_ok[-1], 2),
                                 "good" if nde_ok[-1] < 1.5 else "bad" if nde_ok[-1] > 3 else "flat",
                                 ("%s%s over %d yrs" % ("+" if tr_ >= 0 else "−", fmt_num(abs(tr_), 2), len(nde_ok) - 1))
                                 if len(nde_ok) >= 2 else ""))
    de = (r or {}).get("debt_equity", NAN)
    if _ok(de):
        checks.append(_row_check("Debt / equity", "%sx" % fmt_num(de, 2),
                                 "good" if de < 0.6 else "bad" if de > 1.5 else "flat", ""))
    ic_ = (r or {}).get("interest_cover", NAN)
    if _ok(ic_):
        checks.append(_row_check("Interest coverage", "%sx" % fmt_num(ic_, 1),
                                 "good" if ic_ >= 8 else "bad" if ic_ < 3 else "flat", "EBIT ÷ interest"))
    gd, ge, gn = cagr(f["debt"]), cagr(f["ebitda"]), cagr(f["net_income"])
    if _ok(ge) or _ok(gn):
        prof = ge if _ok(ge) else gn
        if _ok(gd):
            st_ = "good" if prof >= gd else "bad" if prof < gd - 5 else "flat"
            checks.append(_row_check("Profit vs debt growth", "%s%% vs %s%%/yr" % (fmt_num(prof, 1), fmt_num(gd, 1)),
                                     st_, "EBITDA growth vs total-debt growth"))
        else:
            checks.append(_row_check("Profit vs debt growth", "%s%%/yr" % fmt_num(prof, 1), "flat",
                                     "EBITDA growth (debt history missing)"))
    fp = [x for x in f["fcf"] if _ok(x)]
    if fp:
        k = sum(1 for x in fp if x > 0)
        checks.append(_row_check("Free cash flow consistency", "%d/%d yrs positive" % (k, len(fp)),
                                 "good" if k == len(fp) else "bad" if k <= len(fp) / 2 else "flat", ""))
    em = [_d(e, v) * 100 for e, v in zip(f["ebitda"], f["revenue"])]
    em = [x for x in em if _ok(x)]
    if len(em) >= 3:
        sd = float(np.std(em))
        checks.append(_row_check("EBITDA margin stability", "%s%% ± %s" % (fmt_num(em[-1], 1), fmt_num(sd, 1)),
                                 "good" if sd < 4 else "bad" if sd > 10 else "flat", "std. dev. across years"))
    cxr = [abs(x) / v * 100 for x, v in zip(f["capex"], f["revenue"]) if _ok(x) and _ok(v) and v > 0]
    if cxr:
        checks.append(_row_check("Capex intensity", "%s%% of revenue" % fmt_num(cxr[-1], 1),
                                 "flat", "avg %s%%" % fmt_num(float(np.mean(cxr)), 1)))
    if _ok(ro):
        checks.append(_row_check("ROIC vs WACC", "%s%% vs %s%%" % (fmt_num(ro, 1), fmt_num(wacc, 1)),
                                 "good" if ro > wacc + 2 else "bad" if ro < wacc else "flat", "value created per dollar"))
    checks += recurring_checks(f)
    return ms, checks, extra


def cyclical_checks(f, r, timing, pbpos):
    out = []
    if timing:
        if timing.get("margin_pos") is not None:
            mp = timing["margin_pos"]
            out.append(_row_check("Margin vs own range", "%d%% of range" % mp,
                                  "bad" if mp >= 80 else "good" if mp <= 30 else "flat",
                                  "high = earnings near a cyclical peak"))
        if timing.get("revision_90d") is not None:
            rv = timing["revision_90d"]
            out.append(_row_check("Estimate revisions (90d)", "%s%s%%" % ("+" if rv >= 0 else "−", fmt_num(abs(rv), 1)),
                                  "good" if rv > 2 else "bad" if rv < -2 else "flat", "next-year EPS"))
    if pbpos and pbpos.get("pctile") is not None:
        out.append(_row_check("P/B vs own history", "%sx (%dth pct)" % (fmt_num(pbpos["current"], 2), pbpos["pctile"]),
                              "bad" if pbpos["pctile"] >= 80 else "good" if pbpos["pctile"] <= 25 else "flat",
                              "cyclicals tend to bottom near low P/B"))
    if f:
        nde = (r or {}).get("net_debt_ebitda", NAN)
        if _ok(nde):
            out.append(_row_check("Net debt / EBITDA", "%sx" % fmt_num(nde, 2),
                                  "good" if nde < 1.5 else "bad" if nde > 3 else "flat",
                                  "debt must survive the downturn"))
        neg = sum(1 for e in f["eps"] if _ok(e) and e < 0)
        out.append(_row_check("Loss years", "%d of %d" % (neg, f["n"]), "bad" if neg else "good", ""))
    return out


# ======================================================================
# v3.7 — yarım mum hacmi · fiyat boşlukları (gap) · grafik indikatörlerinin değerlendirmesi
# ======================================================================
def bar_progress(df, now=None):
    """Son mumun ne kadarı tamamlandı (0–1]. Ay başında aylık mumun hacmi 'ortalamanın 0,1 katı'
    görünmesin diye hacim bu orana bölünerek tahmin edilir. Bilinmiyorsa 1."""
    try:
        idx = pd.DatetimeIndex(df.index)
        if len(idx) < 3:
            return 1.0
        last = idx[-1]
        tz = last.tz
        now = pd.Timestamp.now(tz="America/New_York") if now is None else pd.Timestamp(now)
        if now.tzinfo is None:
            now = now.tz_localize("America/New_York")
        nl = now.tz_convert(tz).tz_localize(None) if tz is not None else now.tz_convert("America/New_York").tz_localize(None)
        lastn = last.tz_localize(None) if tz is not None else last
        step = float(pd.Series(idx[-12:]).diff().dt.total_seconds().median() or 0) / 86400
        today = nl.normalize()
        if step >= 25:                                   # aylık (etiket ay sonu)
            m0 = lastn.to_period("M").start_time
            m1 = lastn.to_period("M").end_time.normalize()
            if today > m1 or today < m0:
                return 1.0
            tot = max(1, len(pd.bdate_range(m0, m1)))
            done = len(pd.bdate_range(m0, today))
            return float(min(1.0, max(0.05, done / tot)))
        if step >= 5:                                    # haftalık (etiket cuma)
            w0 = (lastn - pd.Timedelta(days=lastn.weekday())).normalize()
            w1 = w0 + pd.Timedelta(days=4)
            if today > w1 or today < w0:
                return 1.0
            done = len(pd.bdate_range(w0, today))
            return float(min(1.0, max(0.05, done / 5)))
        if step >= 0.9:                                  # günlük: seans içindeyse
            ny = now.tz_convert("America/New_York").tz_localize(None)
            if lastn.normalize() != ny.normalize() or ny.weekday() > 4:
                return 1.0
            o = ny.normalize() + pd.Timedelta(hours=9, minutes=30)
            mins = (ny - o).total_seconds() / 60
            if mins <= 0 or mins >= 390:
                return 1.0
            return float(max(0.05, mins / 390))
    except Exception:
        return 1.0
    return 1.0


def vol_ratio(df, n=20):
    """(son mum hacmi / önceki n mumun ortalaması, tamamlanma oranı). Yarım mum orana göre büyütülür."""
    v = pd.to_numeric(df["Volume"], errors="coerce").astype(float)
    if len(v) < n + 1 or float(v.tail(n + 1).sum()) <= 0:
        return float("nan"), 1.0
    base = float(v.iloc[-n - 1:-1].mean())
    frac = bar_progress(df)
    last = float(v.iloc[-1]) / frac
    return (last / base if base > 0 else float("nan")), frac


def price_gaps(df, lookback=260, min_pct=0.25, max_n=8):
    """Doldurulmamış fiyat boşlukları. Yukarı boşluk (bugünkü dip > dünkü tepe) fiyatın altında kalırsa
    destek, aşağı boşluk direnç olur. Sonradan kısmen dolan boşluk daralır, tamamen dolan silinir.
    Döner: [{lo, hi, kind: sup|res, dir: up|down, i, date, pct (boyut %), dist (fiyata uzaklık %)}]"""
    d = df.tail(int(lookback) + 1)
    n = len(d)
    if n < 5:
        return []
    H, L = d["High"].to_numpy(float), d["Low"].to_numpy(float)
    px = float(d["Close"].iloc[-1])
    out = []
    for i in range(1, n):
        if L[i] > H[i - 1] * (1 + min_pct / 100):
            lo, hi, dirn = H[i - 1], L[i], "up"
        elif H[i] < L[i - 1] * (1 - min_pct / 100):
            lo, hi, dirn = H[i], L[i - 1], "down"
        else:
            continue
        # sonraki barlar boşluğu ne kadar doldurdu?
        for j in range(i + 1, n):
            if dirn == "up":
                if L[j] < hi:
                    hi = max(lo, L[j])
            else:
                if H[j] > lo:
                    lo = min(hi, H[j])
            if hi - lo <= max(1e-9, px * 0.0005):
                break
        if hi - lo <= max(1e-9, px * 0.0005) or hi <= lo:
            continue
        mid = (lo + hi) / 2
        out.append({"lo": float(lo), "hi": float(hi), "dir": dirn, "kind": "sup" if mid < px else "res",
                    "i": int(i + (len(df) - n)), "date": d.index[i],
                    "pct": float((hi - lo) / lo * 100), "dist": float((mid / px - 1) * 100)})
    out.sort(key=lambda g: abs(g["dist"]))
    return out[:int(max_n)]


TF_KIND_NAME = {"intraday": "intraday trading", "swing": "swing trading", "position": "position trading"}


def tf_kind(tf):
    t = str(tf or "1d")
    if t in ("1m", "5m", "15m", "30m", "1h"):
        return "intraday"
    if t in ("1wk", "1mo"):
        return "position"
    return "swing"


def _ib_row(name, value, sig, note, src="chart"):
    return {"name": name, "value": value, "sig": int(sig), "note": note, "src": src}


def _slope_word(s, n=5):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) <= n:
        return 0.0
    a, b = float(s.iloc[-1]), float(s.iloc[-1 - n])
    return (a / b - 1) * 100 if b else 0.0


def _ma_row(df, s, label, src):
    px = float(df["Close"].iloc[-1])
    v = _last(s)
    if not _ok(v):
        return None
    sl = _slope_word(s)
    d = (px / v - 1) * 100
    if px > v and sl >= 0:
        sig, note = 1, "price %s%% above, average rising" % _f(d, 1)
    elif px < v and sl <= 0:
        sig, note = -1, "price %s%% below, average falling" % _f(abs(d), 1)
    elif px > v:
        sig, note = 0, "price above (%s%%) but the average is still falling" % _f(d, 1)
    else:
        sig, note = 0, "price below (%s%%) but the average is still rising" % _f(abs(d), 1)
    return _ib_row(label, _f(v), sig, note, src)


def _rsi_row(df, n=14, ob=70, os_=30, src="chart"):
    r = rsi(df["Close"], n)
    v = _last(r)
    if not _ok(v):
        return None
    up = _slope_word(r, 3) > 0
    if v >= ob:
        sig, note = -1, "overbought (>%s) — pullback risk" % _f(ob, 0)
    elif v <= os_:
        sig, note = 1, "oversold (<%s) — bounce potential" % _f(os_, 0)
    elif v >= 50:
        sig, note = (1 if up else 0), "bullish half (>50), %s" % ("rising" if up else "flattening")
    else:
        sig, note = (-1 if not up else 0), "bearish half (<50), %s" % ("rising" if up else "falling")
    return _ib_row("RSI (%d)" % n, _f(v, 1), sig, note, src)


def _macd_row(df, f=12, s=26, sg=9, src="chart"):
    line, sig_, hist = macd(df["Close"], f, s, sg)
    mv, sv, hv = _last(line), _last(sig_), _last(hist)
    if not (_ok(mv) and _ok(sv)):
        return None
    hp = float(hist.dropna().iloc[-2]) if hist.dropna().shape[0] > 1 else hv
    grow = abs(hv) > abs(hp)
    if mv > sv:
        sig = 1
        note = "line above signal%s, %s zero" % (", histogram growing" if grow else ", histogram shrinking",
                                                 "above" if mv > 0 else "below")
    else:
        sig = -1
        note = "line below signal%s, %s zero" % (", histogram growing" if grow else ", histogram shrinking",
                                                 "above" if mv > 0 else "below")
    return _ib_row("MACD (%d, %d, %d)" % (f, s, sg), _f(mv), sig, note, src)


def _stoch_row(df, k=14, d=3, sm=3, ob=80, os_=20, src="chart"):
    kk, dd = stoch(df, k, d, sm)
    kv, dv = _last(kk), _last(dd)
    if not _ok(kv):
        return None
    if kv >= ob:
        sig, note = -1, "overbought (>%s)%s" % (_f(ob, 0), ", %K turning below %D" if _ok(dv) and kv < dv else "")
    elif kv <= os_:
        sig, note = 1, "oversold (<%s)%s" % (_f(os_, 0), ", %K turning above %D" if _ok(dv) and kv > dv else "")
    elif _ok(dv):
        sig, note = (1, "%K above %D") if kv > dv else (-1, "%K below %D")
    else:
        sig, note = 0, "mid-range"
    return _ib_row("Stochastic (%d, %d, %d)" % (k, d, sm), _f(kv, 1), sig, note, src)


def _boll_row(df, n=20, k=2.0, src="chart"):
    up, mid, lo = bollinger(df["Close"], n, k)
    u, m, l_ = _last(up), _last(mid), _last(lo)
    if not (_ok(u) and _ok(l_)) or u <= l_:
        return None
    px = float(df["Close"].iloc[-1])
    pb = (px - l_) / (u - l_)
    bw = ((up - lo) / mid.replace(0, np.nan)).dropna()
    squeeze = len(bw) > 60 and float(bw.iloc[-1]) <= float(bw.tail(120).quantile(0.12))
    mup = _slope_word(mid) >= 0
    if pb > 1:
        sig, note = -1, "closed above the upper band — stretched"
    elif pb < 0:
        sig, note = 1, "closed below the lower band — stretched to the downside"
    elif pb >= 0.5:
        sig, note = (1 if mup else 0), "upper half (%%B %s)%s" % (_f(pb * 100, 0), ", basis rising" if mup else
                                                                 ", basis falling")
    else:
        sig, note = (-1 if not mup else 0), "lower half (%%B %s)%s" % (_f(pb * 100, 0), ", basis falling"
                                                                      if not mup else ", basis rising")
    if squeeze:
        note += " · squeeze: bands at their narrowest — breakout setup"
    return _ib_row("Bollinger (%d, %s)" % (n, _f(k, 1)), "%B " + _f(pb * 100, 0), sig, note, src)


def _dir_row(name, line, dirn, df, src="chart", what="line"):
    v, dv = _last(line), _last(dirn)
    if not _ok(v) or not _ok(dv):
        return None
    px = float(df["Close"].iloc[-1])
    dser = pd.to_numeric(dirn, errors="coerce").dropna()
    flips = dser.ne(dser.shift()).cumsum()
    age = int((flips == flips.iloc[-1]).sum()) if len(flips) else 0
    if dv > 0:
        return _ib_row(name, _f(v), 1, "uptrend for %d bars · %s %s%% below price" % (age, what, _f((1 - v / px) * 100, 1)),
                       src)
    return _ib_row(name, _f(v), -1, "downtrend for %d bars · %s %s%% above price" % (age, what, _f((v / px - 1) * 100, 1)),
                   src)


def _adx_row(df, n=14, src="auto"):
    a, p, m = adx(df, n)
    av, pv, mv = _last(a), _last(p), _last(m)
    if not _ok(av):
        return None
    if av < 20:
        return _ib_row("ADX (%d)" % n, _f(av, 1), 0, "below 20 — no real trend, range conditions", src)
    side = pv > mv
    return _ib_row("ADX (%d)" % n, _f(av, 1), 1 if side else -1,
                   "%s trend (%s), +DI %s −DI" % ("strong" if av >= 25 else "developing",
                                                  "up" if side else "down", ">" if side else "<"), src)


def _vol_row(df, src="chart"):
    rv, frac = vol_ratio(df, 20)
    if not _ok(rv):
        return None
    up = float(df["Close"].iloc[-1]) >= float(df["Open"].iloc[-1])
    pace = " (pace, bar %s%% complete)" % _f(frac * 100, 0) if frac < 0.97 else ""
    if rv >= 1.5:
        sig = 1 if up else -1
        note = "heavy volume on a %s bar%s" % ("up" if up else "down", pace)
    elif rv >= 0.8:
        sig, note = 0, "around average%s" % pace
    else:
        sig, note = 0, "below average — weak confirmation%s" % pace
    return _ib_row("Volume vs 20-bar avg", _f(rv, 2) + "x", sig, note, src)


def _atr_row(df, n=14, src="chart"):
    a = atr(df, n)
    v = _last(a)
    if not _ok(v):
        return None
    px = float(df["Close"].iloc[-1])
    avg = float(a.tail(50).mean())
    trend = "rising" if v > avg * 1.1 else "falling" if v < avg * 0.9 else "steady"
    return _ib_row("ATR (%d)" % n, _f(v), 0, "%s%% of price, volatility %s — size stops with it" % (_f(v / px * 100, 1), trend),
                   src)


def _wt_row(df, n1=10, n2=21, ob=60, os_=-60, src="chart"):
    a, b = wavetrend(df, n1, n2)
    av, bv = _last(a), _last(b)
    if not _ok(av):
        return None
    if av >= ob:
        sig, note = -1, "overbought (>%s)" % _f(ob, 0)
    elif av <= os_:
        sig, note = 1, "oversold (<%s)" % _f(os_, 0)
    elif _ok(bv):
        sig, note = (1, "fast line above signal") if av > bv else (-1, "fast line below signal")
    else:
        sig, note = 0, "mid-range"
    return _ib_row("WaveTrend (%d, %d)" % (n1, n2), _f(av, 1), sig, note, src)


def _nw_row(df, h=8.0, mult=3.0, src="chart"):
    up, lo, mid = nadaraya_watson(df["Close"], h, mult)
    u, l_, m = _last(up), _last(lo), _last(mid)
    if not (_ok(u) and _ok(l_)):
        return None
    px = float(df["Close"].iloc[-1])
    if px > u:
        sig, note = -1, "above the upper envelope — stretched"
    elif px < l_:
        sig, note = 1, "below the lower envelope — stretched to the downside"
    else:
        rising = _slope_word(mid, 3) >= 0
        sig, note = 0, "inside the envelope, centre line %s" % ("rising" if rising else "falling")
    return _ib_row("Nadaraya-Watson", _f(m), sig, note, src)


def _zones_row(df, z, src="chart"):
    zones = ranked_sr_zones(df, z.get("lookback", 300), z.get("left", 8), z.get("right", 8),
                            z.get("merge", 0.6), z.get("max", 8))
    if not zones:
        return None
    px = float(df["Close"].iloc[-1])
    sup = [x for x in zones if (x["lo"] + x["hi"]) / 2 < px]
    res = [x for x in zones if (x["lo"] + x["hi"]) / 2 >= px]
    s = max(sup, key=lambda x: x["hi"]) if sup else None
    r = min(res, key=lambda x: x["lo"]) if res else None
    ds = (px / s["hi"] - 1) * 100 if s else None
    dr = (r["lo"] / px - 1) * 100 if r else None
    if s and (s["lo"] <= px <= s["hi"] * 1.015):
        return _ib_row("Ranked S/R", _f(s["hi"]), 1, "sitting on support (%s%% strength)" % s["pct"], src)
    if r and (r["lo"] * 0.985 <= px <= r["hi"]):
        return _ib_row("Ranked S/R", _f(r["lo"]), -1, "pressing into resistance (%s%% strength)" % r["pct"], src)
    bits = []
    if s:
        bits.append("support %s (−%s%%)" % (_f(s["hi"]), _f(ds, 1)))
    if r:
        bits.append("resistance %s (+%s%%)" % (_f(r["lo"]), _f(dr, 1)))
    sig = 0
    if ds is not None and dr is not None:
        sig = 1 if dr > ds * 2 else -1 if ds > dr * 2 else 0
    return _ib_row("Ranked S/R", _f((s or r)["hi"] if s else r["lo"]), sig, " · ".join(bits), src)


def _div_row(df, dcfg, src="chart"):
    srcn = dcfg.get("src", "rsi")
    osc = {"rsi": lambda: rsi(df["Close"], 14), "macd": lambda: macd(df["Close"])[0],
           "wt": lambda: wavetrend(df)[0]}.get(srcn, lambda: rsi(df["Close"], 14))()
    dv = divergences(df, osc, dcfg.get("left", 5), dcfg.get("right", 5), hidden=dcfg.get("hidden", True))
    n = len(df)
    recent = [x for x in dv if n - 1 - x["i2"] <= 15]
    if not recent:
        return _ib_row("Divergence (%s)" % srcn.upper(), "—", 0, "no divergence in the last 15 bars", src)
    x = recent[0]
    name, side = DIV_KINDS.get(x["kind"], ("Divergence", "bull"))
    return _ib_row("Divergence (%s)" % srcn.upper(), "%d bars ago" % (n - 1 - x["i2"]), 1 if side == "bull" else -1,
                   name.lower(), src)


def _vwap_row(df, src="auto"):
    try:
        idx = pd.DatetimeIndex(df.index)
        day = idx.normalize()
        last_day = day[-1]
        d = df[day == last_day]
        tp = (d["High"] + d["Low"] + d["Close"]) / 3
        vv = d["Volume"].astype(float)
        if float(vv.sum()) <= 0:
            return None
        vw = float((tp * vv).sum() / vv.sum())
    except Exception:
        return None
    px = float(df["Close"].iloc[-1])
    d_ = (px / vw - 1) * 100
    return _ib_row("VWAP (session)", _f(vw), 1 if px > vw else -1,
                   "price %s%% %s session VWAP" % (_f(abs(d_), 1), "above" if px > vw else "below"), src)


# zaman dilimine göre otomatik set: ne değerlendiriliyorsa ona uygun göstergeler
AUTO_SETS = {
    "intraday": ["ema9", "ema21", "vwap", "rsi14", "stoch", "macd", "boll", "vol"],
    "swing": ["rsi14", "macd", "stoch", "boll", "adx", "sma20", "sma50", "sma200", "sup", "vol"],
    "position": ["sma10", "sma40", "rsi14", "macd", "adx", "boll", "vol"],
}


def indicator_board(df, cfg=None, tf="1d", defaults=None):
    """Grafikte açık olan her göstergeyi kendi ayarlarıyla değerlendirir. Kullanıcı varsayılanların
    dışında hiçbir şey eklemediyse zaman dilimine uygun bir set (AUTO_SETS) de eklenir.
    Döner: {rows, buy, sell, neutral, score, label, auto (bool), kind}"""
    cfg = cfg or {}
    defaults = defaults or {}
    rows, have = [], set()

    def add(r, key):
        if r is not None and key not in have:
            rows.append(r)
            have.add(key)

    on = lambda k: bool((cfg.get(k) or {}).get("on"))  # noqa: E731
    if on("sma"):
        for p in (cfg["sma"].get("ps") or []):
            add(_ma_row(df, sma(df["Close"], int(p)), "SMA %d" % int(p), "chart"), "sma%d" % int(p))
    if on("boll"):
        b = cfg["boll"]
        add(_boll_row(df, b.get("n", 20), b.get("k", 2.0)), "boll")
    if on("sup"):
        line, dirn = supertrend(df, cfg["sup"].get("n", 10), cfg["sup"].get("mult", 3.0))
        add(_dir_row("Supertrend (%d, %s)" % (cfg["sup"].get("n", 10), _f(cfg["sup"].get("mult", 3.0), 1)),
                     line, dirn, df), "sup")
    if on("vidya"):
        v = cfg["vidya"]
        vv, _, _, vd, _ = vidya(df, v.get("len", 10), v.get("mom", 20), v.get("mult", 2.0))
        add(_dir_row("VIDYA (%d)" % v.get("len", 10), vv, vd, df, what="average"), "vidya")
    if on("vstop"):
        v = cfg["vstop"]
        line, dirn = volatility_stop(df, v.get("n", 20), v.get("mult", 2.0))
        add(_dir_row("Volatility Stop (%d, %s)" % (v.get("n", 20), _f(v.get("mult", 2.0), 1)), line, dirn, df,
                     what="stop"), "vstop")
    if on("nw"):
        add(_nw_row(df, cfg["nw"].get("h", 8.0), cfg["nw"].get("mult", 3.0)), "nw")
    if on("zones"):
        add(_zones_row(df, cfg["zones"]), "zones")
    if on("rsi"):
        r = cfg["rsi"]
        add(_rsi_row(df, int(r.get("len", 14)), r.get("ob", 70), r.get("os", 30)), "rsi%d" % int(r.get("len", 14)))
    if on("macd"):
        m = cfg["macd"]
        add(_macd_row(df, int(m.get("f", 12)), int(m.get("s", 26)), int(m.get("sig", 9))), "macd")
    if on("stoch"):
        s = cfg["stoch"]
        add(_stoch_row(df, int(s.get("k", 14)), int(s.get("d", 3)), int(s.get("smooth", 3)), s.get("ob", 80),
                       s.get("os", 20)), "stoch")
    if on("wt"):
        w = cfg["wt"]
        add(_wt_row(df, int(w.get("n1", 10)), int(w.get("n2", 21)), w.get("ob", 60), w.get("os", -60)), "wt")
    if on("atr"):
        add(_atr_row(df, int(cfg["atr"].get("n", 14))), "atr")
    if on("div"):
        add(_div_row(df, cfg["div"]), "div")
    if on("vol"):
        add(_vol_row(df), "vol")
    # kullanıcı varsayılanların dışında bir şey açtı mı?
    added = [k for k, v in cfg.items() if isinstance(v, dict) and v.get("on") and
             not (defaults.get(k) or {}).get("on")]
    kind = tf_kind(tf)
    auto = not added
    if auto:
        for key in AUTO_SETS[kind]:
            if key in have:
                continue
            if key.startswith("sma"):
                p = int(key[3:])
                add(_ma_row(df, sma(df["Close"], p), "SMA %d" % p, "auto"), key)
            elif key.startswith("ema"):
                p = int(key[3:])
                add(_ma_row(df, ema(df["Close"], p), "EMA %d" % p, "auto"), key)
            elif key == "rsi14":
                add(_rsi_row(df, 14, src="auto"), key)
            elif key == "macd":
                add(_macd_row(df, src="auto"), key)
            elif key == "stoch":
                add(_stoch_row(df, src="auto"), key)
            elif key == "boll":
                add(_boll_row(df, src="auto"), key)
            elif key == "adx":
                add(_adx_row(df, src="auto"), key)
            elif key == "sup":
                line, dirn = supertrend(df, 10, 3.0)
                add(_dir_row("Supertrend (10, 3.0)", line, dirn, df, src="auto"), key)
            elif key == "vwap":
                add(_vwap_row(df), key)
            elif key == "vol":
                add(_vol_row(df, src="auto"), key)
    score = sum(r["sig"] for r in rows)
    buy = sum(1 for r in rows if r["sig"] > 0)
    sell = sum(1 for r in rows if r["sig"] < 0)
    n = max(1, len(rows))
    ratio = score / n
    label = ("Strong Buy" if ratio >= 0.5 else "Buy" if ratio >= 0.15 else "Strong Sell" if ratio <= -0.5 else
             "Sell" if ratio <= -0.15 else "Neutral")
    return {"rows": rows, "buy": buy, "sell": sell, "neutral": len(rows) - buy - sell, "score": score,
            "label": label, "auto": auto, "kind": kind, "added": added}


# ======================================================================
# v3.8 — Çeyrek çeyrek patika: raporlanan / analist / model (yıllık tahminden dağıtılan)
# ======================================================================
Q_SRC_NAME = {"reported": "Reported", "analyst": "Analyst estimate", "model": "Model estimate"}


def _q_ends(fy_end):
    fy_end = pd.Timestamp(fy_end).normalize()
    return [fy_end - pd.DateOffset(months=3 * (4 - q)) for q in (1, 2, 3, 4)]


def _spread(rem, m, last):
    """Kalan yıllık EPS'i m çeyreğe dağıt: son bilinen çeyrekten geometrik bir eğimle (toplam tam tutar)."""
    if m <= 0:
        return [], None
    if not (_ok(last) and last > 0 and _ok(rem) and rem > 0):
        return [rem / m] * m, None

    def tot(r):
        return sum(last * r ** j for j in range(1, m + 1))
    lo, hi = 0.05, 20.0
    if tot(lo) > rem or tot(hi) < rem:
        return [rem / m] * m, None
    for _ in range(60):
        mid = (lo + hi) / 2
        if tot(mid) < rem:
            lo = mid
        else:
            hi = mid
    r = (lo + hi) / 2
    return [last * r ** j for j in range(1, m + 1)], (r - 1) * 100


def quarter_path(path, q=None, px=None):
    """Değer patikasının çeyrek kırılımı. Her mali yılın 4 çeyreği:
    * reported — şirketin açıkladığı EPS (Yahoo earnings_history; yoksa GAAP),
    * analyst  — sıradaki iki çeyrek için analist ortalaması (en düşük / en yüksek = kötümser / iyimser),
    * model    — kalan çeyrekler: o yılın EPS'inden (analist ya da model) bilinen çeyrekler çıkarılır,
                 kalan son bilinen çeyrekten başlayan düzgün bir QoQ eğimiyle dağıtılır (toplam = yıllık EPS).
    Değer = TTM EPS (son 4 çeyrek) × o tarihteki çarpan; 4. çeyrekte yıllık değerle aynıdır."""
    if not path:
        return None
    q = q or {}
    ends_fy = list(path["ends"])
    fy0 = path["fy0"]
    fy_list = [fy0 - 1] + [fy0 + k for k in range(len(ends_fy))]
    fy_end = {fy0 - 1: ends_fy[0] - pd.DateOffset(years=1)}
    fy_end.update({fy0 + k: e for k, e in enumerate(ends_fy)})
    totals = {key: {fy0 - 1: path["eps_last"]} for key in SCEN_KEYS}
    for key in SCEN_KEYS:
        for k, v in enumerate(path["eps_series"][key]):
            totals[key][fy0 + k] = v
    actual = [r for r in (q.get("q") or []) if _ok(r.get("eps"))]
    est = q.get("est") or {}
    slots = []
    for fy in fy_list:
        for qi, qe in enumerate(_q_ends(fy_end[fy]), start=1):
            slots.append({"fy": fy, "q": qi, "label": f"FY{fy} Q{qi}", "end": qe})
    # raporlanan çeyrekleri eşleştir
    for s in slots:
        m = next((r for r in actual if abs((pd.Timestamp(r["end"]) - s["end"]).days) <= 25), None)
        if m:
            s["src"] = "reported"
            s["eps"] = {key: float(m["eps"]) for key in SCEN_KEYS}
            s["rev"] = m.get("rev") if _ok(m.get("rev")) else None
            s["est_then"] = m.get("est") if _ok(m.get("est")) else None
            s["surprise"] = m.get("surprise") if _ok(m.get("surprise")) else None
            s["gaap"] = bool(m.get("gaap"))
    # analist çeyrekleri: son raporlanandan sonraki iki çeyrek
    last_rep = max([i for i, s in enumerate(slots) if s.get("src") == "reported"], default=None)
    if last_rep is None:
        today = pd.Timestamp.now().normalize()
        last_rep = max([i for i, s in enumerate(slots) if s["end"] < today - pd.Timedelta(days=40)], default=-1)
    for off, key_ in ((1, "0q"), (2, "+1q")):
        i = last_rep + off
        e = est.get(key_)
        if e and 0 <= i < len(slots) and not slots[i].get("src"):
            slots[i]["src"] = "analyst"
            slots[i]["eps"] = {"bear": e["low"], "base": e["avg"], "bull": e["high"]}
            slots[i]["n"] = e.get("n")
            slots[i]["rev"] = e.get("rev")
    # model çeyrekleri: yıl yıl, kronolojik
    for fy in fy_list:
        idx = [i for i, s in enumerate(slots) if s["fy"] == fy]
        unk = [i for i in idx if not slots[i].get("src")]
        if not unk:
            continue
        for i in unk:
            slots[i]["src"] = "model"
            slots[i].setdefault("eps", {})
        for key in SCEN_KEYS:
            known = sum(slots[i]["eps"][key] for i in idx if i not in unk)
            rem = totals[key].get(fy, float("nan")) - known
            # YoY: bilinmeyen çeyrek = geçen yılın aynı çeyreği × (kalan / geçen yılın o çeyreklerinin toplamı)
            ly = [slots[i - 4]["eps"].get(key) if i >= 4 else None for i in unk]
            ok_ly = all(_ok(v) and v > 0 for v in ly)
            if not _ok(rem):
                vals_, g_ = [float("nan")] * len(unk), None
            elif ok_ly and rem > 0:
                g = rem / sum(ly)
                vals_, g_ = [v * g for v in ly], (g - 1) * 100
            else:
                prev = [slots[j]["eps"][key] for j in range(min(unk)) if key in slots[j].get("eps", {})]
                vals_, _r = _spread(rem, len(unk), prev[-1] if prev else None)
                g_ = None
            for i, v in zip(unk, vals_):
                slots[i]["eps"][key] = float(v)
                if key == "base":
                    slots[i]["scale"] = g_
    # çarpan (yıl sonları arasında doğrusal), TTM, QoQ, YoY, değer
    m_ser = path["mult_series"]

    def mult_at(t, key):
        xs = [ends_fy[0] - pd.DateOffset(years=1)] + ends_fy
        ys = [m_ser[key][0]] + list(m_ser[key])
        if t <= xs[0]:
            return ys[0]
        for a in range(1, len(xs)):
            if t <= xs[a]:
                f_ = (t - xs[a - 1]).days / max(1, (xs[a] - xs[a - 1]).days)
                return ys[a - 1] + (ys[a] - ys[a - 1]) * f_
        return ys[-1]
    close = None
    if px is not None and len(px):
        close = px["Close"].astype(float).copy()
        try:
            close.index = close.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
    today = pd.Timestamp.now().normalize()
    for i, s in enumerate(slots):
        e = s["eps"]["base"]
        p_ = slots[i - 1]["eps"]["base"] if i else None
        y_ = slots[i - 4]["eps"]["base"] if i >= 4 else None
        s["qoq"] = (e / p_ - 1) * 100 if (_ok(e) and _ok(p_) and p_ > 0) else None
        s["yoy"] = (e / y_ - 1) * 100 if (_ok(e) and _ok(y_) and y_ > 0) else None
        if i >= 3:
            s["ttm"] = {key: sum(slots[j]["eps"][key] for j in range(i - 3, i + 1)) for key in SCEN_KEYS}
            s["value"] = {key: max(0.0, s["ttm"][key] * mult_at(s["end"], key)) for key in SCEN_KEYS}
            s["mult"] = mult_at(s["end"], "base")
        else:
            s["ttm"], s["value"], s["mult"] = None, None, None
        s["past"] = s["end"] < today
        if close is not None and s["past"]:
            c_ = close[close.index <= s["end"]]
            s["price"] = float(c_.iloc[-1]) if len(c_) else None
    # yıllık değerle tutarlılık: 4. çeyrek = yıllık değer (yıllık tavan uygulandıysa)
    for s in slots:
        if s["q"] == 4 and s["fy"] >= fy0 and s.get("value"):
            row = next((r for r in path["rows"] if r["fy"] == s["fy"]), None)
            if row and s["src"] != "reported":
                s["value"] = dict(row["value"])
    # döngüselde zirve: hiçbir gelecek çeyrek, zirve yılının 4. çeyreğini geçmez
    if path.get("cyclical"):
        pk = next((s for s in slots if s["fy"] == path["peak_fy"] and s["q"] == 4), None)
        if pk and pk.get("value"):
            for s in slots:
                if s is pk or not s.get("value") or s["src"] == "reported":
                    continue
                for key in SCEN_KEYS:
                    if s["value"][key] >= pk["value"][key]:
                        s["value"][key] = pk["value"][key] * 0.99
    by_fy = {fy: [s for s in slots if s["fy"] == fy] for fy in fy_list}
    return {"slots": slots, "by_fy": by_fy, "fy_list": fy_list, "fy_end": fy_end,
            "has_reported": any(s["src"] == "reported" for s in slots),
            "est": est, "next_date": q.get("next_date"), "src": q.get("src", "none")}


# ======================================================================
# v3.9 — Mali yıl → çeyrek finansallar (SEC dönemlerinden ya da Yahoo çeyreklerinden)
# ======================================================================
Q_METRICS = ["revenue", "gross", "op_income", "net_income", "eps", "ocf", "capex"]


def _ts(x):
    t = pd.Timestamp(x)
    try:
        t = t.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return t.normalize()


def fiscal_quarters(fy_ends, sec=None, yq=None, qest=None, cur_fy_end=None):
    """Her mali yıl için 4 çeyrek. Kaynak sırası: SEC (3 aylık dönem; yoksa yıl başından birikimli farkı;
    Q4 = yıllık − ilk 9 ay), Yahoo (son ~5 çeyrek). İçinde bulunulan mali yılda raporlanmamış çeyrekler
    analist beklentisiyle (EPS, ciro) 'expected' olarak işaretlenir.
    Döner: {fy: {"start", "end", "status", "quarters": [...], "src"}}"""
    sec = (sec or {}).get("series") or {}
    yq = (yq or {}).get("series") or {}
    ends = sorted({_ts(e) for e in fy_ends if e is not None})
    if cur_fy_end is not None:
        ce = _ts(cur_fy_end)
        if not ends or ce > ends[-1] + pd.Timedelta(days=200):
            ends.append(ce)
    secp = {m: [(_ts(a), _ts(b), v) for (a, b), v in ser.items()] for m, ser in sec.items()}
    out = {}
    prev_end = None
    for fe in ends:
        fs = (prev_end + pd.Timedelta(days=1)) if prev_end is not None else (fe - pd.DateOffset(years=1) +
                                                                            pd.Timedelta(days=1))
        prev_end = fe
        qends = [fe - pd.DateOffset(months=3 * (4 - k)) for k in (1, 2, 3, 4)]
        qs = [{"q": k, "end": qends[k - 1], "src": None, "derived": set()} for k in (1, 2, 3, 4)]
        used_sec = used_yf = False
        for m in Q_METRICS:
            per = secp.get(m) or []
            direct, ytd, annual = {}, {}, None
            for a, b, v in per:
                d = (b - a).days
                if abs((b - fe).days) <= 12 and abs((a - fs).days) <= 12 and 340 <= d <= 380:
                    annual = v
                for k in (1, 2, 3, 4):
                    if abs((b - qends[k - 1]).days) <= 12:
                        if 75 <= d <= 105:
                            direct[k] = (v, b)
                        if k < 4 and abs((a - fs).days) <= 12 and d > 105:
                            ytd[k] = v
            vals = {}
            if m != "eps":
                cum = {0: 0.0}
                for k in (1, 2, 3):
                    if k in ytd:
                        cum[k] = ytd[k]
                    elif k in direct and (k - 1) in cum:
                        cum[k] = cum[k - 1] + direct[k][0]
                if annual is not None:
                    cum[4] = annual
                for k in (1, 2, 3, 4):
                    if k in direct and k < 4:
                        vals[k] = direct[k][0]
                    elif k in cum and (k - 1) in cum:
                        vals[k] = cum[k] - cum[k - 1]
                        if k == 4 or k not in direct:
                            qs[k - 1]["derived"].add(m)
                    elif k in direct:
                        vals[k] = direct[k][0]
            else:
                for k in (1, 2, 3):
                    if k in direct:
                        vals[k] = direct[k][0]
                if 4 in direct:
                    vals[4] = direct[4][0]
                elif annual is not None and all(k in vals for k in (1, 2, 3)):
                    vals[4] = annual - sum(vals[k] for k in (1, 2, 3))
                    qs[3]["derived"].add("eps")
            for k in (1, 2, 3, 4):
                if k in direct:
                    qs[k - 1]["end"] = direct[k][1]
            if vals:
                used_sec = True
            # Yahoo (3 aylık) — SEC'te olmayanlar için
            for k in (1, 2, 3, 4):
                if k in vals:
                    continue
                for e_, v in (yq.get(m) or {}).items():
                    if abs((_ts(e_) - qends[k - 1]).days) <= 20:
                        vals[k] = v
                        used_yf = True
                        break
            for k, v in vals.items():
                qs[k - 1][m] = float(abs(v) if m == "capex" else v)
        for q in qs:
            if any(m in q for m in Q_METRICS):
                q["src"] = "reported"
            r_ = q.get("revenue")
            if _ok(r_) and r_:
                for m, nm in (("gross", "gross_m"), ("op_income", "op_m"), ("net_income", "net_m")):
                    if _ok(q.get(m)):
                        q[nm] = q[m] / r_ * 100
            if _ok(q.get("ocf")):
                q["fcf"] = q["ocf"] - (q.get("capex") or 0.0)
            q["derived"] = sorted(q["derived"])
        status = "in progress" if fe > pd.Timestamp.now().normalize() else "reported"
        out[int(fe.year)] = {"start": fs, "end": fe, "status": status, "quarters": qs,
                             "src": "SEC 10-Q / 10-K" if used_sec else ("Yahoo Finance" if used_yf else None)}
    # içinde bulunulan yılda raporlanmamış çeyrekler: analist beklentisi
    est = qest or {}
    if out:
        cur = out[max(out)]
        if cur["status"] == "in progress":
            last = max([q["q"] for q in cur["quarters"] if q["src"] == "reported"], default=0)
            for off, key in ((1, "0q"), (2, "+1q")):
                k = last + off
                e = est.get(key)
                if e and k <= 4:
                    q = cur["quarters"][k - 1]
                    q["src"] = "expected"
                    q["eps"] = e.get("avg")
                    q["eps_range"] = (e.get("low"), e.get("high"))
                    q["n"] = e.get("n")
                    if e.get("rev"):
                        q["revenue"] = e["rev"]
            for q in cur["quarters"]:
                if q["src"] is None:
                    q["src"] = "no estimate"
    # QoQ / YoY
    flat = [(fy, q) for fy in sorted(out) for q in out[fy]["quarters"]]
    for i, (fy, q) in enumerate(flat):
        for m in ("revenue", "eps", "net_income"):
            v = q.get(m)
            pv = flat[i - 1][1].get(m) if i else None
            yv = flat[i - 4][1].get(m) if i >= 4 else None
            q[m + "_qoq"] = (v / pv - 1) * 100 if (_ok(v) and _ok(pv) and pv > 0) else None
            q[m + "_yoy"] = (v / yv - 1) * 100 if (_ok(v) and _ok(yv) and yv > 0) else None
    return out


# ======================================================================
# v3.9 — Sürücü modeli: ciro büyümesi (yıl yıl) → marj → faiz / net borç → hisse sayısı → EPS, capex → FCF
#        Değer: F/K merceği (EPS × çarpan) ve FD/FAVÖK merceği ((EBIT × çarpan − net borç) / hisse)
# ======================================================================
LENSES = ["Blend", "P/E", "EV/EBIT"]


def _med_d(xs, default):
    v = [float(x) for x in xs if _ok(x)]
    return float(np.median(v)) if v else default


def hist_rev_drop(revs):
    """Raporlanan yıllık cirolarda zirveden dibe en büyük düşüş (%); hiç düşüş yoksa 0."""
    worst, peak = 0.0, None
    for r in revs or []:
        if not (_ok(r) and r > 0):
            continue
        peak = r if peak is None else max(peak, r)
        worst = max(worst, (1 - r / peak) * 100)
    return float(worst)


def hist_cagr(revs):
    """Raporlanan yıllık ciroların bileşik büyümesi (%/yıl); en az 3 yıl gerekir."""
    v = [r for r in revs or [] if _ok(r) and r > 0]
    if len(v) < 3:
        return None
    return float(((v[-1] / v[0]) ** (1.0 / (len(v) - 1)) - 1) * 100)


def driver_hist(f, an, b_wacc=None, rf=4.3, basis=None):
    """Sürücü modelinin başlangıç değerleri — yalnızca şirketin raporladığı rakamlardan.
    basis (mock_data.get_latest_basis): en son 10-Q / 10-K'dan son 12 ay ve son bilanço; verilirse marj,
    capex, amortisman, hisse sayısı ve net borç buradan alınır (yıllık tablo yerine). 'basis' alanı her
    girdinin değerini, dönemini ve kaynağını listeler."""
    if not f:
        return None
    n = f["n"]
    last = lambda k: next((f[k][i] for i in range(n - 1, -1, -1) if _ok(f[k][i])), float("nan"))  # noqa: E731
    rev = last("revenue")
    sh = last("shares")
    if not (_ok(rev) and rev > 0 and _ok(sh) and sh > 0):
        return None
    caps = [abs(c) / r for c, r in zip(f["capex"][-3:], f["revenue"][-3:]) if _ok(c) and _ok(r) and r > 0]
    das = [d / r for d, r in zip(f["da"][-3:], f["revenue"][-3:]) if _ok(d) and _ok(r) and r > 0]
    tax = _med_d([t for t in f.get("tax_rate", []) if _ok(t) and 0 <= t <= 0.5], 0.18)
    pay = []
    for i in range(max(0, n - 3), n):
        fc = f["fcf"][i]
        ret = abs(f["buyback"][i] if _ok(f["buyback"][i]) else 0) + abs(
            f["dividends_paid"][i] if _ok(f["dividends_paid"][i]) else 0)
        if _ok(fc) and fc > 0:
            pay.append(min(1.5, ret / fc))
    shs = [s_ for s_ in f["shares"] if _ok(s_) and s_ > 0]
    chg = (shs[-1] / shs[-2] - 1) * 100 if len(shs) >= 2 else 0.0
    revs = [r for r in f["revenue"] if _ok(r) and r > 0]
    g_rev = (revs[-1] / revs[-2] - 1) * 100 if len(revs) >= 2 else 5.0
    nd = last("net_debt")
    kd = (b_wacc or {}).get("kd") if b_wacc else None
    yrs = [str(y) for y in (f.get("years") or [])]
    fy_tag = f'fiscal year {yrs[-1]}' if yrs else "last fiscal year"
    ann = "annual report (company filing via Yahoo Finance)"
    out = {"rev_last": float(rev), "shares0": float(sh), "net_debt0": float(nd) if _ok(nd) else 0.0,
           "op_m_hist": [m for m in f["op_m"] if _ok(m)], "op_m_last": last("op_m"),
           "capex_pct": float(min(60.0, _med_d(caps, 0.05) * 100)), "da_pct": float(min(40.0, _med_d(das, 0.04) * 100)),
           "tax": float(tax * 100), "payout": float(min(100.0, max(0.0, _med_d(pay, 0.5) * 100))),
           "share_chg": float(max(-6.0, min(6.0, chg))), "g_rev_last": float(max(-50.0, min(150.0, g_rev))),
           "kd": float(kd if _ok(kd) else rf + 1.5), "rf": float(rf), "eps_last": last("eps"),
           "rev_hist": revs, "hist_years": yrs[-len(revs):] if yrs else []}
    rows = {"rev": ("Revenue (last fiscal year)", out["rev_last"], "money", fy_tag, ann),
            "opm": ("Operating margin", out["op_m_last"], "pct", fy_tag, ann),
            "capex": ("Capex as % of revenue", out["capex_pct"], "pct", "median of the last 3 fiscal years", ann),
            "da": ("Depreciation as % of revenue", out["da_pct"], "pct", "median of the last 3 fiscal years", ann),
            "shares": ("Diluted shares", out["shares0"], "num", fy_tag, ann),
            "nd": ("Net debt (− = net cash)", out["net_debt0"], "money", fy_tag, ann),
            "tax": ("Tax rate", out["tax"], "pct", "median of the reported years", ann),
            "chg": ("Share count change per year", out["share_chg"], "pct", "last two fiscal years", ann),
            "payout": ("Share of free cash flow paid out", out["payout"], "pct", "last 3 fiscal years", ann)}
    it = (basis or {}).get("items") or {}
    use = lambda k: it[k] if (k in it and _ok(it[k].get("val"))) else None  # noqa: E731
    rt, ot = use("rev_ttm"), use("op_ttm")
    if rt and rt["val"] > 0:
        out["rev_ttm"] = float(rt["val"])
        rows["rev_ttm"] = ("Revenue (last 12 months)", rt["val"], "money", rt["as_of"], rt["source"])
        if ot:
            out["op_m_last"] = float(ot["val"] / rt["val"] * 100)
            rows["opm"] = ("Operating margin", out["op_m_last"], "pct", ot["as_of"], ot["source"])
        ct, dt = use("capex_ttm"), use("da_ttm")
        if ct:
            out["capex_pct"] = float(min(60.0, abs(ct["val"]) / rt["val"] * 100))
            rows["capex"] = ("Capex as % of revenue", out["capex_pct"], "pct", ct["as_of"], ct["source"])
        if dt and dt["val"] > 0:
            out["da_pct"] = float(min(40.0, dt["val"] / rt["val"] * 100))
            rows["da"] = ("Depreciation as % of revenue", out["da_pct"], "pct", dt["as_of"], dt["source"])
    ds = use("dil_shares")
    if ds and 0.6 * sh <= ds["val"] <= 1.6 * sh:          # birim hatasına karşı: yıllık rakama yakın olmalı
        out["shares0"] = float(ds["val"])
        rows["shares"] = ("Diluted shares", out["shares0"], "num", ds["as_of"], ds["source"])
    cash, debt = use("cash"), use("debt")
    if cash and debt:
        out["net_debt0"] = float(debt["val"] - cash["val"])
        rows["nd"] = ("Net debt (− = net cash)", out["net_debt0"], "money", debt["as_of"],
                      debt["source"] if debt["source"] == cash["source"] else debt["source"] + " / " + cash["source"])
    # uzun geçmiş (SEC): marj aralığı ve ciro döngüsü yalnızca raporlanan yıllardan
    an_ = (basis or {}).get("annual") or {}
    rv, op = an_.get("revenue") or {}, an_.get("op_income") or {}
    if len(rv) > len(revs):
        ys = sorted(rv)
        out["rev_hist"] = [rv[y] for y in ys]
        out["hist_years"] = [y[:4] for y in ys]
    ms = [(y[:4], op[y] / rv[y] * 100) for y in sorted(rv) if y in op and rv[y] > 0]
    if len(ms) > len(out["op_m_hist"]):
        out["op_m_hist"] = [m for _, m in ms]
        out["op_m_years"] = [y for y, _ in ms]
    else:
        out["op_m_years"] = yrs[-len(out["op_m_hist"]):] if yrs else []
    out["basis"] = [{"k": k, "label": r_[0], "val": r_[1], "fmt": r_[2], "as_of": r_[3], "source": r_[4]}
                    for k, r_ in rows.items()]
    out["basis_src"] = (basis or {}).get("src") or "none"
    return out


def driver_trough(opm_hist, m_peak):
    """Varsayılan dip marjı: şirketin raporladığı yılların EN DÜŞÜK faaliyet marjı (v4.0 — eskiden medyanın
    %40'ı gibi bir varsayımdı). Zirvenin en az 1 puan altında tutulur; −50 ile sınırlı."""
    hs = [m for m in opm_hist or [] if _ok(m)]
    t = min(hs) if hs else m_peak - 5.0
    return float(max(-50.0, min(t, m_peak - 1.0)))


def driver_margin_defaults(hist, an, fy0=None):
    """Varsayılan marjlar: son analist yılının ima ettiği faaliyet marjı ('last'), zirve ('peak' — bununla
    geçmiş zirvenin büyüğü) ve dip ('trough')."""
    n_an = len([e for e in (an or {}).get("fy") or [] if _ok(e.get("avg"))])
    p = driver_path(1.0e9, hist, an, years=max(1, n_an), fy0=fy0) if hist else None
    ms = p["drivers"]["base"]["op_m"][:max(1, n_an)] if p else []
    last = ms[-1] if ms else (hist["op_m_last"] if hist and _ok(hist.get("op_m_last")) else 15.0)
    hs = max(hist["op_m_hist"]) if hist and hist["op_m_hist"] else last
    peak = float(max(last, hs, max(ms) if ms else last))
    return {"last": float(last), "peak": peak, "trough": driver_trough((hist or {}).get("op_m_hist") or [last], peak)}


def driver_defaults(hist, an, cyclical=False, peak_idx=0, years=5, g_lt=8.0, g_up=None, drop=30.0, fy0=None):
    """Her yıl için varsayılan ciro büyümesi (YoY %) ve kaynağı — analist / model / döngü."""
    fy0 = int(fy0 or pd.Timestamp.now().year)
    H_ = int(years) + 1
    est_rev = [e for e in (an or {}).get("rev_fy") or [] if _ok(e.get("avg"))]
    out = []
    prev = hist["rev_last"]
    an_g = [(e["avg"] / (est_rev[i - 1]["avg"] if i else prev) - 1) * 100 for i, e in enumerate(est_rev)]
    last_an_g = an_g[-1] if an_g else hist["g_rev_last"]
    g_up = g_up if _ok(g_up) else max(g_lt, last_an_g * 0.5 if _ok(last_an_g) else g_lt)
    down_years = 2
    per_down = ((1 - min(90.0, max(0.0, drop)) / 100.0) ** (1.0 / down_years) - 1) * 100
    for i in range(H_):
        if i < len(est_rev) and not (cyclical and i > peak_idx):
            out.append((round(an_g[i], 1), "analyst"))
        elif cyclical and i <= peak_idx:
            out.append((round(g_up, 1), "upswing"))
        elif cyclical and i <= peak_idx + down_years:
            out.append((round(per_down, 1), "downturn"))
        elif cyclical:
            out.append((round(g_lt, 1), "recovery"))
        else:
            out.append((round(g_lt, 1), "model"))
    return [{"fy": fy0 + i, "g": g, "src": src_} for i, (g, src_) in enumerate(out)]


def driver_path(price, hist, an, years=5, cyclical=False, peak_idx=0, drop=30.0, g_lt=8.0, g_up=None,
                g_over=None, m_target=None, m_peak=None, m_trough=None, margin_years=3, share_chg=None,
                capex_pct=None, tax=None, lens="Blend", target_mult=None, rerate_years=3, fy0=None, fy0_end=None,
                **_ignore):
    """Sürücü tabanlı değer patikası (mali yıl). Analist yıllarında EPS analist ortalamasına eşitlenir
    (marj buna göre çıkarılır); sonraki yıllar ciro büyümesi × marj × faiz × vergi × hisse sayısıyla kurulur.
    Döngüselde kâr ve değer tam olarak `peak_idx` yılında zirve yapar. Çıktı value_path ile uyumludur."""
    if not hist or not _ok(price) or price <= 0:
        return None
    fy0 = int(fy0 or pd.Timestamp.now().year)
    H_ = int(years) + 1
    peak_idx = int(min(H_ - 1, max(0, peak_idx or 0)))
    g_over = {int(k): float(v) for k, v in (g_over or {}).items() if _ok(v)}
    try:
        end0 = pd.Timestamp(fy0_end) if fy0_end else pd.Timestamp(year=fy0, month=12, day=31)
    except Exception:
        end0 = pd.Timestamp(year=fy0, month=12, day=31)
    ends = [end0 + pd.DateOffset(years=k) for k in range(H_)]
    est_eps = [e for e in (an or {}).get("fy") or [] if _ok(e.get("avg"))]
    est_rev = [e for e in (an or {}).get("rev_fy") or [] if _ok(e.get("avg"))]
    tax = float(hist["tax"] if tax is None or not _ok(tax) else tax) / 100.0
    tax = min(0.4, max(0.0, tax))
    chg = float(hist["share_chg"] if share_chg is None or not _ok(share_chg) else share_chg) / 100.0
    capx = float(hist["capex_pct"] if capex_pct is None or not _ok(capex_pct) else capex_pct) / 100.0
    da_p = hist["da_pct"] / 100.0
    pay = hist["payout"] / 100.0
    kd, rf = hist["kd"] / 100.0, hist["rf"] / 100.0
    defs = driver_defaults(hist, an, cyclical, peak_idx, years, g_lt, g_up, drop, fy0)
    opm_hist = hist["op_m_hist"] or [10.0]
    drivers, eps, srcs = {}, {}, {}
    for key, sgn in (("bear", -1), ("base", 0), ("bull", 1)):
        est_k = {"bear": "low", "base": "avg", "bull": "high"}[key]
        rev, gr, opm, ebit, intr, ni, shs, e_, da, cap, fcf, nd, src = ([] for _ in range(13))
        nd_prev, r_prev = hist["net_debt0"], hist["rev_last"]
        m_last = hist["op_m_last"] if _ok(hist["op_m_last"]) else opm_hist[-1]
        i_last = -1
        for i in range(H_):
            fy = fy0 + i
            d = defs[i]
            sh = hist["shares0"] * (1 + chg) ** (i + 1)
            interest = nd_prev * (kd if nd_prev > 0 else rf)
            post = cyclical and i > peak_idx
            # --- ciro
            if fy in g_over:
                g = g_over[fy] + sgn * max(3.0, abs(g_over[fy]) * 0.3)
                r = r_prev * (1 + g / 100.0)
                sc = "override"
            elif i < len(est_rev) and not post:
                r = float(est_rev[i].get(est_k) or est_rev[i]["avg"])
                g = (r / r_prev - 1) * 100
                sc = "analyst"
            else:
                g0 = d["g"]
                if d["src"] == "downturn":
                    g = g0 * (1.25 if sgn < 0 else 0.75 if sgn > 0 else 1.0)
                else:
                    g = g0 + sgn * max(3.0, abs(g0) * 0.3)
                r = r_prev * (1 + g / 100.0)
                sc = d["src"] if d["src"] != "model" else "model"
            # --- marj
            anchored = i < len(est_eps) and not post and fy not in g_over
            if anchored:
                ev_ = float(est_eps[i].get(est_k) or est_eps[i]["avg"])
                ni_t = ev_ * sh
                ebt = ni_t / (1 - tax) if ni_t > 0 else ni_t
                m = (ebt + interest) / r * 100 if r > 0 else m_last
                if not (-50 <= m <= 80):
                    m = max(-50.0, min(80.0, m))
                    anchored = False
                m_last, i_last = m, i
            else:
                if cyclical:
                    mp = m_peak if _ok(m_peak) else max(m_last, max(opm_hist))
                    mt = m_trough if _ok(m_trough) else driver_trough(opm_hist, mp)
                    if i <= peak_idx:
                        span = max(1, peak_idx - i_last)
                        m = m_last + (mp - m_last) * min(1.0, (i - i_last) / span)
                    else:
                        rp = rev[peak_idx] if peak_idx < len(rev) else r
                        rt = rp * (1 - min(90.0, max(1.0, drop)) / 100.0)
                        pos = (r - rt) / (rp - rt) if rp > rt else 0.0
                        m = mt + (mp - mt) * min(1.0, max(0.0, pos))
                else:
                    tgt = m_target if _ok(m_target) else m_last
                    m = m_last + (tgt - m_last) * min(1.0, (i - i_last) / float(max(1, margin_years)))
                if sgn and not anchored:
                    m = m * (0.9 if sgn < 0 else 1.07) if m > 0 else m * (1.1 if sgn < 0 else 0.93)
            eb = r * m / 100.0
            ebt = eb - interest
            n_i = ebt * (1 - tax) if ebt > 0 else ebt
            if anchored:
                n_i = float(est_eps[i].get(est_k) or est_eps[i]["avg"]) * sh
            dep = r * da_p
            cx = r * capx
            fc = n_i + dep - cx - 0.05 * (r - r_prev)
            nd_new = nd_prev - fc * (1 - pay)
            for lst, v in ((rev, r), (gr, g), (opm, m), (ebit, eb), (intr, interest), (ni, n_i), (shs, sh),
                           (e_, n_i / sh), (da, dep), (cap, cx), (fcf, fc), (nd, nd_new)):
                lst.append(float(v))
            src.append("analyst" if anchored else sc)
            nd_prev, r_prev = nd_new, r
        # döngüsel zirve: EPS seçilen yılda en yüksek
        if cyclical:
            for i in range(1, H_):
                pk = e_[peak_idx]
                adj = None
                if i <= peak_idx and e_[i - 1] > 0 and e_[i] < e_[i - 1] * 1.01:
                    adj, tag = e_[i - 1] * 1.01, "held"
                elif i > peak_idx and pk > 0 and e_[i] > pk * 0.97:
                    adj, tag = pk * 0.97, "capped"
                if adj is not None:
                    e_[i] = adj
                    ni[i] = adj * shs[i]
                    ebt = ni[i] / (1 - tax) if ni[i] > 0 else ni[i]
                    ebit[i] = ebt + intr[i]
                    opm[i] = ebit[i] / rev[i] * 100 if rev[i] else opm[i]
                    src[i] = tag
        drivers[key] = {"rev": rev, "growth": gr, "op_m": opm, "ebit": ebit, "interest": intr, "ni": ni,
                        "shares": shs, "eps": e_, "da": da, "capex": cap, "fcf": fcf, "net_debt": nd,
                        "ebitda": [a + b_ for a, b_ in zip(ebit, da)],
                        "nd_ebitda": [n_ / (a + b_) if (a + b_) > 0 else float("nan") for n_, a, b_ in zip(nd, ebit, da)],
                        "src": src}
        eps[key], srcs[key] = e_, src
    base = drivers["base"]
    e0 = base["eps"][0]
    eb0 = base["ebit"][0]
    pe_cal = min(80.0, max(1.0, price / e0)) if e0 > 0 else None
    ev_now = price * hist["shares0"] + hist["net_debt0"]
    ev_cal = min(80.0, max(2.0, ev_now / eb0)) if eb0 > 0 else None
    if pe_cal is None and ev_cal is None:
        return None
    m_ref = pe_cal or 15.0
    m_tgt = float(target_mult) if (_ok(target_mult) and target_mult > 0) else m_ref
    start = peak_idx if cyclical else 0
    lens = lens if lens in LENSES else "Blend"
    vals, mults, capped = {}, {}, []
    for key, mm in (("bear", 0.85), ("base", 1.0), ("bull", 1.15)):
        dv = drivers[key]
        vs, pe_l, ev_l = [], [], []
        for k in range(H_):
            t = min(1.0, max(0.0, (k - start) / float(max(1, rerate_years))))
            ts = min(1.0, k / float(max(1, rerate_years)))
            rel = (m_ref + (m_tgt - m_ref) * t) / m_ref * (1 + (mm - 1) * ts)
            v_pe = dv["eps"][k] * pe_cal * rel if pe_cal else None
            v_ev = ((dv["ebit"][k] * ev_cal * rel - dv["net_debt"][k]) / dv["shares"][k]) if ev_cal else None
            pick = [x for x in ((v_pe,) if lens == "P/E" else (v_ev,) if lens == "EV/EBIT" else (v_pe, v_ev))
                    if x is not None]
            if not pick:
                pick = [x for x in (v_pe, v_ev) if x is not None]
            vs.append(max(0.0, float(np.mean(pick))))
            pe_l.append(v_pe)
            ev_l.append(v_ev)
        if cyclical and vs[peak_idx] > 0:
            top = vs[peak_idx]
            for k in range(H_):
                if k != peak_idx and vs[k] >= top:
                    vs[k] = top * 0.99
                    if key == "base":
                        capped.append(fy0 + k)
        dv["value_pe"], dv["value_ev"], dv["value"] = pe_l, ev_l, vs
        vals[key] = vs
        mults[key] = [v / e if e > 0 else (pe_cal or 15.0) for v, e in zip(vs, dv["eps"])]
    rows = []
    for k in range(H_):
        prev_v = vals["base"][k - 1] if k else price
        prev_e = base["eps"][k - 1] if k else hist.get("eps_last")
        row = {"year": fy0 + k, "fy": fy0 + k, "label": f"FY{fy0 + k}", "k": k, "end": ends[k],
               "value": {key: round(vals[key][k], 2) for key in SCEN_KEYS},
               "eps": {key: round(eps[key][k], 3) for key in SCEN_KEYS},
               "mult": {key: round(mults[key][k], 2) for key in SCEN_KEYS},
               "src": srcs["base"][k],
               "eps_yoy": round((base["eps"][k] / prev_e - 1) * 100, 1) if (_ok(prev_e) and prev_e > 0) else None,
               "yoy": round((vals["base"][k] / prev_v - 1) * 100, 1) if prev_v > 0 else None,
               "upside": round((vals["base"][k] / price - 1) * 100, 1)}
        rows.append(row)
    pk_k = peak_idx if cyclical else int(np.argmax(vals["base"]))
    eps_last = hist.get("eps_last") if _ok(hist.get("eps_last")) else base["eps"][0]
    return {"rows": rows, "today": {"year": int(pd.Timestamp.now().year), "k": -1,
                                    "value": {key: float(price) for key in SCEN_KEYS}},
            "eps_rows": [{"fy": r["fy"], "label": r["label"], "src": r["src"], "eps": r["eps"], "growth": r["eps_yoy"]}
                         for r in rows],
            "eps_last": float(eps_last), "m_cal": round(pe_cal or 0.0, 2), "ev_cal": round(ev_cal or 0.0, 2),
            "m_target": round(m_tgt, 2), "rerated": m_tgt != m_ref, "cyclical": bool(cyclical),
            "peak_fy": fy0 + peak_idx, "peak_idx": peak_idx, "drop": float(drop), "g_lt": float(g_lt),
            "fy0": fy0, "n_est": len(est_eps), "price_peak_year": fy0 + pk_k, "price_peak_value": vals["base"][pk_k],
            "capped": capped, "ends": ends, "fy0_end": end0, "eps_series": eps, "mult_series": mults,
            "overridden": [fy0 + k for k in range(H_) if srcs["base"][k] in ("held", "capped")],
            "drivers": drivers, "defaults": defs, "lens": lens, "window": 1,
            "assump": {"tax": tax * 100, "share_chg": chg * 100, "capex_pct": capx * 100, "da_pct": da_p * 100,
                       "payout": pay * 100, "kd": kd * 100, "rf": rf * 100},
            "scen": {"bear": {"g": -1, "drop": drop * 1.25, "m": 0.85, "est": "low"},
                     "base": {"g": 0, "drop": drop, "m": 1.0, "est": "avg"},
                     "bull": {"g": 1, "drop": drop * 0.75, "m": 1.15, "est": "high"}}}


def driver_sensitivity(price, hist, an, cfg, rows_vals, mults, years=5):
    """Duyarlılık: satır = döngüselde ciro düşüşü, değilse uzun vade büyümesi (YoY); sütun = hedef F/K."""
    key = "drop" if cfg.get("cyclical") else "g_lt"
    grid = []
    for rv in rows_vals:
        line = []
        for m in mults:
            c = dict(cfg)
            c[key] = rv
            c["target_mult"] = m
            p = driver_path(price, hist, an, years=years, **c)
            line.append(p["rows"][-1]["value"]["base"] if p else float("nan"))
        grid.append(line)
    return {"key": key, "rows": list(rows_vals), "multiples": list(mults), "grid": grid, "years": years}


# ======================================================================
# v4.0 — Short Term grafiği için katmanlar
#   setup_geometry : tablodaki formasyonun (üçgen, dikdörtgen, merdiven, kırılım) çizgileri
#   order_blocks   : güçlü bir hareketten önceki son ters mum (kurumsal emir bölgesi) — hacim teyitli
#   volume_spikes  : ortalamanın belirgin üstünde hacimle yapılan alım / satım barları
#   Konumlar verilen df'nin satır numaralarıdır (0 … len-1).
# ======================================================================
PAT_COLOR = {"bull": "#F5B544", "bear": "#F5B544", "neutral": "#F5B544"}


def setup_geometry(df, key, lookback=140, left=3, right=3):
    """Formasyonun çizimi: {'key','label','lines':[{'pts':[(i, fiyat)…],'dash','w'}],'dots':[(i, fiyat)…],
    'fill':[(i, fiyat)…],'at':(i, fiyat)}  — setup_patterns ile aynı pivotlardan. Bulunamazsa None."""
    if df is None or len(df) < 45 or not key:
        return None
    d = df.tail(int(lookback))
    n, off = len(d), len(df) - len(d)
    H = d["High"].to_numpy(float)
    L = d["Low"].to_numpy(float)
    C = d["Close"].to_numpy(float)
    px = float(C[-1])
    a = _last(atr(d, 14)) or px * 0.02
    hi_i, _ = pivot_points(d["High"], left, right)
    _, lo_i = pivot_points(d["Low"], left, right)
    g = lambda i, p: (int(i) + off, float(p))
    last = n - 1
    if key.startswith("triangle") and len(hi_i) >= 3 and len(lo_i) >= 3:
        hx, hy = hi_i[-3:], [H[j] for j in hi_i[-3:]]
        lx, ly = lo_i[-3:], [L[j] for j in lo_i[-3:]]
        sh, bh = _fit(hx, hy)
        sl, bl = _fit(lx, ly)
        x0 = min(hx[0], lx[0])
        up0, up1 = sh * x0 + bh, sh * last + bh
        dn0, dn1 = sl * x0 + bl, sl * last + bl
        return {"key": key, "label": SETUP_NAMES.get(key, "Triangle"),
                "lines": [{"pts": [g(x0, up0), g(last, up1)], "w": 2},
                          {"pts": [g(x0, dn0), g(last, dn1)], "w": 2}],
                "dots": [g(i, H[i]) for i in hx] + [g(i, L[i]) for i in lx],
                "fill": [g(x0, up0), g(last, up1), g(last, dn1), g(x0, dn0)],
                "at": g((x0 + last) // 2, max(up0, up1))}
    if key == "rectangle" and len(hi_i) >= 2 and len(lo_i) >= 2:
        hs_i, ls_i = hi_i[-3:], lo_i[-3:]
        top = float(np.mean([H[j] for j in hs_i]))
        bot = float(np.mean([L[j] for j in ls_i]))
        x0 = min(hs_i[0], ls_i[0])
        return {"key": key, "label": "Rectangle",
                "lines": [{"pts": [g(x0, top), g(last, top)], "w": 2}, {"pts": [g(x0, bot), g(last, bot)], "w": 2}],
                "dots": [g(i, H[i]) for i in hs_i] + [g(i, L[i]) for i in ls_i],
                "fill": [g(x0, top), g(last, top), g(last, bot), g(x0, bot)], "at": g((x0 + last) // 2, top)}
    if key == "ladder" and len(hi_i) >= 3 and len(lo_i) >= 3:
        hs_i, ls_i = hi_i[-3:], lo_i[-3:]
        piv = sorted([(i, H[i], "h") for i in hs_i] + [(i, L[i], "l") for i in ls_i])
        zig = [g(i, p) for i, p, _ in piv]
        steps = []
        for seq, arr in ((hs_i, H), (ls_i, L)):          # basamaklar: her tepe / dip bir sonrakine kadar yatay
            for k, i in enumerate(seq):
                end = seq[k + 1] if k + 1 < len(seq) else last
                steps.append({"pts": [g(i, arr[i]), g(end, arr[i])], "dash": True, "w": 1.5})
        up = H[hs_i[-1]] > H[hs_i[0]]
        return {"key": key, "label": "Staircase " + ("▲" if up else "▼"),
                "lines": [{"pts": zig, "w": 2}] + steps,
                "dots": zig, "fill": None, "at": g(hs_i[-1], H[hs_i[-1]])}
    if key in ("breakout", "breakdown"):
        for N in (20, 55):
            if n < N + 6:
                continue
            prior_h = float(np.nanmax(H[-N - 1:-1]))
            prior_l = float(np.nanmin(L[-N - 1:-1]))
            x0 = n - N - 1
            if key == "breakout" and px > prior_h + 0.25 * a:
                j = x0 + int(np.nanargmax(H[-N - 1:-1]))
                return {"key": key, "label": f"{N}-day high breakout",
                        "lines": [{"pts": [g(x0, prior_h), g(last, prior_h)], "w": 2},
                                  {"pts": [g(x0, prior_l), g(last, prior_l)], "dash": True, "w": 1}],
                        "dots": [g(j, prior_h), g(last, C[-1])], "fill": None, "at": g(j, prior_h)}
            if key == "breakdown" and px < prior_l - 0.25 * a:
                j = x0 + int(np.nanargmin(L[-N - 1:-1]))
                return {"key": key, "label": f"{N}-day low breakdown",
                        "lines": [{"pts": [g(x0, prior_l), g(last, prior_l)], "w": 2},
                                  {"pts": [g(x0, prior_h), g(last, prior_h)], "dash": True, "w": 1}],
                        "dots": [g(j, prior_l), g(last, C[-1])], "fill": None, "at": g(j, prior_l)}
    return None


def order_blocks(df, lookback=220, vol_n=20, imp_atr=1.2, vol_x=1.3, max_n=4):
    """Order block'lar (kurumsal emir bölgeleri).
    Yükseliş OB: güçlü bir yükselişten (≥ imp_atr × ATR, önceki 10 barın zirvesini aşan kapanış) hemen önceki
    son düşüş mumu; düşüş OB: tersi. Hareket ortalamanın en az vol_x katı hacimle gelmiş olmalı.
    Bölge = o mumun aralığı. Fiyat bölgenin öbür ucunun ötesinde kapanırsa bölge geçersiz ("mitigated").
    Döner: [{kind: bull|bear, i, lo, hi, vol_x, move_atr, end (geçersizleştiği bar | None), tests, dist}]
    — geçerli olanlar, fiyata en yakından uzağa; en çok max_n."""
    if df is None or len(df) < vol_n + 15:
        return []
    d = df.tail(int(lookback))
    n, off = len(d), len(df) - len(d)
    O = d["Open"].to_numpy(float)
    H = d["High"].to_numpy(float)
    L = d["Low"].to_numpy(float)
    C = d["Close"].to_numpy(float)
    V = d["Volume"].to_numpy(float)
    A = atr(d, 14).to_numpy(float)
    px = float(C[-1])
    has_vol = float(np.nansum(V)) > 0
    out = []
    i = vol_n
    while i < n - 2:
        a = A[i]
        if not (a == a and a > 0):
            i += 1
            continue
        va = float(np.nanmean(V[i - vol_n:i])) if has_vol else 0.0
        hit = None
        for side in ("bull", "bear"):
            if side == "bull" and not C[i] < O[i]:
                continue
            if side == "bear" and not C[i] > O[i]:
                continue
            j_end = min(n - 1, i + 3)
            if side == "bull":
                ext = float(np.max(C[i + 1:j_end + 1]))
                move = (ext - H[i]) / a
                broke = ext > float(np.max(H[max(0, i - 10):i + 1]))
            else:
                ext = float(np.min(C[i + 1:j_end + 1]))
                move = (L[i] - ext) / a
                broke = ext < float(np.min(L[max(0, i - 10):i + 1]))
            if move < imp_atr or not broke:
                continue
            vx = float(np.max(V[i:j_end + 1]) / va) if (has_vol and va > 0) else None
            if vx is not None and vx < vol_x:
                continue
            lo, hi = float(L[i]), float(H[i])
            if hi - lo > 2.0 * a:                     # çok uzun mum: gövde + ilgili fitil
                lo, hi = (lo, float(max(O[i], C[i]))) if side == "bull" else (float(min(O[i], C[i])), hi)
            end, tests = None, 0
            inside = False
            for j in range(j_end + 1, n):
                if side == "bull":
                    if C[j] < lo:
                        end = j
                        break
                    touch = L[j] <= hi
                else:
                    if C[j] > hi:
                        end = j
                        break
                    touch = H[j] >= lo
                if touch and not inside:
                    tests += 1
                inside = touch
            hit = {"kind": side, "i": int(i) + off, "lo": lo, "hi": hi,
                   "vol_x": round(vx, 2) if vx is not None else None, "move_atr": round(float(move), 2),
                   "end": (int(end) + off) if end is not None else None, "tests": int(tests),
                   "dist": float(((lo + hi) / 2 / px - 1) * 100) if px > 0 else 0.0}
            break
        if hit:
            out.append(hit)
            i += 2
        else:
            i += 1
    live = [o for o in out if o["end"] is None]
    # aynı yöndeki üst üste binen bölgelerden hacmi yüksek olan kalır
    live.sort(key=lambda o: -(o["vol_x"] or 0))
    keep = []
    for o in live:
        if any(k["kind"] == o["kind"] and o["lo"] <= k["hi"] and o["hi"] >= k["lo"] for k in keep):
            continue
        keep.append(o)
    near = [o for o in keep if abs(o["dist"]) <= 25.0] or keep      # uzak bölgeler çizilmez
    near.sort(key=lambda o: abs(o["dist"]))
    return near[:int(max_n)]


def volume_spikes(df, n=20, mult=2.0, lookback=160, max_n=14):
    """Ortalamanın (önceki n bar) en az mult katı hacimli barlar.
    Yön: kapanış aralığın üst yarısında ve önceki kapanışın üstündeyse ALIM, alt yarısında ve altındaysa SATIM;
    belirsiz barlar atlanır. Döner: [{i, side: buy|sell, ratio, close_pos, chg}] (eski → yeni)."""
    if df is None or len(df) < n + 5:
        return []
    d = df.tail(int(lookback) + n)
    off = len(df) - len(d)
    H = d["High"].to_numpy(float)
    L = d["Low"].to_numpy(float)
    C = d["Close"].to_numpy(float)
    V = d["Volume"].to_numpy(float)
    if float(np.nansum(V)) <= 0:
        return []
    out = []
    for i in range(n, len(d)):
        base = float(np.nanmean(V[i - n:i]))
        if not (base > 0) or not (V[i] == V[i]):
            continue
        r = V[i] / base
        if r < mult:
            continue
        rng = H[i] - L[i]
        pos = (C[i] - L[i]) / rng if rng > 0 else 0.5
        chg = (C[i] / C[i - 1] - 1) * 100 if C[i - 1] > 0 else 0.0
        if pos >= 0.55 and chg > 0:
            side = "buy"
        elif pos <= 0.45 and chg < 0:
            side = "sell"
        else:
            continue
        out.append({"i": int(i) + off, "side": side, "ratio": round(float(r), 1), "close_pos": round(float(pos), 2),
                    "chg": round(float(chg), 2)})
    out.sort(key=lambda m: -m["ratio"])
    out = sorted(out[:int(max_n)], key=lambda m: m["i"])
    return out
