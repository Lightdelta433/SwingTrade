"""
========================================================================
 VERİ KATMANI  (mock_data.py)
========================================================================
Şu an her şey SAHTE (mock) veri üretir. İleride gerçek veriye geçerken
SADECE bu dosyayı değiştirmen yeterli — app.py'ye dokunmana gerek yok.

Gerçek veriye geçiş için öneri:
  - get_index_summary()      -> yfinance / bir fiyat API'si
  - get_ohlc(ticker)         -> yfinance.download(ticker) (OHLCV döndür)
  - get_filtered_companies() -> kendi swing-trade filtrenin çıktısı
  - get_strategy_picks()     -> teknik analiz motorunun çıktısı
  - get_value_stocks()       -> fundamental veri (PEG, Fwd PE, Margin, EPS)

Fonksiyonların DÖNÜŞ FORMATLARINI koru; app.py bu formatlara göre çizer.
========================================================================
"""

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Şirket evreni — ticker -> isim / logo domaini / sektör
# (logo için Clearbit kullanılıyor: https://logo.clearbit.com/<domain>)
# ----------------------------------------------------------------------
COMPANIES = {
    "AAPL":  {"name": "Apple",            "domain": "apple.com",       "sector": "Technology"},
    "MSFT":  {"name": "Microsoft",        "domain": "microsoft.com",   "sector": "Technology"},
    "NVDA":  {"name": "NVIDIA",           "domain": "nvidia.com",      "sector": "Semiconductors"},
    "AMZN":  {"name": "Amazon",           "domain": "amazon.com",      "sector": "Consumer"},
    "GOOGL": {"name": "Alphabet",         "domain": "google.com",      "sector": "Technology"},
    "META":  {"name": "Meta Platforms",   "domain": "meta.com",        "sector": "Technology"},
    "TSLA":  {"name": "Tesla",            "domain": "tesla.com",       "sector": "Automotive"},
    "AMD":   {"name": "AMD",              "domain": "amd.com",         "sector": "Semiconductors"},
    "NFLX":  {"name": "Netflix",          "domain": "netflix.com",     "sector": "Communication"},
    "CRM":   {"name": "Salesforce",       "domain": "salesforce.com",  "sector": "Software"},
    "ADBE":  {"name": "Adobe",            "domain": "adobe.com",       "sector": "Software"},
    "AVGO":  {"name": "Broadcom",         "domain": "broadcom.com",    "sector": "Semiconductors"},
    "COST":  {"name": "Costco",           "domain": "costco.com",      "sector": "Retail"},
    "PEP":   {"name": "PepsiCo",          "domain": "pepsico.com",     "sector": "Consumer Staples"},
    "SHOP":  {"name": "Shopify",          "domain": "shopify.com",     "sector": "Software"},
    "UBER":  {"name": "Uber",             "domain": "uber.com",        "sector": "Technology"},
    "PLTR":  {"name": "Palantir",         "domain": "palantir.com",    "sector": "Software"},
    "SOFI":  {"name": "SoFi",             "domain": "sofi.com",        "sector": "Fintech"},
    "COIN":  {"name": "Coinbase",         "domain": "coinbase.com",    "sector": "Fintech"},
    "SNOW":  {"name": "Snowflake",        "domain": "snowflake.com",   "sector": "Software"},
}


def logo_url(ticker: str) -> str:
    """Ticker için logo URL'i. İnternet yoksa görseller kırık görünür;
    o durumda local dosya yolu döndürecek şekilde burayı değiştir."""
    domain = COMPANIES.get(ticker, {}).get("domain", "")
    return f"https://logo.clearbit.com/{domain}" if domain else ""


def _seed(ticker: str) -> int:
    """Ticker'a göre sabit tohum — her yüklemede aynı grafik çıksın diye."""
    return sum(ord(c) for c in ticker) + 7


# ----------------------------------------------------------------------
# OHLC (candlestick) üretici — rastgele yürüyüş ile gerçekçi mum verisi
# ----------------------------------------------------------------------
def get_ohlc(ticker: str, days: int = 180) -> pd.DataFrame:
    """Date index + Open/High/Low/Close/Volume kolonlu DataFrame döndürür.
    Gerçek veride: yfinance.download(ticker, period='6mo') çıktısını aynı
    kolon isimleriyle döndürmen yeterli."""
    rng = np.random.default_rng(_seed(ticker))
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)

    start = rng.uniform(40, 420)
    drift = rng.uniform(-0.0002, 0.0009)
    rets = rng.normal(drift, 0.018, days)
    close = start * np.cumprod(1 + rets)

    open_ = close * (1 + rng.normal(0, 0.004, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, days)))
    volume = rng.integers(2_000_000, 45_000_000, days)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    df.index.name = "Date"
    return df


def add_emas(df: pd.DataFrame, periods=(20, 50, 100, 200)) -> pd.DataFrame:
    """DataFrame'e EMA20/50/100/200 kolonları ekler."""
    out = df.copy()
    for p in periods:
        out[f"EMA{p}"] = out["Close"].ewm(span=p, adjust=False).mean()
    return out


# ----------------------------------------------------------------------
# Ranked Support / Resistance zones
# ----------------------------------------------------------------------
def get_sr_zones(df: pd.DataFrame, n: int = 3) -> list[dict]:
    """Fiyat aralığından n adet S/R bandı. rank=1 en güçlü.
    Gerçek veride: swing high/low kümeleme veya hacim profili ile üret."""
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    rng = np.random.default_rng(_seed(df.index.name or "x") + len(df))
    centers = np.sort(rng.uniform(lo + (hi - lo) * 0.15, hi - (hi - lo) * 0.15, n))
    band = (hi - lo) * 0.012
    zones = []
    for rank, c in enumerate(sorted(centers, key=lambda _: rng.random()), start=1):
        zones.append({"low": c - band, "high": c + band, "rank": rank})
    return zones


# ----------------------------------------------------------------------
# Formasyonlar (trendline / bull flag / triangle) — çizim için nokta seti
# ----------------------------------------------------------------------
def get_formation(df: pd.DataFrame, ftype: str) -> dict:
    """Formasyon tipi + çizilecek çizgiler (tarih, fiyat) döndürür.
    Gerçek veride: pattern-recognition çıktını bu formata çevir."""
    tail = df.tail(45)
    x0, x1 = tail.index[0], tail.index[-1]
    hi0, hi1 = float(tail["High"].iloc[:10].max()), float(tail["High"].iloc[-10:].max())
    lo0, lo1 = float(tail["Low"].iloc[:10].min()), float(tail["Low"].iloc[-10:].min())

    if ftype == "Triangle":
        lines = [((x0, hi0), (x1, min(hi0, hi1))),   # üst direnç (düşen)
                 ((x0, lo0), (x1, max(lo0, lo1)))]    # alt destek (yükselen)
    elif ftype == "Bull Flag":
        mid = tail.index[len(tail) // 2]
        lines = [((x0, lo0), (mid, hi1)),             # bayrak direği
                 ((mid, hi1), (x1, hi1 * 0.985)),      # bayrak üst
                 ((mid, lo1 * 1.01), (x1, lo1))]       # bayrak alt
    else:  # Trendline
        lines = [((x0, lo0), (x1, lo1))]
    return {"type": ftype, "lines": lines}


# ----------------------------------------------------------------------
# Endeks özeti (üst bölüm)
# ----------------------------------------------------------------------
def get_index_summary() -> list[dict]:
    """S&P 500 / Nasdaq / Dow Jones için günlük özet + mini seri.
    Gerçek veride: her endeks için günlük fiyatı ve intraday seriyi çek."""
    specs = [
        ("S&P 500",   "^GSPC", 5540.0),
        ("Nasdaq",    "^IXIC", 18200.0),
        ("Dow Jones", "^DJI",  41300.0),
    ]
    out = []
    for name, sym, base in specs:
        rng = np.random.default_rng(_seed(sym))
        steps = rng.normal(0, 0.0012, 78)           # ~günlük intraday
        series = base * np.cumprod(1 + steps)
        last = float(series[-1])
        change_pct = (last / base - 1) * 100
        out.append({
            "name": name,
            "symbol": sym,
            "last": last,
            "change_pct": change_pct,
            "series": series.tolist(),
        })
    return out


# ----------------------------------------------------------------------
# Filtrene uyan 20 şirket
# ----------------------------------------------------------------------
def get_filtered_companies() -> list[str]:
    """O gün swing-trade filtrene uyan tickerlar.
    Gerçek veride: filtre motorunun döndürdüğü ticker listesi."""
    return list(COMPANIES.keys())[:20]


# ----------------------------------------------------------------------
# Trading Strategy Picks (filtredekilerin bir kısmı, TA'ya göre)
# ----------------------------------------------------------------------
def get_strategy_picks() -> list[dict]:
    """Her pick: ticker, setup, formasyon tipi + hesaplanmış seviyeler.
    Gerçek veride: TA motorundan gelen sinyalleri bu formata çevir."""
    picks_spec = [
        ("NVDA", "Breakout retest", "Bull Flag"),
        ("AMD",  "Trend continuation", "Triangle"),
        ("SHOP", "Flag breakout", "Bull Flag"),
        ("PLTR", "Ascending triangle", "Triangle"),
        ("UBER", "Pullback to EMA", "Trendline"),
        ("COIN", "Momentum", "Triangle"),
    ]
    picks = []
    for ticker, setup, ftype in picks_spec:
        df = add_emas(get_ohlc(ticker))
        last = float(df["Close"].iloc[-1])
        atr = float((df["High"] - df["Low"]).tail(14).mean())
        picks.append({
            "ticker": ticker,
            "name": COMPANIES[ticker]["name"],
            "setup": setup,
            "formation": ftype,
            "last": last,
            "buy_zone": (round(last - atr * 0.6, 2), round(last + atr * 0.2, 2)),
            "stop": round(last - atr * 1.8, 2),
            "target": round(last + atr * 3.0, 2),
            "rr": round(3.0 / 1.8, 2),
            "avg_volume": int(df["Volume"].tail(20).mean()),
            "rel_volume": round(float(df["Volume"].iloc[-1] / df["Volume"].tail(20).mean()), 2),
        })
    return picks


# ----------------------------------------------------------------------
# Long-term ucuz şirketler (en alt tablo)
# ----------------------------------------------------------------------
def get_value_stocks() -> pd.DataFrame:
    """Kolonlar: Ticker, PEG, Forward PE, Profit Margin %, EPS Next 5Y %.
    Gerçek veride: fundamental veri sağlayıcından çek, aynı kolonlarla döndür."""
    rows = [
        ("GOOGL", 1.1, 18.4, 27.0, 14.5),
        ("META",  0.9, 20.1, 33.2, 16.0),
        ("PEP",   1.4, 16.8, 10.1,  7.2),
        ("COST",  2.0, 34.5,  2.8, 11.0),
        ("AMZN",  1.3, 28.9,  7.4, 22.3),
        ("CRM",   1.0, 22.0, 15.6, 18.9),
        ("AVGO",  1.2, 24.3, 21.9, 19.5),
        ("UBER",  0.8, 21.5,  6.2, 30.1),
        ("SOFI",  0.7, 19.0,  8.9, 28.4),
        ("ADBE",  1.1, 19.9, 28.5, 13.8),
    ]
    df = pd.DataFrame(rows, columns=["Ticker", "PEG", "Forward PE", "Profit Margin %", "EPS Next 5Y %"])
    return df.sort_values("Forward PE").reset_index(drop=True)
