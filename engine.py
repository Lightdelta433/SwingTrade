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

ENGINE_VERSION = "3.0"
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
    s = f"{v:,.{dec}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


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
    "Fiyat": {"fn": lambda df, ctx: df["Close"], "group": "Fiyat", "kind": "price",
              "desc": "Son kapanış fiyatı."},
    "SMA 20": {"fn": lambda df, ctx: sma(df["Close"], 20), "group": "Trend", "kind": "price",
               "desc": "20 günlük basit hareketli ortalama — kısa vadeli trend."},
    "SMA 50": {"fn": lambda df, ctx: sma(df["Close"], 50), "group": "Trend", "kind": "price",
               "desc": "50 günlük basit hareketli ortalama — swing trader'ların en çok izlediği orta vadeli trend."},
    "SMA 200": {"fn": lambda df, ctx: sma(df["Close"], 200), "group": "Trend", "kind": "price",
                "desc": "200 günlük ortalama — fiyat üstündeyse uzun vadeli boğa rejimi kabul edilir."},
    "EMA 20": {"fn": lambda df, ctx: ema(df["Close"], 20), "group": "Trend", "kind": "price",
               "desc": "20 günlük üssel ortalama — son fiyatlara daha fazla ağırlık verir."},
    "EMA 50": {"fn": lambda df, ctx: ema(df["Close"], 50), "group": "Trend", "kind": "price",
               "desc": "50 günlük üssel ortalama."},
    "RSI (14)": {"fn": lambda df, ctx: rsi(df["Close"], 14), "group": "Momentum", "kind": "osc",
                 "desc": "Göreceli Güç Endeksi (0–100). 70 üstü aşırı alım, 30 altı aşırı satım; "
                         "40–60 bandı trend içi geri çekilmeye işaret eder."},
    "Stokastik %K (14)": {"fn": lambda df, ctx: stoch_k(df, 14), "group": "Momentum", "kind": "osc",
                          "desc": "Kapanışın son 14 günlük aralıktaki yeri (0–100). 80 üstü aşırı alım, "
                                  "20 altı aşırı satım."},
    "Williams %R (14)": {"fn": lambda df, ctx: williams_r(df, 14), "group": "Momentum", "kind": "osc",
                         "desc": "−100 ile 0 arası. −20 üstü aşırı alım, −80 altı aşırı satım."},
    "CCI (20)": {"fn": lambda df, ctx: cci(df, 20), "group": "Momentum", "kind": "osc",
                 "desc": "Emtia Kanal Endeksi. +100 üstü güçlü yükseliş, −100 altı güçlü düşüş."},
    "MFI (14)": {"fn": lambda df, ctx: mfi(df, 14), "group": "Hacim", "kind": "osc",
                 "desc": "Para Akışı Endeksi — hacim ağırlıklı RSI (0–100). 80 üstü aşırı alım, 20 altı aşırı satım."},
    "MACD çizgisi": {"fn": lambda df, ctx: macd(df["Close"])[0], "group": "Momentum", "kind": "price",
                     "desc": "EMA 12 − EMA 26. Sıfır üstü yükseliş momentumu."},
    "MACD sinyal": {"fn": lambda df, ctx: macd(df["Close"])[1], "group": "Momentum", "kind": "price",
                    "desc": "MACD çizgisinin 9 günlük üssel ortalaması."},
    "MACD histogram": {"fn": lambda df, ctx: macd(df["Close"])[2], "group": "Momentum", "kind": "price",
                       "desc": "MACD − sinyal. Sıfırı yukarı kesmesi alım momentumunun başladığını gösterir."},
    "Bollinger %B (20,2)": {"fn": lambda df, ctx: boll_pctb(df["Close"]), "group": "Oynaklık", "kind": "ratio",
                            "desc": "Fiyatın Bollinger bandı içindeki yeri: 0 alt bant, 1 üst bant. "
                                    "0 altı aşırı satım, 1 üstü aşırı alım."},
    "ATR % (14)": {"fn": lambda df, ctx: atr(df, 14) / df["Close"] * 100, "group": "Oynaklık", "kind": "pct",
                   "desc": "Ortalama gerçek aralığın fiyata oranı — günlük oynaklık ölçüsü."},
    "Göreli hacim (20g)": {"fn": lambda df, ctx: relvol(df, 20), "group": "Hacim", "kind": "ratio",
                           "desc": "Bugünkü hacim / 20 günlük ortalama hacim. 1,5 üstü güçlü ilgi."},
    "Günlük değişim %": {"fn": lambda df, ctx: pct_ret(df["Close"], 1), "group": "Getiri", "kind": "pct",
                         "desc": "Son günün yüzde değişimi."},
    "1 hafta getiri %": {"fn": lambda df, ctx: pct_ret(df["Close"], 5), "group": "Getiri", "kind": "pct",
                         "desc": "Son 5 işlem gününün getirisi."},
    "1 ay getiri %": {"fn": lambda df, ctx: pct_ret(df["Close"], 21), "group": "Getiri", "kind": "pct",
                      "desc": "Son 21 işlem gününün getirisi (momentum)."},
    "3 ay getiri %": {"fn": lambda df, ctx: pct_ret(df["Close"], 63), "group": "Getiri", "kind": "pct",
                      "desc": "Son 63 işlem gününün getirisi."},
    "52h zirveye uzaklık %": {"fn": lambda df, ctx: (df["Close"] / df["High"].rolling(252, min_periods=20).max() - 1) * 100,
                              "group": "Trend", "kind": "pct",
                              "desc": "52 haftalık zirveye yüzde uzaklık (0 = zirvede, −10 = zirvenin %10 altında)."},
    "Göreli güç vs SPY (3 ay)": {"fn": lambda df, ctx: _bench_rs(df, ctx, 63), "group": "Göreli güç", "kind": "pct",
                                 "desc": "Son 3 ayda hissenin getirisi − S&P 500 (SPY) getirisi (puan). "
                                         "Pozitifse endeksten güçlü."},
    "Bilançoya kalan gün": {"fn": lambda df, ctx: _const(df, (ctx or {}).get("earn_days", NAN)),
                            "group": "Takvim", "kind": "days",
                            "desc": "Bir sonraki bilanço açıklamasına kalan gün (veri yoksa boş)."},
}
IND_NAMES = list(INDICATORS)

ALIASES = {
    "rsi": "RSI (14)", "macd": "MACD histogram", "stoch": "Stokastik %K (14)",
    "stokastik": "Stokastik %K (14)", "bollinger": "Bollinger %B (20,2)", "boll": "Bollinger %B (20,2)",
    "atr": "ATR % (14)", "oynaklık": "ATR % (14)", "volatilite": "ATR % (14)",
    "hacim": "Göreli hacim (20g)", "volume": "Göreli hacim (20g)", "sma": "SMA 50", "ema": "EMA 20",
    "ortalama": "SMA 50", "moving average": "SMA 50", "cci": "CCI (20)", "mfi": "MFI (14)",
    "williams": "Williams %R (14)", "momentum": "1 ay getiri %", "getiri": "1 ay getiri %",
    "bilanço": "Bilançoya kalan gün", "bilanco": "Bilançoya kalan gün", "earnings": "Bilançoya kalan gün",
    "göreli güç": "Göreli güç vs SPY (3 ay)", "relative strength": "Göreli güç vs SPY (3 ay)",
    "rs": "Göreli güç vs SPY (3 ay)", "zirve": "52h zirveye uzaklık %", "52": "52h zirveye uzaklık %",
    "fiyat": "Fiyat", "price": "Fiyat",
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
        return "veri yok"
    kind = INDICATORS.get(name, {}).get("kind", "price")
    if kind == "osc":
        return fmt_num(v, 1)
    if kind == "pct":
        return ("+" if v >= 0 else "−") + "%" + fmt_num(abs(v), 1)
    if kind == "ratio":
        return fmt_num(v, 2) + ("×" if "hacim" in name.lower() else "")
    if kind == "days":
        return "3+ hafta" if v >= EARN_FAR else f"{int(round(v))} gün"
    return fmt_num(v, 2)


# ======================================================================
# KOŞUL MOTORU
# ======================================================================
OPS = ["<", ">", "≤", "≥", "yukarı keser", "aşağı keser"]
NUM = "Sayı"
COMPARE_OPTIONS = [NUM] + IND_NAMES
COND_COLS = ["Aktif", "Gösterge", "Koşul", "Karşılaştır", "Değer"]

DEFAULT_FILTER = [
    {"Aktif": True, "Gösterge": "Fiyat", "Koşul": ">", "Karşılaştır": "SMA 50", "Değer": 0.0},
    {"Aktif": True, "Gösterge": "SMA 50", "Koşul": ">", "Karşılaştır": "SMA 200", "Değer": 0.0},
    {"Aktif": True, "Gösterge": "RSI (14)", "Koşul": "≥", "Karşılaştır": NUM, "Değer": 40.0},
    {"Aktif": True, "Gösterge": "RSI (14)", "Koşul": "≤", "Karşılaştır": NUM, "Değer": 60.0},
    {"Aktif": True, "Gösterge": "Göreli hacim (20g)", "Koşul": ">", "Karşılaştır": NUM, "Değer": 1.5},
    {"Aktif": True, "Gösterge": "Göreli güç vs SPY (3 ay)", "Koşul": ">", "Karşılaştır": NUM, "Değer": 0.0},
]

# Bir indikatör filtreye/backtest'e eklendiğinde mantıklı varsayılan koşul
SUGGESTED = {
    "RSI (14)": (">", NUM, 50.0), "Stokastik %K (14)": ("<", NUM, 20.0),
    "Williams %R (14)": ("<", NUM, -80.0), "CCI (20)": (">", NUM, 100.0), "MFI (14)": ("<", NUM, 20.0),
    "MACD histogram": ("yukarı keser", NUM, 0.0), "MACD çizgisi": (">", "MACD sinyal", 0.0),
    "MACD sinyal": ("<", "MACD çizgisi", 0.0), "Bollinger %B (20,2)": ("<", NUM, 0.0),
    "ATR % (14)": ("<", NUM, 4.0), "Göreli hacim (20g)": (">", NUM, 1.5),
    "Günlük değişim %": (">", NUM, 0.0), "1 hafta getiri %": (">", NUM, 0.0),
    "1 ay getiri %": (">", NUM, 5.0), "3 ay getiri %": (">", NUM, 10.0),
    "52h zirveye uzaklık %": (">", NUM, -10.0), "Göreli güç vs SPY (3 ay)": (">", NUM, 0.0),
    "Bilançoya kalan gün": (">", NUM, 10.0), "Fiyat": (">", "SMA 50", 0.0),
    "SMA 20": ("<", "Fiyat", 0.0), "SMA 50": (">", "SMA 200", 0.0), "SMA 200": ("<", "Fiyat", 0.0),
    "EMA 20": ("<", "Fiyat", 0.0), "EMA 50": ("<", "Fiyat", 0.0),
}


def suggested_condition(name):
    op, cmp_, val = SUGGESTED.get(name, (">", NUM, 0.0))
    return {"Aktif": True, "Gösterge": name, "Koşul": op, "Karşılaştır": cmp_, "Değer": float(val)}


def normalize_conds(rows):
    out = []
    for r in rows or []:
        try:
            if not isinstance(r, dict):
                continue
            g, k = r.get("Gösterge"), r.get("Koşul")
            c = r.get("Karşılaştır") or NUM
            if g not in INDICATORS or k not in OPS or (c != NUM and c not in INDICATORS):
                continue
            v = r.get("Değer")
            try:
                v = float(v)
                if v != v:
                    v = 0.0
            except (TypeError, ValueError):
                v = 0.0
            a = r.get("Aktif")
            a = True if a is None or a != a else bool(a)
            out.append({"Aktif": a, "Gösterge": g, "Koşul": k, "Karşılaştır": c, "Değer": v})
        except Exception:
            continue
    return out


def cond_text(c):
    rhs = c["Karşılaştır"] if c["Karşılaştır"] != NUM else fmt_num(c["Değer"])
    return f'{c["Gösterge"]} {c["Koşul"]} {rhs}'


def needed(conds):
    s = set()
    for c in conds:
        s.add(c["Gösterge"])
        if c["Karşılaştır"] != NUM:
            s.add(c["Karşılaştır"])
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
    if c["Karşılaştır"] == NUM:
        return pd.Series(float(c["Değer"]), index=index)
    return S[c["Karşılaştır"]]


def eval_series(c, S):
    """Koşulun her bar için doğru/yanlış serisi (backtest)."""
    L = S[c["Gösterge"]]
    R = _rhs(c, S, L.index)
    op = c["Koşul"]
    if op == "<":
        m = L < R
    elif op == ">":
        m = L > R
    elif op == "≤":
        m = L <= R
    elif op == "≥":
        m = L >= R
    elif op == "yukarı keser":
        m = (L.shift() < R.shift()) & (L >= R)
    else:
        m = (L.shift() > R.shift()) & (L <= R)
    valid = L.notna() & R.notna()
    if op in ("yukarı keser", "aşağı keser"):
        valid &= L.shift().notna() & R.shift().notna()
    return (m & valid).fillna(False).astype(bool)


def eval_last(c, S):
    """Son bar için (durum, sol değer, sağ değer). Veri yoksa durum None."""
    L = S[c["Gösterge"]]
    R = _rhs(c, S, L.index)
    if len(L) < 2:
        return None, NAN, NAN
    l1, r1, l0, r0 = L.iloc[-1], R.iloc[-1], L.iloc[-2], R.iloc[-2]
    if pd.isna(l1) or pd.isna(r1):
        return None, float(l1) if pd.notna(l1) else NAN, float(r1) if pd.notna(r1) else NAN
    op = c["Koşul"]
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
        ok = (l0 < r0 and l1 >= r1) if op == "yukarı keser" else (l0 > r0 and l1 <= r1)
    return bool(ok), float(l1), float(r1)


# ======================================================================
# SWING TARAYICI
# ======================================================================
SETUPS = ["Pullback", "Kırılım", "Destekten dönüş", "Momentum"]
BASE_NEEDS = ["Fiyat", "SMA 50", "SMA 200", "EMA 20", "RSI (14)", "Göreli hacim (20g)",
              "1 ay getiri %", "Göreli güç vs SPY (3 ay)", "Günlük değişim %"]


def classify_setup(df, S):
    c = _last(S["Fiyat"])
    o = float(df["Open"].iloc[-1])
    hi20 = float(df["High"].iloc[-21:-1].max()) if len(df) > 21 else NAN
    lo60 = float(df["Low"].iloc[-60:].min())
    rv, r = _last(S["Göreli hacim (20g)"]), _last(S["RSI (14)"])
    m1, e20, s50 = _last(S["1 ay getiri %"]), _last(S["EMA 20"]), _last(S["SMA 50"])
    if _ok(hi20) and c >= hi20 * 0.995 and (not _ok(rv) or rv >= 1.2):
        return "Kırılım"
    if _ok(r) and _ok(m1) and r >= 60 and m1 >= 8:
        return "Momentum"
    if c <= lo60 * 1.06 and c > o:
        return "Destekten dönüş"
    if _ok(s50) and _ok(e20) and c > s50 and abs(c / e20 - 1) <= 0.03:
        return "Pullback"
    return "Momentum" if (_ok(r) and r >= 55) else "Pullback"


def trade_levels(setup, df, S, a):
    """ATR(14) bazlı giriş bölgesi, stop ve hedef önerisi."""
    c = _last(S["Fiyat"])
    if not _ok(a) or a <= 0:
        a = c * 0.02
    e20 = _last(S["EMA 20"])
    e20 = e20 if _ok(e20) else c
    lo20 = float(df["Low"].tail(20).min())
    if setup == "Kırılım":
        lo, hi = c - 0.2 * a, c + 0.2 * a
        mid = (lo + hi) / 2
        stop, tgt = mid - 1.5 * a, mid + 3.5 * a
    elif setup == "Pullback":
        base = min(c, e20)
        lo, hi = base - 0.2 * a, base + 0.3 * a
        mid = (lo + hi) / 2
        stop, tgt = lo - 1.2 * a, mid + 3.0 * a
    elif setup == "Destekten dönüş":
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
    c, s50, s200 = _last(S["Fiyat"]), _last(S["SMA 50"]), _last(S["SMA 200"])
    trend = 0.5 * (1 if _ok(s50) and c > s50 else 0) + 0.5 * (1 if _ok(s50) and _ok(s200) and s50 > s200 else 0)
    rv = _last(S["Göreli hacim (20g)"])
    vol = min(max((rv - 0.6) / 1.4, 0), 1) if _ok(rv) else 0.3
    rs = _last(S["Göreli güç vs SPY (3 ay)"])
    rsc = min(max((rs + 10) / 20, 0), 1) if _ok(rs) else 0.5
    return int(round(100 * (0.5 * fit + 0.25 * trend + 0.15 * vol + 0.10 * rsc)))


def scan(hist, conds, logic="VE", min_match=None, bench=None, earn_days=None, names=None):
    """Evren üzerinde filtreyi çalıştırır, eşleşenleri setup/seviye/skorla döndürür.
    hist: {ticker: OHLCV DataFrame}; conds: koşul listesi (normalize edilir)."""
    names = names or {}
    earn_days = earn_days or {}
    active = [c for c in normalize_conds(conds) if c["Aktif"]]
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
            checks.append({"text": cond_text(c), "ok": st_, "val": fmt_ind_value(c["Gösterge"], lv)})
            passes += 1 if st_ else 0
        if N:
            ok = passes >= 1 if logic == "VEYA" else passes >= need_min
            if not ok:
                continue
        a = _last(atr(df, 14))
        setup = classify_setup(df, S)
        lv = trade_levels(setup, df, S, a)
        fit = passes / N if N else 1.0
        nm, sec = names.get(t, (t, ""))
        out.append({
            "ticker": t, "name": nm, "sector": sec, "setup": setup,
            "price": _last(S["Fiyat"]), "chg": _last(S["Günlük değişim %"]),
            **lv, "score": _score(fit, S), "passes": passes, "n": N, "checks": checks,
            "rsi": _last(S["RSI (14)"]), "relvol": _last(S["Göreli hacim (20g)"]),
            "rs": _last(S["Göreli güç vs SPY (3 ay)"]), "earn_days": earn_days.get(t, NAN),
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
        checks.append({"t": f"VIX {fmt_num(vix, 1)} · 20'nin {'altında' if low else 'üstünde'}", "ok": low})
    if pct_above50 is not None and _ok(pct_above50):
        checks.append({"t": f"SMA 50 üstündeki hisse oranı %{fmt_num(pct_above50, 0)}",
                       "ok": pct_above50 >= 50})
    if leader:
        checks.append({"t": f"Lider sektör: {leader}", "ok": True})
    if above and low is not False:
        label, badge, tone = "Yükseliş trendi · düşük oynaklık", "SWING İÇİN UYGUN", "good"
    elif above:
        label, badge, tone = "Yükseliş trendi · yüksek oynaklık", "DİKKATLİ", "warn"
    elif above is False and low:
        label, badge, tone = "Zayıf trend · düşük oynaklık", "SEÇİCİ OL", "warn"
    elif above is False:
        label, badge, tone = "Düşüş trendi · yüksek oynaklık", "SAVUNMACI", "bad"
    else:
        label, badge, tone = "Rejim verisi yok", "—", "warn"
    return {"label": label, "badge": badge, "tone": tone, "checks": checks}


# ======================================================================
# BACKTEST — tasarımdaki Strateji Laboratuvarı'nın birebir portu
# Sinyal mum kapanışında oluşur, giriş bir sonraki mumun açılışında.
# Aynı mumda stop ve hedef görülürse stop varsayılır.
# ======================================================================
IND1 = {
    "RSI": {"fn": lambda df, p: rsi(df["Close"], p), "mirror": lambda v: 100 - v},
    "Stokastik %K": {"fn": lambda df, p: stoch_k(df, p), "mirror": lambda v: 100 - v},
    "MFI": {"fn": lambda df, p: mfi(df, p), "mirror": lambda v: 100 - v},
    "Williams %R": {"fn": lambda df, p: williams_r(df, p), "mirror": lambda v: -100 - v},
    "CCI": {"fn": lambda df, p: cci(df, p), "mirror": lambda v: -v},
}
IND1_OFF = "— (kullanma)"
IND1_OPTIONS = list(IND1) + [IND1_OFF]
OPS1 = {"lt": "altında (<)", "gt": "üstünde (>)", "xup": "yukarı keser", "xdn": "aşağı keser"}
OPS1_SHORT = {"lt": "<", "gt": ">", "xup": "↗ keser", "xdn": "↘ keser"}
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
        parts.append(f'Fiyat {">" if cfg["op2"] == "above" else "<"} {str(cfg["src2"]).upper()}({int(cfg["p2"])})')
    s = (" VE " if cfg["logic"] == "and" else " VEYA ").join(parts)
    ex = [cond_text(c) for c in normalize_conds(cfg.get("extra")) if c["Aktif"]]
    if ex:
        k = _extra_need(cfg, len(ex))
        joined = " VE ".join(ex) if k == len(ex) else f"[en az {k}/{len(ex)}: " + " · ".join(ex) + "]"
        s = (s + " VE " if s else "") + joined
    s = s or "Koşul yok"
    s += " · " + {"long": "Long", "short": "Short", "both": "Long + Short"}.get(cfg["dir"], "Long")
    s += " · SL " + (f'%{fmt_num(cfg["slV"], 1)}' if cfg["slMode"] == "pct" else f'{fmt_num(cfg["slV"], 1)}×ATR')
    if cfg["tpMode"] == "pct":
        s += f' · TP %{fmt_num(cfg["tpV"], 1)}'
    elif cfg["tpMode"] == "rr":
        s += f' · TP {fmt_num(cfg["tpV"], 1)}R'
    else:
        s += f' · TP {fmt_num(cfg["tpV"], 1)}×ATR'
    if int(cfg["maxBars"]) > 0:
        s += f' · maks. {int(cfg["maxBars"])}g'
    return s


def backtest(df, cfg, extra=None, bench=None):
    cfg = {**BT_DEFAULTS, **(cfg or {})}
    if extra is None:
        extra = cfg.get("extra")
    cfg["extra"] = normalize_conds(extra)
    if df is None or len(df) == 0:
        return {"ok": False, "msg": "Fiyat verisi yok."}
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    total = len(df)
    if total < 60:
        return {"ok": False, "msg": "Yetersiz fiyat verisi (en az 60 mum gerekir)."}
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
    extra_c = [x for x in normalize_conds(extra) if x["Aktif"]]
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
                close_pos(i, c[i], "Süre")
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
        close_pos(total - 1, c[total - 1], "Açık")
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
    verdict = "Yetersiz örnek" if n < 5 else "Umut verici" if good else "Sınırda" if okish else "Zayıf"
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
