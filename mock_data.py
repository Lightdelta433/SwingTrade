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

DATA_VERSION = "3.0"

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
    "AAPL":  {"name": "Apple", "domain": "apple.com", "sector": "Teknoloji",
              "desc": "iPhone, Mac ve servislerden oluşan donanım-yazılım ekosistemiyle dünyanın en değerli tüketici teknolojisi şirketlerinden biri."},
    "MSFT":  {"name": "Microsoft", "domain": "microsoft.com", "sector": "Teknoloji",
              "desc": "Windows, Office ve Azure bulut platformuyla kurumsal yazılım ve bulut altyapısında lider."},
    "NVDA":  {"name": "NVIDIA", "domain": "nvidia.com", "sector": "Yarı İletken",
              "desc": "Yapay zeka ve veri merkezi GPU'larında baskın oyuncu; hızlandırılmış hesaplamanın merkezinde."},
    "AMZN":  {"name": "Amazon", "domain": "amazon.com", "sector": "Tüketici",
              "desc": "E-ticaret devi ve AWS ile dünyanın en büyük bulut servis sağlayıcısı."},
    "GOOGL": {"name": "Alphabet", "domain": "google.com", "sector": "Teknoloji",
              "desc": "Google arama, reklam, YouTube ve bulut; ayrıca yapay zeka araştırmalarında öncü."},
    "META":  {"name": "Meta Platforms", "domain": "meta.com", "sector": "Teknoloji",
              "desc": "Facebook, Instagram ve WhatsApp'ı işleten sosyal medya ve dijital reklam devi."},
    "TSLA":  {"name": "Tesla", "domain": "tesla.com", "sector": "Otomotiv",
              "desc": "Elektrikli araç üreticisi; enerji depolama ve otonom sürüş alanlarında da faaliyette."},
    "AMD":   {"name": "AMD", "domain": "amd.com", "sector": "Yarı İletken",
              "desc": "CPU ve GPU üreticisi; veri merkezi ve PC pazarında Intel ve NVIDIA'nın başlıca rakibi."},
    "NFLX":  {"name": "Netflix", "domain": "netflix.com", "sector": "İletişim",
              "desc": "Dünya çapında abonelik tabanlı video akış platformu ve içerik üreticisi."},
    "CRM":   {"name": "Salesforce", "domain": "salesforce.com", "sector": "Yazılım",
              "desc": "Bulut tabanlı müşteri ilişkileri yönetimi (CRM) yazılımında pazar lideri."},
    "ADBE":  {"name": "Adobe", "domain": "adobe.com", "sector": "Yazılım",
              "desc": "Photoshop, Acrobat ve yaratıcı bulut araçlarıyla dijital medya yazılımı lideri."},
    "AVGO":  {"name": "Broadcom", "domain": "broadcom.com", "sector": "Yarı İletken",
              "desc": "Ağ, kablosuz ve altyapı çipleri üreten, kurumsal yazılımda da büyüyen yarı iletken devi."},
    "COST":  {"name": "Costco", "domain": "costco.com", "sector": "Perakende",
              "desc": "Üyelik tabanlı toptan perakende zinciri; istikrarlı gelir ve güçlü müşteri sadakati."},
    "PEP":   {"name": "PepsiCo", "domain": "pepsico.com", "sector": "Temel Tüketim",
              "desc": "İçecek ve atıştırmalık devi; Pepsi, Lay's ve Gatorade gibi küresel markalara sahip."},
    "SHOP":  {"name": "Shopify", "domain": "shopify.com", "sector": "Yazılım",
              "desc": "KOBİ'ler için e-ticaret altyapısı sağlayan bulut tabanlı ticaret platformu."},
    "UBER":  {"name": "Uber", "domain": "uber.com", "sector": "Teknoloji",
              "desc": "Yolculuk paylaşımı ve yemek teslimatında küresel pazar lideri platform."},
    "PLTR":  {"name": "Palantir", "domain": "palantir.com", "sector": "Yazılım",
              "desc": "Devlet ve kurumlar için büyük veri analitiği ve yapay zeka yazılım platformları."},
    "SOFI":  {"name": "SoFi", "domain": "sofi.com", "sector": "Fintek",
              "desc": "Kredi, yatırım ve bankacılığı tek uygulamada birleştiren dijital finans platformu."},
    "COIN":  {"name": "Coinbase", "domain": "coinbase.com", "sector": "Fintek",
              "desc": "ABD merkezli en büyük kripto para borsalarından biri; perakende ve kurumsal işlem."},
    "SNOW":  {"name": "Snowflake", "domain": "snowflake.com", "sector": "Yazılım",
              "desc": "Bulut tabanlı veri ambarı ve veri analitiği platformu; kullandıkça öde modeli."},
    "SPY":   {"name": "SPDR S&P 500 ETF", "domain": "ssga.com", "sector": "Endeks ETF",
              "desc": "S&P 500 endeksini takip eden en büyük ve en likit borsa yatırım fonu; ABD'nin en büyük 500 halka açık şirketini kapsar."},
    "QQQ":   {"name": "Invesco QQQ Trust", "domain": "invesco.com", "sector": "Endeks ETF",
              "desc": "Nasdaq-100 endeksini takip eden ETF; ağırlıklı olarak teknoloji ve büyüme şirketlerinden oluşur."},
    "DIA":   {"name": "SPDR Dow Jones Industrial Average ETF", "domain": "ssga.com", "sector": "Endeks ETF",
              "desc": "Dow Jones Endüstri Ortalaması'nı takip eden ETF; 30 büyük ve köklü ABD şirketini fiyat ağırlıklı izler."},
    "IWM":   {"name": "iShares Russell 2000 ETF", "domain": "ishares.com", "sector": "Endeks ETF",
              "desc": "Russell 2000 endeksini takip eden ETF; ABD'li küçük ölçekli (small-cap) şirketleri kapsar."},
}

# Swing tarayıcının ek evreni (ad, sektör)
SCAN_EXTRA = {
    "MU": ("Micron Technology", "Yarı İletken"), "CRWD": ("CrowdStrike", "Yazılım"),
    "LITE": ("Lumentum", "Teknoloji"), "RKLB": ("Rocket Lab", "Havacılık"),
    "MRVL": ("Marvell Technology", "Yarı İletken"), "ORCL": ("Oracle", "Yazılım"),
    "QCOM": ("Qualcomm", "Yarı İletken"), "TSM": ("Taiwan Semiconductor", "Yarı İletken"),
    "ARM": ("Arm Holdings", "Yarı İletken"), "PANW": ("Palo Alto Networks", "Yazılım"),
    "NET": ("Cloudflare", "Yazılım"), "JPM": ("JPMorgan Chase", "Finans"),
    "V": ("Visa", "Finans"), "GS": ("Goldman Sachs", "Finans"), "LLY": ("Eli Lilly", "Sağlık"),
    "UNH": ("UnitedHealth", "Sağlık"), "XOM": ("Exxon Mobil", "Enerji"),
    "CAT": ("Caterpillar", "Sanayi"), "GE": ("GE Aerospace", "Sanayi"), "BA": ("Boeing", "Sanayi"),
    "WMT": ("Walmart", "Perakende"), "HD": ("Home Depot", "Perakende"), "NKE": ("Nike", "Tüketici"),
    "DIS": ("Disney", "İletişim"), "ABNB": ("Airbnb", "Tüketici"),
}
SCAN_UNIVERSE = [t for t, c in COMPANIES.items() if c["sector"] != "Endeks ETF"] + list(SCAN_EXTRA)

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO"]

# Sektör ETF'leri ve en büyük bileşenleri (ticker, kısa ad, yaklaşık ağırlık %)
SECTORS = [
    ("Teknoloji", "XLK", [("NVDA", "NVIDIA", 15.0), ("AAPL", "Apple", 13.0), ("MSFT", "Microsoft", 12.0),
        ("AVGO", "Broadcom", 5.5), ("ORCL", "Oracle", 3.4), ("PLTR", "Palantir", 3.1), ("AMD", "AMD", 2.8),
        ("CSCO", "Cisco", 2.6), ("IBM", "IBM", 2.3), ("CRM", "Salesforce", 2.2), ("MU", "Micron", 2.1),
        ("INTU", "Intuit", 1.9), ("NOW", "ServiceNow", 1.8), ("QCOM", "Qualcomm", 1.6),
        ("AMAT", "Applied Materials", 1.5), ("TXN", "Texas Instruments", 1.5), ("ADBE", "Adobe", 1.4),
        ("LRCX", "Lam Research", 1.3), ("ANET", "Arista Networks", 1.2), ("KLAC", "KLA", 1.1)]),
    ("Yarı İletken", "SMH", [("NVDA", "NVIDIA", 20.0), ("TSM", "TSMC", 11.0), ("AVGO", "Broadcom", 8.0),
        ("AMD", "AMD", 5.0), ("ASML", "ASML", 4.5), ("MU", "Micron", 4.5), ("QCOM", "Qualcomm", 4.0),
        ("AMAT", "Applied Materials", 4.0), ("LRCX", "Lam Research", 4.0), ("KLAC", "KLA", 4.0),
        ("TXN", "Texas Instruments", 3.8), ("INTC", "Intel", 3.5), ("ADI", "Analog Devices", 3.3),
        ("MRVL", "Marvell", 2.6), ("ARM", "Arm Holdings", 2.4), ("SNPS", "Synopsys", 2.2), ("CDNS", "Cadence", 2.2)]),
    ("Finans", "XLF", [("BRK-B", "Berkshire Hathaway", 12.0), ("JPM", "JPMorgan Chase", 10.5), ("V", "Visa", 7.8),
        ("MA", "Mastercard", 6.3), ("BAC", "Bank of America", 4.5), ("WFC", "Wells Fargo", 3.6),
        ("GS", "Goldman Sachs", 3.1), ("MS", "Morgan Stanley", 2.6), ("AXP", "American Express", 2.5),
        ("SPGI", "S&P Global", 2.3), ("C", "Citigroup", 2.2), ("SCHW", "Charles Schwab", 2.0),
        ("BLK", "BlackRock", 2.0), ("PGR", "Progressive", 1.9), ("CB", "Chubb", 1.6)]),
    ("Enerji", "XLE", [("XOM", "Exxon Mobil", 23.0), ("CVX", "Chevron", 17.0), ("COP", "ConocoPhillips", 7.0),
        ("EOG", "EOG Resources", 4.5), ("WMB", "Williams", 4.5), ("SLB", "Schlumberger", 4.0),
        ("PSX", "Phillips 66", 3.8), ("KMI", "Kinder Morgan", 3.7), ("MPC", "Marathon Petroleum", 3.6),
        ("OKE", "ONEOK", 3.2), ("VLO", "Valero", 3.1), ("OXY", "Occidental", 2.6)]),
    ("Sağlık", "XLV", [("LLY", "Eli Lilly", 13.0), ("JNJ", "Johnson & Johnson", 8.5), ("ABBV", "AbbVie", 7.0),
        ("UNH", "UnitedHealth", 6.0), ("MRK", "Merck", 4.5), ("TMO", "Thermo Fisher", 4.0), ("ABT", "Abbott", 4.0),
        ("ISRG", "Intuitive Surgical", 3.8), ("AMGN", "Amgen", 3.3), ("BSX", "Boston Scientific", 3.0),
        ("DHR", "Danaher", 2.7), ("PFE", "Pfizer", 2.6), ("GILD", "Gilead", 2.5), ("SYK", "Stryker", 2.4)]),
    ("Sanayi", "XLI", [("GE", "GE Aerospace", 6.5), ("CAT", "Caterpillar", 5.5), ("RTX", "RTX", 4.8),
        ("UBER", "Uber", 4.0), ("HON", "Honeywell", 3.2), ("BA", "Boeing", 3.1), ("UNP", "Union Pacific", 3.0),
        ("ETN", "Eaton", 3.0), ("DE", "Deere", 2.8), ("LMT", "Lockheed Martin", 2.3), ("ADP", "ADP", 2.3),
        ("GD", "General Dynamics", 1.9), ("WM", "Waste Management", 1.8), ("PH", "Parker-Hannifin", 1.8)]),
    ("Tüketici (İsteğe Bağlı)", "XLY", [("AMZN", "Amazon", 22.0), ("TSLA", "Tesla", 16.0), ("HD", "Home Depot", 6.5),
        ("MCD", "McDonald's", 4.2), ("BKNG", "Booking", 4.0), ("TJX", "TJX", 3.4), ("LOW", "Lowe's", 3.0),
        ("SBUX", "Starbucks", 2.2), ("NKE", "Nike", 2.0), ("ORLY", "O'Reilly", 2.0), ("CMG", "Chipotle", 1.6),
        ("ABNB", "Airbnb", 1.5), ("GM", "General Motors", 1.4), ("MAR", "Marriott", 1.4)]),
    ("Tüketici (Temel)", "XLP", [("WMT", "Walmart", 11.0), ("COST", "Costco", 10.0), ("PG", "Procter & Gamble", 8.5),
        ("KO", "Coca-Cola", 6.5), ("PM", "Philip Morris", 6.0), ("PEP", "PepsiCo", 4.5), ("MDLZ", "Mondelez", 3.5),
        ("MO", "Altria", 3.4), ("CL", "Colgate-Palmolive", 3.0), ("KMB", "Kimberly-Clark", 2.0),
        ("TGT", "Target", 2.0), ("KR", "Kroger", 2.0), ("KDP", "Keurig Dr Pepper", 1.8)]),
    ("Hizmet", "XLU", [("NEE", "NextEra Energy", 11.0), ("SO", "Southern", 7.5), ("DUK", "Duke Energy", 7.0),
        ("CEG", "Constellation", 6.5), ("VST", "Vistra", 5.0), ("AEP", "AEP", 4.6), ("SRE", "Sempra", 4.0),
        ("D", "Dominion", 3.8), ("EXC", "Exelon", 3.5), ("XEL", "Xcel Energy", 3.3), ("PCG", "PG&E", 3.0),
        ("PEG", "PSEG", 3.0)]),
    ("Hammadde", "XLB", [("LIN", "Linde", 17.0), ("SHW", "Sherwin-Williams", 7.0), ("ECL", "Ecolab", 6.0),
        ("APD", "Air Products", 5.5), ("NEM", "Newmont", 5.5), ("FCX", "Freeport-McMoRan", 5.0),
        ("CTVA", "Corteva", 4.5), ("MLM", "Martin Marietta", 3.5), ("VMC", "Vulcan Materials", 3.5),
        ("NUE", "Nucor", 3.3), ("DD", "DuPont", 3.0), ("PPG", "PPG", 2.8)]),
    ("İletişim", "XLC", [("META", "Meta Platforms", 20.0), ("GOOGL", "Alphabet A", 11.0), ("GOOG", "Alphabet C", 9.0),
        ("NFLX", "Netflix", 7.0), ("TMUS", "T-Mobile", 4.5), ("DIS", "Disney", 4.5), ("T", "AT&T", 4.4),
        ("VZ", "Verizon", 4.3), ("CMCSA", "Comcast", 4.0), ("EA", "Electronic Arts", 3.0),
        ("TTWO", "Take-Two", 2.8), ("CHTR", "Charter", 2.5)]),
    ("Gayrimenkul", "XLRE", [("PLD", "Prologis", 9.0), ("AMT", "American Tower", 8.0), ("WELL", "Welltower", 8.0),
        ("EQIX", "Equinix", 7.0), ("SPG", "Simon Property", 5.0), ("O", "Realty Income", 4.8),
        ("PSA", "Public Storage", 4.3), ("DLR", "Digital Realty", 4.3), ("CCI", "Crown Castle", 4.0),
        ("CBRE", "CBRE", 3.8), ("VICI", "VICI Properties", 3.0), ("EXR", "Extra Space", 2.8)]),
]

_FX_LIST = [
    ("EUR/USD", "EURUSD=X", "Euro / ABD Doları", "Majör", 1.16380, 5),
    ("GBP/USD", "GBPUSD=X", "Sterlin / ABD Doları", "Majör", 1.33520, 5),
    ("USD/JPY", "USDJPY=X", "ABD Doları / Japon Yeni", "Majör", 151.284, 3),
    ("USD/CHF", "USDCHF=X", "ABD Doları / İsviçre Frangı", "Majör", 0.79412, 5),
    ("AUD/USD", "AUDUSD=X", "Avustralya Doları / ABD Doları", "Majör", 0.65518, 5),
    ("USD/CAD", "USDCAD=X", "ABD Doları / Kanada Doları", "Majör", 1.37905, 5),
    ("NZD/USD", "NZDUSD=X", "Yeni Zelanda Doları / ABD Doları", "Majör", 0.59840, 5),
    ("EUR/GBP", "EURGBP=X", "Euro / Sterlin", "Çapraz", 0.87160, 5),
    ("EUR/JPY", "EURJPY=X", "Euro / Japon Yeni", "Çapraz", 176.050, 3),
    ("GBP/JPY", "GBPJPY=X", "Sterlin / Japon Yeni", "Çapraz", 201.980, 3),
    ("AUD/JPY", "AUDJPY=X", "Avustralya Doları / Japon Yeni", "Çapraz", 99.120, 3),
    ("USD/TRY", "USDTRY=X", "ABD Doları / Türk Lirası", "Egzotik", 43.1250, 4),
    ("USD/ZAR", "USDZAR=X", "ABD Doları / G. Afrika Randı", "Egzotik", 17.2400, 4),
    ("USD/MXN", "USDMXN=X", "ABD Doları / Meksika Pesosu", "Egzotik", 18.3900, 4),
    ("XAU/USD", "GC=F", "Altın / ABD Doları", "Metal", 4128.40, 2),
    ("XAG/USD", "SI=F", "Gümüş / ABD Doları", "Metal", 49.880, 3),
]
FX_CATEGORIES = ["Tümü", "Majör", "Çapraz", "Egzotik", "Metal"]

_MACRO = [
    ("Dolar Endeksi", "DXY", "DX-Y.NYB", 98.42, 2),
    ("ABD 10Y Tahvil", "US10Y", "^TNX", 4.38, 2),
    ("Altın", "XAUUSD", "GC=F", 4128.40, 2),
    ("Brent Petrol", "UKOIL", "BZ=F", 64.85, 2),
    ("Dolar / TL", "USDTRY", "USDTRY=X", 43.1250, 4),
    ("Bitcoin", "BTCUSD", "BTC-USD", 108420.0, 0),
]

# Backtest hızlı seçim: (görünen kod, yfinance sembolü, ad)
BT_QUICK = [
    ("AAPL", "AAPL", "Apple Inc."), ("NVDA", "NVDA", "NVIDIA Corp."),
    ("SPX", "^GSPC", "S&P 500"), ("XU100", "XU100.IS", "BIST 100"),
    ("THYAO", "THYAO.IS", "Türk Hava Yolları"), ("MU", "MU", "Micron Technology"),
    ("EURUSD", "EURUSD=X", "Euro / ABD Doları"), ("BTCUSD", "BTC-USD", "Bitcoin"),
]


def _build_names():
    names = {}
    for t, c in COMPANIES.items():
        names[t] = (c["name"], c["sector"])
    for t, (n, s) in SCAN_EXTRA.items():
        names.setdefault(t, (n, s))
    for sname, etf, cons in SECTORS:
        names.setdefault(etf, (f"{sname} sektör ETF'i", "Sektör ETF"))
        for t, n, _w in cons:
            names.setdefault(t, (n, sname))
    for p, sym, n, cat, _b, _d in _FX_LIST:
        names.setdefault(sym, (f"{p} · {n}", "Emtia" if cat == "Metal" else "Döviz"))
    for n, _code, sym, _b, _d in _MACRO:
        names.setdefault(sym, (n, "Makro"))
    for _code, sym, n in BT_QUICK:
        names.setdefault(sym, (n, ""))
    names.setdefault("^VIX", ("CBOE Volatilite Endeksi (VIX)", "Endeks"))
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
_PERIOD_DAYS = {"1d": 1, "2d": 2, "5d": 5, "1mo": 22}


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
        elif t in KNOWN:
            s = _synth(t)
            last, prev, src = float(s["Close"].iloc[-1]), float(s["Close"].iloc[-2]), "mock"
        else:
            continue
        name, sector = NAMES.get(t, (t, ""))
        out[t] = {"ticker": t, "name": name, "sector": sector, "last": last, "prev": prev,
                  "change_pct": (last / prev - 1) * 100 if prev else 0.0, "src": src}
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
    return {"CURRENCY": f"{name} döviz kuru.", "CRYPTOCURRENCY": f"{name} — kripto para.",
            "INDEX": f"{name} endeksi.", "FUTURE": f"{name} — vadeli kontrat (emtia/finansal).",
            "ETF": f"{name} — borsa yatırım fonu (ETF).", "MUTUALFUND": f"{name} — yatırım fonu."}.get(qt, "")


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
    return "Yükseliş" if p > n else "Düşüş" if n > p else "Nötr"


def _age(ts):
    if not ts:
        return 60, "1 sa önce", "1 sa"
    mins = max(1, int((time.time() - float(ts)) / 60))
    if mins < 60:
        return mins, f"{mins} dk önce", f"{mins} dk"
    if mins < 1440:
        return mins, f"{mins // 60} sa önce", f"{mins // 60} sa"
    return mins, f"{mins // 1440} gün önce", f"{mins // 1440} g"


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


_NEWS_TEMPLATES = [
    ("{name} için analistler fiyat hedefini yükseltti", "Reuters", "Yükseliş"),
    ("{name} çeyreklik kazançları piyasa beklentilerini aştı", "Bloomberg", "Yükseliş"),
    ("{name} hissesinde kâr realizasyonu satışı görüldü", "MarketWatch", "Düşüş"),
    ("{name}, tedarik zinciri maliyetleri konusunda uyardı", "CNBC", "Düşüş"),
    ("{name} CEO'su büyüme stratejisini yatırımcılara anlattı", "Yahoo Finance", "Nötr"),
    ("{name} hisse geri alım programını genişletti", "Reuters", "Yükseliş"),
]


def _mock_company_news(t, n=6):
    rng = np.random.default_rng(_seed(t) + 555)
    name = company_name(t)
    idxs = rng.choice(len(_NEWS_TEMPLATES), size=min(n, len(_NEWS_TEMPLATES)), replace=False)
    hrs = sorted(int(h) for h in rng.integers(1, 96, size=len(idxs)))
    out = []
    for i, h in zip(idxs, hrs):
        tt, src, sent = _NEWS_TEMPLATES[i]
        out.append({"ticker": t, "title": tt.format(name=name) + " (örnek)", "source": src,
                    "when": f"{h} sa önce" if h < 24 else f"{h // 24} gün önce",
                    "when_short": f"{h} sa" if h < 24 else f"{h // 24} g", "age_min": h * 60,
                    "hours_ago": h, "sentiment": sent, "link": None, "thumb": None, "summary": "",
                    "related": [t], "src": "mock"})
    return out


@_ttl_cache(900, fail_ttl=120)
def get_company_news(t, n=6):
    if _HAS_YF:
        try:
            raw = yf.Ticker(t).news or []
            parsed = [p for p in (_parse_news_item(x, t) for x in raw) if p]
            if parsed:
                parsed.sort(key=lambda x: x["age_min"])
                return parsed[:n]
        except Exception:
            pass
    return _mock_company_news(t, n) if t in KNOWN else []


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


@_ttl_cache(900, fail_ttl=120)
def _search_news(query, n=10):
    if not _HAS_YF:
        return []
    try:
        raw = yf.Search(query, max_results=1, news_count=n).news or []
    except Exception:
        return []
    return [p for p in (_parse_news_item(x) for x in raw) if p]


NEWS_CATEGORIES = ["Tümü", "Forex", "Merkez Bankaları", "Emtia", "Türkiye"]
_NEWS_Q = {"Forex": ["forex dollar euro currency"], "Merkez Bankaları": ["Federal Reserve ECB central bank rates"],
           "Emtia": ["gold oil prices commodities"], "Türkiye": ["Turkey lira Turkish central bank"]}
_YF2PAIR = {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "JPY=X": "USD/JPY",
            "USDCHF=X": "USD/CHF", "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD", "CAD=X": "USD/CAD",
            "USDTRY=X": "USD/TRY", "TRY=X": "USD/TRY", "GC=F": "XAU/USD", "SI=F": "XAG/USD",
            "CL=F": "WTI", "BZ=F": "UKOIL", "DX-Y.NYB": "DXY", "BTC-USD": "BTC/USD"}
_CAT_SYM = {"Forex": "EURUSD=X", "Merkez Bankaları": "DX-Y.NYB", "Emtia": "GC=F", "Türkiye": "USDTRY=X"}

_FX_NEWS_MOCK = [
    ("Dolar endeksi istihdam verisi öncesi geriliyor", "DXY", "Düşüş", "Forex", 32),
    ("BoJ yetkilileri yendeki hızlı hareketlere karşı uyardı", "USD/JPY", "Düşüş", "Merkez Bankaları", 47),
    ("Altın güvenli liman talebiyle zirveyi yeniden test ediyor", "XAU/USD", "Yükseliş", "Emtia", 60),
    ("TCMB kararı öncesi TL'de oynaklık beklentisi arttı", "USD/TRY", "Nötr", "Türkiye", 120),
    ("Sterlin zayıf hizmet PMI verisi sonrası baskı altında", "GBP/USD", "Düşüş", "Forex", 240),
    ("Euro Bölgesi PMI beklentiyi aştı, euro toparlandı", "EUR/USD", "Yükseliş", "Forex", 360),
]


def _mock_forex_news(category):
    items = []
    for title, pair, sent, cat, mins in _FX_NEWS_MOCK:
        if category != "Tümü" and cat != category:
            continue
        rng = np.random.default_rng(_seed(title))
        items.append({"title": title + " (örnek)", "pair": pair, "sentiment": sent, "category": cat,
                      "when": f"{mins} dk" if mins < 60 else f"{mins // 60} sa", "source": "örnek",
                      "spark": (100 * np.cumprod(1 + rng.normal(0, 0.012, 24))).tolist(), "link": None})
    feat = {"title": "ECB toplantısı öncesi euro dar bantta (örnek)",
            "summary": "Gerçek haber kaynağına ulaşılamadığı için örnek içerik gösteriliyor.",
            "category": "Merkez Bankaları", "sentiment": "Nötr", "source": "örnek", "when": "—",
            "tags": ["EUR/USD", "DXY"], "link": None, "thumb": None}
    return {"featured": feat, "items": items, "src": "mock"}


@_ttl_cache(900, fail_ttl=120)
def get_forex_news(category="Tümü"):
    cats = [c for c in NEWS_CATEGORIES if c != "Tümü"] if category == "Tümü" else [category]
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
        return _mock_forex_news(category)
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
CAL_DAYS = ["Dün", "Bugün", "Yarın", "Bu Hafta"]
CAL_IMPACTS = ["Tümü", "Yüksek", "Orta +"]
_TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
_TR_MON = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
           "Ekim", "Kasım", "Aralık"]
_IMPACT_N = {"high": 3, "medium": 2, "low": 1}
_COUNTRY_CUR = {"united states": "USD", "euro area": "EUR", "germany": "EUR", "france": "EUR",
                "italy": "EUR", "united kingdom": "GBP", "japan": "JPY", "canada": "CAD",
                "australia": "AUD", "switzerland": "CHF", "china": "CNY", "new zealand": "NZD",
                "turkey": "TRY"}
_CAL_MOCK = [
    ("08:00", "EUR", 2, "Almanya GfK Tüketici Güveni", "-22,4", "-21,8", "-22,3"),
    ("10:00", "EUR", 3, "Euro Bölgesi İmalat PMI", "49,9", "49,6", "49,8"),
    ("10:30", "GBP", 3, "BK Hizmet PMI", "50,4", "51,0", "50,8"),
    ("14:00", "TRY", 3, "TCMB Faiz Kararı", "—", "%38,50", "%40,50"),
    ("14:30", "USD", 3, "İşsizlik Maaşı Başvuruları", "—", "232K", "228K"),
    ("16:00", "USD", 1, "İkinci El Konut Satışları", "—", "4,06M", "4,00M"),
]


def tr_date_label(ts):
    return f"{_TR_DAYS[ts.weekday()]} · {ts.day} {_TR_MON[ts.month - 1]}"


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
                         "impact": imp, "event": ev + " (örnek)", "actual": a, "forecast": f,
                         "previous": p, "src": "mock"})
    rows.sort(key=lambda x: x["dt"])
    return rows


def get_calendar_rows(day="Bugün", impact="Tümü"):
    rows = _calendar_all()
    now = pd.Timestamp.now(tz=TZ)
    today = now.normalize()
    target = {"Dün": today - pd.Timedelta(days=1), "Bugün": today, "Yarın": today + pd.Timedelta(days=1)}.get(day)
    if target is not None:
        rows = [r for r in rows if r["dt"].normalize() == target]
    if impact == "Yüksek":
        rows = [r for r in rows if r["impact"] >= 3]
    elif impact == "Orta +":
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
                    "src": qq["src"]})
    return out


def fx_symbol(pair):
    return next((sym for p, sym, *_ in _FX_LIST if p == pair), "EURUSD=X")


def fx_meta(pair):
    for p, sym, n, c, b, d in _FX_LIST:
        if p == pair:
            return {"pair": p, "symbol": sym, "name": n, "category": c, "base": b, "dec": d}
    return {"pair": pair, "symbol": "EURUSD=X", "name": "", "category": "Majör", "base": 1.0, "dec": 5}


def get_fx_list(category="Tümü"):
    q = get_quotes(tuple(sorted(sym for _, sym, *_ in _FX_LIST)))
    out = []
    for p, sym, name, cat, base, dec in _FX_LIST:
        if category != "Tümü" and cat != category:
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
    df = pd.DataFrame([{"Company": f"{n} (örnek)", "Symbol": s, "Exchange": e,
                        "Expected Date": (today + pd.Timedelta(days=d)).strftime("%d.%m.%Y"),
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
                     "Expected Date": pd.Timestamp(x["date"]).strftime("%d.%m.%Y") if x.get("date") else "",
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
                rows.append({"Ticker": sym, "Şirket": q.get("shortName") or sym,
                             "PEG": round(peg, 2) if peg else np.nan, "Forward PE": round(fpe, 1),
                             "Profit Margin %": round(margin * 100, 1) if margin is not None else np.nan,
                             "EPS Büyüme %": round(growth * 100, 1) if growth is not None else np.nan})
            if len(rows) >= 4:
                df = pd.DataFrame(rows).sort_values("Forward PE").head(10).reset_index(drop=True)
                df.attrs["src"] = "real"
                return df
        except Exception:
            pass
    rows = [("GOOGL", "Alphabet", 1.1, 18.4, 27.0, 14.5), ("META", "Meta Platforms", 0.9, 20.1, 33.2, 16.0),
            ("PEP", "PepsiCo", 1.4, 16.8, 10.1, 7.2), ("CRM", "Salesforce", 1.0, 22.0, 15.6, 18.9),
            ("UBER", "Uber", 0.8, 21.5, 6.2, 30.1), ("ADBE", "Adobe", 1.1, 19.9, 28.5, 13.8)]
    df = pd.DataFrame(rows, columns=["Ticker", "Şirket", "PEG", "Forward PE", "Profit Margin %", "EPS Büyüme %"])
    df = df.sort_values("Forward PE").reset_index(drop=True)
    df.attrs["src"] = "mock"
    return df


# ======================================================================
# Sembol arama (yerel + Yahoo Search)
# ======================================================================
_TYPE_TR = {"EQUITY": "Hisse", "ETF": "ETF", "INDEX": "Endeks", "CURRENCY": "Döviz",
            "CRYPTOCURRENCY": "Kripto", "FUTURE": "Vadeli", "MUTUALFUND": "Fon"}


def _local_type(t):
    if t.endswith("=X"):
        return "Döviz"
    if t.endswith("=F"):
        return "Vadeli"
    if t.endswith("-USD"):
        return "Kripto"
    if t.startswith("^"):
        return "Endeks"
    if company_sector(t) in ("Endeks ETF", "Sektör ETF"):
        return "ETF"
    return "Hisse"


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
            h["yf_msg"] = f"yfinance {ver} · AAPL son fiyat {a['last']:.2f}"
        else:
            h["yf_msg"] = f"yfinance {ver} kurulu ama Yahoo veri vermedi (geçici rate-limit olabilir)"
    else:
        h["yf_msg"] = "yfinance import edilemedi — requirements.txt'te 'yfinance' satırı yok"
    h["cnn_ok"] = get_fear_greed().get("src") == "real"
    cal = _calendar_all()
    h["cal_ok"] = bool(cal) and cal[0].get("src") == "real"
    return h
