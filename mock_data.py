"""
========================================================================
 VERİ KATMANI  (mock_data.py)  —  v3 · GERÇEK VERİ ÖNCELİKLİ
========================================================================
Her fonksiyon önce gerçek kaynaktan çeker; başarısız olursa yalnızca
"bilinen" semboller için örnek (mock) veriye düşer ve bunu `src`
alanıyla işaretler ("real" | "mock" | "none"). Arayüz bu işarete göre
"örnek veri" etiketi gösterir — gerçek ile mock asla sessizce karışmaz.

Kaynaklar (API anahtarı gerektirmez):
  - yfinance  : fiyatlar (TOPLU indirme — tek istekte çok sembol),
                grafikler, fundamentaller, haberler (Search), tarayıcılar
  - CNN       : Fear & Greed Index
  - ForexFactory haftalık takvim JSON'u : ekonomik takvim
  - Nasdaq    : IPO ve bilanço takvimi (best-effort)
İsteğe bağlı: Streamlit secrets'a FINNHUB_API_KEY eklenirse IPO ve
bilanço takvimi Finnhub'dan çekilir.

Tüm çağrılar süreli önbellekte tutulur; başarısız sonuçlar kısa sürede
yeniden denenir (fail_ttl), böylece Yahoo düzelince gerçek veri geri gelir.
========================================================================
"""

import os
import re
import time
import functools
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

DATA_VERSION = "4.0"

try:
    import yfinance as yf
    _HAS_YF = True
except Exception:  # pragma: no cover
    yf = None
    _HAS_YF = False

try:
    import requests
    _HAS_REQ = True
except Exception:  # pragma: no cover
    requests = None
    _HAS_REQ = False

TZ = "Europe/Berlin"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9"}
_FULL_DAYS = 1300


# ======================================================================
# Önbellek
# ======================================================================
def _degraded(val):
    if val is None:
        return True
    if isinstance(val, pd.DataFrame):
        return val.empty or val.attrs.get("src") in ("mock", "none")
    if isinstance(val, dict):
        return (not val) or val.get("src") in ("mock", "none")
    if isinstance(val, (list, tuple)):
        if not val:
            return True
        first = val[0]
        return isinstance(first, dict) and first.get("src") in ("mock", "none")
    return False


def _ttl_cache(ttl, fail_ttl=None):
    fail_ttl = ttl if fail_ttl is None else fail_ttl

    def deco(fn):
        store = {}

        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            hit = store.get(key)
            if hit is not None and now - hit[0] < hit[2]:
                return hit[1]
            val = fn(*args, **kwargs)
            store[key] = (now, val, fail_ttl if _degraded(val) else ttl)
            if len(store) > 600:
                for k in list(store)[:150]:
                    store.pop(k, None)
            return val

        wrap.clear = store.clear
        return wrap
    return deco


def _pmap(fn, items, workers=4):
    """Birkaç bağımsız isteği paralel çalıştırır (sıra korunur)."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as ex:
        return list(ex.map(fn, items))


def _num(v):
    try:
        v = float(v)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _g(info, *keys, default=None):
    for k in keys:
        v = info.get(k) if isinstance(info, dict) else None
        if v not in (None, "", "None"):
            return v
    return default


# ======================================================================
# Sembol evreni
# ======================================================================
COMPANIES = {
    "AAPL":  {"name": "Apple", "domain": "apple.com", "sector": "Technology",
              "desc": "One of the world's most valuable consumer technology companies, with a hardware-software ecosystem of iPhone, Mac and services."},
    "MSFT":  {"name": "Microsoft", "domain": "microsoft.com", "sector": "Technology",
              "desc": "Leader in enterprise software and cloud infrastructure with Windows, Office and the Azure cloud platform."},
    "NVDA":  {"name": "NVIDIA", "domain": "nvidia.com", "sector": "Semiconductors",
              "desc": "Dominant player in AI and data-center GPUs; at the centre of accelerated computing."},
    "AMZN":  {"name": "Amazon", "domain": "amazon.com", "sector": "Consumer",
              "desc": "E-commerce giant and, with AWS, the world's largest cloud service provider."},
    "GOOGL": {"name": "Alphabet", "domain": "google.com", "sector": "Technology",
              "desc": "Google search, advertising, YouTube and cloud; also a pioneer in AI research."},
    "META":  {"name": "Meta Platforms", "domain": "meta.com", "sector": "Technology",
              "desc": "Social media and digital advertising giant operating Facebook, Instagram and WhatsApp."},
    "TSLA":  {"name": "Tesla", "domain": "tesla.com", "sector": "Automotive",
              "desc": "Electric vehicle maker; also active in energy storage and autonomous driving."},
    "AMD":   {"name": "AMD", "domain": "amd.com", "sector": "Semiconductors",
              "desc": "CPU and GPU maker; Intel's and NVIDIA's main rival in the data-center and PC markets."},
    "NFLX":  {"name": "Netflix", "domain": "netflix.com", "sector": "Communication",
              "desc": "Worldwide subscription video streaming platform and content producer."},
    "CRM":   {"name": "Salesforce", "domain": "salesforce.com", "sector": "Software",
              "desc": "Market leader in cloud-based customer relationship management (CRM) software."},
    "ADBE":  {"name": "Adobe", "domain": "adobe.com", "sector": "Software",
              "desc": "Digital media software leader with Photoshop, Acrobat and Creative Cloud tools."},
    "AVGO":  {"name": "Broadcom", "domain": "broadcom.com", "sector": "Semiconductors",
              "desc": "Semiconductor giant making networking, wireless and infrastructure chips, also growing in enterprise software."},
    "COST":  {"name": "Costco", "domain": "costco.com", "sector": "Retail",
              "desc": "Membership-based warehouse retail chain; steady revenue and strong customer loyalty."},
    "PEP":   {"name": "PepsiCo", "domain": "pepsico.com", "sector": "Consumer Staples",
              "desc": "Beverage and snack giant owning global brands such as Pepsi, Lay's and Gatorade."},
    "SHOP":  {"name": "Shopify", "domain": "shopify.com", "sector": "Software",
              "desc": "Cloud-based commerce platform providing e-commerce infrastructure for small and mid-sized businesses."},
    "UBER":  {"name": "Uber", "domain": "uber.com", "sector": "Technology",
              "desc": "Global market-leading platform for ride-hailing and food delivery."},
    "PLTR":  {"name": "Palantir", "domain": "palantir.com", "sector": "Software",
              "desc": "Big-data analytics and AI software platforms for governments and enterprises."},
    "SOFI":  {"name": "SoFi", "domain": "sofi.com", "sector": "Fintech",
              "desc": "Digital finance platform combining lending, investing and banking in one app."},
    "COIN":  {"name": "Coinbase", "domain": "coinbase.com", "sector": "Fintech",
              "desc": "One of the largest US-based crypto exchanges; retail and institutional trading."},
    "SNOW":  {"name": "Snowflake", "domain": "snowflake.com", "sector": "Software",
              "desc": "Cloud-based data warehouse and analytics platform; pay-as-you-go model."},
    "SPY":   {"name": "SPDR S&P 500 ETF", "domain": "ssga.com", "sector": "Index ETF",
              "desc": "The largest and most liquid ETF tracking the S&P 500; covers the 500 largest US public companies."},
    "QQQ":   {"name": "Invesco QQQ Trust", "domain": "invesco.com", "sector": "Index ETF",
              "desc": "ETF tracking the Nasdaq-100; made up mostly of technology and growth companies."},
    "DIA":   {"name": "SPDR Dow Jones Industrial Average ETF", "domain": "ssga.com", "sector": "Index ETF",
              "desc": "ETF tracking the Dow Jones Industrial Average; follows 30 large, established US companies, price-weighted."},
    "IWM":   {"name": "iShares Russell 2000 ETF", "domain": "ishares.com", "sector": "Index ETF",
              "desc": "ETF tracking the Russell 2000; covers small-cap US companies."},
}

# Swing tarayıcının ek evreni (ad, sektör)
SCAN_EXTRA = {
    "MU": ("Micron Technology", "Semiconductors"), "CRWD": ("CrowdStrike", "Software"),
    "LITE": ("Lumentum", "Technology"), "RKLB": ("Rocket Lab", "Aerospace"),
    "MRVL": ("Marvell Technology", "Semiconductors"), "ORCL": ("Oracle", "Software"),
    "QCOM": ("Qualcomm", "Semiconductors"), "TSM": ("Taiwan Semiconductor", "Semiconductors"),
    "ARM": ("Arm Holdings", "Semiconductors"), "PANW": ("Palo Alto Networks", "Software"),
    "NET": ("Cloudflare", "Software"), "JPM": ("JPMorgan Chase", "Financials"),
    "V": ("Visa", "Financials"), "GS": ("Goldman Sachs", "Financials"), "LLY": ("Eli Lilly", "Healthcare"),
    "UNH": ("UnitedHealth", "Healthcare"), "XOM": ("Exxon Mobil", "Energy"),
    "CAT": ("Caterpillar", "Industrials"), "GE": ("GE Aerospace", "Industrials"), "BA": ("Boeing", "Industrials"),
    "WMT": ("Walmart", "Retail"), "HD": ("Home Depot", "Retail"), "NKE": ("Nike", "Consumer"),
    "DIS": ("Disney", "Communication"), "ABNB": ("Airbnb", "Consumer"),
}
SCAN_UNIVERSE = [t for t, c in COMPANIES.items() if c["sector"] != "Index ETF"] + list(SCAN_EXTRA)

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO"]

# Sektör ETF'leri ve en büyük bileşenleri (ticker, kısa ad, yaklaşık ağırlık %)
SECTORS = [
    ("Technology", "XLK", [("NVDA", "NVIDIA", 15.0), ("AAPL", "Apple", 13.0), ("MSFT", "Microsoft", 12.0),
        ("AVGO", "Broadcom", 5.5), ("ORCL", "Oracle", 3.4), ("PLTR", "Palantir", 3.1), ("AMD", "AMD", 2.8),
        ("CSCO", "Cisco", 2.6), ("IBM", "IBM", 2.3), ("CRM", "Salesforce", 2.2), ("MU", "Micron", 2.1),
        ("INTU", "Intuit", 1.9), ("NOW", "ServiceNow", 1.8), ("QCOM", "Qualcomm", 1.6),
        ("AMAT", "Applied Materials", 1.5), ("TXN", "Texas Instruments", 1.5), ("ADBE", "Adobe", 1.4),
        ("LRCX", "Lam Research", 1.3), ("ANET", "Arista Networks", 1.2), ("KLAC", "KLA", 1.1)]),
    ("Semiconductors", "SMH", [("NVDA", "NVIDIA", 20.0), ("TSM", "TSMC", 11.0), ("AVGO", "Broadcom", 8.0),
        ("AMD", "AMD", 5.0), ("ASML", "ASML", 4.5), ("MU", "Micron", 4.5), ("QCOM", "Qualcomm", 4.0),
        ("AMAT", "Applied Materials", 4.0), ("LRCX", "Lam Research", 4.0), ("KLAC", "KLA", 4.0),
        ("TXN", "Texas Instruments", 3.8), ("INTC", "Intel", 3.5), ("ADI", "Analog Devices", 3.3),
        ("MRVL", "Marvell", 2.6), ("ARM", "Arm Holdings", 2.4), ("SNPS", "Synopsys", 2.2), ("CDNS", "Cadence", 2.2)]),
    ("Financials", "XLF", [("BRK-B", "Berkshire Hathaway", 12.0), ("JPM", "JPMorgan Chase", 10.5), ("V", "Visa", 7.8),
        ("MA", "Mastercard", 6.3), ("BAC", "Bank of America", 4.5), ("WFC", "Wells Fargo", 3.6),
        ("GS", "Goldman Sachs", 3.1), ("MS", "Morgan Stanley", 2.6), ("AXP", "American Express", 2.5),
        ("SPGI", "S&P Global", 2.3), ("C", "Citigroup", 2.2), ("SCHW", "Charles Schwab", 2.0),
        ("BLK", "BlackRock", 2.0), ("PGR", "Progressive", 1.9), ("CB", "Chubb", 1.6)]),
    ("Energy", "XLE", [("XOM", "Exxon Mobil", 23.0), ("CVX", "Chevron", 17.0), ("COP", "ConocoPhillips", 7.0),
        ("EOG", "EOG Resources", 4.5), ("WMB", "Williams", 4.5), ("SLB", "Schlumberger", 4.0),
        ("PSX", "Phillips 66", 3.8), ("KMI", "Kinder Morgan", 3.7), ("MPC", "Marathon Petroleum", 3.6),
        ("OKE", "ONEOK", 3.2), ("VLO", "Valero", 3.1), ("OXY", "Occidental", 2.6)]),
    ("Healthcare", "XLV", [("LLY", "Eli Lilly", 13.0), ("JNJ", "Johnson & Johnson", 8.5), ("ABBV", "AbbVie", 7.0),
        ("UNH", "UnitedHealth", 6.0), ("MRK", "Merck", 4.5), ("TMO", "Thermo Fisher", 4.0), ("ABT", "Abbott", 4.0),
        ("ISRG", "Intuitive Surgical", 3.8), ("AMGN", "Amgen", 3.3), ("BSX", "Boston Scientific", 3.0),
        ("DHR", "Danaher", 2.7), ("PFE", "Pfizer", 2.6), ("GILD", "Gilead", 2.5), ("SYK", "Stryker", 2.4)]),
    ("Industrials", "XLI", [("GE", "GE Aerospace", 6.5), ("CAT", "Caterpillar", 5.5), ("RTX", "RTX", 4.8),
        ("UBER", "Uber", 4.0), ("HON", "Honeywell", 3.2), ("BA", "Boeing", 3.1), ("UNP", "Union Pacific", 3.0),
        ("ETN", "Eaton", 3.0), ("DE", "Deere", 2.8), ("LMT", "Lockheed Martin", 2.3), ("ADP", "ADP", 2.3),
        ("GD", "General Dynamics", 1.9), ("WM", "Waste Management", 1.8), ("PH", "Parker-Hannifin", 1.8)]),
    ("Consumer (Discretionary)", "XLY", [("AMZN", "Amazon", 22.0), ("TSLA", "Tesla", 16.0), ("HD", "Home Depot", 6.5),
        ("MCD", "McDonald's", 4.2), ("BKNG", "Booking", 4.0), ("TJX", "TJX", 3.4), ("LOW", "Lowe's", 3.0),
        ("SBUX", "Starbucks", 2.2), ("NKE", "Nike", 2.0), ("ORLY", "O'Reilly", 2.0), ("CMG", "Chipotle", 1.6),
        ("ABNB", "Airbnb", 1.5), ("GM", "General Motors", 1.4), ("MAR", "Marriott", 1.4)]),
    ("Consumer (Staples)", "XLP", [("WMT", "Walmart", 11.0), ("COST", "Costco", 10.0), ("PG", "Procter & Gamble", 8.5),
        ("KO", "Coca-Cola", 6.5), ("PM", "Philip Morris", 6.0), ("PEP", "PepsiCo", 4.5), ("MDLZ", "Mondelez", 3.5),
        ("MO", "Altria", 3.4), ("CL", "Colgate-Palmolive", 3.0), ("KMB", "Kimberly-Clark", 2.0),
        ("TGT", "Target", 2.0), ("KR", "Kroger", 2.0), ("KDP", "Keurig Dr Pepper", 1.8)]),
    ("Utilities", "XLU", [("NEE", "NextEra Energy", 11.0), ("SO", "Southern", 7.5), ("DUK", "Duke Energy", 7.0),
        ("CEG", "Constellation", 6.5), ("VST", "Vistra", 5.0), ("AEP", "AEP", 4.6), ("SRE", "Sempra", 4.0),
        ("D", "Dominion", 3.8), ("EXC", "Exelon", 3.5), ("XEL", "Xcel Energy", 3.3), ("PCG", "PG&E", 3.0),
        ("PEG", "PSEG", 3.0)]),
    ("Materials", "XLB", [("LIN", "Linde", 17.0), ("SHW", "Sherwin-Williams", 7.0), ("ECL", "Ecolab", 6.0),
        ("APD", "Air Products", 5.5), ("NEM", "Newmont", 5.5), ("FCX", "Freeport-McMoRan", 5.0),
        ("CTVA", "Corteva", 4.5), ("MLM", "Martin Marietta", 3.5), ("VMC", "Vulcan Materials", 3.5),
        ("NUE", "Nucor", 3.3), ("DD", "DuPont", 3.0), ("PPG", "PPG", 2.8)]),
    ("Communication", "XLC", [("META", "Meta Platforms", 20.0), ("GOOGL", "Alphabet A", 11.0), ("GOOG", "Alphabet C", 9.0),
        ("NFLX", "Netflix", 7.0), ("TMUS", "T-Mobile", 4.5), ("DIS", "Disney", 4.5), ("T", "AT&T", 4.4),
        ("VZ", "Verizon", 4.3), ("CMCSA", "Comcast", 4.0), ("EA", "Electronic Arts", 3.0),
        ("TTWO", "Take-Two", 2.8), ("CHTR", "Charter", 2.5)]),
    ("Real Estate", "XLRE", [("PLD", "Prologis", 9.0), ("AMT", "American Tower", 8.0), ("WELL", "Welltower", 8.0),
        ("EQIX", "Equinix", 7.0), ("SPG", "Simon Property", 5.0), ("O", "Realty Income", 4.8),
        ("PSA", "Public Storage", 4.3), ("DLR", "Digital Realty", 4.3), ("CCI", "Crown Castle", 4.0),
        ("CBRE", "CBRE", 3.8), ("VICI", "VICI Properties", 3.0), ("EXR", "Extra Space", 2.8)]),
]

_FX_LIST = [
    ("EUR/USD", "EURUSD=X", "Euro / US Dollar", "Majors", 1.16380, 5),
    ("GBP/USD", "GBPUSD=X", "British Pound / US Dollar", "Majors", 1.33520, 5),
    ("USD/JPY", "USDJPY=X", "US Dollar / Japanese Yen", "Majors", 151.284, 3),
    ("USD/CHF", "USDCHF=X", "US Dollar / Swiss Franc", "Majors", 0.79412, 5),
    ("AUD/USD", "AUDUSD=X", "Australian Dollar / US Dollar", "Majors", 0.65518, 5),
    ("USD/CAD", "USDCAD=X", "US Dollar / Canadian Dollar", "Majors", 1.37905, 5),
    ("NZD/USD", "NZDUSD=X", "New Zealand Dollar / US Dollar", "Majors", 0.59840, 5),
    ("EUR/GBP", "EURGBP=X", "Euro / British Pound", "Crosses", 0.87160, 5),
    ("EUR/JPY", "EURJPY=X", "Euro / Japanese Yen", "Crosses", 176.050, 3),
    ("GBP/JPY", "GBPJPY=X", "British Pound / Japanese Yen", "Crosses", 201.980, 3),
    ("AUD/JPY", "AUDJPY=X", "Australian Dollar / Japanese Yen", "Crosses", 99.120, 3),
    ("USD/TRY", "USDTRY=X", "US Dollar / Turkish Lira", "Exotics", 43.1250, 4),
    ("USD/ZAR", "USDZAR=X", "US Dollar / South African Rand", "Exotics", 17.2400, 4),
    ("USD/MXN", "USDMXN=X", "US Dollar / Mexican Peso", "Exotics", 18.3900, 4),
    ("XAU/USD", "GC=F", "Gold / US Dollar", "Metal", 4128.40, 2),
    ("XAG/USD", "SI=F", "Silver / US Dollar", "Metal", 49.880, 3),
]
FX_CATEGORIES = ["All", "Majors", "Crosses", "Exotics", "Metal", "Macro"]

_MACRO = [
    ("Dollar Index", "DXY", "DX-Y.NYB", 98.42, 2),
    ("US 10Y Treasury", "US10Y", "^TNX", 4.38, 2),
    ("Gold", "XAUUSD", "GC=F", 4128.40, 2),
    ("Brent Oil", "UKOIL", "BZ=F", 64.85, 2),
    ("Dollar / TRY", "USDTRY", "USDTRY=X", 43.1250, 4),
    ("Bitcoin", "BTCUSD", "BTC-USD", 108420.0, 0),
]

# Backtest hızlı seçim: (görünen kod, yfinance sembolü, ad)
BT_QUICK = [
    ("AAPL", "AAPL", "Apple Inc."), ("NVDA", "NVDA", "NVIDIA Corp."),
    ("SPX", "^GSPC", "S&P 500"), ("XU100", "XU100.IS", "BIST 100"),
    ("THYAO", "THYAO.IS", "Turkish Airlines"), ("MU", "MU", "Micron Technology"),
    ("EURUSD", "EURUSD=X", "Euro / US Dollar"), ("BTCUSD", "BTC-USD", "Bitcoin"),
]


def _build_names():
    names = {}
    for t, c in COMPANIES.items():
        names[t] = (c["name"], c["sector"])
    for t, (n, s) in SCAN_EXTRA.items():
        names.setdefault(t, (n, s))
    for sname, etf, cons in SECTORS:
        names.setdefault(etf, (f"{sname} sector ETF", "Sector ETF"))
        for t, n, _w in cons:
            names.setdefault(t, (n, sname))
    for p, sym, n, cat, _b, _d in _FX_LIST:
        names.setdefault(sym, (f"{p} · {n}", "Commodities" if cat == "Metal" else "FX"))
    for n, _code, sym, _b, _d in _MACRO:
        names.setdefault(sym, (n, "Macro"))
    for _code, sym, n in BT_QUICK:
        names.setdefault(sym, (n, ""))
    names.setdefault("^VIX", ("CBOE Volatility Index (VIX)", "Index"))
    return names


NAMES = _build_names()
KNOWN = set(NAMES)


def company_name(t):
    return NAMES.get(t, (t, ""))[0]


def company_sector(t):
    return NAMES.get(t, ("", ""))[1]


def logo_url(t):
    """Hisse logoları (Financial Modeling Prep'in açık logo servisi, ticker bazlı).
    Döviz/kripto/endeks sembolleri için boş döner → baş harfler gösterilir."""
    if not t or any(ch in t for ch in "=^") or t.endswith((".IS", "-USD")):
        return ""
    return f"https://financialmodelingprep.com/image-stock/{t.upper()}.png"


def _seed(t):
    return sum(ord(c) for c in str(t)) + 7


# ======================================================================
# Sentetik (mock) fiyat — yalnızca bilinen semboller, veri gelmezse
# ======================================================================
_SYN_BASE = {"SPY": 560.0, "QQQ": 485.0, "DIA": 421.0, "IWM": 228.0, "^GSPC": 5600.0,
             "^VIX": 16.0, "XU100.IS": 10842.0, "THYAO.IS": 312.5, "BTC-USD": 108420.0}
for _p, _sym, _n, _c, _b, _d in _FX_LIST:
    _SYN_BASE.setdefault(_sym, _b)
for _n, _code, _sym, _b, _d in _MACRO:
    _SYN_BASE.setdefault(_sym, _b)

_synth_cache = {}


def _syn_vol(t):
    if t.endswith("=X"):
        return 0.004
    if t == "BTC-USD":
        return 0.03
    if t == "^VIX":
        return 0.05
    if t.startswith("^") or t.endswith(".IS"):
        return 0.012
    return 0.018


def _synth(t):
    if t in _synth_cache:
        return _synth_cache[t]
    rng = np.random.default_rng(_seed(t))
    n = _FULL_DAYS
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    start = _SYN_BASE.get(t, rng.uniform(40, 420))
    vol = _syn_vol(t)
    rets = rng.normal(rng.uniform(-0.0001, 0.0006), vol, n)
    close = start * np.cumprod(1 + rets)
    close = close / close[-1] * start * rng.uniform(0.9, 1.1)
    open_ = close * (1 + rng.normal(0, vol * 0.25, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.35, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.35, n)))
    volume = (rng.integers(2_000_000, 45_000_000, n) if not t.endswith("=X") else np.zeros(n)).astype(float)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)
    df.index.name = "Date"
    df.attrs["src"] = "mock"
    _synth_cache[t] = df
    return df


# ======================================================================
# Düşük seviye çekiciler
# ======================================================================
def _clean_ohlc(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    out = pd.DataFrame(index=df.index)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    out = out.dropna(subset=["Close"])
    for c in ["Open", "High", "Low"]:
        out[c] = out[c].fillna(out["Close"])
    out["Volume"] = out["Volume"].fillna(0.0)
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = idx
    out.index.name = "Date"
    return out


def _split_batch(raw, tickers):
    out = {}
    if raw is None or len(raw) == 0:
        return out
    cols = raw.columns
    if isinstance(cols, pd.MultiIndex):
        l0, l1 = set(cols.get_level_values(0)), set(cols.get_level_values(1))
        for t in tickers:
            try:
                if t in l0:
                    sub = raw.xs(t, axis=1, level=0)
                elif t in l1:
                    sub = raw.xs(t, axis=1, level=1)
                else:
                    continue
            except Exception:
                continue
            sub = _clean_ohlc(sub)
            if len(sub):
                out[t] = sub
    elif len(tickers) == 1:
        sub = _clean_ohlc(raw)
        if len(sub):
            out[tickers[0]] = sub
    return out


def _download(tickers, period="5d", interval="1d"):
    """TEK istekte çok sembol (Yahoo rate-limit'ine karşı en etkili yöntem)."""
    tickers = list(tickers)
    if not (_HAS_YF and tickers):
        return {}
    try:
        raw = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                          auto_adjust=False, progress=False, threads=True)
    except Exception:
        return {}
    return _split_batch(raw, tickers)


@_ttl_cache(240, fail_ttl=60)
def _batch_short(tickers, period="5d", interval="1d"):
    return _download(tickers, period, interval)


@_ttl_cache(1800, fail_ttl=120)
def _batch_long(tickers, period="1mo"):
    return _download(tickers, period, "1d")


@_ttl_cache(3600, fail_ttl=120)
def get_history_max(t):
    """Tüm günlük geçmiş (lookback = MAX). Gelmezse ~6 yıllık geçmişe düşer."""
    if _HAS_YF:
        try:
            df = _clean_ohlc(yf.Ticker(t).history(period="max", auto_adjust=False))
            if len(df) > 30:
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    return get_history(t)


@_ttl_cache(1800, fail_ttl=90)
def get_history(t):
    """~6 yıllık günlük OHLCV. Gerçek → bilinen sembolde mock → yoksa boş."""
    if _HAS_YF:
        try:
            df = _clean_ohlc(yf.Ticker(t).history(period="6y", auto_adjust=False))
            if len(df) > 30:
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    if t in KNOWN:
        df = _synth(t).copy()
        df.attrs["src"] = "mock"
        return df
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df.attrs["src"] = "none"
    return df


def get_ohlc(t, days=180):
    df = get_history(t)
    out = df.tail(days).copy()
    out.attrs = dict(df.attrs)
    return out


_INTRA_MIN = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "90m": 90}
_PERIOD_DAYS = {"1d": 1, "2d": 2, "5d": 5, "7d": 5, "1mo": 22, "60d": 42, "3mo": 66, "6mo": 126, "1y": 252,
                "2y": 504, "730d": 504}


def _synth_intraday(t, period="5d", interval="5m"):
    key = ("intra", t, period, interval)
    if key in _synth_cache:
        return _synth_cache[key]
    mins = _INTRA_MIN.get(interval, 5)
    daily = _synth(t)
    n_days = min(_PERIOD_DAYS.get(period, 5), len(daily))
    allday = t.endswith(("=X", "=F", "-USD"))
    per = (24 * 60 if allday else 390) // mins
    start_h = 0.0 if allday else 9.5
    rng = np.random.default_rng(_seed(t) + mins * 31 + n_days)
    idx = []
    for d in daily.index[-n_days:]:
        base = pd.Timestamp(d).normalize() + pd.Timedelta(hours=start_h)
        idx.extend(base + pd.Timedelta(minutes=mins * k) for k in range(per))
    n = len(idx)
    vol = _syn_vol(t) / np.sqrt(per)
    close = np.cumprod(1 + rng.normal(0, vol, n))
    close = close / close[-1] * float(daily["Close"].iloc[-1])
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, vol * 0.2, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.4, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.4, n)))
    volume = (np.zeros(n) if t.endswith("=X") else rng.integers(20_000, 900_000, n)).astype(float)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
                      index=pd.DatetimeIndex(idx, name="Date"))
    df.attrs["src"] = "mock"
    _synth_cache[key] = df
    return df


@_ttl_cache(180, fail_ttl=60)
def get_intraday(t, period="5d", interval="5m"):
    """Gün içi mumlar (1G / 1H grafikleri için). Gerçek → bilinen sembolde mock → boş."""
    if _HAS_YF:
        try:
            df = _clean_ohlc(yf.Ticker(t).history(period=period, interval=interval, auto_adjust=False))
            if len(df) > 10:
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    if t in KNOWN:
        df = _synth_intraday(t, period, interval).copy()
        df.attrs["src"] = "mock"
        return df
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df.attrs["src"] = "none"
    return df


def add_emas(df, periods=(20, 50, 100, 200)):
    out = df.copy()
    for p in periods:
        out[f"EMA{p}"] = out["Close"].ewm(span=p, adjust=False).mean()
    out.attrs = dict(df.attrs)
    return out


# ======================================================================
# Fiyat özetleri (toplu)
# ======================================================================
def get_quotes(tickers):
    """{ticker: {last, prev, change_pct, src, ...}} — tek toplu istekle."""
    ticks = tuple(dict.fromkeys(t for t in tickers if t))
    if not ticks:
        return {}
    data = _batch_short(tuple(sorted(ticks)), "5d", "1d")
    out = {}
    for t in ticks:
        df = data.get(t)
        if df is not None and len(df) >= 2:
            last, prev, src = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2]), "real"
            vol = float(df["Volume"].iloc[-1]) if "Volume" in df else 0.0
        elif t in KNOWN:
            s = _synth(t)
            last, prev, src = float(s["Close"].iloc[-1]), float(s["Close"].iloc[-2]), "mock"
            vol = float(s["Volume"].iloc[-1])
        else:
            continue
        name, sector = NAMES.get(t, (t, ""))
        out[t] = {"ticker": t, "name": name, "sector": sector, "last": last, "prev": prev,
                  "volume": vol, "change_pct": (last / prev - 1) * 100 if prev else 0.0, "src": src}
    return out


def get_quote(t):
    q = get_quotes([t]).get(t)
    if q:
        return q
    return {"ticker": t, "name": company_name(t), "sector": "", "last": float("nan"),
            "prev": float("nan"), "change_pct": 0.0, "src": "none"}


_INDEX_SPECS = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow Jones"), ("IWM", "Russell 2000")]


def _mock_index_item(t, sub):
    s = _synth(t)
    series = (s["Close"].iloc[-1] * np.cumprod(1 + np.random.default_rng(_seed(t)).normal(0, 0.0013, 78))).tolist()
    prev = float(s["Close"].iloc[-2])
    return {"ticker": t, "subtitle": sub, "prev_close": prev, "last": float(series[-1]),
            "change_pct": (series[-1] / prev - 1) * 100, "series": series, "src": "mock"}


@_ttl_cache(240, fail_ttl=60)
def get_index_summary():
    ticks = tuple(t for t, _ in _INDEX_SPECS)
    q = get_quotes(ticks)
    intr = _batch_short(tuple(sorted(ticks)), "1d", "5m")
    out = []
    for t, sub in _INDEX_SPECS:
        qq = q.get(t)
        if qq and qq["src"] == "real":
            s = intr.get(t)
            series = [float(x) for x in s["Close"].tolist()][-90:] if s is not None and len(s) > 3 \
                else [qq["prev"], qq["last"]]
            out.append({"ticker": t, "subtitle": sub, "prev_close": qq["prev"], "last": qq["last"],
                        "change_pct": qq["change_pct"], "series": series, "src": "real"})
        else:
            out.append(_mock_index_item(t, sub))
    return out


# ======================================================================
# Şirket / sembol detayı
# ======================================================================
def _fi_get(fi, *names):
    for n in names:
        v = None
        try:
            v = getattr(fi, n)
        except Exception:
            try:
                v = fi[n]
            except Exception:
                v = None
        v2 = _num(v) if not isinstance(v, str) else v
        if v2 not in (None, ""):
            return v2
    return None


def _ts(v):
    if v in (None, "", 0):
        return None
    try:
        f = float(v)
        return pd.Timestamp(f, unit="s") if f > 1e8 else None
    except (TypeError, ValueError):
        try:
            return pd.Timestamp(v)
        except Exception:
            return None


def _type_desc(qt, name):
    qt = (qt or "").upper()
    return {"CURRENCY": f"{name} exchange rate.", "CRYPTOCURRENCY": f"{name} — cryptocurrency.",
            "INDEX": f"{name} index.", "FUTURE": f"{name} — futures contract (commodity/financial).",
            "ETF": f"{name} — exchange-traded fund (ETF).", "MUTUALFUND": f"{name} — investment fund."}.get(qt, "")


def _real_detail(t):
    tk = yf.Ticker(t)
    fi = tk.fast_info
    last = _fi_get(fi, "last_price")
    prev = _fi_get(fi, "previous_close", "regular_market_previous_close")
    try:
        info = tk.get_info() or {}
    except Exception:
        info = {}
    if last is None:
        last = _num(_g(info, "currentPrice", "regularMarketPrice"))
    if prev is None:
        prev = _num(_g(info, "previousClose", "regularMarketPreviousClose"))
    if last is None or prev is None:
        return None
    base = COMPANIES.get(t, {})
    name = base.get("name") or _g(info, "shortName", "longName") or company_name(t)
    qt = _fi_get(fi, "quote_type") or _g(info, "quoteType", default="")
    pe, fpe = _num(_g(info, "trailingPE")), _num(_g(info, "forwardPE"))
    eps, pt = _num(_g(info, "trailingEps")), _num(_g(info, "targetMeanPrice"))
    div_rate = _num(_g(info, "dividendRate", "trailingAnnualDividendRate")) or 0.0
    nan = float("nan")
    return {
        "ticker": t, "name": name, "sector": base.get("sector") or _g(info, "sector", default="") or company_sector(t),
        "industry": _g(info, "industry", default="") or "", "country": _g(info, "country", default="") or "",
        "website": _g(info, "website", default="") or "", "employees": _g(info, "fullTimeEmployees"),
        "desc": base.get("desc", "") or _type_desc(qt, name),
        "summary_en": _g(info, "longBusinessSummary", "description", default="") or "",
        "quote_type": qt, "currency": _fi_get(fi, "currency") or _g(info, "currency", default="USD"),
        "exchange": _fi_get(fi, "exchange") or _g(info, "exchange", default=""),
        "last": float(last), "prev_close": float(prev), "change_abs": float(last) - float(prev),
        "change_pct": (float(last) / float(prev) - 1) * 100 if prev else 0.0,
        "market_cap": _fi_get(fi, "market_cap") or _num(_g(info, "marketCap")) or nan,
        "revenue": _num(_g(info, "totalRevenue")) or nan,
        "net_income": _num(_g(info, "netIncomeToCommon")) or nan,
        "eps": eps if eps is not None else nan,
        "shares_out": _fi_get(fi, "shares") or _num(_g(info, "sharesOutstanding")) or nan,
        "pe": pe if pe is not None else nan, "fwd_pe": fpe if fpe is not None else nan,
        "dividend": div_rate, "div_yield": (div_rate / float(last) * 100) if div_rate and last else 0.0,
        "ex_div_date": _ts(_g(info, "exDividendDate")),
        "volume": int(_fi_get(fi, "last_volume") or _num(_g(info, "volume", "regularMarketVolume")) or 0),
        "open": _fi_get(fi, "open") or float(last), "day_low": _fi_get(fi, "day_low") or float(last),
        "day_high": _fi_get(fi, "day_high") or float(last),
        "low_52w": _fi_get(fi, "year_low") or _num(_g(info, "fiftyTwoWeekLow")) or float(last),
        "high_52w": _fi_get(fi, "year_high") or _num(_g(info, "fiftyTwoWeekHigh")) or float(last),
        "beta": _num(_g(info, "beta")) or nan,
        "analysts": str(_g(info, "recommendationKey", default="") or "").replace("_", " ").title() or "—",
        "price_target": pt if pt is not None else nan,
        "target_upside": ((pt / float(last) - 1) * 100) if pt else nan,
        "earnings_date": _ts(_g(info, "earningsTimestamp", "earningsTimestampStart")),
        "src": "real",
    }


def _mock_detail(t):
    s = _synth(t)
    last, prev = float(s["Close"].iloc[-1]), float(s["Close"].iloc[-2])
    rng = np.random.default_rng(_seed(t) + 99)
    shares = rng.uniform(0.2, 16.0) * 1e9
    pe = float(rng.uniform(9, 42))
    has_div = bool(rng.random() < 0.55)
    div = float(rng.uniform(0.4, 3.2)) if has_div else 0.0
    today = pd.Timestamp.today().normalize()
    base = COMPANIES.get(t, {})
    name, sector = NAMES.get(t, (t, ""))
    qt = "CURRENCY" if t.endswith("=X") else "CRYPTOCURRENCY" if t.endswith("-USD") else \
        "INDEX" if t.startswith("^") else "FUTURE" if t.endswith("=F") else "EQUITY"
    mc = last * shares
    return {
        "ticker": t, "name": base.get("name", name), "sector": base.get("sector", sector), "industry": "",
        "country": "", "website": "", "employees": None, "desc": base.get("desc", "") or _type_desc(qt, name),
        "summary_en": "", "quote_type": qt, "currency": "TRY" if t.endswith(".IS") else "USD", "exchange": "",
        "last": last, "prev_close": prev, "change_abs": last - prev, "change_pct": (last / prev - 1) * 100,
        "market_cap": mc, "revenue": mc * rng.uniform(0.08, 0.6), "net_income": mc * rng.uniform(0.01, 0.1),
        "eps": last / pe, "shares_out": shares, "pe": pe, "fwd_pe": pe * rng.uniform(0.82, 0.98),
        "dividend": div, "div_yield": div / last * 100 if div else 0.0,
        "ex_div_date": today - pd.Timedelta(days=int(rng.integers(5, 60))) if has_div else None,
        "volume": int(s["Volume"].iloc[-1]), "open": float(s["Open"].iloc[-1]),
        "day_low": float(s["Low"].iloc[-1]), "day_high": float(s["High"].iloc[-1]),
        "low_52w": float(s["Low"].tail(252).min()), "high_52w": float(s["High"].tail(252).max()),
        "beta": float(rng.uniform(0.55, 1.9)), "analysts": str(rng.choice(["Strong Buy", "Buy", "Hold"])),
        "price_target": last * (1 + rng.uniform(0.05, 0.3)), "target_upside": float(rng.uniform(5, 30)),
        "earnings_date": today + pd.Timedelta(days=int(rng.integers(5, 70))), "src": "mock",
    }


@_ttl_cache(1800, fail_ttl=90)
def get_company_detail(t):
    """Gerçek detay; alınamazsa bilinen sembolde mock; bilinmeyen sembolde None."""
    if _HAS_YF:
        try:
            d = _real_detail(t)
            if d:
                return d
        except Exception:
            pass
    return _mock_detail(t) if t in KNOWN else None


# ======================================================================
# Haberler (gerçek: yfinance) + başlık duyarlılığı
# ======================================================================
_POS = re.compile(r"\b(surg\w*|soar\w*|jump\w*|rall\w*|gain\w*|rise[sn]?|rising|climb\w*|beat[s]?|record|"
                  r"upgrad\w*|bullish|strong\w*|boost\w*|higher|tops?|outperform\w*|rebound\w*|recover\w*)\b", re.I)
_NEG = re.compile(r"\b(plung\w*|slump\w*|fall[s]?|fallen|fell|drop\w*|sink[s]?|sank|tumbl\w*|miss\w*|cut[s]?|"
                  r"downgrad\w*|bearish|weak\w*|lower|loss\w*|slid\w*|warn\w*|fear\w*|crash\w*|declin\w*|"
                  r"pressure|sell-?off)\b", re.I)


def _sentiment(text):
    p, n = len(_POS.findall(text or "")), len(_NEG.findall(text or ""))
    return "Bullish" if p > n else "Bearish" if n > p else "Neutral"


def _age(ts):
    if not ts:
        return 60, "1 h ago", "1 h"
    mins = max(1, int((time.time() - float(ts)) / 60))
    if mins < 60:
        return mins, f"{mins} min ago", f"{mins} min"
    if mins < 1440:
        return mins, f"{mins // 60} h ago", f"{mins // 60} h"
    return mins, f"{mins // 1440} d ago", f"{mins // 1440} d"


def _thumb_url(th):
    try:
        res = sorted(th.get("resolutions") or [], key=lambda r: r.get("width", 0))
        for r in res:
            if r.get("width", 0) >= 300:
                return r.get("url")
        return (res[-1].get("url") if res else None) or th.get("originalUrl")
    except Exception:
        return None


def _parse_news_item(it, ticker=None):
    if not isinstance(it, dict):
        return None
    c = it.get("content") if isinstance(it.get("content"), dict) else None
    try:
        if c:
            title = c.get("title")
            pub_src = (c.get("provider") or {}).get("displayName")
            pub = c.get("pubDate") or c.get("displayTime")
            ts = pd.Timestamp(pub).timestamp() if pub else None
            link = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
            thumb = _thumb_url(c.get("thumbnail") or {}) if c.get("thumbnail") else None
            summary = c.get("summary") or ""
            related = [x.get("symbol") for x in ((c.get("finance") or {}).get("stockTickers") or [])
                       if isinstance(x, dict) and x.get("symbol")]
        else:
            title = it.get("title")
            pub_src = it.get("publisher")
            ts = it.get("providerPublishTime")
            link = it.get("link")
            thumb = _thumb_url(it.get("thumbnail") or {}) if it.get("thumbnail") else None
            summary = it.get("summary") or ""
            related = list(it.get("relatedTickers") or [])
    except Exception:
        return None
    if not title:
        return None
    mins, when, short = _age(ts)
    return {"ticker": ticker or (related[0] if related else ""), "title": title,
            "source": pub_src or "Yahoo Finance", "when": when, "when_short": short, "age_min": mins,
            "hours_ago": max(1, mins // 60), "sentiment": _sentiment(title + " " + summary),
            "link": link, "thumb": thumb, "summary": summary, "related": related, "src": "real"}


@_ttl_cache(900, fail_ttl=180)
def get_company_news(t, n=6):
    """Yalnızca gerçek kaynaklar: yfinance → Yahoo RSS → Google News RSS."""
    items = []
    if _HAS_YF:
        try:
            raw = yf.Ticker(t).news or []
            items = [p for p in (_parse_news_item(x, t) for x in raw) if p]
        except Exception:
            items = []
    if len(items) < n:
        items = items + _yahoo_rss(t, n * 2)
    if len(items) < n:
        items = items + _google_rss(f'"{company_name(t)}" OR {t} stock', n * 2, t)
    return _dedupe_news(items, n)


def get_watchlist_news(tickers, per_ticker=3, max_tickers=5):
    out = []
    for lst in _pmap(lambda t: get_company_news(t, n=per_ticker), list(tickers)[:max_tickers], workers=5):
        out.extend(lst)
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: x["age_min"]):
        k = x["title"].strip().lower()
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


@_ttl_cache(900, fail_ttl=180)
def _search_news(query, n=10):
    """Konu bazlı haber: yfinance araması → Google News RSS."""
    out = []
    if _HAS_YF:
        try:
            raw = yf.Search(query, max_results=1, news_count=n).news or []
            out = [p for p in (_parse_news_item(x) for x in raw) if p]
        except Exception:
            out = []
    if len(out) < max(3, n // 2):
        out = out + _google_rss(query, n)
    return out


NEWS_CATEGORIES = ["All", "Forex", "Central Banks", "Commodities", "Turkey"]
_NEWS_Q = {"Forex": ["forex dollar euro currency"], "Central Banks": ["Federal Reserve ECB central bank rates"],
           "Commodities": ["gold oil prices commodities"], "Turkey": ["Turkey lira Turkish central bank"]}
_YF2PAIR = {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "JPY=X": "USD/JPY",
            "USDCHF=X": "USD/CHF", "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD", "CAD=X": "USD/CAD",
            "USDTRY=X": "USD/TRY", "TRY=X": "USD/TRY", "GC=F": "XAU/USD", "SI=F": "XAG/USD",
            "CL=F": "WTI", "BZ=F": "UKOIL", "DX-Y.NYB": "DXY", "BTC-USD": "BTC/USD"}
_CAT_SYM = {"Forex": "EURUSD=X", "Central Banks": "DX-Y.NYB", "Commodities": "GC=F", "Turkey": "USDTRY=X"}

@_ttl_cache(900, fail_ttl=120)
def get_forex_news(category="All"):
    cats = [c for c in NEWS_CATEGORIES if c != "All"] if category == "All" else [category]
    items = []
    for cat in cats:
        for q in _NEWS_Q.get(cat, []):
            for p in _search_news(q, 8):
                p = dict(p)
                p["category"] = cat
                items.append(p)
    seen, uniq = set(), []
    for p in sorted(items, key=lambda x: x["age_min"]):
        k = p["title"].strip().lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    if not uniq:
        return {"featured": None, "items": [], "src": "none"}
    for p in uniq:
        sym = next((r for r in p.get("related", []) if r in _YF2PAIR), None) or _CAT_SYM.get(p["category"])
        p["pair"], p["spark_sym"] = _YF2PAIR.get(sym, sym or p["category"]), sym
    syms = tuple(sorted({p["spark_sym"] for p in uniq if p.get("spark_sym")}))
    hist = _batch_long(syms, "1mo") if syms else {}
    for p in uniq:
        h = hist.get(p.get("spark_sym"))
        p["spark"] = [float(x) for x in h["Close"].tolist()][-24:] if h is not None and len(h) > 3 else [1.0, 1.0]
    fi = next((i for i, p in enumerate(uniq) if p.get("thumb")), 0)
    f = uniq[fi]
    tags = [f["pair"]] + [_YF2PAIR.get(r, r) for r in f.get("related", [])[:3] if _YF2PAIR.get(r, r) != f["pair"]]
    featured = {"title": f["title"], "summary": f.get("summary") or "", "category": f["category"],
                "sentiment": f["sentiment"], "source": f["source"], "when": f["when_short"],
                "tags": tags[:3], "link": f.get("link"), "thumb": f.get("thumb")}
    rest = [{"title": p["title"], "pair": p["pair"], "sentiment": p["sentiment"], "category": p["category"],
             "when": p["when_short"], "source": p["source"], "spark": p["spark"], "link": p.get("link"),
             "thumb": p.get("thumb")}
            for i, p in enumerate(uniq) if i != fi][:8]
    return {"featured": featured, "items": rest, "src": "real"}


# ======================================================================
# Ekonomik takvim (ForexFactory haftalık JSON → TradingEconomics → mock)
# ======================================================================
CAL_DAYS = ["Yesterday", "Today", "Tomorrow", "This Week"]
CAL_IMPACTS = ["All", "High", "Medium +"]
_TR_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_TR_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]
_IMPACT_N = {"high": 3, "medium": 2, "low": 1}
_COUNTRY_CUR = {"united states": "USD", "euro area": "EUR", "germany": "EUR", "france": "EUR",
                "italy": "EUR", "united kingdom": "GBP", "japan": "JPY", "canada": "CAD",
                "australia": "AUD", "switzerland": "CHF", "china": "CNY", "new zealand": "NZD",
                "turkey": "TRY"}
_CAL_MOCK = [
    ("08:00", "EUR", 2, "Germany GfK Consumer Confidence", "-22.4", "-21.8", "-22.3"),
    ("10:00", "EUR", 3, "Eurozone Manufacturing PMI", "49.9", "49.6", "49.8"),
    ("10:30", "GBP", 3, "UK Services PMI", "50.4", "51.0", "50.8"),
    ("14:00", "TRY", 3, "CBRT Rate Decision", "—", "38.50%", "40.50%"),
    ("14:30", "USD", 3, "Initial Jobless Claims", "—", "232K", "228K"),
    ("16:00", "USD", 1, "Existing Home Sales", "—", "4.06M", "4.00M"),
]


def tr_date_label(ts):
    return f"{_TR_DAYS[ts.weekday()]} · {_TR_MON[ts.month - 1]} {ts.day}"


@_ttl_cache(1800, fail_ttl=300)
def _calendar_all():
    rows = []
    if _HAS_REQ:
        try:
            r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                             headers=_HEADERS, timeout=12)
            for ev in r.json():
                imp = _IMPACT_N.get(str(ev.get("impact", "")).lower())
                if not imp:
                    continue
                dt = pd.Timestamp(ev.get("date"))
                dt = (dt.tz_localize("UTC") if dt.tzinfo is None else dt).tz_convert(TZ)
                rows.append({"dt": dt, "time": dt.strftime("%H:%M"), "cur": str(ev.get("country", "")).upper(),
                             "impact": imp, "event": ev.get("title", ""),
                             "actual": str(ev.get("actual") or "—"), "forecast": str(ev.get("forecast") or "—"),
                             "previous": str(ev.get("previous") or "—"), "src": "real"})
        except Exception:
            rows = []
    if not rows and _HAS_REQ:
        try:
            today = pd.Timestamp.now(tz=TZ).normalize()
            r = requests.get("https://api.tradingeconomics.com/calendar",
                             params={"c": "guest:guest", "format": "json",
                                     "d1": (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                     "d2": (today + pd.Timedelta(days=6)).strftime("%Y-%m-%d")},
                             headers=_HEADERS, timeout=12)
            for ev in r.json():
                cur = _COUNTRY_CUR.get(str(ev.get("Country", "")).lower())
                imp = ev.get("Importance")
                if cur is None or not imp:
                    continue
                dt = pd.Timestamp(ev.get("Date"))
                dt = (dt.tz_localize("UTC") if dt.tzinfo is None else dt).tz_convert(TZ)
                rows.append({"dt": dt, "time": dt.strftime("%H:%M"), "cur": cur, "impact": int(imp),
                             "event": ev.get("Event", ""), "actual": str(ev.get("Actual") or "—"),
                             "forecast": str(ev.get("Forecast") or "—"),
                             "previous": str(ev.get("Previous") or "—"), "src": "real"})
        except Exception:
            rows = []
    if not rows:
        today = pd.Timestamp.now(tz=TZ).normalize()
        for t, cur, imp, ev, a, f, p in _CAL_MOCK:
            hh, mm = map(int, t.split(":"))
            rows.append({"dt": today + pd.Timedelta(hours=hh, minutes=mm), "time": t, "cur": cur,
                         "impact": imp, "event": ev + " (sample)", "actual": a, "forecast": f,
                         "previous": p, "src": "mock"})
    rows.sort(key=lambda x: x["dt"])
    return rows


# --- v3.8: para birimi filtresi + açıklanan değer (Actual) ---------------------------------------
CAL_CCYS = [("USD", "🇺🇸", "US Dollar"), ("EUR", "🇪🇺", "Euro"), ("GBP", "🇬🇧", "British Pound"),
            ("JPY", "🇯🇵", "Japanese Yen"), ("CHF", "🇨🇭", "Swiss Franc"), ("CAD", "🇨🇦", "Canadian Dollar"),
            ("AUD", "🇦🇺", "Australian Dollar"), ("NZD", "🇳🇿", "New Zealand Dollar"), ("CNY", "🇨🇳", "Chinese Yuan"),
            ("TRY", "🇹🇷", "Turkish Lira")]
CAL_MAJORS = ["USD", "EUR", "GBP", "JPY"]
CCY_FLAG = {c: f for c, f, _ in CAL_CCYS}
_TV_CCY = {"US": "USD", "EU": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "GB": "GBP", "UK": "GBP",
           "JP": "JPY", "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CN": "CNY", "TR": "TRY"}
_TV_URL = "https://economic-calendar.tradingview.com/events"
# FF ile TradingView başlıkları farklı yazılıyor — eşleştirme için ortak sözcüklere çevrilir
_CAL_SYN = [(r"non[\s-]*farm (employment change|payrolls)", "nfp"), (r"\bcpi\b|consumer price index|inflation rate",
            "cpi"), (r"\bppi\b|producer price index", "ppi"), (r"\bgdp\b|gross domestic product", "gdp"),
            (r"\bpmi\b|purchasing managers", "pmi"), (r"\bm/m\b|\bmom\b|month over month", "mom"),
            (r"\by/y\b|\byoy\b|year over year", "yoy"), (r"\bq/q\b|\bqoq\b|quarter over quarter", "qoq"),
            (r"(initial |continuing )?(jobless|unemployment) claims|initial claims", "claims"),
            (r"interest rate decision|rate decision|"
            r"official bank rate|cash rate|federal funds rate|refinancing rate|policy rate", "ratedec"),
            (r"unemployment rate|jobless rate", "unemp"), (r"retail sales", "retail"),
            (r"average hourly earnings", "ahe"), (r"crude oil (inventories|stocks)", "crude")]
_CAL_STOP = {"the", "of", "and", "s", "a", "final", "prelim", "preliminary", "flash", "sa", "nsa", "change", "index",
             "rate", "us", "uk", "eu", "german", "germany", "french", "france", "italian", "euro", "area", "zone",
             "eurozone", "japan", "japanese", "canada", "canadian", "australia", "australian", "chinese", "china",
             "swiss", "new", "zealand", "initial"}
_CAL_INVERSE = re.compile(r"unemploy|jobless|claims|claimant|inventor", re.I)


def _cal_tokens(title):
    t = str(title or "").lower()
    for pat, rep_ in _CAL_SYN:
        t = re.sub(pat, " " + rep_ + " ", t)
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in _CAL_STOP}


def cal_num(v):
    """'0.3%', '-45.3B', '232K', '<0.10%' → sayı (K/M/B/T çarpanlarıyla). Okunamazsa None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    t = str(v).strip().replace(",", "").replace("−", "-").lstrip("<>~≈ ")
    m = re.match(r"^([+-]?\d*\.?\d+)\s*([KMBT]?)\s*%?$", t, re.I)
    if not m:
        return None
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]


def cal_eval(event, actual, forecast):
    """Açıklanan değer beklentiden iyi mi (+1), kötü mü (-1), aynı mı (0)? İşsizlik / başvuru gibi
    göstergelerde düşük değer iyidir. Karşılaştırılamazsa None."""
    a, f = cal_num(actual), cal_num(forecast)
    if a is None or f is None:
        return None
    if abs(a - f) <= 1e-12 * max(1.0, abs(f)):
        return 0
    better = a > f
    if _CAL_INVERSE.search(str(event or "")):
        better = not better
    return 1 if better else -1


def _tv_fmt(v, unit, scale):
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    try:
        x = float(v)
        txt = (f"{x:.2f}".rstrip("0").rstrip(".") if abs(x) < 1000 else f"{x:,.0f}")
    except (TypeError, ValueError):
        txt = str(v)
    sc = str(scale or "").strip().upper()
    sc = sc if sc in ("K", "M", "B", "T") else ""
    un = "%" if str(unit or "").strip() == "%" else ""
    return f"{txt}{sc}{un}"


@_ttl_cache(120, fail_ttl=90)
def _tv_calendar():
    """TradingView ekonomik takvimi (açıklanan değerler dahil) — bu hafta ± 1 gün. Resmi olmayan uç."""
    if not _HAS_REQ:
        return []
    now = pd.Timestamp.now(tz="UTC")
    d1 = (now.normalize() - pd.Timedelta(days=now.weekday() + 1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d2 = (now.normalize() + pd.Timedelta(days=8 - now.weekday())).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        r = requests.get(_TV_URL, params={"from": d1, "to": d2, "countries": ",".join(_TV_CCY)},
                         headers={**_HEADERS, "Origin": "https://www.tradingview.com",
                                  "Referer": "https://www.tradingview.com/"}, timeout=12)
        js = r.json()
    except Exception:
        return []
    items = js.get("result") if isinstance(js, dict) else js
    out = []
    for ev in items or []:
        try:
            cur = str(ev.get("currency") or _TV_CCY.get(str(ev.get("country", "")).upper(), "")).upper()
            if not cur:
                continue
            dt = pd.Timestamp(ev.get("date"))
            dt = (dt.tz_localize("UTC") if dt.tzinfo is None else dt).tz_convert(TZ)
            unit, scale = ev.get("unit"), ev.get("scale")
            out.append({"dt": dt, "cur": cur, "event": str(ev.get("title") or ev.get("indicator") or ""),
                        "actual": _tv_fmt(ev.get("actual"), unit, scale),
                        "forecast": _tv_fmt(ev.get("forecast"), unit, scale),
                        "previous": _tv_fmt(ev.get("previous"), unit, scale),
                        "impact": {1: 3, 0: 2, -1: 1}.get(int(ev.get("importance") or 0), 2) if
                        str(ev.get("importance", "")).lstrip("-").isdigit() else 2})
        except Exception:
            continue
    return out


def _attach_actuals(rows):
    """ForexFactory satırlarına açıklanan değeri ekler: aynı para birimi, ±75 dk, başlık benzerliği
    (ve varsa aynı beklenti). Eşleşme yoksa satır olduğu gibi kalır."""
    tv = _tv_calendar()
    if not tv:
        return rows, False
    used = set()
    for r in rows:
        if r.get("src") != "real":
            continue
        if cal_num(r.get("actual")) is not None:
            continue
        rt = _cal_tokens(r["event"])
        best, bs = None, 0.0
        for j, t in enumerate(tv):
            if j in used or t["cur"] != r["cur"] or abs((t["dt"] - r["dt"]).total_seconds()) > 75 * 60:
                continue
            tt = _cal_tokens(t["event"])
            sc = len(rt & tt) / max(1, len(rt | tt))
            # dönem eki (mom / yoy / qoq) farklıysa eşleşme değil
            per_r, per_t = rt & {"mom", "yoy", "qoq"}, tt & {"mom", "yoy", "qoq"}
            if per_r and per_t and per_r != per_t:
                continue
            fr, ft = cal_num(r.get("forecast")), cal_num(t.get("forecast"))
            if fr is not None and ft is not None and abs(fr - ft) <= max(abs(fr) * 0.02, 1e-9):
                sc += 0.35
            if sc > bs:
                best, bs = j, sc
        if best is not None and bs >= 0.34:
            used.add(best)
            t = tv[best]
            if t.get("actual") is not None:
                r["actual"] = t["actual"]
                r["actual_src"] = "TradingView"
            if r.get("forecast") in ("—", "", None) and t.get("forecast"):
                r["forecast"] = t["forecast"]
    return rows, True


def get_calendar_rows(day="Today", impact="All", ccys=None):
    base = _calendar_all()
    tv_ok = False
    if base and base[0].get("src") == "real":
        rows = [dict(r) for r in base]
        rows, tv_ok = _attach_actuals(rows)
    elif not base or base[0].get("src") == "mock":
        tv = _tv_calendar()
        if tv:                                   # ForexFactory yoksa takvimin kendisi TradingView'den
            rows = [{**t, "time": t["dt"].strftime("%H:%M"), "actual": t["actual"] or "—",
                     "forecast": t["forecast"] or "—", "previous": t["previous"] or "—", "src": "real",
                     "actual_src": "TradingView"} for t in sorted(tv, key=lambda x: x["dt"])]
            tv_ok = True
        else:
            rows = [dict(r) for r in base]
    else:
        rows = [dict(r) for r in base]
    now = pd.Timestamp.now(tz=TZ)
    today = now.normalize()
    target = {"Yesterday": today - pd.Timedelta(days=1), "Today": today, "Tomorrow": today + pd.Timedelta(days=1)}.get(day)
    if target is not None:
        rows = [r for r in rows if r["dt"].normalize() == target]
    if impact == "High":
        rows = [r for r in rows if r["impact"] >= 3]
    elif impact == "Medium +":
        rows = [r for r in rows if r["impact"] >= 2]
    if ccys is not None:
        cs = set(ccys)
        rows = [r for r in rows if r["cur"] in cs or (r["cur"] in ("ALL", "") and cs)]
    nxt = next((r for r in rows if r["dt"] >= now), None)
    out = []
    for r in rows:
        rr = dict(r)
        rr["next"] = r is nxt
        rr["day_label"] = tr_date_label(r["dt"])
        has_a = cal_num(rr.get("actual")) is not None or (rr.get("actual") not in (None, "", "—"))
        if has_a:
            rr["state"] = "released"
            rr["eval"] = cal_eval(rr["event"], rr.get("actual"), rr.get("forecast"))
        elif rr["dt"] <= now:
            rr["state"] = "pending" if (now - rr["dt"]) < pd.Timedelta(hours=3) else "n/a"
        else:
            rr["state"] = "upcoming"
        rr["tv_ok"] = tv_ok
        out.append(rr)
    return out


# ======================================================================
# Makro şerit, pariteler
# ======================================================================
def _series_or_synth(hist, sym, n=40):
    h = hist.get(sym)
    if h is not None and len(h) > 3:
        return [float(x) for x in h["Close"].tolist()][-n:]
    return [float(x) for x in _synth(sym)["Close"].tolist()][-n:]


@_ttl_cache(300, fail_ttl=60)
def get_macro_strip():
    syms = tuple(sorted(sym for _, _, sym, _, _ in _MACRO))
    q = get_quotes(syms)
    hist = _batch_long(syms, "1mo")
    out = []
    for name, code, sym, base, dec in _MACRO:
        qq = q.get(sym) or {"last": base, "change_pct": 0.0, "src": "none"}
        out.append({"name": name, "code": code, "symbol": sym, "value": qq["last"],
                    "change_pct": qq["change_pct"], "series": _series_or_synth(hist, sym), "dec": dec,
                    "src": qq["src"], "pair": fx_pair_for_symbol(sym) or code})
    return out


# Makro şeritte görünen ama parite listesinde olmayan semboller — grafikte açılabilsin diye
_FX_EXTRA = [
    ("DXY", "DX-Y.NYB", "US Dollar Index", "Macro", 98.42, 2),
    ("US10Y", "^TNX", "US 10-Year Treasury Yield", "Macro", 4.38, 3),
    ("UKOIL", "BZ=F", "Brent Oil (futures)", "Macro", 64.85, 2),
    ("BTC/USD", "BTC-USD", "Bitcoin / US Dollar", "Macro", 108420.0, 0),
]


def fx_all():
    return _FX_LIST + _FX_EXTRA


def fx_pairs():
    return [p for p, *_ in fx_all()]


def fx_pair_for_symbol(sym):
    """yfinance sembolünden parite kodu (önce ana listeye bakar)."""
    return next((p for p, s, *_ in fx_all() if s == sym), None)


def fx_symbol(pair):
    return next((sym for p, sym, *_ in fx_all() if p == pair), "EURUSD=X")


def fx_meta(pair):
    for p, sym, n, c, b, d in fx_all():
        if p == pair:
            return {"pair": p, "symbol": sym, "name": n, "category": c, "base": b, "dec": d}
    return {"pair": pair, "symbol": "EURUSD=X", "name": "", "category": "Majors", "base": 1.0, "dec": 5}


def get_fx_list(category="All"):
    q = get_quotes(tuple(sorted(sym for _, sym, *_ in fx_all())))
    out = []
    for p, sym, name, cat, base, dec in fx_all():
        if category != "All" and cat != category:
            continue
        qq = q.get(sym) or {"last": base, "change_pct": 0.0, "src": "none"}
        out.append({"pair": p, "symbol": sym, "name": name, "category": cat, "last": qq["last"],
                    "change_pct": qq["change_pct"], "dec": dec, "src": qq["src"]})
    return out


def get_fx_history(pair, days=120):
    df = add_emas(get_history(fx_symbol(pair)))
    out = df.tail(days).copy()
    out.attrs = dict(df.attrs)
    return out


# ======================================================================
# Sektörler: günlük performans, aylık performans, şirket ısı haritası
# ======================================================================
def sector_by_etf(etf):
    return next((s for s in SECTORS if s[1] == etf), None)


def get_sector_performance():
    q = get_quotes([e for _, e, _ in SECTORS])
    return [{"name": n, "etf": e, "change_pct": q[e]["change_pct"] if e in q else 0.0,
             "src": q.get(e, {}).get("src", "none")} for n, e, _ in SECTORS]


@_ttl_cache(1800, fail_ttl=120)
def get_sector_month_perf():
    etfs = tuple(sorted(e for _, e, _ in SECTORS))
    data = _batch_long(etfs, "1mo")
    out = []
    for name, etf, _ in SECTORS:
        df = data.get(etf)
        if df is not None and len(df) > 5:
            ch, src = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100, "real"
        else:
            s = _synth(etf).tail(22)
            ch, src = (s["Close"].iloc[-1] / s["Close"].iloc[0] - 1) * 100, "mock"
        out.append({"name": name, "etf": etf, "change_pct": float(ch), "src": src})
    return out


def get_sector_constituents(etf):
    sec = sector_by_etf(etf)
    if not sec:
        return []
    q = get_quotes([t for t, _, _ in sec[2]])
    out = []
    for t, n, w in sec[2]:
        qq = q.get(t)
        if qq:
            out.append({"ticker": t, "name": n, "weight": w, "last": qq["last"],
                        "change_pct": qq["change_pct"], "src": qq["src"]})
    return out


# ======================================================================
# Swing tarayıcı evreni + bilanço takvimi
# ======================================================================
@_ttl_cache(1800, fail_ttl=120)
def get_universe_history():
    ticks = tuple(sorted(set(SCAN_UNIVERSE + ["SPY"])))
    data = _download(ticks, "1y", "1d") if _HAS_YF else {}
    hist = {}
    for t in ticks:
        df = data.get(t)
        if df is not None and len(df) > 60:
            df = df.copy()
            df.attrs["src"] = "real"
        else:
            df = _synth(t).tail(260).copy()
            df.attrs["src"] = "mock"
        hist[t] = df
    n_real = sum(1 for d in hist.values() if d.attrs.get("src") == "real")
    return {"hist": hist, "fetched": pd.Timestamp.now(tz=TZ), "n": len(hist) - 1, "n_real": n_real,
            "src": "real" if n_real >= len(hist) * 0.5 else "mock"}


@_ttl_cache(21600, fail_ttl=900)
def get_earnings_map(days=21):
    """{ticker: 'YYYY-MM-DD'} — önümüzdeki günlerde bilanço açıklayacaklar (Nasdaq takvimi; yoksa Finnhub)."""
    today = us_today()
    bdays = [today + pd.Timedelta(days=i) for i in range(days + 1)]
    bdays = [d for d in bdays if d.weekday() < 5]
    emap = {}
    res = _pmap(_nasdaq_earn_day, [str(d.date()) for d in bdays], workers=6)
    for d, rows in zip(bdays, res):                       # gün sırası korunur
        for x in rows or []:
            emap.setdefault(x["sym"], str(d.date()))
    if not emap:
        fh = _finnhub_earn(bdays[0], bdays[-1]) or {}
        for d in sorted(fh):
            for x in fh[d]:
                emap.setdefault(x["sym"], d)
    if emap:
        return {"map": emap, "src": "real"}
    return {"map": {}, "src": "none"}


def earnings_days(emap):
    today = pd.Timestamp.now(tz=TZ).normalize().tz_localize(None)
    out = {}
    for t, d in (emap or {}).items():
        try:
            out[t] = float((pd.Timestamp(d) - today).days)
        except Exception:
            pass
    return out


# ======================================================================
# Top movers / losers (Yahoo tarayıcıları)
# ======================================================================
def _screen_quotes(name, n):
    res = yf.screen(name)
    quotes = res.get("quotes", []) if isinstance(res, dict) else []
    out = []
    for q in quotes[:n]:
        sym = q.get("symbol")
        if sym:
            out.append({"ticker": sym, "name": q.get("shortName") or q.get("displayName") or sym,
                        "sector": q.get("sector", "") or "", "last": float(q.get("regularMarketPrice") or 0),
                        "change_pct": float(q.get("regularMarketChangePercent") or 0), "src": "real"})
    return out


def _fallback_movers(reverse, n):
    q = list(get_quotes(SCAN_UNIVERSE).values())
    q.sort(key=lambda x: x["change_pct"], reverse=reverse)
    return q[:n]


@_ttl_cache(300, fail_ttl=90)
def get_top_movers(n=5):
    if _HAS_YF:
        try:
            m = _screen_quotes("day_gainers", n)
            if m:
                return m
        except Exception:
            pass
    return _fallback_movers(True, n)


@_ttl_cache(300, fail_ttl=90)
def get_top_losers(n=5):
    if _HAS_YF:
        try:
            m = _screen_quotes("day_losers", n)
            if m:
                return m
        except Exception:
            pass
    return _fallback_movers(False, n)


# ======================================================================
# Yaklaşan IPO'lar
# ======================================================================
def _mock_ipos():
    today = pd.Timestamp.today().normalize()
    rows = [("NovaAI Systems", "NOVA", "NASDAQ", 4, "$18 – $20", 12.5),
            ("Helios Energy", "HELE", "NYSE", 9, "$22 – $25", 8.0),
            ("Quantio Compute", "QNTO", "NASDAQ", 12, "$30 – $34", 15.2),
            ("Verdant Biotech", "VRDB", "NASDAQ", 16, "$14 – $16", 6.4)]
    df = pd.DataFrame([{"Company": f"{n} (sample)", "Symbol": s, "Exchange": e,
                        "Expected Date": (today + pd.Timedelta(days=d)).strftime("%b %d, %Y"),
                        "Price Range": p, "Shares (M)": sh} for n, s, e, d, p, sh in rows])
    df.attrs["src"] = "mock"
    return df


@_ttl_cache(3600, fail_ttl=600)
def get_upcoming_ipos():
    key = os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY")
    today = pd.Timestamp.today().normalize()
    if key and _HAS_REQ:
        try:
            r = requests.get("https://finnhub.io/api/v1/calendar/ipo",
                             params={"from": today.strftime("%Y-%m-%d"),
                                     "to": (today + pd.Timedelta(days=45)).strftime("%Y-%m-%d"), "token": key},
                             timeout=12)
            rows = [{"Company": x.get("name", ""), "Symbol": x.get("symbol", ""), "Exchange": x.get("exchange", ""),
                     "Expected Date": pd.Timestamp(x["date"]).strftime("%b %d, %Y") if x.get("date") else "",
                     "Price Range": f'${x["price"]}' if x.get("price") else "—",
                     "Shares (M)": round(float(x["numberOfShares"]) / 1e6, 2) if x.get("numberOfShares") else np.nan}
                    for x in r.json().get("ipoCalendar", []) if x.get("status") in (None, "expected", "filed", "priced")]
            if rows:
                df = pd.DataFrame(rows[:15])
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    if _HAS_REQ:
        try:
            out = []
            for m in (today, today + pd.offsets.MonthBegin(1)):
                r = requests.get("https://api.nasdaq.com/api/ipo/calendar",
                                 params={"date": m.strftime("%Y-%m")}, headers=_HEADERS, timeout=10)
                rows = ((r.json().get("data") or {}).get("upcoming") or {}).get("upcomingTable", {}).get("rows") or []
                for row in rows:
                    try:
                        sh = round(float(str(row.get("sharesOffered", "")).replace(",", "")) / 1e6, 2)
                    except Exception:
                        sh = np.nan
                    out.append({"Company": row.get("companyName", ""), "Symbol": row.get("proposedTickerSymbol", ""),
                                "Exchange": row.get("proposedExchange", ""),
                                "Expected Date": row.get("expectedPriceDate", ""),
                                "Price Range": row.get("proposedSharePrice", ""), "Shares (M)": sh})
            if out:
                df = pd.DataFrame(out[:15])
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    return _mock_ipos()


# ======================================================================
# Fear & Greed (CNN)
# ======================================================================
def _fg_label(v):
    v = float(v)
    return "Extreme Fear" if v < 25 else "Fear" if v < 45 else "Neutral" if v < 55 else \
        "Greed" if v < 75 else "Extreme Greed"


_FG_QUOTE = "Be fearful when others are greedy, and greedy when others are fearful."


@_ttl_cache(900, fail_ttl=180)
def get_fear_greed():
    if _HAS_REQ:
        try:
            r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                             headers=_HEADERS, timeout=10)
            fg = r.json()["fear_and_greed"]
            value = round(float(fg["score"]))
            pairs = [("Previous close", fg.get("previous_close")), ("1 week ago", fg.get("previous_1_week")),
                     ("1 month ago", fg.get("previous_1_month")), ("1 year ago", fg.get("previous_1_year"))]
            hist = [{"when": w, "value": round(float(v)), "label": _fg_label(v)} for w, v in pairs if v is not None]
            if hist:
                return {"value": value, "label": _fg_label(value), "history": hist, "quote": _FG_QUOTE,
                        "quote_author": "Warren Buffett", "src": "real"}
        except Exception:
            pass
    hist = [{"when": w, "value": v, "label": _fg_label(v)}
            for w, v in [("Previous close", 23), ("1 week ago", 44), ("1 month ago", 30), ("1 year ago", 29)]]
    return {"value": 27, "label": _fg_label(27), "history": hist, "quote": _FG_QUOTE,
            "quote_author": "Warren Buffett", "src": "mock"}


# ======================================================================
# Ucuz şirketler (PEG / Forward PE) — Yahoo "undervalued_large_caps"
# ======================================================================
@_ttl_cache(21600, fail_ttl=600)
def get_value_stocks():
    if _HAS_YF:
        try:
            res = yf.screen("undervalued_large_caps")
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
            cands = [q for q in quotes[:12] if q.get("symbol")]

            def info_of(q):
                try:
                    return q, (yf.Ticker(q["symbol"]).get_info() or {})
                except Exception:
                    return q, {}

            rows = []
            for q, info in _pmap(info_of, cands, workers=4):
                sym = q["symbol"]
                fpe = _num(_g(info, "forwardPE")) or _num(q.get("forwardPE"))
                if not fpe or fpe <= 0:
                    continue
                peg = _num(_g(info, "trailingPegRatio", "pegRatio"))
                margin, growth = _num(_g(info, "profitMargins")), _num(_g(info, "earningsGrowth"))
                rows.append({"Ticker": sym, "Company": q.get("shortName") or sym,
                             "PEG": round(peg, 2) if peg else np.nan, "Forward PE": round(fpe, 1),
                             "Profit Margin %": round(margin * 100, 1) if margin is not None else np.nan,
                             "EPS Growth %": round(growth * 100, 1) if growth is not None else np.nan})
            if len(rows) >= 4:
                df = pd.DataFrame(rows).sort_values("Forward PE").head(10).reset_index(drop=True)
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    rows = [("GOOGL", "Alphabet", 1.1, 18.4, 27.0, 14.5), ("META", "Meta Platforms", 0.9, 20.1, 33.2, 16.0),
            ("PEP", "PepsiCo", 1.4, 16.8, 10.1, 7.2), ("CRM", "Salesforce", 1.0, 22.0, 15.6, 18.9),
            ("UBER", "Uber", 0.8, 21.5, 6.2, 30.1), ("ADBE", "Adobe", 1.1, 19.9, 28.5, 13.8)]
    df = pd.DataFrame(rows, columns=["Ticker", "Company", "PEG", "Forward PE", "Profit Margin %", "EPS Growth %"])
    df = df.sort_values("Forward PE").reset_index(drop=True)
    df.attrs["src"] = "mock"
    return df


# ======================================================================
# Sembol arama (yerel + Yahoo Search)
# ======================================================================
_TYPE_TR = {"EQUITY": "Stock", "ETF": "ETF", "INDEX": "Index", "CURRENCY": "FX",
            "CRYPTOCURRENCY": "Crypto", "FUTURE": "Futures", "MUTUALFUND": "Fund"}


def _local_type(t):
    if t.endswith("=X"):
        return "FX"
    if t.endswith("=F"):
        return "Futures"
    if t.endswith("-USD"):
        return "Crypto"
    if t.startswith("^"):
        return "Index"
    if company_sector(t) in ("Index ETF", "Sector ETF"):
        return "ETF"
    return "Stock"


@_ttl_cache(600, fail_ttl=60)
def search_symbols(q):
    q = (q or "").strip()
    if not q:
        return []
    ql = q.lower().replace("/", "")
    res = []
    for t, (name, sector) in NAMES.items():
        tl = t.lower().replace("=x", "").replace("-", "")
        if ql == tl or ql in t.lower() or ql in name.lower().replace("/", ""):
            score = 0 if ql == tl else 1 if t.lower().startswith(ql) else 2
            res.append((score, {"ticker": t, "name": name, "type": _local_type(t), "exchange": "",
                                "sector": sector, "desc": COMPANIES.get(t, {}).get("desc", "")}))
    res = [r for _, r in sorted(res, key=lambda x: (x[0], len(x[1]["ticker"])))][:6]
    if _HAS_YF and len(q) >= 1:
        try:
            for it in (yf.Search(q, max_results=8, news_count=0).quotes or []):
                sym = it.get("symbol")
                if not sym or any(r["ticker"] == sym for r in res):
                    continue
                res.append({"ticker": sym, "name": it.get("shortname") or it.get("longname") or sym,
                            "type": _TYPE_TR.get(str(it.get("quoteType", "")).upper(), it.get("typeDisp") or ""),
                            "exchange": it.get("exchDisp") or it.get("exchange") or "",
                            "sector": it.get("sectorDisp") or it.get("sector") or "",
                            "desc": COMPANIES.get(sym, {}).get("desc", "")})
        except Exception:
            pass
    return res[:10]


# ======================================================================
# Teşhis
# ======================================================================
@_ttl_cache(120, fail_ttl=60)
def get_data_health():
    ver = getattr(yf, "__version__", "") if yf else ""
    h = {"yfinance_installed": _HAS_YF, "yf_version": ver, "yf_ok": False, "yf_msg": "",
         "cnn_ok": False, "cal_ok": False, "src": "real"}
    if _HAS_YF:
        q = get_quotes(["AAPL", "SPY"])
        a = q.get("AAPL")
        if a and a["src"] == "real":
            h["yf_ok"] = True
            h["yf_msg"] = f"yfinance {ver} · AAPL last price {a['last']:.2f}"
        else:
            h["yf_msg"] = f"yfinance {ver} is installed but Yahoo returned no data (could be a temporary rate limit)"
    else:
        h["yf_msg"] = "yfinance could not be imported — the 'yfinance' line is missing from requirements.txt"
    h["cnn_ok"] = get_fear_greed().get("src") == "real"
    cal = _calendar_all()
    h["cal_ok"] = bool(cal) and cal[0].get("src") == "real"
    return h


# ======================================================================
# v3.2 — Piyasa anlık görüntüsü (Nasdaq tarayıcı servisi)
#   Tek istekte NASDAQ + NYSE'nin tamamı: fiyat, günlük değişim, hacim,
#   piyasa değeri, sektör. S&P 500'ün tamamı bunun içindedir.
# ======================================================================
_NQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks"
_SYM_OK = re.compile(r"^[A-Z][A-Z.\-]{0,5}$")


def _num_money(v):
    """'$123.45' · '1,234,567' · '1.23%' → float (boşsa nan)."""
    if v is None:
        return float("nan")
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if s in ("", "--", "N/A", "n/a", "NA"):
        return float("nan")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        f = float(s)
    except ValueError:
        return float("nan")
    return -f if neg else f


def _nasdaq_screener(exchange):
    if not _HAS_REQ:
        return []
    r = requests.get(_NQ_SCREENER, headers=_HEADERS, timeout=25,
                     params={"tableonly": "true", "limit": "10000", "offset": "0",
                             "download": "true", "exchange": exchange})
    if r.status_code != 200:
        return []
    data = (r.json() or {}).get("data") or {}
    rows = data.get("rows")
    if rows is None:
        rows = (data.get("table") or {}).get("rows") or []
    return rows or []


def _snapshot_fallback():
    """Tarayıcı servisi kapalıysa: bilinen evrenin canlı kotasyonları (piyasa değeri yok)."""
    ticks = sorted(set(SCAN_UNIVERSE) | {t for _, _, cs in SECTORS for t, _, _ in cs} | set(DEFAULT_WATCHLIST))
    q = get_quotes(ticks)
    rows = []
    for t in ticks:
        qq = q.get(t)
        if not qq:
            continue
        rows.append({"ticker": t, "name": company_name(t), "last": qq["last"],
                     "change_pct": qq["change_pct"], "volume": float(qq.get("volume") or 0.0),
                     "market_cap": float("nan"), "exchange": "—",
                     "sector": company_sector(t) or ""})
    df = pd.DataFrame(rows)
    df.attrs["src"] = "mock" if (not rows or any(q.get(t, {}).get("src") == "mock" for t in ticks[:5])) else "real"
    df.attrs["capless"] = True
    return df


@_ttl_cache(600, fail_ttl=120)
def get_market_snapshot():
    """NASDAQ + NYSE'deki tüm hisseler: ticker, ad, fiyat, günlük %, hacim, piyasa değeri."""
    rows, got = [], False
    for ex in ("NASDAQ", "NYSE"):
        try:
            raw = _nasdaq_screener(ex)
        except Exception:
            raw = []
        if not raw:
            continue
        got = True
        for r in raw:
            t = str(r.get("symbol") or "").strip().upper()
            if not _SYM_OK.match(t):
                continue
            rows.append({"ticker": t, "name": str(r.get("name") or t)[:60],
                         "last": _num_money(r.get("lastsale")),
                         "change_pct": _num_money(r.get("pctchange")),
                         "volume": _num_money(r.get("volume")),
                         "market_cap": _num_money(r.get("marketCap")),
                         "exchange": ex, "sector": str(r.get("sector") or ""),
                         "industry": str(r.get("industry") or "")})
    if not got or len(rows) < 100:
        return _snapshot_fallback()
    df = pd.DataFrame(rows).drop_duplicates(subset=["ticker"]).reset_index(drop=True)
    df = df[df["last"] == df["last"]]
    df.attrs["src"] = "real"
    df.attrs["capless"] = False
    return df


@_ttl_cache(300, fail_ttl=120)
def get_daily_batch(tickers, period="1y"):
    """Çok sembollü günlük OHLCV — tek toplu istek."""
    ticks = tuple(sorted(set(tickers)))
    if not ticks:
        return {}
    data = _download(ticks, period, "1d") if _HAS_YF else {}
    out = {}
    for t in ticks:
        df = data.get(t)
        if df is not None and len(df) > 60:
            df = df.copy()
            df.attrs["src"] = "real"
            out[t] = df
        elif t in KNOWN:
            df = _synth(t).tail(300).copy()
            df.attrs["src"] = "mock"
            out[t] = df
    return out


@_ttl_cache(180, fail_ttl=60)
def get_intraday_batch(tickers, period="5d", interval="15m"):
    """Çok sembollü gün içi mumlar — 15 dakikalık teyit için."""
    ticks = tuple(sorted(set(tickers)))
    if not ticks:
        return {}
    data = _download(ticks, period, interval) if _HAS_YF else {}
    out = {}
    for t in ticks:
        df = data.get(t)
        if df is not None and len(df) > 10:
            df = df.copy()
            df.attrs["src"] = "real"
            out[t] = df
        elif t in KNOWN:
            df = _synth_intraday(t, period, interval).copy()
            df.attrs["src"] = "mock"
            out[t] = df
    return out


# ======================================================================
# v3.3 — Haberler yalnızca gerçek kaynaklardan
#   yfinance → Yahoo Finance RSS → Google News RSS. Üçü de boşsa haber yok;
#   uydurma başlık üretilmez.
# ======================================================================
_YF_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_GN_RSS = "https://news.google.com/rss/search"


def _rss_fetch(url, params=None):
    if not _HAS_REQ:
        return []
    r = requests.get(url, params=params, headers=_HEADERS, timeout=12)
    if r.status_code != 200 or not r.content:
        return []
    import xml.etree.ElementTree as ET
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        def _t(tag):
            e = it.find(tag)
            return (e.text or "").strip() if e is not None and e.text else ""
        src = it.find("source")
        thumb = None
        for el in it:                      # media:content / media:thumbnail / enclosure (görsel varsa)
            ln = el.tag.rsplit("}", 1)[-1]
            u = el.get("url") or ""
            if ln in ("content", "thumbnail") and u.startswith("http") and \
                    (el.get("medium", "image") == "image" or re.search(r"\.(jpe?g|png|webp)", u, re.I)):
                thumb = thumb or u
            elif ln == "enclosure" and u.startswith("http") and (el.get("type") or "").startswith("image"):
                thumb = thumb or u
        if not thumb:
            m = re.search(r'<img[^>]+src="(https?://[^"]+)"', _t("description"))
            thumb = m.group(1) if m else None
        out.append({"title": _t("title"), "link": _t("link"), "pub": _t("pubDate"),
                    "desc": _t("description"), "thumb": thumb,
                    "source": (src.text.strip() if src is not None and src.text else "")})
    return out


def _rss_to_items(raw, ticker=None, default_src="Yahoo Finance", limit=12):
    out = []
    for r in raw[:limit]:
        title = re.sub(r"\s+", " ", r.get("title") or "").strip()
        if not title:
            continue
        ts = None
        if r.get("pub"):
            try:
                ts = pd.Timestamp(r["pub"]).timestamp()
            except (ValueError, TypeError):
                ts = None
        mins, when, short = _age(ts)
        # Google News başlıkları "Başlık - Kaynak" biçiminde gelir
        src = r.get("source") or ""
        if not src and " - " in title:
            title, src = title.rsplit(" - ", 1)
        summary = re.sub(r"<[^>]+>", " ", r.get("desc") or "")
        summary = re.sub(r"\s+", " ", summary).strip()[:280]
        out.append({"ticker": ticker or "", "title": title.strip(), "source": src.strip() or default_src,
                    "when": when, "when_short": short, "age_min": mins,
                    "hours_ago": max(1, mins // 60),
                    "sentiment": _sentiment(title + " " + summary), "link": r.get("link") or None,
                    "thumb": r.get("thumb"), "summary": summary, "related": [ticker] if ticker else [],
                    "src": "real"})
    return out


@_ttl_cache(900, fail_ttl=180)
def _yahoo_rss(t, n=10):
    try:
        return _rss_to_items(_rss_fetch(_YF_RSS, {"s": t, "region": "US", "lang": "en-US"}), t,
                             "Yahoo Finance", n)
    except Exception:
        return []


@_ttl_cache(900, fail_ttl=180)
def _google_rss(query, n=10, ticker=None):
    try:
        return _rss_to_items(_rss_fetch(_GN_RSS, {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}),
                             ticker, "Google News", n)
    except Exception:
        return []


def _dedupe_news(items, n):
    seen, out = set(), []
    for p in sorted(items, key=lambda x: x.get("age_min", 10 ** 9)):
        k = re.sub(r"[^a-z0-9]+", "", (p.get("title") or "").lower())[:70]
        if k and k not in seen:
            seen.add(k)
            out.append(p)
    return out[:n]


# ======================================================================
# v3.3 — Finansal tablolar, analist tahminleri ve rakip listesi
# ======================================================================
def _clean_stmt(df, keep=5):
    """yfinance tablosu → sütunlar eskiden yeniye, son `keep` dönem."""
    if df is None or not hasattr(df, "empty") or df.empty:
        return pd.DataFrame()
    out = df.copy()
    try:
        out = out.loc[:, sorted(out.columns)]
    except TypeError:
        pass
    if out.shape[1] > keep:
        out = out.iloc[:, -keep:]
    out = out.dropna(how="all")
    return out


@_ttl_cache(10800, fail_ttl=600)
def get_statements(t):
    """Yıllık gelir tablosu, bilanço ve nakit akışı tablosu (gerçek veri)."""
    out = {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame(), "src": "none"}
    if not _HAS_YF:
        return out
    try:
        tk = yf.Ticker(t)
        inc = _clean_stmt(getattr(tk, "income_stmt", None))
        bal = _clean_stmt(getattr(tk, "balance_sheet", None))
        cfl = _clean_stmt(getattr(tk, "cashflow", None))
    except Exception:
        return out
    if inc is None or inc.empty:
        return out
    out.update({"income": inc, "balance": bal if bal is not None else pd.DataFrame(),
                "cashflow": cfl if cfl is not None else pd.DataFrame(), "src": "real"})
    return out


def _fiscal_year0(info):
    """Analistlerin '0y' satırının ait olduğu mali yıl (ör. Micron Ekim 2026'da → FY2027)."""
    for k in ("nextFiscalYearEnd", "lastFiscalYearEnd"):
        v = _num(_g(info, k))
        if v:
            try:
                y = int(pd.Timestamp(v, unit="s").year)
                return y if k == "nextFiscalYearEnd" else y + 1
            except Exception:
                pass
    return int(pd.Timestamp.now().year)


def _pct_val(v):
    v = _num(v)
    if v is None:
        return None
    return float(v) * (100 if abs(float(v)) < 5 else 1)


@_ttl_cache(10800, fail_ttl=600)
def get_analyst(t):
    """Analist tahminleri: mali yıl bazında EPS (ortalama / en düşük / en yüksek), büyüme, hedef fiyat.

    '0y' = içinde bulunulan mali yıl, '+1y' = bir sonraki mali yıl. Çeyreklik
    `earningsGrowth` (son çeyrek / geçen yılın aynı çeyreği) burada kullanılmaz — o bir
    beklenti değil, geçmiş bir çeyrek kıyası.
    """
    nan = float("nan")
    out = {"growth_next_y": nan, "growth_0y": nan, "growth_1y": nan, "growth_5y": nan,
           "eps_next_y": nan, "eps_last_fy": nan, "fy0": None, "fy0_left": 0.5, "fy0_end": None, "fy": [],
           "rev_fy": [], "rev_growth_0y": nan, "revisions": {},
           "fwd_eps": nan, "trailing_eps": nan,
           "target_mean": nan, "target_high": nan, "target_low": nan,
           "n": 0, "src": "none"}
    if not _HAS_YF:
        return out
    tk = yf.Ticker(t)
    try:
        info = tk.get_info() or {}
    except Exception:
        info = {}
    for k, keys in (("target_mean", ("targetMeanPrice",)), ("target_high", ("targetHighPrice",)),
                    ("target_low", ("targetLowPrice",)), ("fwd_eps", ("forwardEps",)),
                    ("trailing_eps", ("trailingEps", "epsTrailingTwelveMonths"))):
        v = _num(_g(info, *keys))
        if v is not None:
            out[k] = float(v)
    out["n"] = int(_num(_g(info, "numberOfAnalystOpinions")) or 0)
    fy0 = _fiscal_year0(info)
    out["fy0"] = fy0
    nfe = _num(_g(info, "nextFiscalYearEnd"))
    if nfe:
        try:
            left = (pd.Timestamp(nfe, unit="s") - pd.Timestamp.now()).days / 365.25
            out["fy0_left"] = float(min(1.0, max(0.0, left)))
            out["fy0_end"] = str(pd.Timestamp(nfe, unit="s").date())
        except Exception:
            pass
    try:
        ee = getattr(tk, "earnings_estimate", None)
        if ee is not None and hasattr(ee, "empty") and not ee.empty and "avg" in ee.columns:
            for i, idx in enumerate(("0y", "+1y")):
                if idx not in ee.index:
                    continue
                row = ee.loc[idx]
                avg = _num(row.get("avg"))
                if avg is None:
                    continue
                lo, hi = _num(row.get("low")), _num(row.get("high"))
                out["fy"].append({"fy": fy0 + i, "label": f"FY{fy0 + i}", "avg": float(avg),
                                  "low": float(lo) if lo is not None else float(avg),
                                  "high": float(hi) if hi is not None else float(avg),
                                  "n": int(_num(row.get("numberOfAnalysts")) or 0),
                                  "growth": _pct_val(row.get("growth"))})
                if idx == "0y":
                    ya = _num(row.get("yearAgoEps"))
                    if ya is not None:
                        out["eps_last_fy"] = float(ya)
    except Exception:
        pass
    try:
        re_ = getattr(tk, "revenue_estimate", None)
        if re_ is not None and hasattr(re_, "empty") and not re_.empty and "avg" in re_.columns:
            for i, idx in enumerate(("0y", "+1y")):
                if idx not in re_.index:
                    continue
                row = re_.loc[idx]
                avg = _num(row.get("avg"))
                if avg is None or avg <= 0:
                    continue
                lo, hi = _num(row.get("low")), _num(row.get("high"))
                ya = _num(row.get("yearAgoRevenue"))
                g = (avg / ya - 1) * 100 if ya else _pct_val(row.get("growth"))
                out["rev_fy"].append({"fy": fy0 + i, "avg": float(avg), "low": float(lo or avg),
                                      "high": float(hi or avg), "growth": g})
            if out["rev_fy"] and out["rev_fy"][0].get("growth") is not None:
                out["rev_growth_0y"] = float(out["rev_fy"][0]["growth"])
    except Exception:
        pass
    try:
        et = getattr(tk, "eps_trend", None)
        if et is not None and hasattr(et, "empty") and not et.empty and "current" in et.columns:
            for idx in ("0y", "+1y"):
                if idx in et.index:
                    cur_, old_ = _num(et.loc[idx, "current"]), _num(et.loc[idx].get("90daysAgo"))
                    if cur_ is not None and old_ and old_ > 0:
                        out["revisions"][idx] = (cur_ / old_ - 1) * 100
    except Exception:
        pass
    try:
        ge = getattr(tk, "growth_estimates", None)
        if ge is not None and hasattr(ge, "empty") and not ge.empty:
            col = ge.columns[0]
            for idx, key in (("0y", "growth_0y"), ("+1y", "growth_1y"), ("+5y", "growth_5y")):
                if idx in ge.index:
                    v = _pct_val(ge.loc[idx, col])
                    if v is not None:
                        out[key] = v
    except Exception:
        pass
    # tahmin tablosundaki büyüme ve EPS'ler birbirini tamamlar
    fys = out["fy"]
    # büyümeyi EPS'lerden kendimiz hesaplarız (Yahoo'nun oran alanı %500 üstünde birim karıştırabiliyor)
    for i, e in enumerate(fys):
        prev = fys[i - 1]["avg"] if i else out["eps_last_fy"]
        if prev == prev and prev and prev > 0:
            e["growth"] = (e["avg"] / prev - 1) * 100
    if fys:
        if fys[0].get("growth") is not None:
            out["growth_0y"] = fys[0]["growth"]
        if len(fys) > 1 and fys[1].get("growth") is not None:
            out["growth_1y"] = fys[1]["growth"]
        if out["growth_0y"] != out["growth_0y"] and out["eps_last_fy"] == out["eps_last_fy"] \
                and out["eps_last_fy"] > 0:
            out["growth_0y"] = (fys[0]["avg"] / out["eps_last_fy"] - 1) * 100
        if len(fys) > 1:
            out["eps_next_y"] = fys[1]["avg"]
            if out["growth_1y"] != out["growth_1y"] and fys[0]["avg"] > 0:
                out["growth_1y"] = (fys[1]["avg"] / fys[0]["avg"] - 1) * 100
    for key in ("growth_0y", "growth_1y"):
        if out[key] == out[key]:
            out["growth_next_y"] = out[key]
            break
    if out["n"] or fys or out["target_mean"] == out["target_mean"] or \
            out["growth_next_y"] == out["growth_next_y"]:
        out["src"] = "real"
    return out


# Sektör ETF'leri çok geniş (MU ile PLTR aynı ETF'de). Burada aynı ürünü satan, gerçekten
# rekabet eden şirketler tutulur — yabancı borsalardakiler dahil. "cyc" döngüsel sektör demek.
# "vtype" değerleme tipi (engine.VTYPES); None ise endüstri ve finansal ölçütlere bakılır.
PEER_GROUPS = [
    {"name": "Memory and storage", "vtype": "cyclical", "cyc": True,
     "syms": ["MU", "000660.KS", "005930.KS", "2408.TW", "SNDK", "285A.T", "WDC", "STX"],
     "core": {"MU": ["000660.KS", "005930.KS", "2408.TW", "SNDK", "285A.T"],
              "SNDK": ["285A.T", "MU", "005930.KS", "000660.KS", "WDC"],
              "WDC": ["STX", "SNDK", "MU", "285A.T"],
              "STX": ["WDC", "SNDK", "MU"]}},
    {"name": "GPUs and accelerators", "vtype": "capital", "cyc": False,
     "syms": ["NVDA", "AMD", "AVGO", "INTC", "MRVL", "QCOM", "ARM"]},
    {"name": "Foundry", "vtype": "capital", "cyc": True, "syms": ["TSM", "INTC", "GFS", "UMC", "005930.KS"]},
    {"name": "Semiconductor equipment", "vtype": "capital", "cyc": True,
     "syms": ["ASML", "AMAT", "LRCX", "KLAC", "8035.T", "TER"]},
    {"name": "Analog and microcontrollers", "vtype": "capital", "cyc": True,
     "syms": ["TXN", "ADI", "NXPI", "MCHP", "ON", "STM", "IFNNY"]},
    {"name": "Cloud and software giants", "vtype": "growth", "cyc": False,
     "syms": ["MSFT", "ORCL", "CRM", "SAP", "ADBE", "NOW"]},
    {"name": "Internet and advertising", "vtype": "growth", "cyc": False, "syms": ["GOOGL", "META", "AMZN", "SNAP", "PINS", "TTD"]},
    {"name": "Smartphones and hardware", "vtype": "capital", "cyc": False, "syms": ["AAPL", "005930.KS", "1810.HK", "DELL", "HPQ"]},
    {"name": "EVs and automotive", "vtype": "cyclical", "cyc": True,
     "syms": ["TSLA", "BYDDY", "TM", "GM", "F", "RIVN", "LI", "NIO", "STLA"]},
    {"name": "Big banks", "vtype": "cyclical", "cyc": True, "syms": ["JPM", "BAC", "C", "WFC", "GS", "MS"]},
    {"name": "Payment networks", "vtype": None, "cyc": False, "syms": ["V", "MA", "AXP", "PYPL", "FI"]},
    {"name": "Oil majors", "vtype": "cyclical", "cyc": True, "syms": ["XOM", "CVX", "SHEL", "BP", "TTE", "COP"]},
    {"name": "Pharma", "vtype": "defensive", "cyc": False, "syms": ["LLY", "NVO", "JNJ", "MRK", "PFE", "ABBV", "AZN"]},
    {"name": "Retail", "vtype": None, "cyc": False, "syms": ["WMT", "COST", "TGT", "AMZN", "HD", "LOW"]},
    {"name": "Streaming and entertainment", "vtype": "growth", "cyc": False, "syms": ["NFLX", "DIS", "WBD", "ROKU", "SPOT"]},
    {"name": "Airlines", "vtype": "cyclical", "cyc": True, "syms": ["DAL", "UAL", "AAL", "LUV", "ALK"]},
    {"name": "Steel and metals", "vtype": "cyclical", "cyc": True, "syms": ["NUE", "STLD", "CLF", "X", "FCX", "AA"]},
    {"name": "Chemicals", "vtype": "cyclical", "cyc": True, "syms": ["DOW", "LYB", "DD", "CE", "EMN"]},
]


@_ttl_cache(21600, fail_ttl=600)
def get_dividends(t):
    """Hisse başı temettü geçmişi (tarih → tutar). Yoksa boş seri."""
    if _HAS_YF:
        try:
            s = yf.Ticker(t).dividends
            if s is not None and len(s):
                return s.astype(float)
        except Exception:
            pass
    return pd.Series(dtype=float)


@_ttl_cache(3600, fail_ttl=300)
def get_risk_free():
    """ABD 10 yıllık tahvil faizi (%) — CAPM'deki risksiz faiz. Gelmezse 4,3."""
    try:
        h = get_history("^TNX")
        if h is not None and len(h) and h.attrs.get("src") == "real":
            v = float(h["Close"].dropna().iloc[-1])
            v = v / 10.0 if v > 20 else v
            if 0.5 < v < 15:
                return round(v, 2), "real"
    except Exception:
        pass
    return 4.3, "default"


def peer_group(t):
    """Seçili hissenin elle derlenmiş rakip grubu (varsa)."""
    for g in PEER_GROUPS:
        if t in g.get("core", {}) or t in g["syms"]:
            return g
    return None


def is_cyclical_industry(t):
    g = peer_group(t)
    return bool(g and g.get("cyc"))


def peer_universe(t):
    """Rakip adayları: önce elle derlenmiş grup, sonra aynı endüstri, en son aynı sektör."""
    g = peer_group(t)
    if g:
        core = g.get("core", {}).get(t)
        if core:
            return list(core)
        return [s for s in g["syms"] if s != t]
    snap = get_market_snapshot()
    if snap is not None and len(snap) and "industry" in snap.columns:
        row = snap[snap["ticker"] == t]
        ind = str(row["industry"].iloc[0]) if len(row) else ""
        if ind:
            same = snap[(snap["industry"] == ind) & (snap["ticker"] != t)]
            if len(same) >= 3:
                return list(same["ticker"])
    for _, _, cons in SECTORS:
        syms = [c[0] for c in cons]
        if t in syms:
            return [s for s in syms if s != t]
    sec = company_sector(t)
    if sec:
        return [x for x, c in COMPANIES.items() if c.get("sector") == sec and x != t][:24]
    return []


def peer_source(t):
    """Rakip listesinin nereden geldiği — arayüzde açıklama için."""
    g = peer_group(t)
    if g:
        return g["name"]
    snap = get_market_snapshot()
    if snap is not None and len(snap) and "industry" in snap.columns:
        row = snap[snap["ticker"] == t]
        if len(row) and str(row["industry"].iloc[0]):
            return f'{row["industry"].iloc[0]} (NASDAQ industry class)'
    return "Sector ETF constituents"


@_ttl_cache(1800, fail_ttl=300)
def get_peers(t, n=5):
    """Rakipler. Elle derlenmiş grupta sıra korunur; diğerlerinde piyasa değeri en yakınlar."""
    cand = peer_universe(t)
    if not cand:
        return []
    if peer_group(t):
        return cand[:int(n)]
    snap = get_market_snapshot()
    caps = {}
    if snap is not None and len(snap):
        caps = dict(zip(snap["ticker"], snap["market_cap"]))
    me = caps.get(t)
    if me is None or me != me:
        d = get_company_detail(t) or {}
        me = d.get("market_cap")
    scored = []
    for s in cand:
        c = caps.get(s)
        if c is None or c != c:
            scored.append((9e18, s))
            continue
        scored.append((abs(np.log(max(c, 1.0)) - np.log(max(me or c, 1.0))), s))
    scored.sort()
    return [s for _, s in scored[:int(n)]]


# Kur bulunamazsa kullanılacak yaklaşık değerler (1 birim = ? USD)
_USD_FALLBACK = {"USD": 1.0, "KRW": 0.00072, "JPY": 0.0066, "TWD": 0.031, "EUR": 1.08, "GBP": 1.27,
                 "HKD": 0.128, "CNY": 0.138, "CHF": 1.13, "CAD": 0.73, "AUD": 0.66, "INR": 0.012,
                 "SEK": 0.095, "DKK": 0.145, "TRY": 0.029}


@_ttl_cache(3600, fail_ttl=300)
def usd_rate(cur):
    """1 birim yerel para kaç dolar (GBp gibi kuruş cinsleri de çevrilir)."""
    cur = str(cur or "USD")
    div = 1.0
    if cur in ("GBp", "GBX"):
        cur, div = "GBP", 100.0
    elif cur == "ZAc":
        cur, div = "ZAR", 100.0
    cur = cur.upper()
    if cur == "USD":
        return 1.0 / div
    rate = None
    if _HAS_YF:
        try:
            h = yf.Ticker(f"{cur}USD=X").history(period="5d")
            if h is not None and len(h):
                rate = float(h["Close"].dropna().iloc[-1])
        except Exception:
            rate = None
    if not rate or rate != rate:
        rate = _USD_FALLBACK.get(cur)
    return (rate / div) if rate else float("nan")


@_ttl_cache(1800, fail_ttl=300)
def get_valuation(t):
    """Karşılaştırma tablosu için çarpanlar — tek info çağrısı, önbellekli.

    growth = ileri EPS büyümesi (analistlerin önümüzdeki mali yıl EPS'i ÷ son 12 ay EPS).
    Piyasa değeri dolara çevrilir (Samsung, SK Hynix vb. yerel parayla yayımlanır).
    """
    nan = float("nan")
    out = {"ticker": t, "name": company_name(t), "market_cap": nan, "pe": nan, "fwd_pe": nan,
           "peg": nan, "ev_ebitda": nan, "growth": nan, "rev_growth": nan, "net_margin": nan,
           "ev_sales": nan, "pb": nan, "currency": "USD", "src": "none"}
    if not _HAS_YF:
        return out
    try:
        info = yf.Ticker(t).get_info() or {}
    except Exception:
        return out
    if not info:
        return out
    def _f(*keys):
        v = _num(_g(info, *keys))
        return float(v) if v is not None else nan
    out["name"] = _g(info, "shortName", "longName") or company_name(t)
    cur = _g(info, "currency", default="USD")
    out["currency"] = cur
    mc = _f("marketCap")
    if mc == mc and cur not in ("USD", None):
        r = usd_rate(cur)
        mc = mc * r if r == r else nan
    out["market_cap"] = mc
    out["pe"] = _f("trailingPE")
    out["fwd_pe"] = _f("forwardPE")
    te, fe = _f("trailingEps"), _f("forwardEps")
    if out["pe"] != out["pe"]:
        p = _f("currentPrice", "regularMarketPrice")
        if p == p and te == te and te > 0:
            out["pe"] = p / te
    if out["fwd_pe"] != out["fwd_pe"]:
        p = _f("currentPrice", "regularMarketPrice")
        if p == p and fe == fe and fe > 0:
            out["fwd_pe"] = p / fe
    out["ev_ebitda"] = _f("enterpriseToEbitda")
    if te == te and fe == fe and te > 0:
        out["growth"] = (fe / te - 1) * 100
    rg = _f("revenueGrowth")
    out["rev_growth"] = rg * 100 if rg == rg else nan
    m = _f("profitMargins")
    out["net_margin"] = m * 100 if m == m else nan
    g = out["growth"]
    if out["fwd_pe"] == out["fwd_pe"] and g == g and g > 0:
        out["peg"] = out["fwd_pe"] / g
    out["src"] = "real"
    return out


def get_valuations(tickers):
    """Birden çok sembol için çarpanlar (paralel)."""
    ticks = [t for t in dict.fromkeys(tickers) if t]
    return {v["ticker"]: v for v in _pmap(get_valuation, ticks, workers=4)}


# ======================================================================
# v3.7 — Gelir kırılımı ve operasyonel göstergeler: SEC EDGAR (XBRL)
#   Yahoo segment vermez. Şirketin son 10-K / 20-F dosyasındaki XBRL verisinden
#   ürün-hizmet, iş segmenti ve coğrafya bazında gelir okunur; abone / müşteri / üye
#   sayısı gibi sayılar ve sözleşmeli gelecek gelir (RPO), ertelenmiş gelir ise
#   son 10-K veya 10-Q'dan. Yalnızca SEC'e rapor veren şirketler kapsanır.
# ======================================================================
import xml.etree.ElementTree as _ET  # noqa: E402

_SEC_UA = (os.environ.get("SEC_USER_AGENT") or
           "Pulse Market Dashboard (open-source Streamlit app; personal research use)")
_SEC_ANNUAL = ("10-K", "20-F", "40-F")
_SEC_ANY = ("10-K", "20-F", "40-F", "10-Q")
_SEC_STD_NS = ("fasb.org/us-gaap", "fasb.org/srt", "xbrl.ifrs.org", "xbrl.sec.gov/dei", "fasb.org/us-types")
SEC_REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                    "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
                    "Revenue", "RevenueFromContractsWithCustomers", "RevenuesNetOfInterestExpense"]
SEC_AXES = {"product": ("ProductOrServiceAxis", "ProductsAndServicesAxis"),
            "segment": ("StatementBusinessSegmentsAxis", "SegmentsAxis"),
            "geo": ("StatementGeographicalAxis", "GeographicalAreasAxis")}
SEC_AXIS_NAME = {"product": "Products & services", "segment": "Business segments", "geo": "Geography"}
# sayı birimi olan ama gösterge olmayan kavramlar
_KPI_SKIP = re.compile(r"Segment|Vote|Share|Stock|Option|Warrant|Award|Lease|Propert|Plan\b|Director|Year|Month|"
                       r"Day|Percent|Ratio|Rate|Pension|Tax|Acquisition|Business|Reportable|Employee|Patent|Lawsuit|"
                       r"Claim|Facility|Debt|Note|Loan|Swap|Derivative|Contract(?!WithCustomer)|Hedge", re.I)
_KPI_WORDS = re.compile(r"Subscri|Member|Customer|User|Account|Client|Store|Restaurant|Location|Seat|Device|"
                        r"Vehicle|Deliver|Unit|Household|Policy|Room|Order|Booking|Trip|Transaction|Merchant|Partner|"
                        r"Hotel|Night|Viewer|Listener|Player|Patient|Site|Server|Download|Install|Licens", re.I)
_KPI_MONEY = {"RevenueRemainingPerformanceObligation": "Remaining performance obligations (contracted, not yet billed)",
              "ContractWithCustomerLiability": "Deferred revenue (contract liabilities)",
              "ContractWithCustomerLiabilityCurrent": "Deferred revenue — current"}
_KPI_MONEY_WORDS = re.compile(r"RecurringRevenue|AnnualizedRevenue|Bookings|Backlog|GrossMerchandiseValue|"
                              r"GrossBookings|TotalPaymentVolume|AssetsUnderManagement", re.I)


def _sec_get(url, timeout=25):
    r = requests.get(url, headers={"User-Agent": _SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=timeout)
    r.raise_for_status()
    return r


@_ttl_cache(86400, fail_ttl=900)
def _sec_cik_map():
    if not _HAS_REQ:
        return {}
    try:
        js = _sec_get("https://www.sec.gov/files/company_tickers.json").json()
        return {str(v.get("ticker", "")).upper(): int(v.get("cik_str")) for v in js.values() if v.get("cik_str")}
    except Exception:
        return {}


def sec_cik(t):
    m = _sec_cik_map()
    t = str(t or "").upper()
    for k in (t, t.replace(".", "-"), t.replace("-", ".")):
        if k in m:
            return m[k]
    return None


@_ttl_cache(21600, fail_ttl=900)
def _sec_filings(cik):
    """Son dosyalar: [{form, acc, doc, report, filed}] — yeni → eski."""
    try:
        js = _sec_get("https://data.sec.gov/submissions/CIK%010d.json" % int(cik)).json()
        rc = (js.get("filings") or {}).get("recent") or {}
        out = []
        for i, form in enumerate(rc.get("form") or []):
            if form not in _SEC_ANY:
                continue
            out.append({"form": form, "acc": rc["accessionNumber"][i], "doc": rc["primaryDocument"][i],
                        "report": (rc.get("reportDate") or [""] * (i + 1))[i],
                        "filed": (rc.get("filingDate") or [""] * (i + 1))[i]})
        return out
    except Exception:
        return []


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.rsplit(":", 1)[-1]


def sec_parse_instance(xml_bytes):
    """XBRL instance → {contexts: id→{dims, start, end, instant}, units: id→measure, facts: [...]}.
    Ad alanı öneklerinden bağımsız (yerel adlarla) çalışır."""
    root = _ET.fromstring(xml_bytes)
    ctx, units, facts = {}, {}, []
    for el in root:
        ln = _local(el.tag)
        if ln == "context":
            dims, start, end, inst, typed = {}, None, None, None, False
            for sub in el.iter():
                sl = _local(sub.tag)
                if sl == "explicitMember":
                    dims[_local(sub.get("dimension") or "")] = (sub.text or "").strip()
                elif sl == "typedMember":
                    typed = True
                elif sl == "startDate":
                    start = (sub.text or "").strip()
                elif sl == "endDate":
                    end = (sub.text or "").strip()
                elif sl == "instant":
                    inst = (sub.text or "").strip()
            ctx[el.get("id")] = {"dims": dims, "typed": typed, "start": start, "end": end or inst,
                                 "instant": inst is not None}
        elif ln == "unit":
            ms = [(m.text or "").strip() for m in el.iter() if _local(m.tag) == "measure"]
            units[el.get("id")] = "/".join(ms)
        elif el.get("contextRef") is not None:
            txt = (el.text or "").strip()
            if not txt:
                continue
            try:
                val = float(txt)
            except ValueError:
                continue
            ns = el.tag[1:].split("}", 1)[0] if el.tag.startswith("{") else ""
            facts.append({"c": _local(el.tag), "std": any(s in ns for s in _SEC_STD_NS),
                          "ctx": el.get("contextRef"), "unit": el.get("unitRef") or "", "v": val})
    return {"contexts": ctx, "units": units, "facts": facts}


def sec_parse_labels(xml_bytes):
    """Etiket linkbase → {'aapl_IPhoneMember': 'iPhone', ...} (standart 'label' rolü öncelikli)."""
    root = _ET.fromstring(xml_bytes)
    XL = "{http://www.w3.org/1999/xlink}"
    loc, lab, arcs = {}, {}, []
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "loc":
            href = el.get(XL + "href") or ""
            loc[el.get(XL + "label")] = href.split("#", 1)[-1]
        elif ln == "label":
            role = (el.get(XL + "role") or "").rsplit("/", 1)[-1]
            lab.setdefault(el.get(XL + "label"), []).append((role, (el.text or "").strip()))
        elif ln == "labelArc":
            arcs.append((el.get(XL + "from"), el.get(XL + "to")))
    out = {}
    rank = {"terseLabel": 0, "label": 1, "verboseLabel": 2}
    for fr, to in arcs:
        cid = loc.get(fr)
        if not cid or to not in lab:
            continue
        best = sorted(lab[to], key=lambda x: rank.get(x[0], 9))[0]
        prev = out.get(cid)
        if prev is None or rank.get(best[0], 9) < prev[0]:
            out[cid] = (rank.get(best[0], 9), best[1])
    return {k: re.sub(r"\s*\[(Member|Axis|Domain|Line Items|Abstract)\]\s*$", "", v[1]) for k, v in out.items()}


_COUNTRY = {"US": "United States", "CN": "China", "JP": "Japan", "GB": "United Kingdom", "DE": "Germany",
            "FR": "France", "CA": "Canada", "TW": "Taiwan", "KR": "South Korea", "IN": "India", "IE": "Ireland",
            "NL": "Netherlands", "SG": "Singapore", "MX": "Mexico", "BR": "Brazil", "AU": "Australia",
            "CH": "Switzerland", "HK": "Hong Kong", "IL": "Israel", "IT": "Italy", "ES": "Spain"}


def _humanize(member):
    pre, _, name = member.rpartition(":")
    if pre == "country":
        return _COUNTRY.get(name, name)
    name = re.sub(r"(Member|Segment)$", "", name) or name
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    s = re.sub(r"\bNon Us\b", "Non-US", s)
    s = re.sub(r"\bUs\b", "US", s)
    s = re.sub(r"\bNumber Of\b", "Number of", s)
    return re.sub(r"\b(And|Of|The|In|For)\b", lambda m: m.group(1).lower(), s).strip()


def _sec_label(labels, member):
    key = member.replace(":", "_")
    if key in labels:
        return labels[key]
    loc = key.split("_", 1)[-1]
    for k, v in labels.items():          # önek bilinmiyorsa yerel ada göre
        if k.split("_", 1)[-1] == loc:
            return v
    return _humanize(member)


def _days(a, b):
    try:
        return (pd.Timestamp(b) - pd.Timestamp(a)).days
    except Exception:
        return None


def sec_revenue_breakdown(parsed, labels=None):
    """Yıllık gelir: toplam + eksen (ürün/segment/coğrafya) bazında üyeler, son 3 mali yıl."""
    labels = labels or {}
    C = parsed["contexts"]

    def annual(cid):
        c = C.get(cid)
        if not c or c["instant"] or c["typed"]:
            return None
        d = _days(c["start"], c["end"])
        return c if d is not None and 330 <= d <= 380 else None

    totals, cur = {}, {}             # kavram → {bitiş: değer}
    for f in parsed["facts"]:
        if f["c"] not in SEC_REV_CONCEPTS or not f["std"]:
            continue
        c = annual(f["ctx"])
        if c and not c["dims"]:
            totals.setdefault(f["c"], {})[c["end"]] = max(f["v"], totals.get(f["c"], {}).get(c["end"], 0))
            u = (parsed["units"].get(f["unit"]) or "")
            if u.lower().startswith("iso4217:"):
                cur[f["c"]] = u.split(":", 1)[1].upper()
    if not totals:
        return None
    last_end = max(e for v in totals.values() for e in v)
    concept = next((k for k in SEC_REV_CONCEPTS if last_end in totals.get(k, {})), None)
    if not concept:
        return None
    total = totals[concept]
    ends = sorted(total, reverse=True)[:3]
    groups = {}
    for f in parsed["facts"]:
        if f["c"] not in SEC_REV_CONCEPTS or not f["std"]:
            continue
        c = annual(f["ctx"])
        if not c or len(c["dims"]) != 1 or c["end"] not in ends:
            continue
        axis, member = next(iter(c["dims"].items()))
        g = next((k for k, axes in SEC_AXES.items() if axis in axes), None)
        if not g:
            continue
        slot = groups.setdefault(g, {}).setdefault(member, {})
        prev = slot.get(c["end"])
        # aynı üye için tercih: seçili kavram, sonra en büyük değer
        if prev is None or (f["c"] == concept and prev[1] != concept) or \
                (f["c"] == prev[1] and f["v"] > prev[0]):
            slot[c["end"]] = (f["v"], f["c"])
    out_groups = []
    t0 = total.get(ends[0])
    for g in ("product", "segment", "geo"):
        mem = groups.get(g) or {}
        rows = []
        for m, vals in mem.items():
            v0 = (vals.get(ends[0]) or (None,))[0]
            if v0 is None or v0 <= 0:
                continue
            hist = [(vals.get(e) or (None,))[0] for e in ends]
            v1 = hist[1] if len(hist) > 1 else None
            rows.append({"member": m, "label": _sec_label(labels, m), "values": hist,
                         "share": v0 / t0 * 100 if t0 else None,
                         "yoy": (v0 / v1 - 1) * 100 if v1 else None})
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: -r["values"][0])
        ssum = sum(r["values"][0] for r in rows)
        out_groups.append({"key": g, "name": SEC_AXIS_NAME[g], "rows": rows[:14],
                           "overlap": bool(t0 and ssum > t0 * 1.06)})
    return {"concept": concept, "ends": ends, "total": [total.get(e) for e in ends], "groups": out_groups,
            "currency": cur.get(concept, "USD")}


def sec_kpis(parsed, labels=None, limit=8):
    """Abone / müşteri / üye / mağaza sayısı gibi sayılar + RPO, ertelenmiş gelir. Şirket düzeyi (boyutsuz)."""
    labels = labels or {}
    C, U = parsed["contexts"], parsed["units"]
    by, cur_of = {}, {}
    for f in parsed["facts"]:
        c = C.get(f["ctx"])
        if not c or c["dims"] or c["typed"] or not c["end"]:
            continue
        unit = (U.get(f["unit"]) or f["unit"] or "").lower()
        money = unit.startswith("iso4217:") and "/" not in unit
        name = f["c"]
        if money:
            cur_of[name] = unit.split(":", 1)[1].upper()
            if name in _KPI_MONEY:
                lab, kind = _KPI_MONEY[name], "money"
            elif not f["std"] and _KPI_MONEY_WORDS.search(name):
                lab, kind = None, "money"
            else:
                continue
        else:
            ul = unit.split(":")[-1]
            if ul in ("shares", "pure", "") or "/" in unit or "iso4217" in unit:
                continue
            if _KPI_SKIP.search(name) or not (_KPI_WORDS.search(name) or _KPI_WORDS.search(ul)):
                continue
            lab, kind = None, "count"
        dur = None if c["instant"] else _days(c["start"], c["end"])
        key = (name, kind, "i" if c["instant"] else ("q" if dur and dur < 120 else "y" if dur and dur > 300 else "o"))
        by.setdefault(key, {})[c["end"]] = f["v"]
        by[key]["__lab"] = lab
        by[key]["__std"] = f["std"]
    out = []
    for (name, kind, per), vals in by.items():
        lab = vals.pop("__lab")
        std = vals.pop("__std")
        if not vals:
            continue
        end = max(vals)
        v = vals[end]
        prev = None
        for e, pv in vals.items():
            dd = _days(e, end)
            if dd is not None and 340 <= dd <= 390:
                prev = pv
        label = lab or _sec_label(labels, ("us-gaap:" if std else "x:") + name)
        pri = 0 if kind == "money" and name in _KPI_MONEY else 1
        if (kind == "count" and re.search(r"Subscri|Member|Customer|User|Account|Client", name, re.I)) or \
                re.search(r"Recurring", name, re.I):
            pri = -1
        out.append({"concept": name, "label": label, "kind": kind, "value": v, "end": end, "period": per,
                    "currency": cur_of.get(name, "USD"),
                    "yoy": (v / prev - 1) * 100 if prev else None, "pri": pri})
    out.sort(key=lambda k: (k["pri"], k["end"] == "" , -pd.Timestamp(k["end"]).value if k["end"] else 0))
    # aynı kavramdan tek satır (anlık değer öncelikli)
    seen, res = set(), []
    for k in out:
        if k["concept"] in seen:
            continue
        seen.add(k["concept"])
        res.append(k)
    return res[:int(limit)]


def _sec_folder(cik, acc):
    return "https://www.sec.gov/Archives/edgar/data/%d/%s/" % (int(cik), acc.replace("-", ""))


@_ttl_cache(259200, fail_ttl=1800)
def _sec_filing_data(cik, acc, doc):
    """Bir dosyanın XBRL instance + etiketleri (ayrıştırılmış)."""
    folder = _sec_folder(cik, acc)
    items = _sec_get(folder + "index.json").json().get("directory", {}).get("item", [])
    names = [i.get("name", "") for i in items]
    sizes = {i.get("name", ""): int(i.get("size") or 0) if str(i.get("size") or "").isdigit() else 0 for i in items}
    inst = next((n for n in names if n.endswith("_htm.xml")), None)
    if not inst:
        cand = [n for n in names if n.endswith(".xml") and not re.search(r"_(cal|def|lab|pre)\.xml$", n)
                and n not in ("FilingSummary.xml",)]
        inst = max(cand, key=lambda n: sizes.get(n, 0)) if cand else None
    if not inst:
        return None
    parsed = sec_parse_instance(_sec_get(folder + inst, timeout=40).content)
    lab = next((n for n in names if n.endswith("_lab.xml")), None)
    labels = {}
    if lab:
        try:
            labels = sec_parse_labels(_sec_get(folder + lab, timeout=30).content)
        except Exception:
            labels = {}
    parsed["labels"] = labels
    parsed["url"] = folder + doc
    return parsed


@_ttl_cache(86400, fail_ttl=1800)
def get_revenue_breakdown(t):
    """Gelir kırılımı + operasyonel göstergeler. src: real | none (SEC'e rapor vermeyen / erişilemeyen)."""
    out = {"src": "none", "ticker": t}
    if not _HAS_REQ or not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", str(t or "").upper()):
        out["why"] = "Only companies that file with the SEC (US listings) are covered."
        return out
    cik = sec_cik(t)
    if not cik:
        out["why"] = ("No SEC filer found for this symbol — non-US listings, ETFs and funds aren't covered."
                      if _sec_cik_map() else "SEC EDGAR could not be reached right now.")
        return out
    fl = _sec_filings(cik)
    ann = next((x for x in fl if x["form"] in _SEC_ANNUAL), None)
    if not ann:
        out["why"] = "No annual report (10-K / 20-F) with XBRL data was found."
        return out
    try:
        pa = _sec_filing_data(cik, ann["acc"], ann["doc"])
    except Exception:
        pa = None
    if not pa:
        out["why"] = "The annual report's XBRL data could not be read."
        return out
    out.update({"src": "real", "cik": cik, "form": ann["form"], "filed": ann["filed"], "report": ann["report"],
                "url": pa["url"]})
    out["rev"] = sec_revenue_breakdown(pa, pa["labels"])
    # göstergeler: en yeni dosya (10-Q daha yeniyse onu da tara)
    latest = fl[0] if fl else ann
    kp = sec_kpis(pa, pa["labels"])
    out["kpi_src"] = {"form": ann["form"], "filed": ann["filed"], "url": pa["url"]}
    if latest["acc"] != ann["acc"]:
        try:
            pq = _sec_filing_data(cik, latest["acc"], latest["doc"])
            if pq:
                kq = sec_kpis(pq, pq["labels"] or pa["labels"])
                if kq:
                    known = {k["concept"] for k in kq}
                    kp = kq + [k for k in kp if k["concept"] not in known]
                    kp = kp[:8]
                    out["kpi_src"] = {"form": latest["form"], "filed": latest["filed"], "url": pq["url"]}
        except Exception:
            pass
    out["kpis"] = kp
    return out


# ======================================================================
# v3.8 — Çeyrek verileri: raporlanan çeyrekler + analistlerin çeyrek tahminleri (0q, +1q)
# ======================================================================
@_ttl_cache(21600, fail_ttl=900)
def get_quarterly(t):
    """Çeyreklik EPS/ciro. Raporlananlar: earnings_history (analist tahminiyle aynı baz, düzeltilmiş EPS) +
    quarterly_income_stmt (ciro, GAAP EPS). Tahminler: earnings_estimate / revenue_estimate '0q', '+1q'.
    Döner: {src, q: [{end, eps, eps_gaap, rev, est, surprise}], est: {'0q': {...}, '+1q': {...}}, next_date}"""
    out = {"src": "none", "q": [], "est": {}, "next_date": None}
    if not _HAS_YF:
        return out
    tk = yf.Ticker(t)
    rows = {}

    def _slot(ts):
        ts = pd.Timestamp(ts)
        try:
            ts = ts.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        ts = ts.normalize()
        for k in rows:                       # aynı çeyrek (±25 gün) tek satır
            if abs((k - ts).days) <= 25:
                return k
        rows[ts] = {"end": ts, "eps": float("nan"), "eps_gaap": float("nan"), "rev": float("nan"),
                    "est": float("nan"), "surprise": float("nan")}
        return ts

    try:
        qi = getattr(tk, "quarterly_income_stmt", None)
        if qi is not None and hasattr(qi, "empty") and not qi.empty:
            idx = {str(i).strip().lower(): i for i in qi.index}

            def _row(*names):
                for n in names:
                    if n.lower() in idx:
                        return qi.loc[idx[n.lower()]]
                return None
            eps_r = _row("Diluted EPS", "Basic EPS")
            rev_r = _row("Total Revenue", "Operating Revenue")
            for c in qi.columns:
                k = _slot(c)
                if eps_r is not None and _num(eps_r.get(c)) is not None:
                    rows[k]["eps_gaap"] = float(_num(eps_r.get(c)))
                if rev_r is not None and _num(rev_r.get(c)) is not None:
                    rows[k]["rev"] = float(_num(rev_r.get(c)))
    except Exception:
        pass
    try:
        eh = getattr(tk, "earnings_history", None)
        if eh is not None and hasattr(eh, "empty") and not eh.empty:
            for i, r in eh.iterrows():
                a = _num(r.get("epsActual"))
                if a is None:
                    continue
                k = _slot(i)
                rows[k]["eps"] = float(a)
                e = _num(r.get("epsEstimate"))
                if e is not None:
                    rows[k]["est"] = float(e)
                sp_ = _num(r.get("surprisePercent"))
                if sp_ is not None:
                    rows[k]["surprise"] = float(sp_) * (100 if abs(sp_) < 5 else 1)
    except Exception:
        pass
    for r in rows.values():                  # düzeltilmiş EPS yoksa GAAP EPS
        if r["eps"] != r["eps"] and r["eps_gaap"] == r["eps_gaap"]:
            r["eps"] = r["eps_gaap"]
            r["gaap"] = True
    out["q"] = sorted([r for r in rows.values() if r["eps"] == r["eps"] or r["rev"] == r["rev"]],
                      key=lambda r: r["end"])
    try:
        ee = getattr(tk, "earnings_estimate", None)
        re_ = getattr(tk, "revenue_estimate", None)
        for idx in ("0q", "+1q"):
            if ee is None or not hasattr(ee, "index") or idx not in ee.index:
                continue
            row = ee.loc[idx]
            avg = _num(row.get("avg"))
            if avg is None:
                continue
            lo, hi = _num(row.get("low")), _num(row.get("high"))
            d = {"avg": float(avg), "low": float(lo if lo is not None else avg),
                 "high": float(hi if hi is not None else avg), "n": int(_num(row.get("numberOfAnalysts")) or 0),
                 "year_ago": _num(row.get("yearAgoEps")), "rev": None}
            if re_ is not None and hasattr(re_, "index") and idx in re_.index:
                rv = _num(re_.loc[idx].get("avg"))
                d["rev"] = float(rv) if rv else None
            out["est"][idx] = d
    except Exception:
        pass
    try:
        cal = getattr(tk, "calendar", None)
        ed = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            out["next_date"] = str(pd.Timestamp(ed[0] if isinstance(ed, (list, tuple)) else ed).date())
    except Exception:
        pass
    if out["q"] or out["est"]:
        out["src"] = "real"
    return out


# ======================================================================
# v3.9 — Analist görüşleri ve beklentiler · çeyrek finansallar (SEC companyfacts + Yahoo)
# ======================================================================
@_ttl_cache(21600, fail_ttl=900)
def get_analyst_detail(t):
    """Analist dağılımı, hedef fiyatlar, tahminler (0q/+1q/0y/+1y), revizyonlar, son not değişiklikleri."""
    out = {"src": "none", "dist": None, "dist_3m": None, "targets": {}, "est": [], "trend": {}, "revisions": {},
           "changes": [], "rec_mean": None, "rec_key": None, "n": 0}
    if not _HAS_YF:
        return out
    tk = yf.Ticker(t)
    try:
        info = tk.info or {}
        out["rec_mean"] = _num(info.get("recommendationMean"))
        out["rec_key"] = str(info.get("recommendationKey") or "").replace("_", " ").title() or None
        out["n"] = int(_num(info.get("numberOfAnalystOpinions")) or 0)
        for k, src in (("mean", "targetMeanPrice"), ("median", "targetMedianPrice"), ("high", "targetHighPrice"),
                       ("low", "targetLowPrice"), ("current", "currentPrice")):
            v = _num(info.get(src))
            if v is not None:
                out["targets"][k] = float(v)
    except Exception:
        pass
    try:
        apt = getattr(tk, "analyst_price_targets", None)
        if isinstance(apt, dict):
            for k in ("mean", "median", "high", "low", "current"):
                v = _num(apt.get(k))
                if v is not None:
                    out["targets"][k] = float(v)
    except Exception:
        pass
    try:
        rs = getattr(tk, "recommendations_summary", None)
        if rs is not None and hasattr(rs, "empty") and not rs.empty:
            cols = ["strongBuy", "buy", "hold", "sell", "strongSell"]

            def _d(row):
                return {c: int(_num(row.get(c)) or 0) for c in cols}
            rows = list(rs.iterrows())
            by = {str(r.get("period", "")): r for _, r in rows}
            cur = by["0m"] if "0m" in by else rows[0][1]
            out["dist"] = _d(cur)
            old = by["-3m"] if "-3m" in by else (rows[-1][1] if len(rows) > 1 else None)
            out["dist_3m"] = _d(old) if old is not None else None
    except Exception:
        pass
    try:
        ee = getattr(tk, "earnings_estimate", None)
        re_ = getattr(tk, "revenue_estimate", None)
        names = {"0q": "Current quarter", "+1q": "Next quarter", "0y": "Current fiscal year", "+1y": "Next fiscal year"}
        for idx in ("0q", "+1q", "0y", "+1y"):
            row = {"period": idx, "name": names[idx]}
            if ee is not None and hasattr(ee, "index") and idx in ee.index:
                e = ee.loc[idx]
                for k, src in (("eps", "avg"), ("eps_low", "low"), ("eps_high", "high"), ("n", "numberOfAnalysts"),
                               ("year_ago", "yearAgoEps"), ("growth", "growth")):
                    v = _num(e.get(src))
                    row[k] = float(v) if v is not None else None
                if row.get("growth") is not None and abs(row["growth"]) < 20:
                    row["growth"] *= 100
            if re_ is not None and hasattr(re_, "index") and idx in re_.index:
                r = re_.loc[idx]
                v, g = _num(r.get("avg")), _num(r.get("growth"))
                ya = _num(r.get("yearAgoRevenue"))
                if g is None and v is not None and ya:
                    g = v / ya - 1
                row["rev"] = float(v) if v is not None else None
                row["rev_growth"] = (float(g) * (100 if abs(g) < 20 else 1)) if g is not None else None
            if row.get("eps") is not None or row.get("rev") is not None:
                out["est"].append(row)
    except Exception:
        pass
    try:
        et = getattr(tk, "eps_trend", None)
        if et is not None and hasattr(et, "index"):
            for idx in ("0q", "0y", "+1y"):
                if idx in et.index:
                    r = et.loc[idx]
                    out["trend"][idx] = {k: _num(r.get(k)) for k in ("current", "7daysAgo", "30daysAgo",
                                                                    "60daysAgo", "90daysAgo")}
        er = getattr(tk, "eps_revisions", None)
        if er is not None and hasattr(er, "index"):
            for idx in ("0q", "0y", "+1y"):
                if idx in er.index:
                    r = er.loc[idx]
                    out["revisions"][idx] = {k: int(_num(r.get(k)) or 0) for k in
                                             ("upLast7days", "upLast30days", "downLast30days", "downLast7Days")}
    except Exception:
        pass
    try:
        ud = getattr(tk, "upgrades_downgrades", None)
        if ud is not None and hasattr(ud, "empty") and not ud.empty:
            for i, r in ud.head(8).iterrows():
                out["changes"].append({"date": str(pd.Timestamp(i).date()), "firm": str(r.get("Firm") or ""),
                                       "to": str(r.get("ToGrade") or ""), "from": str(r.get("FromGrade") or ""),
                                       "action": str(r.get("Action") or ""),
                                       "pt": _num(r.get("currentPriceTarget")),
                                       "pt_prev": _num(r.get("priorPriceTarget"))})
    except Exception:
        pass
    if out["dist"] or out["targets"] or out["est"]:
        out["src"] = "real"
    return out


_SEC_Q_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    "gross": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortization"],
    "dil_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
# Bilanço (an) değerleri: yalnızca "end" tarihi olur
_SEC_INSTANT = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "ltd": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "std": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper"],
}


def _sec_periods(facts):
    """Bir kavramın (start, end) → değer haritası (en son dosyalanan kazanır)."""
    out = {}
    for x in facts:
        s_, e_, v = x.get("start"), x.get("end"), x.get("val")
        if not (s_ and e_) or v is None:
            continue
        k = (s_, e_)
        if k not in out or str(x.get("filed", "")) >= out[k][1]:
            out[k] = (float(v), str(x.get("filed", "")))
    return {k: v[0] for k, v in out.items()}


@_ttl_cache(86400, fail_ttl=1800)
def get_sec_quarterly(t):
    """SEC companyfacts → her kavram için tüm dönemler {metric: {(start, end): value}} — çeyrek tablosu
    engine.fiscal_quarters ile kurulur. Yalnızca 10-Q / 10-K veren şirketler."""
    out = {"src": "none", "series": {}}
    if not _HAS_REQ or not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", str(t or "").upper()):
        return out
    cik = sec_cik(t)
    if not cik:
        return out
    try:
        js = _sec_get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % int(cik), timeout=40).json()
    except Exception:
        return out
    gaap = (js.get("facts") or {}).get("us-gaap") or {}
    for metric, names in _SEC_Q_CONCEPTS.items():
        best, best_end = None, ""
        for nm in names:
            node = gaap.get(nm)
            if not node:
                continue
            units = node.get("units") or {}
            arr = units.get("USD/shares") if metric == "eps" else (units.get("USD") or next(iter(units.values()), []))
            if not arr:
                continue
            per = _sec_periods(arr)
            last = max((e for _, e in per), default="")
            if last > best_end:
                best, best_end = per, last
        if best:
            out["series"][metric] = best
    # ---- v4.0: bilanço kalemleri (son değer) + kapak sayfasındaki hisse sayısı + son dosyalama
    inst = {}

    def _latest(node, unit="USD"):
        arr = ((node or {}).get("units") or {}).get(unit) or []
        arr = [x for x in arr if x.get("end") and x.get("val") is not None]
        if not arr:
            return None
        x = max(arr, key=lambda x: (str(x["end"]), str(x.get("filed", ""))))
        return {"val": float(x["val"]), "end": str(x["end"]), "form": str(x.get("form") or ""),
                "filed": str(x.get("filed") or "")}
    for k, names in _SEC_INSTANT.items():
        cands = [c for c in (_latest(gaap.get(nm)) for nm in names) if c]
        if cands:
            inst[k] = max(cands, key=lambda c: c["end"])
    dei = (js.get("facts") or {}).get("dei") or {}
    sh = _latest(dei.get("EntityCommonStockSharesOutstanding"), "shares")
    if sh:
        inst["shares_out"] = sh
    out["instant"] = inst
    try:
        rev_names = [nm for nm in _SEC_Q_CONCEPTS["revenue"] + _SEC_Q_CONCEPTS["net_income"] if gaap.get(nm)]
        allx = [x for nm in rev_names for x in ((gaap[nm].get("units") or {}).get("USD") or []) if x.get("filed")]
        if allx:
            x = max(allx, key=lambda x: (str(x.get("end")), str(x["filed"])))
            out["latest"] = {"form": str(x.get("form") or ""), "filed": str(x["filed"]), "end": str(x.get("end"))}
    except Exception:
        pass
    if out["series"].get("revenue") or out["series"].get("net_income"):
        out["src"] = "real"
        out["cik"] = cik
    return out


@_ttl_cache(21600, fail_ttl=900)
def get_yf_quarterly_fin(t):
    """Yahoo çeyrek tabloları (son ~5 çeyrek): gelir tablosu + nakit akışı, {metric: {end: value}}."""
    out = {"src": "none", "series": {}}
    if not _HAS_YF:
        return out
    tk = yf.Ticker(t)
    maps = {"revenue": ("Total Revenue", "Operating Revenue"), "gross": ("Gross Profit",),
            "op_income": ("Operating Income", "EBIT"), "net_income": ("Net Income Common Stockholders", "Net Income"),
            "eps": ("Diluted EPS", "Basic EPS")}
    cmaps = {"ocf": ("Operating Cash Flow",), "capex": ("Capital Expenditure",)}
    for attr, mp in (("quarterly_income_stmt", maps), ("quarterly_cashflow", cmaps)):
        try:
            df = getattr(tk, attr, None)
            if df is None or not hasattr(df, "empty") or df.empty:
                continue
            idx = {str(i).strip().lower(): i for i in df.index}
            for m, names in mp.items():
                row = next((df.loc[idx[n.lower()]] for n in names if n.lower() in idx), None)
                if row is None:
                    continue
                ser = {}
                for c in df.columns:
                    v = _num(row.get(c))
                    if v is not None:
                        ts = pd.Timestamp(c)
                        try:
                            ts = ts.tz_localize(None)
                        except (TypeError, AttributeError):
                            pass
                        ser[ts.normalize()] = float(abs(v) if m == "capex" else v)
                if ser:
                    out["series"][m] = ser
        except Exception:
            continue
    if out["series"]:
        out["src"] = "real"
    return out


# ======================================================================
# v4.0 — Bilanço (earnings) takvimi ve şirket bazında bilanço bilgisi
#   Kaynaklar: Nasdaq günlük bilanço takvimi (tarih, saat dilimi, EPS beklentisi, piyasa değeri),
#   Yahoo (takvim, earnings_dates, earnings_history, tahminler, çeyrek tablolar),
#   isteğe bağlı Finnhub (FINNHUB_API_KEY). Hiçbir alan üretilmez: kaynak vermiyorsa None.
# ======================================================================
US_TZ = "America/New_York"
_EARN_DAY = {}
_WHEN = {"time-pre-market": "bmo", "time-after-hours": "amc", "bmo": "bmo", "amc": "amc"}


def _f_or_none(v):
    f = _num_money(v) if not isinstance(v, (int, float)) else float(v)
    return None if f != f else float(f)


def us_today():
    return pd.Timestamp.now(tz=US_TZ).normalize().tz_localize(None)


def _nasdaq_earn_day(day):
    """Nasdaq bilanço takvimi — tek gün. Döner: [{sym, name, when, cap, eps_est, n, eps, surprise, fq,
    last_year_eps}] ya da None (alınamadı). Geçmiş günler 24 saat, bugün/gelecek 2 saat önbellekte."""
    day = str(pd.Timestamp(day).date())
    now = time.time()
    hit = _EARN_DAY.get(day)
    if hit is not None and now - hit[0] < hit[1]:
        return hit[2]
    rows = None
    if _HAS_REQ:
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day},
                             headers=_HEADERS, timeout=8)
            data = (r.json() or {}).get("data") or {}
            raw = data.get("rows")
            if raw is None and isinstance(data, dict) and "rows" in data:
                raw = []
            if raw is not None:
                rows = []
                for x in raw:
                    sym = str(x.get("symbol") or "").strip().upper()
                    if not sym or not re.match(r"^[A-Z][A-Z.\-]{0,6}$", sym):
                        continue
                    n = _f_or_none(x.get("noOfEsts"))
                    rows.append({"sym": sym, "name": str(x.get("name") or "").strip(),
                                 "when": _WHEN.get(str(x.get("time") or "").strip(), ""),
                                 "cap": _f_or_none(x.get("marketCap")), "eps_est": _f_or_none(x.get("epsForecast")),
                                 "n": int(n) if n is not None else None, "eps": _f_or_none(x.get("eps")),
                                 "surprise": _f_or_none(x.get("surprise")),
                                 "fq": str(x.get("fiscalQuarterEnding") or "").strip(),
                                 "last_year_eps": _f_or_none(x.get("lastYearEPS"))})
        except Exception:
            rows = None
    past = pd.Timestamp(day) < us_today()
    _EARN_DAY[day] = (now, (86400 if past else 7200) if rows is not None else 300, rows)
    if len(_EARN_DAY) > 400:
        for k in sorted(_EARN_DAY)[:150]:
            _EARN_DAY.pop(k, None)
    return rows


def _finnhub_earn(d0, d1):
    key = os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY")
    if not key or not _HAS_REQ:
        return None
    try:
        r = requests.get("https://finnhub.io/api/v1/calendar/earnings",
                         params={"from": str(d0.date()), "to": str(d1.date()), "token": key}, timeout=12)
        out = {}
        for e in (r.json() or {}).get("earningsCalendar", []):
            if not e.get("symbol") or not e.get("date"):
                continue
            a, est = _num(e.get("epsActual")), _num(e.get("epsEstimate"))
            out.setdefault(e["date"], []).append(
                {"sym": str(e["symbol"]).upper(), "name": "", "when": _WHEN.get(str(e.get("hour") or ""), ""),
                 "cap": None, "eps_est": est, "n": None, "eps": a,
                 "surprise": ((a - est) / abs(est) * 100) if (a is not None and est) else None,
                 "fq": f'Q{e.get("quarter")} {e.get("year")}' if e.get("quarter") else "", "last_year_eps": None})
        return out
    except Exception:
        return None


def earnings_week_start(offset=0, now=None):
    """Gösterilecek haftanın pazartesisi. İçinde bulunulan hafta pazartesiden cuma akşamına kadar
    sabit kalır; cumartesi (ABD saatiyle) gelince bir sonraki haftaya geçer."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=US_TZ)
    day = now.normalize().tz_localize(None) if now.tzinfo is not None else now.normalize()
    wd = day.weekday()
    monday = day - pd.Timedelta(days=wd) if wd <= 4 else day + pd.Timedelta(days=7 - wd)
    return monday + pd.Timedelta(days=7 * int(offset))


def get_earnings_week(monday):
    """Haftanın 5 işlem günü: {'days': [{'date', 'bmo': [...], 'amc': [...], 'tbd': [...], 'ok'}], 'src'}.
    Satırlar piyasa değerine göre büyükten küçüğe."""
    monday = pd.Timestamp(monday).normalize()
    days = [monday + pd.Timedelta(days=i) for i in range(5)]
    res = _pmap(_nasdaq_earn_day, [str(d.date()) for d in days], workers=5)
    if all(r is None for r in res):
        fh = _finnhub_earn(days[0], days[-1])
        if fh is not None:
            res = [fh.get(str(d.date()), []) for d in days]
    out = []
    for d, rows in zip(days, res):
        slot = {"date": str(d.date()), "bmo": [], "amc": [], "tbd": [], "ok": rows is not None}
        for x in sorted(rows or [], key=lambda x: -(x["cap"] or 0)):
            slot[x["when"] or "tbd"].append(x)
        out.append(slot)
    return {"days": out, "src": "real" if any(s["ok"] for s in out) else "none"}


def _earn_scan(sym, days=12):
    """Önümüzdeki işlem günlerinde Nasdaq takviminde bu sembol var mı? → (tarih, satır) ya da (None, None)."""
    t0 = us_today()
    ds = [t0 + pd.Timedelta(days=i) for i in range(days + 1)]
    ds = [str(d.date()) for d in ds if d.weekday() < 5]
    for d, rows in zip(ds, _pmap(_nasdaq_earn_day, ds, workers=6)):
        for x in rows or []:
            if x["sym"] == sym:
                return d, x
    return None, None


def _yf_earn_dates(tk):
    """Yahoo earnings_dates → [{'date', 'when', 'est', 'eps', 'surprise'}] (yeni → eski)."""
    out = []
    try:
        df = tk.get_earnings_dates(limit=12) if hasattr(tk, "get_earnings_dates") else getattr(tk, "earnings_dates", None)
        if df is None or not hasattr(df, "iterrows") or df.empty:
            return out
        for ts, r in df.iterrows():
            ts = pd.Timestamp(ts)
            if ts.tzinfo is not None:
                ts = ts.tz_convert(US_TZ).tz_localize(None)
            hm = ts.hour + ts.minute / 60.0
            when = "bmo" if 0 < hm < 9.5 else "amc" if hm >= 16 else ""
            sp_ = _num(r.get("Surprise(%)"))
            out.append({"date": str(ts.date()), "when": when, "est": _num(r.get("EPS Estimate")),
                        "eps": _num(r.get("Reported EPS")), "surprise": sp_})
        out.sort(key=lambda x: x["date"], reverse=True)
    except Exception:
        return []
    return out


def earnings_verdict(eps, est):
    """Beat / Miss / In line (sent hassasiyetinde)."""
    if eps is None or est is None:
        return None
    d = float(eps) - float(est)
    if abs(d) < 0.005:
        return "In line"
    return "Beat" if d > 0 else "Miss"


def _earnings_info(t):
    out = {"sym": t, "src": "none", "next": None, "last": None, "sources": [],
           "checked": pd.Timestamp.now(tz=TZ).strftime("%b %d %H:%M")}
    if not _HAS_YF or not t or any(c in t for c in "=^") or t.endswith("-USD"):
        return out
    tk = yf.Ticker(t)
    try:
        qd = get_quarterly.__wrapped__(t)
    except Exception:
        qd = {"q": [], "est": {}, "next_date": None}
    qrows = [r for r in qd.get("q") or [] if r.get("eps") == r.get("eps")]
    today = us_today()
    ed = _yf_earn_dates(tk)
    if ed:
        out["sources"].append("Yahoo earnings dates")
    # ---- seyreltilmiş hisse sayısı: son çeyreğin net kârı ÷ seyreltilmiş EPS (raporlanan değerlerden)
    shares, ni_last, ni_map = None, None, {}
    try:
        qf = get_yf_quarterly_fin.__wrapped__(t)
        ni_map = (qf.get("series") or {}).get("net_income") or {}
        eps_map = (qf.get("series") or {}).get("eps") or {}
        for k in sorted(ni_map, reverse=True):
            e = eps_map.get(k)
            if e and abs(e) > 1e-6 and ni_map[k]:
                sh = ni_map[k] / e
                if sh > 0:
                    shares = sh
                    break
    except Exception:
        pass
    # ---- sıradaki bilanço
    nd, nrow = _earn_scan(t)
    cal = {}
    try:
        c = getattr(tk, "calendar", None)
        cal = c if isinstance(c, dict) else {}
    except Exception:
        cal = {}
    cal_dates = []
    try:
        raw = cal.get("Earnings Date") or []
        raw = raw if isinstance(raw, (list, tuple)) else [raw]
        cal_dates = sorted(str(pd.Timestamp(x).date()) for x in raw)
    except Exception:
        cal_dates = []
    nxt = None
    if nd:
        nxt = {"date": nd, "when": nrow["when"], "confirmed": True, "source": "Nasdaq earnings calendar",
               "eps_est": nrow.get("eps_est"), "n": nrow.get("n")}
        out["sources"].append("Nasdaq earnings calendar")
    else:
        fut = [d for d in cal_dates if pd.Timestamp(d) >= today]
        fut_ed = sorted(x["date"] for x in ed if pd.Timestamp(x["date"]) >= today and x["eps"] is None)
        d0 = fut[0] if fut else (fut_ed[0] if fut_ed else None)
        if d0:
            w = next((x["when"] for x in ed if x["date"] == d0), "")
            nxt = {"date": d0, "when": w, "confirmed": bool(fut) and len(cal_dates) == 1,
                   "source": "Yahoo Finance", "eps_est": None, "n": None}
            out["sources"].append("Yahoo calendar")
    if nxt:
        if not nxt["when"]:
            nxt["when"] = next((x["when"] for x in ed if x["date"] == nxt["date"]), "")
        est = (qd.get("est") or {}).get("0q") or {}
        ya = est.get("year_ago")
        eps_est = est.get("avg")
        if eps_est is None:
            eps_est = _num(cal.get("Earnings Average")) if cal else None
        if eps_est is None:
            eps_est = nxt.get("eps_est")
        rev_est = est.get("rev") or (_num(cal.get("Revenue Average")) if cal else None)
        nxt.update({"eps_est": eps_est, "eps_low": est.get("low"), "eps_high": est.get("high"),
                    "n": est.get("n") or nxt.get("n"), "year_ago_eps": ya, "rev_est": rev_est,
                    "ni_est": (eps_est * shares) if (eps_est is not None and shares) else None,
                    "days": int((pd.Timestamp(nxt["date"]) - today).days), "period": "", "period_end": None})
        out["next"] = nxt
    # ---- son açıklanan bilanço
    rep = next((x for x in ed if x["eps"] is not None), None)
    last = None
    if qrows:
        r = qrows[-1]
        last = {"period_end": str(pd.Timestamp(r["end"]).date()), "eps": float(r["eps"]),
                "eps_est": None if r.get("est") != r.get("est") else float(r["est"]),
                "surprise_pct": None if r.get("surprise") != r.get("surprise") else float(r["surprise"]),
                "rev": None if r.get("rev") != r.get("rev") else float(r["rev"]), "gaap": bool(r.get("gaap")),
                "date": None, "when": ""}
        prev = next((p for p in qrows[:-1] if abs((pd.Timestamp(r["end"]) - pd.Timestamp(p["end"])).days - 365) <= 25), None)
        if prev:
            if prev.get("eps") == prev.get("eps") and abs(prev["eps"]) > 1e-9:
                last["eps_yoy"] = (r["eps"] / prev["eps"] - 1) * 100 if prev["eps"] > 0 else None
            if last["rev"] is not None and prev.get("rev") == prev.get("rev") and prev["rev"]:
                last["rev_yoy"] = (last["rev"] / prev["rev"] - 1) * 100
        out["sources"].append("Yahoo earnings history")
        if rep and abs(rep["eps"] - last["eps"]) < 0.011:
            last["date"], last["when"] = rep["date"], rep["when"]
            if last["eps_est"] is None:
                last["eps_est"] = rep["est"]
        elif rep and pd.Timestamp(rep["date"]) > pd.Timestamp(last["period_end"]) + pd.Timedelta(days=100):
            # tablolar henüz güncellenmedi ama yeni çeyreğin EPS'i açıklandı
            last = {"period_end": rep["date"], "eps": rep["eps"], "eps_est": rep["est"],
                    "surprise_pct": rep["surprise"], "rev": None, "gaap": False, "date": rep["date"],
                    "when": rep["when"], "fresh": True}
    elif rep:
        last = {"period_end": rep["date"], "eps": rep["eps"], "eps_est": rep["est"], "surprise_pct": rep["surprise"],
                "rev": None, "gaap": False, "date": rep["date"], "when": rep["when"], "fresh": True}
    if last:
        if last.get("surprise_pct") is None and last.get("eps_est"):
            last["surprise_pct"] = (last["eps"] - last["eps_est"]) / abs(last["eps_est"]) * 100
        last["verdict"] = earnings_verdict(last["eps"], last.get("eps_est"))
        if not last.get("fresh"):
            k = next((k for k in ni_map if abs((pd.Timestamp(k) - pd.Timestamp(last["period_end"])).days) <= 25), None)
            last["ni"] = float(ni_map[k]) if k is not None else None
        if shares:
            last["ni_adj"] = last["eps"] * shares
            last["ni_est"] = last["eps_est"] * shares if last.get("eps_est") is not None else None
        if last.get("date"):
            try:
                h = get_history(t)
                if h is not None and len(h) > 5 and h.attrs.get("src") != "mock":
                    idx = h.index
                    rd = pd.Timestamp(last["date"])
                    base = h[idx <= rd] if last.get("when") == "amc" else h[idx < rd]
                    if len(base) and len(h[idx > base.index[-1]]):
                        last["reaction_pct"] = (float(h["Close"].iloc[-1]) / float(base["Close"].iloc[-1]) - 1) * 100
            except Exception:
                pass
        out["last"] = last
    # açıklanma günü geçti ama rakam henüz yok
    if out["next"] and out["next"]["days"] < 0:
        out["next"]["overdue"] = True
    if out["next"] or out["last"]:
        out["src"] = "real"
    return out


_EINFO = {}


def get_earnings_info(t):
    """Şirketin sıradaki bilanço tarihi + beklentiler ve son bilançonun beklentiyle karşılaştırması.
    Bilanço yakınken (±2 gün) 10 dakikada, bir hafta içindeyse saatte, değilse 6 saatte bir yenilenir."""
    now = time.time()
    hit = _EINFO.get(t)
    if hit is not None and now - hit[0] < hit[1]:
        return hit[2]
    try:
        val = _earnings_info(t)
    except Exception:
        val = {"sym": t, "src": "none", "next": None, "last": None, "sources": [], "checked": ""}
    ttl = 21600
    if val.get("src") != "real":
        ttl = 600
    else:
        nx, ls = val.get("next"), val.get("last")
        if nx and nx.get("days") is not None and nx["days"] <= 1:
            ttl = 600
        elif ls and ls.get("date") and (us_today() - pd.Timestamp(ls["date"])).days <= 2:
            ttl = 900
        elif nx and nx.get("days") is not None and nx["days"] <= 7:
            ttl = 3600
    _EINFO[t] = (now, ttl, val)
    if len(_EINFO) > 500:
        for k in list(_EINFO)[:150]:
            _EINFO.pop(k, None)
    return val


get_earnings_info.clear = _EINFO.clear


# ======================================================================
# v4.0 — Unusual Whales (kurumsal / dark pool işlemleri)
#   Ücretli API: Secrets'ta UNUSUAL_WHALES_TOKEN olmalı. Token yoksa hiçbir şey üretilmez ("none").
#   GET https://api.unusualwhales.com/api/darkpool/{ticker}   (Authorization: Bearer <token>)
# ======================================================================
_UW = {"err": "", "ok_at": None}


def uw_token():
    return os.environ.get("UNUSUAL_WHALES_TOKEN") or os.environ.get("UW_TOKEN") or ""


def uw_status():
    return {"on": bool(uw_token()), "err": _UW["err"], "ok_at": _UW["ok_at"]}


def _uw_get(path, params=None):
    tok = uw_token()
    if not tok or not _HAS_REQ:
        return None
    try:
        r = requests.get("https://api.unusualwhales.com" + path, params=params or {}, timeout=10,
                         headers={"Authorization": "Bearer " + tok, "Accept": "application/json",
                                  "User-Agent": "pulse-dashboard"})
        if r.status_code in (401, 403):
            _UW["err"] = f"Unusual Whales rejected the token (HTTP {r.status_code})"
            return None
        if r.status_code == 429:
            _UW["err"] = "Unusual Whales rate limit reached — retrying later"
            return None
        if r.status_code != 200:
            _UW["err"] = f"Unusual Whales answered HTTP {r.status_code}"
            return None
        _UW["err"], _UW["ok_at"] = "", time.time()
        return r.json()
    except Exception as ex:
        _UW["err"] = f"Unusual Whales not reachable ({type(ex).__name__})"
        return None


@_ttl_cache(900, fail_ttl=180)
def get_uw_darkpool(t, days=5, min_premium=250000):
    """Son işlem günlerinin büyük dark-pool / borsa dışı işlemleri.
    Döner: {'src': 'uw'|'none'|'error', 'err', 'prints': [...], 'levels': [...], 'by_day': {...}, 'total'}
      prints : {date, ts, price, size, premium, side}   side: buy (≥ en iyi satış), sell (≤ en iyi alış), mid
      levels : fiyat kümeleri — {price, premium, size, n, buy, sell}  (primi en yüksek 6)
      by_day : {'YYYY-MM-DD': {'premium', 'buy', 'sell', 'n'}}"""
    out = {"src": "none", "err": "", "prints": [], "levels": [], "by_day": {}, "total": 0.0}
    if not uw_token():
        return out
    d = us_today()
    dates = []
    while len(dates) < int(days):
        if d.weekday() < 5:
            dates.append(str(d.date()))
        d -= pd.Timedelta(days=1)

    def one(day):
        return _uw_get(f"/api/darkpool/{t}", {"date": day, "limit": 500, "min_premium": int(min_premium),
                                               "order_by": "premium", "cancellation_status": "hide_cancelled"})
    res = _pmap(one, dates, workers=3)
    if all(r is None for r in res):
        out.update({"src": "error", "err": _UW["err"] or "no answer"})
        return out
    prints = []
    for day, r in zip(dates, res):
        rows = (r or {}).get("data") if isinstance(r, dict) else None
        for x in rows or []:
            try:
                if x.get("canceled"):
                    continue
                price, size = float(x.get("price")), float(x.get("size") or 0)
                prem = float(x.get("premium") or price * size)
                ask, bid = _num(x.get("nbbo_ask")), _num(x.get("nbbo_bid"))
                side = "buy" if (ask and price >= ask) else "sell" if (bid and price <= bid) else "mid"
                prints.append({"date": day, "ts": str(x.get("executed_at") or ""), "price": price, "size": size,
                               "premium": prem, "side": side})
            except (TypeError, ValueError):
                continue
    if not prints:
        out["src"] = "uw"
        return out
    px = float(np.median([p["price"] for p in prints]))
    step = max(px * 0.0025, 0.01)
    lv, by_day = {}, {}
    for p_ in prints:
        k = round(p_["price"] / step)
        e = lv.setdefault(k, {"pp": 0.0, "premium": 0.0, "size": 0.0, "n": 0, "buy": 0.0, "sell": 0.0})
        e["pp"] += p_["price"] * p_["premium"]
        e["premium"] += p_["premium"]
        e["size"] += p_["size"]
        e["n"] += 1
        if p_["side"] in ("buy", "sell"):
            e[p_["side"]] += p_["premium"]
        dd = by_day.setdefault(p_["date"], {"premium": 0.0, "buy": 0.0, "sell": 0.0, "n": 0})
        dd["premium"] += p_["premium"]
        dd["n"] += 1
        if p_["side"] in ("buy", "sell"):
            dd[p_["side"]] += p_["premium"]
    levels = [{"price": e["pp"] / e["premium"], "premium": e["premium"], "size": e["size"], "n": e["n"],
               "buy": e["buy"], "sell": e["sell"]} for e in lv.values() if e["premium"] > 0]
    levels.sort(key=lambda e: -e["premium"])
    prints.sort(key=lambda p_: -p_["premium"])
    out.update({"src": "uw", "prints": prints[:60], "levels": levels[:6], "by_day": by_day,
                "total": float(sum(p_["premium"] for p_ in prints))})
    return out


# ======================================================================
# v4.0 — Topluluk duyarlılığı (Reddit · StockTwits · X)
#   Reddit    : finans alt-forumlarında arama (herkese açık JSON; REDDIT_CLIENT_ID/SECRET varsa OAuth)
#               + ApeWisdom'un Reddit anılma sayıları (hype)
#   StockTwits: sembol akışı — kullanıcıların kendi koyduğu Bullish/Bearish etiketi
#   X         : yalnızca X_BEARER_TOKEN varsa (X'in ücretsiz okuma API'si yok)
#   Metin puanı sözlük tabanlıdır (şeffaf, model yok). Hiçbir gönderi / sayı üretilmez.
# ======================================================================
SENT_SUBS = "wallstreetbets+stocks+investing+options+StockMarket+pennystocks+Daytrading+swingtrading"
_BULL_W = {"bull", "bullish", "buy", "buying", "bought", "long", "calls", "call", "moon", "mooning", "rocket",
           "breakout", "breaking", "rally", "rallying", "rip", "ripping", "squeeze", "undervalued", "cheap",
           "beat", "beats", "upgrade", "upgraded", "strong", "growth", "accumulate", "accumulating", "hold",
           "holding", "hodl", "dip", "btfd", "green", "up", "higher", "outperform", "winner", "gains", "gain",
           "profit", "bottomed", "oversold", "support", "loading", "adding", "added", "tendies", "ath", "soar",
           "soaring", "surge", "surging", "pump", "pumping", "yolo", "print", "printing", "upside", "raised"}
_BEAR_W = {"bear", "bearish", "sell", "selling", "sold", "short", "shorting", "puts", "put", "crash", "crashing",
           "dump", "dumping", "drop", "dropping", "tank", "tanking", "overvalued", "expensive", "bubble", "miss",
           "missed", "downgrade", "downgraded", "weak", "red", "down", "lower", "underperform", "loser", "loss",
           "losses", "bagholder", "bagholding", "bag", "rug", "rugpull", "overbought", "resistance", "dilution",
           "diluting", "offering", "bankrupt", "bankruptcy", "fraud", "scam", "plunge", "plunging", "collapse",
           "fall", "falling", "fell", "dead", "top", "topped", "downside", "cut", "warning", "lawsuit", "fade"}
_NEG_W = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wont", "won't", "cant", "can't", "without",
          "nobody", "stop", "avoid"}
_BULL_E = ("🚀", "📈", "🟢", "💎", "🐂", "🔥", "🌕", "💰")
_BEAR_E = ("📉", "🔻", "🩸", "🐻", "💀", "🤡", "🔴", "⚰")


def text_sentiment(text):
    """Metnin duyarlılığı: −1 … +1 (sözlük + olumsuzlama + emoji). 0 = belirsiz / nötr."""
    txt = str(text or "")
    low = txt.lower()
    toks = re.findall(r"[a-z']+", low)
    b = s = 0.0
    for i, w in enumerate(toks):
        v = 1 if w in _BULL_W else -1 if w in _BEAR_W else 0
        if not v:
            continue
        if any(x in _NEG_W for x in toks[max(0, i - 2):i]):
            v = -v
        if v > 0:
            b += 1
        else:
            s += 1
    b += sum(min(3, txt.count(e)) for e in _BULL_E) * 0.7
    s += sum(min(3, txt.count(e)) for e in _BEAR_E) * 0.7
    if b + s == 0:
        return 0.0
    return float((b - s) / (b + s))


def _mentions(t, name, text):
    """Gönderi gerçekten bu hisseden mi söz ediyor? ($TICKER, büyük harfle TICKER ya da şirket adı)."""
    if not text:
        return False
    if re.search(r"\$" + re.escape(t) + r"\b", text, re.I):
        return True
    if len(t) >= 3 and re.search(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", text):
        return True
    first = re.sub(r"[^A-Za-z ]", "", str(name or "")).split()
    key = first[0] if first else ""
    return len(key) >= 4 and key.lower() not in ("the", "inc", "corp", "group", "holdings") and \
        re.search(r"\b" + re.escape(key) + r"\b", text, re.I) is not None


_RTOK = {"tok": None, "exp": 0.0}


def _reddit_token():
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and sec and _HAS_REQ):
        return None
    if _RTOK["tok"] and time.time() < _RTOK["exp"]:
        return _RTOK["tok"]
    try:
        r = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                          data={"grant_type": "client_credentials"},
                          headers={"User-Agent": "pulse-dashboard/4.0"}, timeout=8)
        j = r.json()
        _RTOK["tok"], _RTOK["exp"] = j.get("access_token"), time.time() + float(j.get("expires_in", 3000)) - 120
        return _RTOK["tok"]
    except Exception:
        return None


def _reddit_posts(t, name):
    """(gönderiler | None, hata). Gönderi: {title, text, score, comments, ts, url, sub}."""
    if not _HAS_REQ:
        return None, "offline"
    q = f'"${t}" OR "{t}"' if len(t) >= 3 else f'"${t}"'
    params = {"q": q, "restrict_sr": 1, "sort": "new", "t": "week", "limit": 100, "raw_json": 1}
    tok = _reddit_token()
    try:
        if tok:
            r = requests.get(f"https://oauth.reddit.com/r/{SENT_SUBS}/search", params=params, timeout=10,
                             headers={"Authorization": "Bearer " + tok, "User-Agent": "pulse-dashboard/4.0"})
        else:
            r = requests.get(f"https://www.reddit.com/r/{SENT_SUBS}/search.json", params=params, timeout=10,
                             headers={"User-Agent": "pulse-dashboard/4.0 (market dashboard)"})
        if r.status_code != 200:
            return None, f"Reddit answered HTTP {r.status_code}" + (
                "" if tok else " — Reddit often blocks cloud servers without an app key")
        out = []
        for ch_ in ((r.json() or {}).get("data") or {}).get("children") or []:
            x = ch_.get("data") or {}
            title, body = str(x.get("title") or ""), str(x.get("selftext") or "")[:1500]
            if not _mentions(t, name, title + " " + body):
                continue
            out.append({"title": title, "text": body, "score": float(x.get("score") or 0),
                        "comments": float(x.get("num_comments") or 0), "ts": float(x.get("created_utc") or 0),
                        "url": "https://www.reddit.com" + str(x.get("permalink") or ""),
                        "sub": str(x.get("subreddit") or "")})
        return out, ""
    except Exception as ex:
        return None, f"Reddit not reachable ({type(ex).__name__})"


@_ttl_cache(600, fail_ttl=180)
def get_reddit_trending():
    """ApeWisdom: Reddit'te en çok anılan hisseler → {ticker: {rank, mentions, upvotes, rank_prev, mentions_prev}}."""
    if not _HAS_REQ:
        return {"map": {}, "src": "none"}

    def page(n):
        try:
            r = requests.get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{n}", timeout=8,
                             headers={"User-Agent": "pulse-dashboard/4.0"})
            return (r.json() or {}).get("results") or []
        except Exception:
            return None
    out = {}
    for rows in _pmap(page, [1, 2, 3], workers=3):
        for x in rows or []:
            tk_ = str(x.get("ticker") or "").upper()
            if not tk_:
                continue
            f = lambda k: _num(x.get(k))
            out[tk_] = {"rank": f("rank"), "mentions": f("mentions"), "upvotes": f("upvotes"),
                        "rank_prev": f("rank_24h_ago"), "mentions_prev": f("mentions_24h_ago")}
    return {"map": out, "src": "real" if out else "none"}


def _stocktwits(t):
    if not _HAS_REQ:
        return None, "offline", None
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{t}.json", timeout=8,
                         headers={"User-Agent": _HEADERS.get("User-Agent", "Mozilla/5.0"), "Accept": "application/json"})
        if r.status_code != 200:
            return None, f"StockTwits answered HTTP {r.status_code}", None
        j = r.json() or {}
        out = []
        for m in j.get("messages") or []:
            lab = (((m.get("entities") or {}).get("sentiment")) or {}).get("basic")
            try:
                ts = pd.Timestamp(m.get("created_at")).timestamp()
            except Exception:
                ts = 0.0
            out.append({"title": str(m.get("body") or "")[:400], "text": "", "label": lab,
                        "score": float(((m.get("likes") or {}).get("total")) or 0), "comments": 0.0, "ts": ts,
                        "url": f"https://stocktwits.com/message/{m.get('id')}" if m.get("id") else "", "sub": ""})
        return out, "", _num((j.get("symbol") or {}).get("watchlist_count"))
    except Exception as ex:
        return None, f"StockTwits not reachable ({type(ex).__name__})", None


def x_token():
    return os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN") or ""


def _x_posts(t):
    tok = x_token()
    if not tok or not _HAS_REQ:
        return None, "not connected"
    try:
        r = requests.get("https://api.twitter.com/2/tweets/search/recent", timeout=10,
                         headers={"Authorization": "Bearer " + tok},
                         params={"query": f'("${t}" OR #{t}) lang:en -is:retweet', "max_results": 100,
                                 "tweet.fields": "created_at,public_metrics"})
        if r.status_code != 200:
            return None, f"X answered HTTP {r.status_code}"
        out = []
        for x in (r.json() or {}).get("data") or []:
            pm = x.get("public_metrics") or {}
            try:
                ts = pd.Timestamp(x.get("created_at")).timestamp()
            except Exception:
                ts = 0.0
            out.append({"title": str(x.get("text") or "")[:400], "text": "", "ts": ts, "sub": "",
                        "score": float(pm.get("like_count") or 0) + 2 * float(pm.get("retweet_count") or 0),
                        "comments": float(pm.get("reply_count") or 0),
                        "url": f"https://x.com/i/web/status/{x.get('id')}"})
        return out, ""
    except Exception as ex:
        return None, f"X not reachable ({type(ex).__name__})"


def _score_posts(posts):
    """Gönderiler → {'n','bull','bear','neutral','score'} (beğeni/yorumla ağırlıklı, −100 … +100)."""
    b = s = n0 = 0
    wsum = acc = 0.0
    for p_ in posts:
        lab = p_.get("label")
        v = 1.0 if lab == "Bullish" else -1.0 if lab == "Bearish" else text_sentiment(p_["title"] + " " + p_.get("text", ""))
        sgn = 1 if v > 0.15 else -1 if v < -0.15 else 0
        p_["sent"] = sgn
        w = 1.0 + np.log10(1.0 + max(0.0, p_.get("score", 0.0)) + max(0.0, p_.get("comments", 0.0)))
        wsum += w
        acc += w * sgn
        if sgn > 0:
            b += 1
        elif sgn < 0:
            s += 1
        else:
            n0 += 1
    return {"n": len(posts), "bull": b, "bear": s, "neutral": n0,
            "score": float(acc / wsum * 100) if wsum else 0.0}


def sentiment_label(score, n):
    if n < 5:
        return "Not enough posts"
    return "Bullish" if score >= 20 else "Bearish" if score <= -20 else "Neutral"


def hype_level(h):
    m, prev, rank = h.get("mentions"), h.get("mentions_prev"), h.get("rank")
    if m is None:
        return "Unknown"
    ratio = (m / prev) if prev else None
    if (rank is not None and rank <= 10) or (ratio is not None and ratio >= 3 and m >= 50):
        return "Extreme"
    if (rank is not None and rank <= 30) or (ratio is not None and ratio >= 1.6 and m >= 20):
        return "Elevated"
    return "Normal" if m >= 5 else "Low"


_SENT, _SENT_HIST = {}, {}


def _social_sentiment(t):
    name = company_name(t)
    red, red_err = _reddit_posts(t, name)
    stw, stw_err, watchers = _stocktwits(t)
    xp, x_err = _x_posts(t)
    tr_ = get_reddit_trending()
    ape = (tr_.get("map") or {}).get(t)
    now = time.time()
    src = {}
    total_w = total = 0.0
    n_all = bull = bear = neu = 0
    top = []
    for key, label, posts, err in (("reddit", "Reddit", red, red_err), ("stocktwits", "StockTwits", stw, stw_err),
                                   ("x", "X (Twitter)", xp, x_err)):
        if posts is None:
            src[key] = {"name": label, "ok": False, "err": err, "n": 0}
            continue
        sc = _score_posts(posts)
        d24 = sum(1 for p_ in posts if now - p_["ts"] <= 86400)
        src[key] = {"name": label, "ok": True, "err": "", **sc, "last24h": d24}
        w = min(sc["n"], 60)
        total_w += w
        total += w * sc["score"]
        n_all += sc["n"]
        bull += sc["bull"]
        bear += sc["bear"]
        neu += sc["neutral"]
        for p_ in posts:
            top.append({"src": label, "title": p_["title"][:160], "url": p_["url"], "sent": p_["sent"],
                        "eng": p_.get("score", 0) + p_.get("comments", 0), "ts": p_["ts"], "sub": p_.get("sub", "")})
    score = total / total_w if total_w else 0.0
    hype = {"mentions": (ape or {}).get("mentions"), "mentions_prev": (ape or {}).get("mentions_prev"),
            "rank": (ape or {}).get("rank"), "rank_prev": (ape or {}).get("rank_prev"),
            "upvotes": (ape or {}).get("upvotes"), "watchers": watchers,
            "tracked": tr_.get("src") == "real"}
    if hype["mentions"] is None and hype["tracked"]:
        hype["mentions"] = 0.0            # liste alındı ama hisse ilk 300'de değil → az anılıyor
    if hype["mentions"] is not None and hype["mentions_prev"]:
        hype["change_pct"] = (hype["mentions"] / hype["mentions_prev"] - 1) * 100
    hype["level"] = hype_level(hype)
    top.sort(key=lambda p_: (-(now - p_["ts"] <= 3 * 86400), -p_["eng"]))
    ok_any = any(v.get("ok") for v in src.values()) or hype["tracked"]
    out = {"sym": t, "src": "real" if ok_any else "none", "score": round(score, 1), "n": n_all,
           "label": sentiment_label(score, n_all), "bull": bull, "bear": bear, "neutral": neu,
           "sources": src, "hype": hype, "top": top[:5],
           "checked": pd.Timestamp.now(tz=TZ).strftime("%H:%M")}
    if ok_any and n_all >= 5:
        hist = _SENT_HIST.setdefault(t, [])
        if not hist or now - hist[-1][0] > 540:
            hist.append((now, out["score"]))
            del hist[:-144]
    out["hist"] = [(a_, b_) for a_, b_ in _SENT_HIST.get(t, [])]
    return out


def get_sentiment(t):
    """Topluluk duyarlılığı — 10 dakikada bir yenilenir (sayfa açıkken sürekli tarama)."""
    now = time.time()
    hit = _SENT.get(t)
    if hit is not None and now - hit[0] < hit[1]:
        return hit[2]
    try:
        val = _social_sentiment(t)
    except Exception:
        val = {"sym": t, "src": "none", "score": 0.0, "n": 0, "label": "Not enough posts", "bull": 0, "bear": 0,
               "neutral": 0, "sources": {}, "hype": {"level": "Unknown"}, "top": [], "checked": "", "hist": []}
    _SENT[t] = (now, 600 if val.get("src") == "real" else 180, val)
    if len(_SENT) > 300:
        for k in list(_SENT)[:100]:
            _SENT.pop(k, None)
    return val


get_sentiment.clear = _SENT.clear



# ======================================================================
# v4.0 — Değer patikasının veri tabanı: şirketin EN SON resmî raporları
#   Akış kalemleri (ciro, faaliyet kârı, capex …): son 12 ay = son mali yıl + bu yılın YTD'si − geçen yılın
#   aynı dönemi (SEC 10-K / 10-Q). Bilanço kalemleri: son çeyrek sonu. Hiçbir değer tahmin edilmez; kaynak
#   vermiyorsa alan boş kalır ve model yıllık tabloya (son 10-K) döner.
# ======================================================================
def _sec_ttm(per):
    """{(start, end): değer} → son 12 ay: {'val', 'end', 'kind'} ya da None."""
    items = []
    for (s_, e_), v in (per or {}).items():
        try:
            items.append((pd.Timestamp(s_), pd.Timestamp(e_), float(v)))
        except (TypeError, ValueError):
            continue
    fy = [x for x in items if 350 <= (x[1] - x[0]).days <= 380]
    if not fy:
        return None
    s0, e0, v0 = max(fy, key=lambda x: x[1])
    base = {"val": v0, "end": str(e0.date()), "kind": "fiscal year"}
    day = pd.Timedelta(days=1)

    def ytd(start, until=None):
        """start'tan başlayan en uzun dönem: doğrudan YTD kaydı ya da art arda çeyreklerin toplamı."""
        direct = [x for x in items if abs((x[0] - start).days) <= 7 and (x[1] - x[0]).days < 350
                  and (until is None or x[1] <= until + pd.Timedelta(days=8))]
        best = max(direct, key=lambda x: x[1]) if direct else None
        cur, tot, end = start, 0.0, None
        while True:
            nx = [x for x in items if abs((x[0] - cur).days) <= 7 and (x[1] - x[0]).days <= 100
                  and (until is None or x[1] <= until + pd.Timedelta(days=8))]
            if not nx:
                break
            x = max(nx, key=lambda x: x[1])
            tot, end, cur = tot + x[2], x[1], x[1] + day
        if end is not None and (best is None or end > best[1] + pd.Timedelta(days=8)):
            return end, tot
        return (best[1], best[2]) if best else (None, None)
    e1, v1 = ytd(e0 + day)
    if e1 is None:
        return base
    ep, vp = ytd(s0, until=e1 - pd.DateOffset(years=1))
    if ep is None or abs((ep - (e1 - pd.DateOffset(years=1))).days) > 8:
        return base
    return {"val": v0 + v1 - vp, "end": str(e1.date()), "kind": "last 12 months"}


def _sec_annual(per):
    """Mali yıl değerleri {yıl sonu: değer} (eski → yeni)."""
    out = {}
    for (s_, e_), v in (per or {}).items():
        try:
            d = (pd.Timestamp(e_) - pd.Timestamp(s_)).days
        except (TypeError, ValueError):
            continue
        if 350 <= d <= 380:
            out[str(pd.Timestamp(e_).date())] = float(v)
    return dict(sorted(out.items()))


@_ttl_cache(21600, fail_ttl=900)
def get_latest_basis(t):
    """Şirketin en güncel resmî verileri → {'src', 'items': {ad: {'val', 'as_of', 'source'}}, 'annual': {...}}.
    items: rev_ttm, op_ttm, ni_ttm, ocf_ttm, capex_ttm, da_ttm, dil_shares, shares_out, cash, debt."""
    out = {"src": "none", "items": {}, "annual": {}, "latest": None}
    sec = get_sec_quarterly(t)
    ser = sec.get("series") or {}
    put = lambda k, v, as_of, source: out["items"].__setitem__(k, {"val": float(v), "as_of": as_of, "source": source})  # noqa: E731
    if sec.get("src") == "real":
        lt = sec.get("latest") or {}
        out["latest"] = lt
        tag = f'SEC {lt.get("form") or "filing"}' + (f', filed {lt["filed"]}' if lt.get("filed") else "")
        for k, m in (("rev_ttm", "revenue"), ("op_ttm", "op_income"), ("ni_ttm", "net_income"), ("ocf_ttm", "ocf"),
                     ("capex_ttm", "capex"), ("da_ttm", "da")):
            x = _sec_ttm(ser.get(m))
            if x:
                put(k, abs(x["val"]) if k == "capex_ttm" else x["val"], f'{x["kind"]} to {x["end"]}', tag)
        ds = ser.get("dil_shares") or {}
        q = [(pd.Timestamp(e_), v) for (s_, e_), v in ds.items()
             if (pd.Timestamp(e_) - pd.Timestamp(s_)).days <= 100]
        if q:
            e_, v = max(q, key=lambda x: x[0])
            put("dil_shares", v, f"quarter to {e_.date()}", tag)
        inst = sec.get("instant") or {}
        if inst.get("shares_out"):
            x = inst["shares_out"]
            put("shares_out", x["val"], f'as of {x["end"]}', f'SEC {x.get("form") or "filing"} cover page')
        if inst.get("cash"):
            c = inst["cash"]
            sti = inst.get("sti")
            put("cash", c["val"] + (sti["val"] if sti and sti["end"] == c["end"] else 0.0), f'as of {c["end"]}',
                f'SEC {c.get("form") or "filing"} balance sheet')
        debt = [inst[k] for k in ("ltd", "std") if inst.get(k)]
        if debt:
            end = max(x["end"] for x in debt)
            put("debt", sum(x["val"] for x in debt if x["end"] == end), f"as of {end}",
                f'SEC {debt[0].get("form") or "filing"} balance sheet')
        out["annual"] = {"revenue": _sec_annual(ser.get("revenue")), "op_income": _sec_annual(ser.get("op_income"))}
        out["src"] = "sec"
    # Yahoo'nun çeyrek bilançosu (şirketin raporundan): toplam borç ve nakit — SEC etiketleri eksikse
    if _HAS_YF and ("debt" not in out["items"] or "cash" not in out["items"]):
        try:
            bs = getattr(yf.Ticker(t), "quarterly_balance_sheet", None)
            if bs is not None and hasattr(bs, "empty") and not bs.empty:
                idx = {str(i).strip().lower(): i for i in bs.index}
                col = max(bs.columns)
                as_of = f"as of {pd.Timestamp(col).date()}"
                for k, names in (("debt", ("total debt",)),
                                 ("cash", ("cash cash equivalents and short term investments",
                                           "cash and cash equivalents"))):
                    if k in out["items"]:
                        continue
                    v = next((_num(bs.loc[idx[n], col]) for n in names if n in idx), None)
                    if v is not None:
                        put(k, v, as_of, "company balance sheet via Yahoo Finance")
                        if out["src"] == "none":
                            out["src"] = "yahoo"
        except Exception:
            pass
    return out
