"""
========================================================================
 VERİ KATMANI  (mock_data.py)
========================================================================
Şu an her şey SAHTE (mock) veri üretir. İleride gerçek veriye geçerken
SADECE bu dosyayı değiştirmen yeterli — app.py'ye dokunmana gerek yok.

Gerçek veriye geçiş için öneri:
  - get_index_summary()      -> yfinance / bir fiyat API'si
  - get_ohlc(ticker)         -> yfinance.download(ticker) (OHLCV döndür)
  - get_company_detail(t)    -> fundamental + anlık fiyat verisi
  - get_filtered_companies() -> kendi swing-trade filtrenin çıktısı
  - get_strategy_picks()     -> teknik analiz motorunun çıktısı
  - get_value_stocks()       -> fundamental veri (PEG, Fwd PE, Margin, EPS)

Fonksiyonların DÖNÜŞ FORMATLARINI koru; app.py bu formatlara göre çizer.
========================================================================
"""

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Şirket evreni — ticker -> isim / logo domaini / sektör / kısa tanım
# (logo için Clearbit: https://logo.clearbit.com/<domain>)
# ----------------------------------------------------------------------
COMPANIES = {
    "AAPL":  {"name": "Apple",          "domain": "apple.com",      "sector": "Technology",
              "desc": "iPhone, Mac ve servislerden oluşan donanım-yazılım ekosistemiyle dünyanın en değerli tüketici teknolojisi şirketlerinden biri."},
    "MSFT":  {"name": "Microsoft",      "domain": "microsoft.com",  "sector": "Technology",
              "desc": "Windows, Office ve Azure bulut platformuyla kurumsal yazılım ve bulut altyapısında lider."},
    "NVDA":  {"name": "NVIDIA",         "domain": "nvidia.com",     "sector": "Semiconductors",
              "desc": "Yapay zeka ve veri merkezi GPU'larında baskın oyuncu; hızlandırılmış hesaplamanın merkezinde."},
    "AMZN":  {"name": "Amazon",         "domain": "amazon.com",     "sector": "Consumer",
              "desc": "E-ticaret devi ve AWS ile dünyanın en büyük bulut servis sağlayıcısı."},
    "GOOGL": {"name": "Alphabet",       "domain": "google.com",     "sector": "Technology",
              "desc": "Google arama, reklam, YouTube ve bulut; ayrıca yapay zeka araştırmalarında öncü."},
    "META":  {"name": "Meta Platforms", "domain": "meta.com",       "sector": "Technology",
              "desc": "Facebook, Instagram ve WhatsApp'ı işleten sosyal medya ve dijital reklam devi."},
    "TSLA":  {"name": "Tesla",          "domain": "tesla.com",      "sector": "Automotive",
              "desc": "Elektrikli araç üreticisi; enerji depolama ve otonom sürüş alanlarında da faaliyette."},
    "AMD":   {"name": "AMD",            "domain": "amd.com",        "sector": "Semiconductors",
              "desc": "CPU ve GPU üreticisi; veri merkezi ve PC pazarında Intel ve NVIDIA'nın başlıca rakibi."},
    "NFLX":  {"name": "Netflix",        "domain": "netflix.com",    "sector": "Communication",
              "desc": "Dünya çapında abonelik tabanlı video akış platformu ve içerik üreticisi."},
    "CRM":   {"name": "Salesforce",     "domain": "salesforce.com", "sector": "Software",
              "desc": "Bulut tabanlı müşteri ilişkileri yönetimi (CRM) yazılımında pazar lideri."},
    "ADBE":  {"name": "Adobe",          "domain": "adobe.com",      "sector": "Software",
              "desc": "Photoshop, Acrobat ve yaratıcı bulut araçlarıyla dijital medya yazılımı lideri."},
    "AVGO":  {"name": "Broadcom",       "domain": "broadcom.com",   "sector": "Semiconductors",
              "desc": "Ağ, kablosuz ve altyapı çipleriyle kurumsal yazılım alanında genişleyen yarı iletken devi."},
    "COST":  {"name": "Costco",         "domain": "costco.com",     "sector": "Retail",
              "desc": "Üyelik tabanlı toptan perakende zinciri; istikrarlı gelir ve güçlü müşteri sadakati."},
    "PEP":   {"name": "PepsiCo",        "domain": "pepsico.com",    "sector": "Consumer Staples",
              "desc": "İçecek ve atıştırmalık devi; Pepsi, Lay's ve Gatorade gibi küresel markalara sahip."},
    "SHOP":  {"name": "Shopify",        "domain": "shopify.com",    "sector": "Software",
              "desc": "KOBİ'ler için e-ticaret altyapısı sağlayan bulut tabanlı ticaret platformu."},
    "UBER":  {"name": "Uber",           "domain": "uber.com",       "sector": "Technology",
              "desc": "Yolculuk paylaşımı ve yemek teslimatında küresel pazar lideri platform."},
    "PLTR":  {"name": "Palantir",       "domain": "palantir.com",   "sector": "Software",
              "desc": "Devlet ve kurumlar için büyük veri analitiği ve yapay zeka yazılım platformları."},
    "SOFI":  {"name": "SoFi",           "domain": "sofi.com",       "sector": "Fintech",
              "desc": "Kredi, yatırım ve bankacılığı tek uygulamada birleştiren dijital finans platformu."},
    "COIN":  {"name": "Coinbase",       "domain": "coinbase.com",   "sector": "Fintech",
              "desc": "ABD merkezli en büyük kripto para borsalarından biri; perakende ve kurumsal işlem."},
    "SNOW":  {"name": "Snowflake",      "domain": "snowflake.com",  "sector": "Software",
              "desc": "Bulut tabanlı veri ambarı ve veri analitiği platformu; kullandıkça öde modeli."},
    # Endeks ETF'leri — Märkte kartlarına tıklayınca aynı detay sayfasını kullanabilmek için
    "SPY":   {"name": "SPDR S&P 500 ETF",         "domain": "ssga.com",    "sector": "Index ETF",
              "desc": "S&P 500 endeksini takip eden en büyük ve en likit borsa yatırım fonu (ETF); ABD'nin en büyük 500 halka açık şirketini kapsar."},
    "QQQ":   {"name": "Invesco QQQ Trust",         "domain": "invesco.com","sector": "Index ETF",
              "desc": "Nasdaq-100 endeksini takip eden ETF; ağırlıklı olarak teknoloji ve büyüme odaklı şirketlerden oluşur."},
    "DIA":   {"name": "SPDR Dow Jones Industrial Average ETF", "domain": "ssga.com", "sector": "Index ETF",
              "desc": "Dow Jones Endüstri Ortalaması'nı takip eden ETF; 30 büyük ve köklü ABD şirketini fiyat ağırlıklı olarak izler."},
    "IWM":   {"name": "iShares Russell 2000 ETF",  "domain": "ishares.com","sector": "Index ETF",
              "desc": "Russell 2000 endeksini takip eden ETF; ABD'li küçük ölçekli (small-cap) şirketleri kapsar."},
}

# Endeks ETF'leri için gerçekçi başlangıç fiyatı (genel 40-420 aralığındaki rastgele
# başlangıç yerine). get_index_summary()'deki prev_close değerleriyle aynı seviyede
# tutuluyor ki Märkte kartındaki fiyat ile detay sayfasındaki grafik birbirini tutsun.
_BASE_PRICE_OVERRIDE = {"SPY": 560.0, "QQQ": 485.0, "DIA": 421.0, "IWM": 228.0}


def logo_url(ticker: str) -> str:
    """Ticker için logo URL'i. İnternet yoksa görseller kırık görünür;
    o durumda local dosya yolu döndürecek şekilde burayı değiştir."""
    domain = COMPANIES.get(ticker, {}).get("domain", "")
    return f"https://logo.clearbit.com/{domain}" if domain else ""


def _seed(ticker: str) -> int:
    """Ticker'a göre sabit tohum — her yüklemede aynı grafik çıksın diye."""
    return sum(ord(c) for c in ticker) + 7


# ----------------------------------------------------------------------
# OHLC (candlestick) üretici
# Tek bir uzun geçmiş (~5 yıl) üretilir ve istenen kadarı (tail) döndürülür.
# Böylece dashboard'daki kısa grafik ile detaydaki uzun grafik TUTARLI olur.
# ----------------------------------------------------------------------
_FULL_DAYS = 1300  # ~5 iş yılı

_full_cache: dict[str, pd.DataFrame] = {}


def _full_ohlc(ticker: str) -> pd.DataFrame:
    if ticker in _full_cache:
        return _full_cache[ticker]
    rng = np.random.default_rng(_seed(ticker))
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=_FULL_DAYS)

    start = _BASE_PRICE_OVERRIDE.get(ticker, rng.uniform(40, 420))
    drift = rng.uniform(-0.0001, 0.0007)
    rets = rng.normal(drift, 0.018, _FULL_DAYS)
    close = start * np.cumprod(1 + rets)

    open_ = close * (1 + rng.normal(0, 0.004, _FULL_DAYS))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, _FULL_DAYS)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, _FULL_DAYS)))
    volume = rng.integers(2_000_000, 45_000_000, _FULL_DAYS)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    df.index.name = "Date"
    _full_cache[ticker] = df
    return df


def get_ohlc(ticker: str, days: int = 180) -> pd.DataFrame:
    """Date index + Open/High/Low/Close/Volume kolonlu DataFrame döndürür.
    Gerçek veride: yfinance.download(ticker, period=...) çıktısını aynı
    kolon isimleriyle döndürmen yeterli."""
    full = _full_ohlc(ticker)
    return full.tail(days).copy()


def add_emas(df: pd.DataFrame, periods=(20, 50, 100, 200)) -> pd.DataFrame:
    """DataFrame'e EMA20/50/100/200 kolonları ekler.
    EMA'lar verilen df üzerinde hesaplanır; uzun geçmişle çağırıp sonra
    kısaltırsan EMA200 baştan itibaren doğru olur."""
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
# Endeks / ETF özeti (üst bölüm) — SPY / QQQ / DIA / IWM
# ----------------------------------------------------------------------
def get_index_summary() -> list[dict]:
    """Her kart için: ticker, subtitle, prev_close, last, change_pct, intraday seri.
    Gerçek veride: her ETF için günlük fiyatı ve intraday seriyi çek,
    prev_close olarak bir önceki kapanışı ver (grafikteki kesikli çizgi için)."""
    specs = [
        ("SPY", "S&P 500",      560.0),
        ("QQQ", "Nasdaq 100",   485.0),
        ("DIA", "Dow Jones",    421.0),
        ("IWM", "Russell 2000", 228.0),
    ]
    out = []
    for ticker, subtitle, prev_close in specs:
        rng = np.random.default_rng(_seed(ticker))
        steps = rng.normal(0, 0.0013, 78)           # ~intraday
        series = prev_close * np.cumprod(1 + steps)
        last = float(series[-1])
        change_pct = (last / prev_close - 1) * 100
        out.append({
            "ticker": ticker,
            "subtitle": subtitle,
            "prev_close": prev_close,
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
# Şirket detayı (ticker'a tıklayınca açılan sayfa) — fundamental + fiyat
# ----------------------------------------------------------------------
def get_company_detail(ticker: str) -> dict:
    """Detay sayfasındaki sol taraftaki tüm veriler + şirket tanımı.
    Gerçek veride: fiyatı canlı feed'den, fundamentalleri veri
    sağlayıcıdan çek; aynı anahtarlarla döndür."""
    info = COMPANIES[ticker]
    df = _full_ohlc(ticker)
    last = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    day = df.iloc[-1]
    y1 = df.tail(252)

    rng = np.random.default_rng(_seed(ticker) + 99)
    shares_out = rng.uniform(0.2, 16.0)            # milyar adet
    market_cap = last * shares_out * 1e9           # $
    pe = float(rng.uniform(9, 42))
    eps = last / pe
    fwd_pe = pe * float(rng.uniform(0.82, 0.98))
    revenue = market_cap * float(rng.uniform(0.08, 0.6))
    net_income = revenue * float(rng.uniform(0.05, 0.34))
    beta = float(rng.uniform(0.55, 1.9))
    has_div = bool(rng.random() < 0.55)
    div_amt = float(rng.uniform(0.4, 3.2)) if has_div else 0.0
    div_yield = (div_amt / last * 100) if has_div else 0.0
    rating = str(rng.choice(["Strong Buy", "Buy", "Hold"], p=[0.4, 0.4, 0.2]))
    price_target = last * (1 + float(rng.uniform(0.05, 0.30)))

    today = pd.Timestamp.today().normalize()
    earnings = today + pd.Timedelta(days=int(rng.integers(5, 70)))
    ex_div = today - pd.Timedelta(days=int(rng.integers(5, 60))) if has_div else None

    return {
        "ticker": ticker,
        "name": info["name"],
        "sector": info["sector"],
        "desc": info["desc"],
        "last": last,
        "prev_close": prev_close,
        "change_abs": last - prev_close,
        "change_pct": (last / prev_close - 1) * 100,
        "market_cap": market_cap,
        "revenue": revenue,
        "net_income": net_income,
        "eps": eps,
        "shares_out": shares_out * 1e9,
        "pe": pe,
        "fwd_pe": fwd_pe,
        "dividend": div_amt,
        "div_yield": div_yield,
        "ex_div_date": ex_div,
        "volume": int(day["Volume"]),
        "open": float(day["Open"]),
        "day_low": float(day["Low"]),
        "day_high": float(day["High"]),
        "low_52w": float(y1["Low"].min()),
        "high_52w": float(y1["High"].max()),
        "beta": beta,
        "analysts": rating,
        "price_target": price_target,
        "target_upside": (price_target / last - 1) * 100,
        "earnings_date": earnings,
    }


# ----------------------------------------------------------------------
# Şirket haberleri (detay sayfasında grafiğin altında gösterilir)
# ----------------------------------------------------------------------
_NEWS_TEMPLATES = [
    ("{name} için analistler fiyat hedefini yükseltti", "Reuters", "Positive"),
    ("{name} çeyreklik kazançları piyasa beklentilerini aştı", "Bloomberg", "Positive"),
    ("{name} yeni ürün/hizmet lansmanını duyurdu", "TechCrunch", "Positive"),
    ("{name} hissesinde kâr realizasyonu satışı görüldü", "MarketWatch", "Negative"),
    ("{name}, tedarik zinciri maliyetleri konusunda uyardı", "CNBC", "Negative"),
    ("{name} CEO'su büyüme stratejisini yatırımcılara anlattı", "Yahoo Finance", "Neutral"),
    ("{name} hisseleri sektör ortalamasının üzerinde performans gösterdi", "Seeking Alpha", "Positive"),
    ("{name} hisse geri alım programını genişletti", "Reuters", "Positive"),
    ("{name} düzenleyici inceleme haberiyle baskı altında", "Bloomberg", "Negative"),
    ("{name} yapay zeka / Ar-Ge yatırımlarını artıracağını açıkladı", "CNBC", "Neutral"),
    ("Kurumsal yatırımcılar {name} payını artırdı", "Barron's", "Positive"),
    ("{name} için \"Hold\" notu korundu, hedef fiyat sabit", "Morningstar", "Neutral"),
]


def get_company_news(ticker: str, n: int = 6) -> list[dict]:
    """Detay sayfasında grafiğin altında gösterilecek haber listesi.
    Her haber: title, source, when (göreli zaman), sentiment (Positive/Negative/Neutral).
    Gerçek veride: bir haber API'sinden (NewsAPI, Finnhub vb.) çekip aynı
    anahtarlarla döndür — en yeni haber listenin başında olacak şekilde sırala."""
    rng = np.random.default_rng(_seed(ticker) + 555)
    name = COMPANIES[ticker]["name"]
    n = min(n, len(_NEWS_TEMPLATES))
    idxs = rng.choice(len(_NEWS_TEMPLATES), size=n, replace=False)
    hours_ago = sorted(int(h) for h in rng.integers(1, 96, size=n))
    news = []
    for idx, hours in zip(idxs, hours_ago):
        title_t, source, sentiment = _NEWS_TEMPLATES[idx]
        when = f"{hours} saat önce" if hours < 24 else f"{hours // 24} gün önce"
        news.append({"ticker": ticker, "title": title_t.format(name=name), "source": source,
                     "when": when, "hours_ago": int(hours), "sentiment": sentiment})
    return news


def get_watchlist_news(tickers: list[str], per_ticker: int = 3) -> list[dict]:
    """Watchlist'teki şirketlerin haberlerini birleştirip en yeniden eskiye sıralar.
    Her haberde ayrıca 'ticker' alanı var ki hangi şirkete ait görülebilsin."""
    all_news = []
    for t in tickers:
        all_news.extend(get_company_news(t, n=per_ticker))
    all_news.sort(key=lambda x: x["hours_ago"])
    return all_news


# ----------------------------------------------------------------------
# Trading Strategy Picks (filtredekilerin bir kısmı, TA'ya göre)
# ----------------------------------------------------------------------
def get_strategy_picks() -> list[dict]:
    """Her pick: ticker, setup, formasyon tipi + hesaplanmış seviyeler + kısa not.
    Gerçek veride: TA motorundan gelen sinyalleri bu formata çevir."""
    picks_spec = [
        ("NVDA", "Breakout retest",   "Bull Flag",
         "EMA20 üzerinde sıkışan fiyat, 50 günlük ortalamaya yapılan geri çekilmenin ardından "
         "bayrak formasyonunu yukarı kırdı. Hacim teyidiyle momentum devam edebilir; kırılım "
         "bölgesine geri test alım fırsatı sunuyor."),
        ("AMD",  "Trend continuation", "Triangle",
         "Yükselen tabanlar ve yatay direnç bir simetrik üçgen oluşturuyor. Fiyat tüm EMA'ların "
         "üzerinde seyrediyor; üçgenin üst sınırının kırılması trendin devamı sinyali verir."),
        ("SHOP", "Flag breakout",     "Bull Flag",
         "Güçlü yükseliş sonrası sağlıklı bir konsolidasyon bayrağı. Risk/ödül oranı cazip; "
         "stop seviyesi bayrağın alt sınırının hemen altında tutulabilir."),
        ("PLTR", "Ascending triangle","Triangle",
         "Sabit direnç seviyesine karşı yükselen destek çizgisi klasik bir yükselen üçgen. "
         "Alıcılar her geri çekilmede daha yüksek fiyattan devrede; kırılım yukarı yönlü beklenir."),
        ("UBER", "Pullback to EMA",   "Trendline",
         "Fiyat ana trend çizgisine ve 50 günlük EMA'ya geri çekildi. Trend bozulmadığı sürece "
         "bu bölge dinamik destek olarak alım için izleniyor."),
        ("COIN", "Momentum",          "Triangle",
         "Yüksek volatilite ve artan hacimle momentum oyunu. Daralan fiyat aralığı yakında sert "
         "bir hareketin habercisi; seviyeler yakından takip edilmeli, pozisyon küçük tutulmalı."),
    ]
    picks = []
    for ticker, setup, ftype, note in picks_spec:
        df = add_emas(get_ohlc(ticker))
        last = float(df["Close"].iloc[-1])
        atr = float((df["High"] - df["Low"]).tail(14).mean())
        picks.append({
            "ticker": ticker,
            "name": COMPANIES[ticker]["name"],
            "setup": setup,
            "formation": ftype,
            "note": note,
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
