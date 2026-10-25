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

ENGINE_VERSION = "3.2"
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


DIV_KINDS = {"reg_bull": ("Yükseliş uyumsuzluğu", "bull"), "hid_bull": ("Gizli yükseliş", "bull"),
             "reg_bear": ("Düşüş uyumsuzluğu", "bear"), "hid_bear": ("Gizli düşüş", "bear")}


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
        base = "Direnç" if kind == "res" else "Destek"
        out.append({"lo": r["lo"] - pad, "hi": r["hi"] + pad, "pct": int(pct), "kind": kind,
                    "weak": bool(weak), "touches": r["touches"],
                    "start": int(r["start"]) + (len(df) - n), "last": int(r["last"]) + (len(df) - n),
                    "label": ("Zayıf " + base) if weak else base})
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
                out.append({"name": "Çift dip", "kind": "bull", "conf": float(round(min(1.0, conf), 2)),
                            "i": int(i2) + (len(df) - n),
                            "note": "boyun %s%s" % (fmt_num(neck, 2), " kırıldı" if px > neck else " henüz kırılmadı")})
    if len(hi_i) >= 2:
        i1, i2 = hi_i[-2], hi_i[-1]
        gap = i2 - i1
        if 5 <= gap <= 90 and rel(H[i1], H[i2]) <= tol:
            mid = [j for j in lo_i if i1 < j < i2]
            neck = float(L[min(mid, key=lambda j: L[j])]) if mid else float(L[i1:i2 + 1].min())
            if neck < min(H[i1], H[i2]):
                conf = 0.55 + 0.25 * (1 - rel(H[i1], H[i2]) / tol) + (0.2 if px < neck else 0.0)
                out.append({"name": "Çift tepe", "kind": "bear", "conf": float(round(min(1.0, conf), 2)),
                            "i": int(i2) + (len(df) - n),
                            "note": "boyun %s%s" % (fmt_num(neck, 2), " kırıldı" if px < neck else " henüz kırılmadı")})
    # ---- omuz-baş-omuz / ters OBO
    if len(hi_i) >= 3:
        a, b, c = hi_i[-3], hi_i[-2], hi_i[-1]
        if H[b] > H[a] and H[b] > H[c] and rel(H[a], H[c]) <= tol * 1.8 and (c - a) <= 140:
            mids = [j for j in lo_i if a < j < c]
            neck = float(np.mean([L[j] for j in mids])) if mids else float(L[a:c + 1].min())
            out.append({"name": "Omuz-baş-omuz", "kind": "bear", "conf": 0.72,
                        "i": int(c) + (len(df) - n),
                        "note": "boyun %s%s" % (fmt_num(neck, 2), " kırıldı" if px < neck else "")})
    if len(lo_i) >= 3:
        a, b, c = lo_i[-3], lo_i[-2], lo_i[-1]
        if L[b] < L[a] and L[b] < L[c] and rel(L[a], L[c]) <= tol * 1.8 and (c - a) <= 140:
            mids = [j for j in hi_i if a < j < c]
            neck = float(np.mean([H[j] for j in mids])) if mids else float(H[a:c + 1].max())
            out.append({"name": "Ters omuz-baş-omuz", "kind": "bull", "conf": 0.72,
                        "i": int(c) + (len(df) - n),
                        "note": "boyun %s%s" % (fmt_num(neck, 2), " kırıldı" if px > neck else "")})
    # ---- üçgen (son 3 tepe / 3 dip eğimi)
    if len(hi_i) >= 3 and len(lo_i) >= 3:
        hs = _slope(hi_i[-3:], [H[j] for j in hi_i[-3:]]) / max(px, 1e-9) * 100
        ls = _slope(lo_i[-3:], [L[j] for j in lo_i[-3:]]) / max(px, 1e-9) * 100
        flat = 0.035
        if hs < -flat and ls > flat:
            out.append({"name": "Simetrik üçgen", "kind": "neutral", "conf": 0.6,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n), "note": "sıkışma — kırılım bekleniyor"})
        elif abs(hs) <= flat and ls > flat:
            out.append({"name": "Yükselen üçgen", "kind": "bull", "conf": 0.68,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n),
                        "note": "yatay direnç %s" % fmt_num(float(np.mean([H[j] for j in hi_i[-3:]])), 2)})
        elif hs < -flat and abs(ls) <= flat:
            out.append({"name": "Alçalan üçgen", "kind": "bear", "conf": 0.68,
                        "i": int(max(hi_i[-1], lo_i[-1])) + (len(df) - n),
                        "note": "yatay destek %s" % fmt_num(float(np.mean([L[j] for j in lo_i[-3:]])), 2)})
    # ---- bayrak / flama (sert hareket + sıkışma)
    if n >= 45:
        imp = (C[-20] / C[-40] - 1) * 100 if C[-40] else 0.0
        rng = (H[-15:].max() - L[-15:].min()) / max(px, 1e-9) * 100
        if abs(imp) >= 8 and rng <= max(4.0, abs(imp) * 0.45):
            out.append({"name": "Boğa bayrağı" if imp > 0 else "Ayı bayrağı",
                        "kind": "bull" if imp > 0 else "bear", "conf": 0.6,
                        "i": len(df) - 1,
                        "note": "%%%s'lik hareket sonrası %%%s bantta sıkışma"
                                % (fmt_num(abs(imp), 1), fmt_num(rng, 1))})
    out.sort(key=lambda p: (-p["conf"], -p["i"]))
    return out[:int(limit)]


# ======================================================================
# A–Z notu — altı grup, kural tabanlı puanlama ve Türkçe yorum
#   A = en güçlü alım · M/N = nötr · Z = en güçlü satım
# ======================================================================
GRADE_GROUPS = [("mom", "Momentum", 25), ("form", "Formasyon & uyumsuzluk", 20),
                ("vol", "Hacim", 20), ("rr", "Risk / Ödül", 20),
                ("trend", "Trend & ortalamalar", 10), ("volat", "Volatilite & konum", 5)]
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
            s, t = 68, "RSI %s — güçlü ama aşırı alım bölgesinde, geri çekilme riski var" % _f(r, 1)
        elif r >= 58:
            s, t = 90, "RSI %s — momentum alıcıda" % _f(r, 1)
        elif r >= 50:
            s, t = 66, "RSI %s — 50'nin hafif üstünde" % _f(r, 1)
        elif r >= 42:
            s, t = 40, "RSI %s — 50'nin altında, momentum zayıf" % _f(r, 1)
        elif r > 30:
            s, t = 24, "RSI %s — satıcı baskın" % _f(r, 1)
        else:
            s, t = 38, "RSI %s — aşırı satım, tepki yükselişi olabilir" % _f(r, 1)
        s = min(100, max(0, s + (6 if dr > 4 else -6 if dr < -4 else 0)))
        parts.append((s, 1.1))
        why.append(t + (" ve son 5 barda yükseliyor" if dr > 4 else " ve son 5 barda zayıflıyor" if dr < -4 else ""))
    line, sig, hist = macd(close)
    h, hp = _last(hist), _last(hist.shift(1))
    if _ok(h):
        rising = _ok(hp) and h > hp
        hv = hist.to_numpy(float)
        cross = next((k for k in range(1, min(40, len(hv))) if _ok(hv[-k]) and _ok(hv[-k - 1])
                      and np.sign(hv[-k]) != np.sign(hv[-k - 1])), None)
        if h > 0:
            s = 92 if rising else 68
            t = "MACD histogramı pozitif ve %s" % ("genişliyor" if rising else "daralıyor")
        else:
            s = 34 if rising else 10
            t = "MACD histogramı negatif ve %s" % ("toparlıyor" if rising else "derinleşiyor")
        if cross is not None and cross <= 5:
            t += " · %d bar önce yön değiştirdi" % cross
            s = min(100, s + 6) if h > 0 else max(0, s - 6)
        parts.append((s, 1.2))
        why.append(t)
    k_s, d_s = stoch(df)
    kk, dd = _last(k_s), _last(d_s)
    if _ok(kk) and _ok(dd):
        if kk > 80:
            s, t = 48, "Stokastik %s — aşırı alım" % _f(kk, 0)
        elif kk < 20:
            s, t = 52, "Stokastik %s — aşırı satım" % _f(kk, 0)
        elif kk > dd:
            s, t = 82, "Stokastik %s, sinyalin üstünde" % _f(kk, 0)
        else:
            s, t = 28, "Stokastik %s, sinyalin altında" % _f(kk, 0)
        parts.append((s, 0.8))
        why.append(t)
    if not parts:
        return 50.0, ["Momentum için yeterli bar yok"]
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
        label = DIV_KINDS.get(d.get("kind"), ("Uyumsuzluk", ""))[0]
        if kind == "bull":
            bull += 0.55
        elif kind == "bear":
            bear += 0.55
        why.append("%s — RSI ile fiyat ayrışıyor" % label)
    if not pats and not fresh:
        return 50.0, ["Belirgin formasyon ya da uyumsuzluk yok"]
    net = (bull - bear) / max(1.0, bull + bear)
    return 50 + net * 46, why


def _g_volume(df):
    why, parts = [], []
    rv = _last(relvol(df, 20))
    up = _last(df["Close"].diff()) or 0.0
    if _ok(rv):
        if rv >= 1.5:
            s = 90 if up >= 0 else 14
            why.append("Hacim ortalamanın %sx üstünde ve bar %s" % (_f(rv, 1), "yükseliş" if up >= 0 else "düşüş"))
        elif rv >= 1.0:
            s = 68 if up >= 0 else 34
            why.append("Hacim ortalamanın hafif üstünde (%sx)" % _f(rv, 1))
        else:
            s = 44
            why.append("Hacim ortalamanın altında (%sx) — hareketin teyidi zayıf" % _f(rv, 1))
        parts.append((s, 1.2))
    m = _last(mfi(df, 14))
    if _ok(m):
        s = 88 if m >= 60 else 68 if m >= 50 else 34 if m >= 40 else 16
        parts.append((s, 1.0))
        why.append("Para akışı (MFI) %s" % _f(m, 0))
    o = obv(df)
    if len(o) > 25:
        ov = o.to_numpy(float)[-21:]
        sl = _slope(range(len(ov)), ov)
        base = abs(float(df["Volume"].tail(21).mean())) or 1.0
        rr = sl / base
        s = 86 if rr > 0.25 else 64 if rr > 0.02 else 36 if rr > -0.25 else 14
        parts.append((s, 0.9))
        why.append("OBV son 20 barda %s" % ("yükseliyor" if rr > 0.02 else "düşüyor" if rr < -0.02 else "yatay"))
    if not parts:
        return 50.0, ["Hacim verisi yok"]
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
        (levels_up if mid > px else levels_dn).append((mid, z.get("pct", 50), z.get("label", "bant")))
    for p in (50, 200):
        v = _last(sma(df["Close"], p))
        if _ok(v):
            (levels_up if v > px else levels_dn).append((v, 55, "SMA %d" % p))
    why, notes = [], []
    if not levels_up:
        hh = float(df["High"].tail(252).max())
        if hh > px * 1.004:
            levels_up.append((hh, 50, "52 haftalık zirve"))
            notes.append("Üstte pivot bandı kalmadı; hedef 52 haftalık zirve")
        else:
            levels_up.append((px + 2.5 * a, 50, "ATR hedefi"))
            notes.append("Fiyat zirvede, üstte engel yok — hedef 2,5×ATR")
    if not levels_dn:
        levels_dn.append((px - 2.0 * a, 50, "ATR stopu"))
        notes.append("Altta kayıtlı destek yok — stop 2×ATR")
    res = min(levels_up, key=lambda x: x[0])
    sup = max(levels_dn, key=lambda x: x[0])
    rew = max(0.0, (res[0] - px) / px * 100)
    raw_risk = max(0.0, (px - sup[0]) / px * 100)
    atr_pct = a / px * 100
    # Stop 0,5×ATR'den dar olamaz: gürültü stopu düşürmesin, R/R şişmesin
    risk = max(raw_risk, 0.5 * atr_pct)
    rr = min(10.0, rew / risk) if risk > 0.02 else 0.0
    why.append("Üstte %s %s (+%%%s), altta %s %s (−%%%s)"
               % (res[2], _f(res[0]), _f(rew, 1), sup[2], _f(sup[0]), _f(raw_risk, 1)))
    if risk > raw_risk + 0.01:
        notes.append("Destek %s%% uzakta; stop gürültüye takılmasın diye 0,5×ATR (%%%s) tabanına çekildi"
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
    why.append("Risk/ödül 1 : %s%s" % (_f(rr, 2), "+" if rr >= 10 else ""))
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
            why.append("Ortalamalar mükemmel dizilişte (20>50>100>200)")
        elif rev and len(have) >= 3:
            s = max(0, s - 12)
            why.append("Ortalamalar düşüş dizilişinde (20<50<100<200)")
        why.append("Fiyat %d/%d hareketli ortalamanın üstünde" % (above, len(have)))
        parts.append((s, 1.3))
    try:
        _, sd = supertrend(df, 10, 3.0)
        v = int(sd.iloc[-1])
        parts.append((84 if v > 0 else 16, 1.0))
        why.append("Supertrend %s" % ("yukarı" if v > 0 else "aşağı"))
    except Exception:
        pass
    ax, pdi, mdi = adx(df, 14)
    av = _last(ax)
    if _ok(av):
        why.append("ADX %s — trend %s" % (_f(av, 0), "güçlü" if av >= 25 else "zayıf/yatay"))
        if av < 18 and parts:
            parts = [(50 + (s - 50) * 0.55, w) for s, w in parts]
    if not parts:
        return 50.0, ["Trend için yeterli bar yok"]
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def _g_volat(df):
    close = df["Close"]
    px = float(close.iloc[-1])
    why, parts = [], []
    b = _last(boll_pctb(close, 20, 2.0))
    if _ok(b):
        if b > 1:
            s, t = 38, "Bollinger üst bandının dışında — aşırı uzama"
        elif b >= 0.55:
            s, t = 82, "Bollinger bandının üst yarısında (%%B %s)" % _f(b * 100, 0)
        elif b >= 0.45:
            s, t = 58, "Bollinger ortasında"
        elif b >= 0:
            s, t = 34, "Bollinger bandının alt yarısında (%%B %s)" % _f(b * 100, 0)
        else:
            s, t = 46, "Bollinger alt bandının dışında — tepki gelebilir"
        parts.append((s, 1.0))
        why.append(t)
    a = _last(atr(df, 14))
    s20 = _last(sma(close, 20))
    if _ok(a) and _ok(s20) and a > 0:
        ext = (px - s20) / a
        if abs(ext) > 3:
            parts.append((40 if ext > 0 else 50, 0.8))
            why.append("Fiyat 20 günlük ortalamadan %s ATR uzakta — geri çekilme olası" % _f(abs(ext), 1))
        else:
            parts.append((70 if ext > 0 else 46, 0.8))
    if len(df) > 60:
        lo, hi = float(df["Low"].tail(252).min()), float(df["High"].tail(252).max())
        if hi > lo:
            pos = (px - lo) / (hi - lo) * 100
            why.append("Son 1 yıllık aralığın %%%s seviyesinde" % _f(pos, 0))
            parts.append((min(100, max(0, pos * 0.8 + 10)), 0.7))
    if not parts:
        return 50.0, []
    tot = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / tot, why


def grade(df, zones=None, tf_name="günlük"):
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
        action, tone = "Güçlü Al", "bull"
    elif li <= 8:
        action, tone = "Al", "bull"
    elif li <= 11:
        action, tone = "Zayıf Al", "bull"
    elif li <= 14:
        action, tone = "Nötr", "flat"
    elif li <= 17:
        action, tone = "Zayıf Sat", "bear"
    elif li <= 22:
        action, tone = "Sat", "bear"
    else:
        action, tone = "Güçlü Sat", "bear"
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
    out.append("%s zaman diliminde %s puanla **%s** notu veriyorum — %s."
               % (tf_name.capitalize(), _f(score, 0), letter, action.lower()))
    mom, trend = gd["mom"], gd["trend"]
    lead = []
    if mom["reasons"]:
        lead.append(mom["reasons"][0])
    if trend["reasons"]:
        lead.append(trend["reasons"][-1] if len(trend["reasons"]) > 1 else trend["reasons"][0])
    if lead:
        out.append("Tabloyu kuran şey: " + "; ".join(lead) + ".")
    if gd["form"]["reasons"] and pats:
        bits = [p["name"].lower() + ((" (" + p["note"] + ")") if p.get("note") else "") for p in pats[:2]]
        out.append("Formasyon tarafında " + ", ".join(bits) + " görünüyor.")
    elif gd["form"]["reasons"]:
        out.append(gd["form"]["reasons"][0] + ".")
    if gd["vol"]["reasons"]:
        out.append(gd["vol"]["reasons"][0] + ".")
    if gd["rr"]["reasons"]:
        out.append(" ".join(r.rstrip(".") + "." for r in gd["rr"]["reasons"][:2]))
    out.append("En güçlü taraf %s (%s/100), en zayıf taraf %s (%s/100). Son fiyat %s."
               % (top["name"].lower(), _f(top["score"], 0), bot["name"].lower(), _f(bot["score"], 0), _f(px)))
    if gd["volat"]["reasons"]:
        out.append("Risk notu: " + gd["volat"]["reasons"][0] + ".")
    return " ".join(out)


# ======================================================================
# v3.2 — Kurulum formasyonları (günlük): üçgen · dikdörtgen · merdiven · kırılım
#   Hepsi pivot noktaları üzerinden çalışır; her biri kırılacak SEVİYEYİ döndürür,
#   böylece 15 dakikalık teyit ve stop/hedef planı aynı seviyeyi kullanabilir.
# ======================================================================
SETUP_NAMES = {"triangle_sym": "Simetrik üçgen", "triangle_asc": "Yükselen üçgen",
               "triangle_desc": "Alçalan üçgen", "rectangle": "Dikdörtgen (yatay kanal)",
               "ladder": "Merdiven (yükselen zirve/dip)", "breakout": "Kırılım",
               "breakdown": "Aşağı kırılım"}


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
                            "note": "bant %s%% daraldı" % fmt_num((1 - w1 / w0) * 100, 0)})

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
                        "note": "%s – %s bandı, yükseklik %%%s"
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
                        "note": "üç basamakta %%%s" % fmt_num(abs(legs), 1)})

    # ---------------- 4) KIRILIM ----------------------------------------------
    # N barlık zirvenin ATR payıyla üstünde kapanış + hacim teyidi + güçlü kapanış yeri.
    for N, tag in ((20, "20 günlük"), (55, "55 günlük")):
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
            out.append({"key": "breakout", "name": "%s zirve kırılımı" % tag, "kind": "bull",
                        "level": prior_h, "lower": prior_l, "state": "breakout",
                        "bars_since": int(since), "conf": round(min(1.0, max(0.15, conf)), 2),
                        "vol_x": round(vx, 2), "start": int(n - N - 1) + (len(df) - n),
                        "note": "%s zirvesi %s aşıldı · hacim %sx%s"
                                % (tag, fmt_num(prior_h, 2), fmt_num(vx, 1),
                                   " · dar sıkışmadan" if rng10 <= 4.5 else "")})
            break
        if px < prior_l - 0.25 * a:
            out.append({"key": "breakdown", "name": "%s dip kırılımı" % tag, "kind": "bear",
                        "level": prior_l, "lower": prior_h, "state": "breakout", "bars_since": 0,
                        "conf": 0.55, "vol_x": round(vx, 2), "start": int(n - N - 1) + (len(df) - n),
                        "note": "%s dibi %s kırıldı" % (tag, fmt_num(prior_l, 2))})
            break

    out.sort(key=lambda p: (-(p["state"] == "breakout"), -p["conf"]))
    return out[:int(limit)]


def confirm_15m(df15, level, kind="bull", vol_n=20, window=26):
    """Günlük kırılımın 15 dakikalık grafikte tutup tutmadığı.
    teyitli = seviyenin üstünde + hacimli kesiş + EMA9>EMA21 · bekleniyor = zayıf · bozuldu = altına döndü."""
    out = {"state": "veri yok", "ok": False, "vol_x": None, "bars_since": None,
           "note": "15 dakikalık veri alınamadı", "last": None}
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
        out["state"] = "bozuldu"
        out["note"] = "15dk fiyat %s seviyesinin %s döndü" % (fmt_num(level, 2),
                                                              "altına" if kind == "bull" else "üstüne")
        return out
    if strong and aligned:
        out["state"], out["ok"] = "teyitli", True
        out["note"] = "15dk %s üstünde tutuyor · hacim %sx · EMA9>EMA21" \
            % (fmt_num(level, 2), fmt_num(out["vol_x"] or 1, 1))
    else:
        out["state"] = "bekleniyor"
        eksik = []
        if not strong:
            eksik.append("hacim zayıf")
        if not aligned:
            eksik.append("EMA dizilimi henüz dönmedi")
        out["note"] = "15dk seviyenin üstünde ama " + " ve ".join(eksik)
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
        cands = [("son günlük mum", last_low - 0.08 * a)]
        if sup:
            cands.append(("destek bandı", float(sup[0]["lo"]) - 0.08 * a))
        if level is not None and _ok(level):
            cands.append(("kırılım seviyesi", float(level) - 0.5 * a))
        name, stop = min(cands, key=lambda x: x[1])
        if px - stop > 3.2 * a:                       # çok geniş stop → ATR'ye çek
            name, stop = "2×ATR (bantlar çok uzak)", px - 2.0 * a
        risk = max(px - stop, 0.15 * a)
        t1_src = "direnç bandı"
        tp1 = float(res[0]["lo"]) if res else px + 2.0 * risk
        if not res:
            t1_src = "2R hedefi"
        if tp1 <= px + 0.35 * risk:                   # bant çok yakınsa bir sonrakine geç
            if len(res) > 1:
                tp1 = float(res[1]["lo"])
            else:
                tp1, t1_src = px + 2.0 * risk, "2R hedefi"
        t2_src = "üstteki ikinci bant"
        nxt = [z for z in res if float(z["lo"]) > tp1 * 1.001]
        tp2 = float(nxt[0]["lo"]) if nxt else px + 3.5 * risk
        if not nxt:
            t2_src = "3,5R hedefi"
    else:
        cands = [("son günlük mum", last_high + 0.08 * a)]
        if res:
            cands.append(("direnç bandı", float(res[0]["hi"]) + 0.08 * a))
        name, stop = max(cands, key=lambda x: x[1])
        if stop - px > 3.2 * a:
            name, stop = "2×ATR (bantlar çok uzak)", px + 2.0 * a
        risk = max(stop - px, 0.15 * a)
        tp1 = float(sup[0]["hi"]) if sup else px - 2.0 * risk
        t1_src = "destek bandı" if sup else "2R hedefi"
        nxt = [z for z in sup if float(z["hi"]) < tp1 * 0.999]
        tp2 = float(nxt[0]["hi"]) if nxt else px - 3.5 * risk
        t2_src = "alttaki ikinci bant" if nxt else "3,5R hedefi"
    rr1 = abs(tp1 - px) / risk if risk > 0 else 0.0
    rr2 = abs(tp2 - px) / risk if risk > 0 else 0.0
    part = float(min(0.9, max(0.1, tp1_part)))
    return {"entry": round(px, 4), "stop": round(stop, 4), "tp1": round(tp1, 4), "tp2": round(tp2, 4),
            "risk": round(risk, 4), "risk_pct": round(risk / px * 100, 2),
            "rr1": round(rr1, 2), "rr2": round(rr2, 2), "atr": round(float(a), 4),
            "stop_src": name, "tp1_src": t1_src, "tp2_src": t2_src,
            "part1": part, "part2": round(1 - part, 2),
            "rule": ("TP1'de %%%d sat, kalan %%%d trendi takip etsin; TP1 görüldükten sonra "
                     "kalanın stopu TP1 (%s) seviyesine çekilir."
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
AI_C15_PTS = {"teyitli": 20.0, "bekleniyor": 8.0, "veri yok": 6.0, "bozuldu": 0.0}


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
    steps = {"evren": 0, "fiyat": 0, "degisim": 0, "piyasa_degeri": 0, "capless": True}
    if snap is None or len(snap) == 0:
        return snap, steps
    capless = bool((getattr(snap, "attrs", None) or {}).get("capless"))
    d = snap.copy()
    steps["evren"] = len(d)
    d = d[d["last"].astype(float) >= c["min_price"]]
    steps["fiyat"] = len(d)
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
    return bool(r.get("ema_ok")) and bool(c15 and c15.get("state") in ("teyitli", "bekleniyor"))


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
        durum = {"breakout": "kırılım gerçekleşti", "retest": "seviyeyi geri test ediyor",
                 "forming": "henüz oluşuyor"}.get(b["state"], b["state"])
        bits.append("%s — %s (%s)" % (b["name"], durum, b["note"]))
    else:
        bits.append("Net bir formasyon yok, yalnızca trend ve hacim şartlarını geçti")
    if c:
        bits.append("15 dakikalık teyit: %s — %s" % (c["state"], c["note"]))
    if p:
        bits.append("Giriş %s · stop %s (%s, −%%%s) · TP1 %s (%s, R/R 1:%s)"
                    % (fmt_num(p["entry"], 2), fmt_num(p["stop"], 2), p["stop_src"],
                       fmt_num(p["risk_pct"], 1), fmt_num(p["tp1"], 2), p["tp1_src"],
                       fmt_num(p["rr1"], 2)))
        bits.append(p["rule"])
    return " ".join(bits)
