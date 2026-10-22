"""
========================================================================
 VERİ KATMANI  (mock_data.py)  —  GERÇEK VERİ + mock fallback
========================================================================
Artık fonksiyonlar önce GERÇEK veriyi çeker (yfinance / CNN / Nasdaq /
TradingEconomics). Herhangi bir çağrı başarısız olursa (ağ yok, API
tıkandı, format değişti) sessizce eski MOCK veriye düşer — böylece
uygulama asla çökmez.

Her fonksiyonun DÖNÜŞ FORMATI aynı kaldı; app.py'ye dokunmaya gerek yok.

Kaynaklar:
  - yfinance : endeks/hisse fiyatı, grafik (OHLC), fundamentaller,
               forex, top movers/losers, ucuz şirket taraması
  - CNN      : Fear & Greed Index
  - Nasdaq   : yaklaşan IPO takvimi (best-effort)
  - TradingEconomics (guest) : ekonomik takvim (best-effort)

Not: Performans için her çağrı TTL önbelleğe alınır (Streamlit her
etkileşimde sayfayı baştan çalıştırdığından API'leri dövmemek şart).
========================================================================
"""

import time
import functools
import numpy as np
import pandas as pd

# ---- Opsiyonel bağımlılıklar (yoksa her şey mock'a düşer) -------------
try:
    import yfinance as yf
    _HAS_YF = True
except Exception:
    _HAS_YF = False

try:
    import requests
    _HAS_REQ = True
except Exception:
    _HAS_REQ = False

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}


def _ttl_cache(ttl):
    """Basit süreli (TTL) önbellek. Streamlit her rerun'da aynı veriyi
    tekrar çekmesin diye."""
    def deco(fn):
        store = {}

        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in store and now - store[key][0] < ttl:
                return store[key][1]
            val = fn(*args, **kwargs)
            store[key] = (now, val)
            return val
        return wrap
    return deco


# ----------------------------------------------------------------------
# Şirket evreni — ticker -> isim / logo domaini / sektör / kısa tanım
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
    # Endeks ETF'leri
    "SPY":   {"name": "SPDR S&P 500 ETF",         "domain": "ssga.com",    "sector": "Index ETF",
              "desc": "S&P 500 endeksini takip eden en büyük ve en likit borsa yatırım fonu (ETF); ABD'nin en büyük 500 halka açık şirketini kapsar."},
    "QQQ":   {"name": "Invesco QQQ Trust",         "domain": "invesco.com","sector": "Index ETF",
              "desc": "Nasdaq-100 endeksini takip eden ETF; ağırlıklı olarak teknoloji ve büyüme odaklı şirketlerden oluşur."},
    "DIA":   {"name": "SPDR Dow Jones Industrial Average ETF", "domain": "ssga.com", "sector": "Index ETF",
              "desc": "Dow Jones Endüstri Ortalaması'nı takip eden ETF; 30 büyük ve köklü ABD şirketini fiyat ağırlıklı olarak izler."},
    "IWM":   {"name": "iShares Russell 2000 ETF",  "domain": "ishares.com","sector": "Index ETF",
              "desc": "Russell 2000 endeksini takip eden ETF; ABD'li küçük ölçekli (small-cap) şirketleri kapsar."},
}

_BASE_PRICE_OVERRIDE = {"SPY": 560.0, "QQQ": 485.0, "DIA": 421.0, "IWM": 228.0}

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
                     "META", "TSLA", "AMD", "NFLX", "AVGO"]

_FULL_DAYS = 1300  # mock fallback uzunluğu / Max timeframe


def logo_url(ticker: str) -> str:
    domain = COMPANIES.get(ticker, {}).get("domain", "")
    return f"https://logo.clearbit.com/{domain}" if domain else ""


def company_name(ticker: str) -> str:
    return COMPANIES.get(ticker, {}).get("name", ticker)


def company_sector(ticker: str) -> str:
    return COMPANIES.get(ticker, {}).get("sector", "")


def _seed(ticker: str) -> int:
    return sum(ord(c) for c in str(ticker)) + 7


def get_filtered_companies() -> list[str]:
    return list(COMPANIES.keys())[:20]


# ======================================================================
# OHLC — gerçek (yfinance) + sentetik fallback
# ======================================================================
_synth_cache: dict[str, pd.DataFrame] = {}


def _synth_full_ohlc(ticker: str) -> pd.DataFrame:
    if ticker in _synth_cache:
        return _synth_cache[ticker]
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
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                       "Volume": volume}, index=dates)
    df.index.name = "Date"
    _synth_cache[ticker] = df
    return df


@_ttl_cache(1800)
def _full_ohlc(ticker: str) -> pd.DataFrame:
    """Gerçek ~6 yıllık günlük OHLC (yfinance). Başarısızsa sentetik."""
    if _HAS_YF:
        try:
            df = yf.Ticker(ticker).history(period="6y", auto_adjust=False)
            if df is not None and len(df) > 60:
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                idx = pd.to_datetime(df.index)
                try:
                    idx = idx.tz_localize(None)
                except (TypeError, AttributeError):
                    idx = idx.tz_convert(None) if getattr(idx, "tz", None) else idx
                df.index = idx
                df.index.name = "Date"
                return df
        except Exception:
            pass
    return _synth_full_ohlc(ticker)


def get_ohlc(ticker: str, days: int = 180) -> pd.DataFrame:
    return _full_ohlc(ticker).tail(days).copy()


def add_emas(df: pd.DataFrame, periods=(20, 50, 100, 200)) -> pd.DataFrame:
    out = df.copy()
    for p in periods:
        out[f"EMA{p}"] = out["Close"].ewm(span=p, adjust=False).mean()
    return out


def get_sr_zones(df: pd.DataFrame, n: int = 3) -> list[dict]:
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    rng = np.random.default_rng(int(abs(hi - lo)) + len(df) + 7)
    centers = np.sort(rng.uniform(lo + (hi - lo) * 0.15, hi - (hi - lo) * 0.15, n))
    band = (hi - lo) * 0.012
    zones = []
    for rank, c in enumerate(sorted(centers, key=lambda _: rng.random()), start=1):
        zones.append({"low": c - band, "high": c + band, "rank": rank})
    return zones


def get_formation(df: pd.DataFrame, ftype: str) -> dict:
    tail = df.tail(45)
    x0, x1 = tail.index[0], tail.index[-1]
    hi0, hi1 = float(tail["High"].iloc[:10].max()), float(tail["High"].iloc[-10:].max())
    lo0, lo1 = float(tail["Low"].iloc[:10].min()), float(tail["Low"].iloc[-10:].min())
    if ftype == "Triangle":
        lines = [((x0, hi0), (x1, min(hi0, hi1))), ((x0, lo0), (x1, max(lo0, lo1)))]
    elif ftype == "Bull Flag":
        mid = tail.index[len(tail) // 2]
        lines = [((x0, lo0), (mid, hi1)), ((mid, hi1), (x1, hi1 * 0.985)),
                 ((mid, lo1 * 1.01), (x1, lo1))]
    else:
        lines = [((x0, lo0), (x1, lo1))]
    return {"type": ftype, "lines": lines}


# ======================================================================
# ENDEKS ÖZETİ (SPY/QQQ/DIA/IWM) — gerçek + mock fallback
# ======================================================================
_INDEX_SPECS = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"),
                ("DIA", "Dow Jones"), ("IWM", "Russell 2000")]


def _mock_index_item(ticker, subtitle):
    base = _BASE_PRICE_OVERRIDE.get(ticker, 300.0)
    rng = np.random.default_rng(_seed(ticker))
    steps = rng.normal(0, 0.0013, 78)
    series = base * np.cumprod(1 + steps)
    last = float(series[-1])
    return {"ticker": ticker, "subtitle": subtitle, "prev_close": base,
            "last": last, "change_pct": (last / base - 1) * 100, "series": series.tolist()}


def _real_index_item(ticker, subtitle):
    t = yf.Ticker(ticker)
    fi = t.fast_info
    last = float(fi.last_price); prev = float(fi.previous_close)
    try:
        intr = t.history(period="1d", interval="5m")["Close"].dropna()
        series = [float(x) for x in intr.tolist()] if len(intr) > 3 else [prev, last]
    except Exception:
        series = [prev, last]
    return {"ticker": ticker, "subtitle": subtitle, "prev_close": prev,
            "last": last, "change_pct": (last / prev - 1) * 100, "series": series}


@_ttl_cache(300)
def get_index_summary() -> list[dict]:
    out = []
    for ticker, subtitle in _INDEX_SPECS:
        item = None
        if _HAS_YF:
            try:
                item = _real_index_item(ticker, subtitle)
            except Exception:
                item = None
        out.append(item or _mock_index_item(ticker, subtitle))
    return out


# ======================================================================
# ŞİRKET DETAYI — gerçek + mock fallback
# ======================================================================
def _mock_company_detail(ticker: str) -> dict:
    info = COMPANIES.get(ticker, {"name": ticker, "sector": "", "desc": ""})
    df = _synth_full_ohlc(ticker)
    last = float(df["Close"].iloc[-1]); prev_close = float(df["Close"].iloc[-2])
    day = df.iloc[-1]; y1 = df.tail(252)
    rng = np.random.default_rng(_seed(ticker) + 99)
    shares_out = rng.uniform(0.2, 16.0)
    market_cap = last * shares_out * 1e9
    pe = float(rng.uniform(9, 42)); eps = last / pe
    fwd_pe = pe * float(rng.uniform(0.82, 0.98))
    revenue = market_cap * float(rng.uniform(0.08, 0.6))
    net_income = revenue * float(rng.uniform(0.05, 0.34))
    beta = float(rng.uniform(0.55, 1.9))
    has_div = bool(rng.random() < 0.55)
    div_amt = float(rng.uniform(0.4, 3.2)) if has_div else 0.0
    today = pd.Timestamp.today().normalize()
    return {
        "ticker": ticker, "name": info["name"], "sector": info["sector"], "desc": info["desc"],
        "last": last, "prev_close": prev_close, "change_abs": last - prev_close,
        "change_pct": (last / prev_close - 1) * 100, "market_cap": market_cap,
        "revenue": revenue, "net_income": net_income, "eps": eps,
        "shares_out": shares_out * 1e9, "pe": pe, "fwd_pe": fwd_pe,
        "dividend": div_amt, "div_yield": (div_amt / last * 100) if has_div else 0.0,
        "ex_div_date": (today - pd.Timedelta(days=int(rng.integers(5, 60)))) if has_div else None,
        "volume": int(day["Volume"]), "open": float(day["Open"]),
        "day_low": float(day["Low"]), "day_high": float(day["High"]),
        "low_52w": float(y1["Low"].min()), "high_52w": float(y1["High"].max()),
        "beta": beta, "analysts": str(rng.choice(["Strong Buy", "Buy", "Hold"])),
        "price_target": last * (1 + float(rng.uniform(0.05, 0.30))),
        "target_upside": float(rng.uniform(5, 30)),
        "earnings_date": today + pd.Timedelta(days=int(rng.integers(5, 70))),
    }


def _g(info, *keys, default=None):
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return default


def _real_company_detail(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.get_info()
    last = _g(info, "currentPrice", "regularMarketPrice", "regularMarketPreviousClose")
    prev = _g(info, "previousClose", "regularMarketPreviousClose")
    if last is None or prev is None:
        raise ValueError("fiyat yok")
    last = float(last); prev = float(prev)
    name = COMPANIES.get(ticker, {}).get("name") or _g(info, "shortName", "longName", default=ticker)
    sector = COMPANIES.get(ticker, {}).get("sector") or _g(info, "sector", default="")
    desc = _g(info, "longBusinessSummary") or COMPANIES.get(ticker, {}).get("desc", "")
    pe = _g(info, "trailingPE")
    eps = _g(info, "trailingEps", default=(last / pe if pe else float("nan")))
    pt = _g(info, "targetMeanPrice", default=last)

    def _ts(v):
        try:
            return pd.to_datetime(v, unit="s") if v and float(v) > 1e6 else pd.to_datetime(v)
        except Exception:
            return None

    return {
        "ticker": ticker, "name": name, "sector": sector, "desc": desc,
        "last": last, "prev_close": prev, "change_abs": last - prev,
        "change_pct": (last / prev - 1) * 100,
        "market_cap": float(_g(info, "marketCap", default=0) or 0),
        "revenue": float(_g(info, "totalRevenue", default=0) or 0),
        "net_income": float(_g(info, "netIncomeToCommon", default=0) or 0),
        "eps": float(eps) if eps is not None else float("nan"),
        "shares_out": float(_g(info, "sharesOutstanding", default=0) or 0),
        "pe": float(pe) if pe else float("nan"),
        "fwd_pe": float(_g(info, "forwardPE", default=pe or float("nan"))),
        "dividend": float(_g(info, "dividendRate", default=0) or 0),
        "div_yield": float(_g(info, "dividendYield", default=0) or 0) * 100,
        "ex_div_date": _ts(_g(info, "exDividendDate")),
        "volume": int(_g(info, "volume", "regularMarketVolume", default=0) or 0),
        "open": float(_g(info, "open", "regularMarketOpen", default=last)),
        "day_low": float(_g(info, "dayLow", "regularMarketDayLow", default=last)),
        "day_high": float(_g(info, "dayHigh", "regularMarketDayHigh", default=last)),
        "low_52w": float(_g(info, "fiftyTwoWeekLow", default=last)),
        "high_52w": float(_g(info, "fiftyTwoWeekHigh", default=last)),
        "beta": float(_g(info, "beta", default=1.0) or 1.0),
        "analysts": str(_g(info, "recommendationKey", default="hold")).replace("_", " ").title(),
        "price_target": float(pt),
        "target_upside": (float(pt) / last - 1) * 100,
        "earnings_date": _ts(_g(info, "earningsTimestamp", "earningsTimestampStart"))
                         or (pd.Timestamp.today().normalize() + pd.Timedelta(days=30)),
    }


@_ttl_cache(1800)
def get_company_detail(ticker: str) -> dict:
    if _HAS_YF:
        try:
            return _real_company_detail(ticker)
        except Exception:
            pass
    return _mock_company_detail(ticker)


# ======================================================================
# HAFİF FİYAT ÖZETİ (quote) — gerçek + fallback
# ======================================================================
def _daily_change(ticker: str):
    df = _full_ohlc(ticker)
    last = float(df["Close"].iloc[-1]); prev = float(df["Close"].iloc[-2])
    return last, (last / prev - 1) * 100


@_ttl_cache(300)
def get_quote(ticker: str) -> dict:
    name = company_name(ticker); sector = company_sector(ticker)
    if _HAS_YF:
        try:
            fi = yf.Ticker(ticker).fast_info
            last = float(fi.last_price); prev = float(fi.previous_close)
            return {"ticker": ticker, "name": name, "sector": sector,
                    "last": last, "change_pct": (last / prev - 1) * 100}
        except Exception:
            pass
    last, chg = _daily_change(ticker)
    return {"ticker": ticker, "name": name, "sector": sector, "last": last, "change_pct": chg}


# ======================================================================
# HABERLER — gerçek (yfinance) + mock fallback
# ======================================================================
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


def _mock_company_news(ticker: str, n: int = 6) -> list[dict]:
    rng = np.random.default_rng(_seed(ticker) + 555)
    name = company_name(ticker)
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


def _parse_news_item(it, ticker):
    title = source = None; ts = None
    if isinstance(it, dict) and it.get("title"):
        title = it.get("title"); source = it.get("publisher")
        ts = it.get("providerPublishTime")
    elif isinstance(it, dict) and isinstance(it.get("content"), dict):
        c = it["content"]; title = c.get("title")
        prov = c.get("provider") or {}
        source = prov.get("displayName")
        pub = c.get("pubDate") or c.get("displayTime")
        if pub:
            try:
                ts = pd.Timestamp(pub).timestamp()
            except Exception:
                ts = None
    if not title:
        return None
    if ts:
        hours = max(1, int((time.time() - float(ts)) / 3600))
    else:
        hours = 1
    when = f"{hours} saat önce" if hours < 24 else f"{hours // 24} gün önce"
    return {"ticker": ticker, "title": title, "source": source or "Yahoo Finance",
            "when": when, "hours_ago": hours, "sentiment": "Neutral"}


@_ttl_cache(900)
def get_company_news(ticker: str, n: int = 6) -> list[dict]:
    if _HAS_YF:
        try:
            raw = yf.Ticker(ticker).news or []
            parsed = [p for p in (_parse_news_item(it, ticker) for it in raw) if p]
            if parsed:
                parsed.sort(key=lambda x: x["hours_ago"])
                return parsed[:n]
        except Exception:
            pass
    return _mock_company_news(ticker, n)


def get_watchlist_news(tickers: list[str], per_ticker: int = 3) -> list[dict]:
    all_news = []
    for t in tickers:
        all_news.extend(get_company_news(t, n=per_ticker))
    all_news.sort(key=lambda x: x["hours_ago"])
    return all_news


# ======================================================================
# STRATEGY PICKS — gerçek OHLC üzerinde hesaplanır
# ======================================================================
def get_strategy_picks() -> list[dict]:
    picks_spec = [
        ("NVDA", "Breakout retest", "Bull Flag",
         "EMA20 üzerinde sıkışan fiyat, 50 günlük ortalamaya yapılan geri çekilmenin ardından "
         "bayrak formasyonunu yukarı kırdı. Hacim teyidiyle momentum devam edebilir."),
        ("AMD", "Trend continuation", "Triangle",
         "Yükselen tabanlar ve yatay direnç bir simetrik üçgen oluşturuyor. Fiyat tüm EMA'ların "
         "üzerinde; üçgenin üst sınırının kırılması trendin devamı sinyali verir."),
        ("SHOP", "Flag breakout", "Bull Flag",
         "Güçlü yükseliş sonrası sağlıklı bir konsolidasyon bayrağı. Risk/ödül oranı cazip; "
         "stop seviyesi bayrağın alt sınırının altında tutulabilir."),
        ("PLTR", "Ascending triangle", "Triangle",
         "Sabit direnç seviyesine karşı yükselen destek çizgisi klasik bir yükselen üçgen. "
         "Alıcılar her geri çekilmede daha yüksek fiyattan devrede."),
        ("UBER", "Pullback to EMA", "Trendline",
         "Fiyat ana trend çizgisine ve 50 günlük EMA'ya geri çekildi. Trend bozulmadığı sürece "
         "bu bölge dinamik destek olarak izleniyor."),
        ("COIN", "Momentum", "Triangle",
         "Yüksek volatilite ve artan hacimle momentum oyunu. Daralan fiyat aralığı yakında sert "
         "bir hareketin habercisi; seviyeler yakından takip edilmeli, pozisyon küçük tutulmalı."),
    ]
    picks = []
    for ticker, setup, ftype, note in picks_spec:
        df = add_emas(get_ohlc(ticker))
        last = float(df["Close"].iloc[-1])
        atr = float((df["High"] - df["Low"]).tail(14).mean())
        picks.append({
            "ticker": ticker, "name": company_name(ticker), "setup": setup,
            "formation": ftype, "note": note, "last": last,
            "buy_zone": (round(last - atr * 0.6, 2), round(last + atr * 0.2, 2)),
            "stop": round(last - atr * 1.8, 2), "target": round(last + atr * 3.0, 2),
            "rr": round(3.0 / 1.8, 2), "avg_volume": int(df["Volume"].tail(20).mean()),
            "rel_volume": round(float(df["Volume"].iloc[-1] / df["Volume"].tail(20).mean()), 2),
        })
    return picks


# ======================================================================
# UCUZ ŞİRKETLER (PEG / Forward PE) — gerçek tarama + mock fallback
# ======================================================================
def _mock_value_stocks() -> pd.DataFrame:
    rows = [
        ("GOOGL", 1.1, 18.4, 27.0, 14.5), ("META", 0.9, 20.1, 33.2, 16.0),
        ("PEP", 1.4, 16.8, 10.1, 7.2), ("COST", 2.0, 34.5, 2.8, 11.0),
        ("AMZN", 1.3, 28.9, 7.4, 22.3), ("CRM", 1.0, 22.0, 15.6, 18.9),
        ("AVGO", 1.2, 24.3, 21.9, 19.5), ("UBER", 0.8, 21.5, 6.2, 30.1),
        ("SOFI", 0.7, 19.0, 8.9, 28.4), ("ADBE", 1.1, 19.9, 28.5, 13.8),
    ]
    df = pd.DataFrame(rows, columns=["Ticker", "PEG", "Forward PE", "Profit Margin %", "EPS Next 5Y %"])
    return df.sort_values("Forward PE").reset_index(drop=True)


@_ttl_cache(1800)
def get_value_stocks() -> pd.DataFrame:
    """Yahoo 'undervalued_large_caps' taramasından en düşük Forward PE'li
    şirketleri getirir. Başarısızsa mock liste."""
    if _HAS_YF:
        try:
            res = yf.screen("undervalued_large_caps")
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
            rows = []
            for q in quotes[:14]:
                sym = q.get("symbol")
                if not sym:
                    continue
                try:
                    info = yf.Ticker(sym).get_info()
                except Exception:
                    info = {}
                peg = _g(info, "trailingPegRatio", "pegRatio")
                fpe = _g(info, "forwardPE") or q.get("forwardPE")
                margin = _g(info, "profitMargins")
                growth = _g(info, "earningsGrowth")
                if fpe is None:
                    continue
                rows.append((sym,
                             round(float(peg), 2) if peg else np.nan,
                             round(float(fpe), 1),
                             round(float(margin) * 100, 1) if margin is not None else np.nan,
                             round(float(growth) * 100, 1) if growth is not None else np.nan))
            if len(rows) >= 5:
                df = pd.DataFrame(rows, columns=["Ticker", "PEG", "Forward PE",
                                                 "Profit Margin %", "EPS Next 5Y %"])
                df = df[df["Forward PE"] > 0].sort_values("Forward PE").head(10)
                return df.reset_index(drop=True)
        except Exception:
            pass
    return _mock_value_stocks()


# ======================================================================
# FEAR & GREED — gerçek (CNN) + mock fallback
# ======================================================================
def _fg_label(v) -> str:
    v = float(v)
    if v < 25: return "Extreme Fear"
    if v < 45: return "Fear"
    if v < 55: return "Neutral"
    if v < 75: return "Greed"
    return "Extreme Greed"


_FG_QUOTE = "Be fearful when others are greedy, and greedy when others are fearful."
_FG_AUTHOR = "Warren Buffett"


def _mock_fear_greed() -> dict:
    history = [{"when": "Previous close", "value": 23}, {"when": "1 week ago", "value": 44},
               {"when": "1 month ago", "value": 30}, {"when": "1 year ago", "value": 29}]
    for h in history:
        h["label"] = _fg_label(h["value"])
    return {"value": 27, "label": _fg_label(27), "history": history,
            "quote": _FG_QUOTE, "quote_author": _FG_AUTHOR}


@_ttl_cache(900)
def get_fear_greed() -> dict:
    if _HAS_REQ:
        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            r = requests.get(url, headers=_HEADERS, timeout=10)
            fg = r.json()["fear_and_greed"]
            value = round(float(fg["score"]))
            pairs = [("Previous close", fg.get("previous_close")),
                     ("1 week ago", fg.get("previous_1_week")),
                     ("1 month ago", fg.get("previous_1_month")),
                     ("1 year ago", fg.get("previous_1_year"))]
            history = [{"when": w, "value": round(float(v)), "label": _fg_label(v)}
                       for w, v in pairs if v is not None]
            if history:
                return {"value": value, "label": _fg_label(value), "history": history,
                        "quote": _FG_QUOTE, "quote_author": _FG_AUTHOR}
        except Exception:
            pass
    return _mock_fear_greed()


# ======================================================================
# TOP MOVERS / LOSERS — gerçek (Yahoo screener) + fallback
# ======================================================================
def _screen_quotes(screen_name, n):
    res = yf.screen(screen_name)
    quotes = res.get("quotes", []) if isinstance(res, dict) else []
    out = []
    for q in quotes[:n]:
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({"ticker": sym,
                    "name": q.get("shortName") or q.get("displayName") or sym,
                    "sector": q.get("sector", "") or "",
                    "last": float(q.get("regularMarketPrice") or 0),
                    "change_pct": float(q.get("regularMarketChangePercent") or 0)})
    return out


def _mock_movers(reverse, n):
    quotes = [get_quote(t) for t in get_filtered_companies()]
    quotes.sort(key=lambda x: x["change_pct"], reverse=reverse)
    return quotes[:n]


@_ttl_cache(300)
def get_top_movers(n: int = 5) -> list[dict]:
    if _HAS_YF:
        try:
            m = _screen_quotes("day_gainers", n)
            if m:
                return m
        except Exception:
            pass
    return _mock_movers(True, n)


@_ttl_cache(300)
def get_top_losers(n: int = 5) -> list[dict]:
    if _HAS_YF:
        try:
            m = _screen_quotes("day_losers", n)
            if m:
                return m
        except Exception:
            pass
    return _mock_movers(False, n)


# ======================================================================
# YAKLAŞAN IPO'LAR — gerçek (Nasdaq) + mock fallback
# ======================================================================
def _mock_ipos() -> pd.DataFrame:
    today = pd.Timestamp.today().normalize()
    rows = [
        ("NovaAI Systems", "NASDAQ", 4, "$18 – $20", 12.5),
        ("Helios Energy", "NYSE", 9, "$22 – $25", 8.0),
        ("Quantio Compute", "NASDAQ", 12, "$30 – $34", 15.2),
        ("Verdant Biotech", "NASDAQ", 16, "$14 – $16", 6.4),
        ("Orbit Logistics", "NYSE", 21, "$25 – $28", 10.1),
        ("Lumen Robotics", "NASDAQ", 27, "$40 – $45", 9.8),
    ]
    return pd.DataFrame([{"Company": n, "Exchange": e,
                          "Expected Date": (today + pd.Timedelta(days=d)).strftime("%b %d, %Y"),
                          "Price Range": p, "Shares (M)": s} for n, e, d, p, s in rows])


@_ttl_cache(3600)
def get_upcoming_ipos() -> pd.DataFrame:
    if _HAS_REQ:
        try:
            month = pd.Timestamp.today().strftime("%Y-%m")
            url = "https://api.nasdaq.com/api/ipo/calendar"
            r = requests.get(url, params={"date": month}, headers=_HEADERS, timeout=10)
            rows = (r.json().get("data", {}).get("upcoming", {})
                    .get("upcomingTable", {}).get("rows") or [])
            out = []
            for row in rows[:12]:
                shares = str(row.get("sharesOffered", "")).replace(",", "")
                try:
                    shares_m = round(float(shares) / 1e6, 2)
                except Exception:
                    shares_m = np.nan
                out.append({"Company": row.get("companyName", ""),
                            "Exchange": row.get("proposedExchange", ""),
                            "Expected Date": row.get("expectedPriceDate", ""),
                            "Price Range": row.get("proposedSharePrice", ""),
                            "Shares (M)": shares_m})
            if out:
                return pd.DataFrame(out)
        except Exception:
            pass
    return _mock_ipos()


# ======================================================================
# EKONOMİK TAKVİM — gerçek (TradingEconomics guest) + mock fallback
# ======================================================================
def _mock_calendar() -> pd.DataFrame:
    today = pd.Timestamp.today().normalize()
    rows = [
        (0, "14:30", "USD", "Core CPI (MoM)", "High", "0.3%", "0.2%"),
        (0, "16:00", "USD", "Fed Chair Speech", "High", "—", "—"),
        (1, "11:00", "EUR", "ECB Interest Rate Decision", "High", "3.25%", "3.25%"),
        (1, "14:30", "USD", "Initial Jobless Claims", "Medium", "228K", "223K"),
        (2, "08:00", "GBP", "GDP (QoQ)", "High", "0.4%", "0.5%"),
        (2, "14:30", "USD", "Nonfarm Payrolls", "High", "180K", "254K"),
        (3, "10:00", "EUR", "German Ifo Business Climate", "Medium", "86.0", "85.4"),
        (4, "14:30", "CAD", "Unemployment Rate", "Medium", "6.6%", "6.5%"),
    ]
    return pd.DataFrame([{"Date": (today + pd.Timedelta(days=d)).strftime("%a %b %d"),
                          "Time": t, "Cur": c, "Event": e, "Impact": i,
                          "Forecast": f, "Previous": p} for d, t, c, e, i, f, p in rows])


_IMPORTANCE = {1: "Low", 2: "Medium", 3: "High"}
_COUNTRY_CUR = {"united states": "USD", "euro area": "EUR", "germany": "EUR",
                "united kingdom": "GBP", "japan": "JPY", "canada": "CAD",
                "australia": "AUD", "switzerland": "CHF", "china": "CNY"}


@_ttl_cache(3600)
def get_economic_calendar() -> pd.DataFrame:
    if _HAS_REQ:
        try:
            today = pd.Timestamp.today().normalize()
            end = today + pd.Timedelta(days=7)
            url = "https://api.tradingeconomics.com/calendar"
            params = {"c": "guest:guest", "format": "json",
                      "d1": today.strftime("%Y-%m-%d"), "d2": end.strftime("%Y-%m-%d")}
            r = requests.get(url, params=params, headers=_HEADERS, timeout=12)
            data = r.json()
            out = []
            for ev in data:
                country = str(ev.get("Country", "")).lower()
                cur = _COUNTRY_CUR.get(country)
                imp = ev.get("Importance")
                if cur is None or imp not in (2, 3):
                    continue
                d = pd.to_datetime(ev.get("Date"))
                out.append({"Date": d.strftime("%a %b %d"), "Time": d.strftime("%H:%M"),
                            "Cur": cur, "Event": ev.get("Event", ""),
                            "Impact": _IMPORTANCE.get(imp, "Medium"),
                            "Forecast": str(ev.get("Forecast", "") or "—"),
                            "Previous": str(ev.get("Previous", "") or "—")})
                if len(out) >= 20:
                    break
            if out:
                return pd.DataFrame(out)
        except Exception:
            pass
    return _mock_calendar()


# ======================================================================
# FOREX KURLARI — gerçek (yfinance) + mock fallback
# ======================================================================
_FX_PAIRS = [("EUR/USD", "EURUSD=X", 1.0845), ("GBP/USD", "GBPUSD=X", 1.2680),
             ("USD/JPY", "USDJPY=X", 149.30), ("USD/CHF", "USDCHF=X", 0.8820),
             ("AUD/USD", "AUDUSD=X", 0.6615), ("USD/CAD", "USDCAD=X", 1.3720)]


@_ttl_cache(300)
def get_forex_rates() -> list[dict]:
    out = []
    for pair, sym, base in _FX_PAIRS:
        item = None
        if _HAS_YF:
            try:
                fi = yf.Ticker(sym).fast_info
                last = float(fi.last_price); prev = float(fi.previous_close)
                item = {"pair": pair, "rate": last, "change_pct": (last / prev - 1) * 100}
            except Exception:
                item = None
        if item is None:
            rng = np.random.default_rng(_seed(pair) + 11)
            item = {"pair": pair, "rate": base, "change_pct": float(rng.normal(0, 0.35))}
        out.append(item)
    return out


# ======================================================================
# SEKTÖR SIRALAMASI & KATEGORİ HABERLERİ — analitik/kurgusal (mock kalır)
# ======================================================================
def get_index_rankings() -> pd.DataFrame:
    rows = [
        ("Semiconductors", 28.5, 31.2), ("Software", 22.1, 24.8),
        ("Technology", 18.9, 27.5), ("Fintech", 26.4, 12.1),
        ("Communication", 14.2, 20.3), ("Consumer", 11.8, 9.4),
        ("Automotive", 17.5, 8.9), ("Retail", 8.6, 4.2),
        ("Consumer Staples", 6.1, 11.0),
    ]
    df = pd.DataFrame(rows, columns=["Sector", "Growth %", "Profit Margin %"])
    df["Score"] = (df["Growth %"] * 0.6 + df["Profit Margin %"] * 0.4).round(1)
    df = df.sort_values("Score", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))
    return df


_MARKET_NEWS = {
    "war_politics": [
        ("Jeopolitik gerilim enerji fiyatlarında oynaklığı artırdı", "Reuters", "2 saat önce"),
        ("Ticaret tarifeleri görüşmeleri piyasalarda temkinli hava yarattı", "Bloomberg", "5 saat önce"),
        ("Seçim belirsizliği bölgesel endekslerde baskı oluşturdu", "AP", "9 saat önce"),
        ("Merkez bankası başkanından jeopolitik risk uyarısı", "FT", "1 gün önce"),
        ("Yaptırım haberleri emtia piyasalarını hareketlendirdi", "Reuters", "1 gün önce"),
    ],
    "markets": [
        ("S&P 500 kazanç sezonu beklentileriyle dalgalı seyretti", "CNBC", "1 saat önce"),
        ("Tahvil getirileri yükselince büyüme hisseleri geriledi", "Bloomberg", "3 saat önce"),
        ("Dolar endeksi haftalık kazancını korudu", "MarketWatch", "6 saat önce"),
        ("Petrol fiyatları arz endişeleriyle yükseldi", "Reuters", "8 saat önce"),
        ("Altın güvenli liman talebiyle rekor seviyeye yaklaştı", "Kitco", "12 saat önce"),
    ],
    "index": [
        ("Yapay zeka hisseleri endeks getirisinin büyük kısmını sürüklüyor", "The Information", "2 saat önce"),
        ("Yarı iletken endeksi yeni veri merkezi siparişleriyle yükseldi", "SemiAnalysis", "4 saat önce"),
        ("Yazılım sektörü bulut harcamalarının toparlanmasıyla güçlendi", "Seeking Alpha", "7 saat önce"),
        ("AI altyapı yatırımları teknoloji ağırlıklı endeksleri destekliyor", "CNBC", "10 saat önce"),
        ("Küçük ölçekli (small-cap) endeks faiz beklentisiyle öne çıktı", "Barron's", "1 gün önce"),
    ],
}


def get_market_news(category: str) -> list[dict]:
    return [{"title": t, "source": s, "when": w}
            for t, s, w in _MARKET_NEWS.get(category, [])]


# ======================================================================
# TEŞHİS — veri kaynakları canlı mı? (uygulamada panel olarak gösterilir)
# ======================================================================
@_ttl_cache(120)
def get_data_health() -> dict:
    """yfinance ve CNN gerçekten erişilebiliyor mu diye hızlı bir test.
    Uygulamadaki '🔎 Veri kaynağı durumu' paneli bunu gösterir."""
    info = {"yfinance_installed": _HAS_YF, "requests_installed": _HAS_REQ,
            "yf_ok": False, "yf_msg": "", "cnn_ok": False, "cnn_msg": ""}
    if _HAS_YF:
        try:
            import yfinance as _yf
            v = _yf.__version__
            price = _yf.Ticker("AAPL").fast_info.last_price
            if price and float(price) > 0:
                info["yf_ok"] = True
                info["yf_msg"] = f"yfinance {v} · AAPL son fiyat = {float(price):.2f}"
            else:
                info["yf_msg"] = f"yfinance {v} kurulu ama fiyat boş döndü (Yahoo engellemiş olabilir)"
        except Exception as e:
            info["yf_msg"] = f"{type(e).__name__}: {str(e)[:140]}"
    else:
        info["yf_msg"] = "yfinance IMPORT EDİLEMEDİ — requirements.txt'te 'yfinance' yok ya da kurulmadı."
    if _HAS_REQ:
        try:
            r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                             headers=_HEADERS, timeout=8)
            info["cnn_ok"] = (r.status_code == 200 and "fear_and_greed" in r.text)
            info["cnn_msg"] = f"HTTP {r.status_code}"
        except Exception as e:
            info["cnn_msg"] = f"{type(e).__name__}: {str(e)[:140]}"
    else:
        info["requests_msg"] = "requests import edilemedi."
    return info


# ======================================================================
# SEKTÖR PERFORMANSI (ısı haritası) — Long Term + Piyasalar görünümü
# ======================================================================
_SECTOR_ETFS = [
    ("Teknoloji", "XLK"), ("Yarı İletken", "SMH"), ("Finans", "XLF"),
    ("Enerji", "XLE"), ("Sağlık", "XLV"), ("Sanayi", "XLI"),
    ("Tüketici (İsteğe Bağlı)", "XLY"), ("Tüketici (Temel)", "XLP"),
    ("Hizmet", "XLU"), ("Hammadde", "XLB"), ("İletişim", "XLC"),
    ("Gayrimenkul", "XLRE"),
]


@_ttl_cache(300)
def get_sector_performance() -> list[dict]:
    """Sektör ETF'lerinin günlük % değişimi (ısı haritası için).
    Gerçek veride: her sektör ETF'inin günlük değişimini çeker; başarısızsa
    deterministik mock."""
    out = []
    for name, etf in _SECTOR_ETFS:
        chg = None
        if _HAS_YF:
            try:
                fi = yf.Ticker(etf).fast_info
                last = float(fi.last_price); prev = float(fi.previous_close)
                chg = (last / prev - 1) * 100
            except Exception:
                chg = None
        if chg is None:
            rng = np.random.default_rng(_seed(etf) + 3)
            chg = float(rng.normal(0.1, 1.1))
        out.append({"name": name, "etf": etf, "change_pct": chg})
    return out


# ======================================================================
# FOREX & HABERLER sayfası için veri
# ======================================================================

# --- Üst makro şerit: DXY, 10Y tahvil, altın, brent, USDTRY, BTC --------
_MACRO = [
    ("Dolar Endeksi", "DXY",     "DX-Y.NYB", 98.42,    2),
    ("ABD 10Y Tahvil", "US10Y",  "^TNX",      4.38,    2),
    ("Altın", "XAUUSD",          "GC=F",      4128.40, 2),
    ("Brent Petrol", "UKOIL",    "BZ=F",      64.85,   2),
    ("Dolar / TL", "USDTRY",     "USDTRY=X",  43.1250, 4),
    ("Bitcoin", "BTCUSD",        "BTC-USD",   108420., 0),
]


@_ttl_cache(300)
def get_macro_strip() -> list[dict]:
    """Forex sayfasının üstündeki 6 enstrüman kartı."""
    out = []
    for name, code, sym, base, dec in _MACRO:
        last = chg = None
        series = None
        if _HAS_YF:
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                last = float(fi.last_price); prev = float(fi.previous_close)
                chg = (last / prev - 1) * 100
                h = t.history(period="1mo")["Close"].dropna()
                if len(h) > 5:
                    series = [float(x) for x in h.tolist()][-40:]
            except Exception:
                last = chg = None
        if last is None:
            rng = np.random.default_rng(_seed(code) + 21)
            chg = float(rng.normal(0, 0.8))
            last = base * (1 + chg / 100)
            series = (base * np.cumprod(1 + rng.normal(0, 0.004, 40))).tolist()
        if not series:
            series = [last] * 10
        out.append({"name": name, "code": code, "value": last,
                    "change_pct": chg, "series": series, "dec": dec})
    return out


# --- Pariteler listesi (kategorili) ------------------------------------
_FX_LIST = [
    ("EUR/USD", "EURUSD=X", "Euro / ABD Doları",            "Majör",   1.16380, 5),
    ("GBP/USD", "GBPUSD=X", "Sterlin / ABD Doları",         "Majör",   1.33520, 5),
    ("USD/JPY", "USDJPY=X", "ABD Doları / Japon Yeni",      "Majör",   151.284, 3),
    ("USD/CHF", "USDCHF=X", "ABD Doları / İsviçre Frangı",  "Majör",   0.79412, 5),
    ("AUD/USD", "AUDUSD=X", "Avustralya Doları / ABD Doları","Majör",  0.65518, 5),
    ("USD/CAD", "USDCAD=X", "ABD Doları / Kanada Doları",   "Majör",   1.37905, 5),
    ("NZD/USD", "NZDUSD=X", "Yeni Zelanda Doları / ABD Doları","Majör",0.59840, 5),
    ("EUR/GBP", "EURGBP=X", "Euro / Sterlin",               "Çapraz",  0.87160, 5),
    ("EUR/JPY", "EURJPY=X", "Euro / Japon Yeni",            "Çapraz",  176.050, 3),
    ("GBP/JPY", "GBPJPY=X", "Sterlin / Japon Yeni",         "Çapraz",  201.980, 3),
    ("AUD/JPY", "AUDJPY=X", "Avustralya Doları / Japon Yeni","Çapraz", 99.120,  3),
    ("USD/TRY", "USDTRY=X", "ABD Doları / Türk Lirası",     "Egzotik", 43.1250, 4),
    ("USD/ZAR", "USDZAR=X", "ABD Doları / G. Afrika Randı", "Egzotik", 17.2400, 4),
    ("USD/MXN", "USDMXN=X", "ABD Doları / Meksika Pesosu",  "Egzotik", 18.3900, 4),
    ("XAU/USD", "GC=F",     "Altın / ABD Doları",           "Metal",   4128.40, 2),
    ("XAG/USD", "SI=F",     "Gümüş / ABD Doları",           "Metal",   49.880,  3),
]

FX_CATEGORIES = ["Tümü", "Majör", "Çapraz", "Egzotik", "Metal"]


def fx_symbol(pair: str) -> str:
    for p, sym, _n, _c, _b, _d in _FX_LIST:
        if p == pair:
            return sym
    return "EURUSD=X"


def fx_meta(pair: str) -> dict:
    for p, sym, n, c, b, d in _FX_LIST:
        if p == pair:
            return {"pair": p, "symbol": sym, "name": n, "category": c, "base": b, "dec": d}
    return {"pair": pair, "symbol": "EURUSD=X", "name": "", "category": "Majör",
            "base": 1.0, "dec": 5}


@_ttl_cache(300)
def get_fx_list(category: str = "Tümü") -> list[dict]:
    """Pariteler paneli. category: Tümü/Majör/Çapraz/Egzotik/Metal"""
    out = []
    for p, sym, name, cat, base, dec in _FX_LIST:
        if category != "Tümü" and cat != category:
            continue
        last = chg = None
        if _HAS_YF:
            try:
                fi = yf.Ticker(sym).fast_info
                last = float(fi.last_price); prev = float(fi.previous_close)
                chg = (last / prev - 1) * 100
            except Exception:
                last = None
        if last is None:
            rng = np.random.default_rng(_seed(p) + 33)
            chg = float(rng.normal(0, 0.3))
            last = base * (1 + chg / 100)
        out.append({"pair": p, "symbol": sym, "name": name, "category": cat,
                    "last": last, "change_pct": chg, "dec": dec})
    return out


def get_fx_history(pair: str, days: int = 120):
    """Parite için OHLC geçmişi (grafik)."""
    return add_emas(get_ohlc(fx_symbol(pair), days=max(days, 260))).tail(days)


# --- Ekonomik takvim satırları (etki noktalarıyla) ---------------------
_CAL_MOCK = [
    ("08:00", "EUR", 2, "Almanya GfK Tüketici Güveni", "-22,4", "-21,8", "-22,3"),
    ("10:00", "EUR", 3, "Euro Bölgesi İmalat PMI",      "49,9",  "49,6",  "49,8"),
    ("10:30", "GBP", 3, "BK Hizmet PMI",                "50,4",  "51,0",  "50,8"),
    ("14:00", "TRY", 3, "TCMB Faiz Kararı",             "—",     "%38,50", "%40,50"),
    ("14:30", "USD", 3, "İşsizlik Maaşı Başvuruları",   "—",     "232K",  "228K"),
    ("16:00", "USD", 1, "İkinci El Konut Satışları",    "—",     "4,06M", "4,00M"),
]

CAL_FILTERS = ["Dün", "Bugün", "Yarın", "Bu Hafta"]
CAL_IMPACTS = ["Tümü", "Yüksek", "Orta +"]


@_ttl_cache(1800)
def get_calendar_rows(impact: str = "Tümü") -> list[dict]:
    """Takvim satırları: saat, döviz, etki (1-3), etkinlik, açıklanan, beklenti, önceki.
    Gerçek veride TradingEconomics'ten; başarısızsa mock."""
    rows = []
    if _HAS_REQ:
        try:
            today = pd.Timestamp.today().normalize()
            end = today + pd.Timedelta(days=2)
            r = requests.get("https://api.tradingeconomics.com/calendar",
                             params={"c": "guest:guest", "format": "json",
                                     "d1": today.strftime("%Y-%m-%d"),
                                     "d2": end.strftime("%Y-%m-%d")},
                             headers=_HEADERS, timeout=12)
            for ev in r.json():
                cur = _COUNTRY_CUR.get(str(ev.get("Country", "")).lower())
                imp = ev.get("Importance")
                if cur is None or not imp:
                    continue
                d = pd.to_datetime(ev.get("Date"))
                rows.append({"time": d.strftime("%H:%M"), "cur": cur, "impact": int(imp),
                             "event": ev.get("Event", ""),
                             "actual": str(ev.get("Actual", "") or "—"),
                             "forecast": str(ev.get("Forecast", "") or "—"),
                             "previous": str(ev.get("Previous", "") or "—")})
                if len(rows) >= 20:
                    break
        except Exception:
            rows = []
    if not rows:
        rows = [{"time": t, "cur": c, "impact": i, "event": e,
                 "actual": a, "forecast": f, "previous": p}
                for t, c, i, e, a, f, p in _CAL_MOCK]
    if impact == "Yüksek":
        rows = [r for r in rows if r["impact"] >= 3]
    elif impact == "Orta +":
        rows = [r for r in rows if r["impact"] >= 2]
    return rows


# --- Piyasa haberleri (öne çıkan + liste, kategorili) ------------------
NEWS_CATEGORIES = ["Tümü", "Forex", "Merkez Bankaları", "Emtia", "Türkiye"]

_FX_NEWS = [
    ("Dolar endeksi istihdam verisi öncesi geriliyor", "DXY", "Düşüş", "Forex", 32),
    ("BoJ yetkilileri yendeki hızlı hareketlere karşı uyardı", "USD/JPY", "Düşüş", "Merkez Bankaları", 47),
    ("Altın güvenli liman talebiyle zirveyi yeniden test ediyor", "XAU/USD", "Yükseliş", "Emtia", 60),
    ("TCMB kararı öncesi TL'de oynaklık beklentisi arttı", "USD/TRY", "Nötr", "Türkiye", 120),
    ("Brent stok verisi sonrası toparlandı, Kanada doları destek buldu", "USD/CAD", "Düşüş", "Emtia", 180),
    ("Sterlin zayıf hizmet PMI verisi sonrası baskı altında", "GBP/USD", "Düşüş", "Forex", 240),
    ("Fed tutanakları faiz patikasında ayrışmaya işaret etti", "DXY", "Nötr", "Merkez Bankaları", 300),
    ("Euro Bölgesi PMI beklentiyi aştı, euro toparlandı", "EUR/USD", "Yükseliş", "Forex", 360),
]

_FEATURED = {
    "title": "ECB toplantısı öncesi euro dar bantta; piyasa Aralık için indirim fiyatlıyor",
    "summary": ("Yatırımcılar Lagarde'ın basın toplantısındaki tonu bekliyor. Opsiyon piyasası "
                "kısa vadede EUR/USD'de sınırlı oynaklık fiyatlıyor; 1,1600 desteği öne çıkıyor."),
    "category": "Merkez Bankaları", "sentiment": "Nötr", "source": "Reuters",
    "when": "18 dk", "tags": ["EUR/USD", "USD/JPY", "DXY"],
}


def get_forex_news(category: str = "Tümü") -> dict:
    """Forex sayfasının haber bölümü: öne çıkan + liste."""
    items = []
    for title, pair, sent, cat, mins in _FX_NEWS:
        if category != "Tümü" and cat != category:
            continue
        when = f"{mins} dk" if mins < 60 else f"{mins // 60} sa"
        rng = np.random.default_rng(_seed(title) + 5)
        spark = (100 * np.cumprod(1 + rng.normal(0, 0.012, 24))).tolist()
        items.append({"title": title, "pair": pair, "sentiment": sent,
                      "category": cat, "when": when, "source": "KAYNAK", "spark": spark})
    return {"featured": _FEATURED, "items": items}
