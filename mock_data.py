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

DATA_VERSION = "3.6"

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
             "when": p["when_short"], "source": p["source"], "spark": p["spark"], "link": p.get("link")}
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


def get_calendar_rows(day="Today", impact="All"):
    rows = _calendar_all()
    now = pd.Timestamp.now(tz=TZ)
    today = now.normalize()
    target = {"Yesterday": today - pd.Timedelta(days=1), "Today": today, "Tomorrow": today + pd.Timedelta(days=1)}.get(day)
    if target is not None:
        rows = [r for r in rows if r["dt"].normalize() == target]
    if impact == "High":
        rows = [r for r in rows if r["impact"] >= 3]
    elif impact == "Medium +":
        rows = [r for r in rows if r["impact"] >= 2]
    nxt = next((r for r in rows if r["dt"] >= now), None)
    out = []
    for r in rows:
        rr = dict(r)
        rr["next"] = r is nxt
        rr["day_label"] = tr_date_label(r["dt"])
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
    """{ticker: 'YYYY-MM-DD'} — önümüzdeki günlerde bilanço açıklayacaklar."""
    today = pd.Timestamp.now(tz=TZ).normalize()
    end = today + pd.Timedelta(days=days)
    key = os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY")
    emap = {}
    if key and _HAS_REQ:
        try:
            r = requests.get("https://finnhub.io/api/v1/calendar/earnings",
                             params={"from": today.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"),
                                     "token": key}, timeout=12)
            for e in r.json().get("earningsCalendar", []):
                if e.get("symbol") and e.get("date"):
                    emap.setdefault(e["symbol"], e["date"])
            if emap:
                return {"map": emap, "src": "real"}
        except Exception:
            emap = {}
    if _HAS_REQ:
        def one_day(d):
            try:
                r = requests.get("https://api.nasdaq.com/api/calendar/earnings",
                                 params={"date": d.strftime("%Y-%m-%d")}, headers=_HEADERS, timeout=6)
                rows = (r.json().get("data") or {}).get("rows") or []
                return [row["symbol"] for row in rows if row.get("symbol")]
            except Exception:
                return None

        bdays = [today + pd.Timedelta(days=i) for i in range(days + 1)]
        bdays = [d for d in bdays if d.weekday() < 5]
        for d, syms in zip(bdays, _pmap(one_day, bdays, workers=6)):  # gün sırası korunur
            for s in syms or []:
                emap.setdefault(s, d.strftime("%Y-%m-%d"))
        if emap:
            return {"map": emap, "src": "real"}
    if not _HAS_YF:  # tamamen çevrimdışı demo modu
        rng = np.random.default_rng(42)
        return {"map": {t: (today + pd.Timedelta(days=int(rng.integers(2, 60)))).strftime("%Y-%m-%d")
                        for t in SCAN_UNIVERSE}, "src": "mock"}
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
        out.append({"title": _t("title"), "link": _t("link"), "pub": _t("pubDate"),
                    "desc": _t("description"),
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
                    "thumb": None, "summary": summary, "related": [ticker] if ticker else [], "src": "real"})
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
