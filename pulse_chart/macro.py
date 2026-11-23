# -*- coding: utf-8 -*-
"""Pulse v5.9 — Global Macro (Markets sekmesi, Upcoming IPOs'un altı): 6 makro gösterge için ülke verisi.

Kaynaklar (hepsi ücretsiz, anahtarsız, resmi):
  • OECD (Key Short-Term Economic Indicators): EN SON açıklanan aylık / çeyreklik değerler — GSYH YoY, TÜFE YoY,
    işsizlik oranı, sanayi üretimi YoY (OECD üyeleri + seçili G20 ülkeleri). Varsa diğer kaynakların önüne geçer.
  • IMF DataMapper (World Economic Outlook): GSYH büyümesi, enflasyon, işsizlik, kamu borcu / GSYH — ~190 ülke,
    yıllık (cari yıl = IMF tahmini, borçta son tamamlanan yıl).
  • BIS (WS_CBPOL): merkez bankası politika faizleri — ~40 merkez bankası + euro bölgesi (ECB → euro üyeleri).
  • Dünya Bankası: hâlâ eksik kalan ülkeler için yedek (yıllık; üretimde 'sanayi katma değeri' vekil gösterge).
Değer UYDURULMAZ: veri yoksa ülke gri ('No data') kalır. Her değer (değer, dönem, kaynak kodu) olarak taşınır.
Son başarılı veri diske yazılır (.pulse_data/macro_snapshot.json) → bir kaynak geçici olarak çökse de harita boş
kalmaz; 6 saatten eski veri arka planda yenilenir (sayfa beklemez). Streamlit içe aktarılmaz.
"""
import csv
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

MACRO_VERSION = "5.11"
DATA_DIR = os.environ.get("PULSE_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                           ".pulse_data")
SNAP_NAME = "macro_snapshot.json"
TTL = 6 * 3600              # bu süreden eski veri arka planda yenilenir
RETRY_FAIL = 20 * 60        # tüm kaynaklar çöktüyse en erken bu kadar sonra yeniden dene
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ----------------------------------------------------------------------
# Göstergeler — renk skalası: v < s0 → c0, s0 ≤ v < s1 → c1 … v ≥ s4 → c5 (koyu tonlar koyu zeminde okunur)
# ----------------------------------------------------------------------
INDICATORS = [
    {"k": "gdp", "name": "GDP Growth YoY", "short": "GDP growth", "steps": [0, 3, 6, 8, 10],
     "colors": ["#D5F5F6", "#9EE6EA", "#5CCFD6", "#22B3BE", "#0E8C99", "#0A6670"],
     "desc": "Real GDP, % change on the same period a year earlier"},
    {"k": "infl", "name": "Inflation YoY", "short": "Inflation", "steps": [0, 2, 4, 6, 10],
     "colors": ["#FFF4C2", "#FFE08A", "#FDBA4D", "#F98C2E", "#E5531C", "#B91C1C"],
     "desc": "Consumer prices, % change on a year earlier"},
    {"k": "rate", "name": "Interest Rates", "short": "Policy rate", "steps": [3, 5, 7, 12, 25],
     "colors": ["#D9F2E3", "#A8E0BF", "#63C493", "#2EA36A", "#168553", "#0F6B40"],
     "desc": "Central bank policy rate, % per year"},
    {"k": "unemp", "name": "Unemployment", "short": "Unemployment", "steps": [3, 5, 7, 10, 15],
     "colors": ["#EFE6FC", "#D6C2F7", "#BB9CF0", "#A077E6", "#8656D8", "#6B38C4"],
     "desc": "Unemployment rate, % of the labour force"},
    {"k": "debt", "name": "Debt to GDP", "short": "Gov. debt / GDP", "steps": [30, 50, 70, 90, 110],
     "colors": ["#FBE1EC", "#F5B5CF", "#EC86B0", "#DE5590", "#C42F74", "#A3185B"],
     "desc": "General government gross debt, % of GDP"},
    {"k": "prod", "name": "Production YoY", "short": "Production", "steps": [0, 3, 6, 10, 15],
     "colors": ["#DCEBFF", "#B0D0FF", "#7DB0FF", "#4A8DF7", "#2C6BE0", "#1E4FC0"],
     "desc": "Industrial production, % change on a year earlier"},
]
IND_KEYS = [i["k"] for i in INDICATORS]
MISSING = {"dark": "#2A2E36", "light": "#E3E6EB"}

# Kaynak kodları → kısa ad (ipucunda / detayda gösterilir)
SOURCES = {"O": "OECD", "Oc": "OECD (YoY from index)", "I": "IMF WEO", "B": "BIS", "E": "ECB rate via BIS",
           "W": "World Bank", "Wc": "World Bank · central gov. debt",
           "Wp": "World Bank · industry value added (annual proxy)"}

# ----------------------------------------------------------------------
# Ülkeler: ISO3 | ISO2 | ISO sayısal (world-atlas kimliği) | ad | G = G20 üyesi
# ----------------------------------------------------------------------
_C = """
AFG|AF|4|Afghanistan|
ALB|AL|8|Albania|
DZA|DZ|12|Algeria|
AND|AD|20|Andorra|
AGO|AO|24|Angola|
ATG|AG|28|Antigua & Barbuda|
ARG|AR|32|Argentina|G
ARM|AM|51|Armenia|
ABW|AW|533|Aruba|
AUS|AU|36|Australia|G
AUT|AT|40|Austria|
AZE|AZ|31|Azerbaijan|
BHS|BS|44|Bahamas|
BHR|BH|48|Bahrain|
BGD|BD|50|Bangladesh|
BRB|BB|52|Barbados|
BLR|BY|112|Belarus|
BEL|BE|56|Belgium|
BLZ|BZ|84|Belize|
BEN|BJ|204|Benin|
BTN|BT|64|Bhutan|
BOL|BO|68|Bolivia|
BIH|BA|70|Bosnia & Herzegovina|
BWA|BW|72|Botswana|
BRA|BR|76|Brazil|G
BRN|BN|96|Brunei|
BGR|BG|100|Bulgaria|
BFA|BF|854|Burkina Faso|
BDI|BI|108|Burundi|
CPV|CV|132|Cabo Verde|
KHM|KH|116|Cambodia|
CMR|CM|120|Cameroon|
CAN|CA|124|Canada|G
CAF|CF|140|Central African Rep.|
TCD|TD|148|Chad|
CHL|CL|152|Chile|
CHN|CN|156|China|G
COL|CO|170|Colombia|
COM|KM|174|Comoros|
COD|CD|180|DR Congo|
COG|CG|178|Congo|
CRI|CR|188|Costa Rica|
CIV|CI|384|Côte d'Ivoire|
HRV|HR|191|Croatia|
CUB|CU|192|Cuba|
CYP|CY|196|Cyprus|
CZE|CZ|203|Czechia|
DNK|DK|208|Denmark|
DJI|DJ|262|Djibouti|
DMA|DM|212|Dominica|
DOM|DO|214|Dominican Republic|
ECU|EC|218|Ecuador|
EGY|EG|818|Egypt|
SLV|SV|222|El Salvador|
GNQ|GQ|226|Equatorial Guinea|
ERI|ER|232|Eritrea|
EST|EE|233|Estonia|
SWZ|SZ|748|Eswatini|
ETH|ET|231|Ethiopia|
FJI|FJ|242|Fiji|
FIN|FI|246|Finland|
FRA|FR|250|France|G
GAB|GA|266|Gabon|
GMB|GM|270|Gambia|
GEO|GE|268|Georgia|
DEU|DE|276|Germany|G
GHA|GH|288|Ghana|
GRC|GR|300|Greece|
GRD|GD|308|Grenada|
GTM|GT|320|Guatemala|
GIN|GN|324|Guinea|
GNB|GW|624|Guinea-Bissau|
GUY|GY|328|Guyana|
HTI|HT|332|Haiti|
HND|HN|340|Honduras|
HKG|HK|344|Hong Kong|
HUN|HU|348|Hungary|
ISL|IS|352|Iceland|
IND|IN|356|India|G
IDN|ID|360|Indonesia|G
IRN|IR|364|Iran|
IRQ|IQ|368|Iraq|
IRL|IE|372|Ireland|
ISR|IL|376|Israel|
ITA|IT|380|Italy|G
JAM|JM|388|Jamaica|
JPN|JP|392|Japan|G
JOR|JO|400|Jordan|
KAZ|KZ|398|Kazakhstan|
KEN|KE|404|Kenya|
KIR|KI|296|Kiribati|
PRK|KP|408|North Korea|
KOR|KR|410|South Korea|G
XKX|XK|0|Kosovo|
KWT|KW|414|Kuwait|
KGZ|KG|417|Kyrgyzstan|
LAO|LA|418|Laos|
LVA|LV|428|Latvia|
LBN|LB|422|Lebanon|
LSO|LS|426|Lesotho|
LBR|LR|430|Liberia|
LBY|LY|434|Libya|
LIE|LI|438|Liechtenstein|
LTU|LT|440|Lithuania|
LUX|LU|442|Luxembourg|
MAC|MO|446|Macao|
MDG|MG|450|Madagascar|
MWI|MW|454|Malawi|
MYS|MY|458|Malaysia|
MDV|MV|462|Maldives|
MLI|ML|466|Mali|
MLT|MT|470|Malta|
MHL|MH|584|Marshall Islands|
MRT|MR|478|Mauritania|
MUS|MU|480|Mauritius|
MEX|MX|484|Mexico|G
FSM|FM|583|Micronesia|
MDA|MD|498|Moldova|
MCO|MC|492|Monaco|
MNG|MN|496|Mongolia|
MNE|ME|499|Montenegro|
MAR|MA|504|Morocco|
MOZ|MZ|508|Mozambique|
MMR|MM|104|Myanmar|
NAM|NA|516|Namibia|
NRU|NR|520|Nauru|
NPL|NP|524|Nepal|
NLD|NL|528|Netherlands|
NZL|NZ|554|New Zealand|
NIC|NI|558|Nicaragua|
NER|NE|562|Niger|
NGA|NG|566|Nigeria|
MKD|MK|807|North Macedonia|
NOR|NO|578|Norway|
OMN|OM|512|Oman|
PAK|PK|586|Pakistan|
PLW|PW|585|Palau|
PSE|PS|275|Palestine|
PAN|PA|591|Panama|
PNG|PG|598|Papua New Guinea|
PRY|PY|600|Paraguay|
PER|PE|604|Peru|
PHL|PH|608|Philippines|
POL|PL|616|Poland|
PRT|PT|620|Portugal|
PRI|PR|630|Puerto Rico|
QAT|QA|634|Qatar|
ROU|RO|642|Romania|
RUS|RU|643|Russia|G
RWA|RW|646|Rwanda|
KNA|KN|659|St. Kitts & Nevis|
LCA|LC|662|St. Lucia|
VCT|VC|670|St. Vincent & Grenadines|
WSM|WS|882|Samoa|
SMR|SM|674|San Marino|
STP|ST|678|São Tomé & Príncipe|
SAU|SA|682|Saudi Arabia|G
SEN|SN|686|Senegal|
SRB|RS|688|Serbia|
SYC|SC|690|Seychelles|
SLE|SL|694|Sierra Leone|
SGP|SG|702|Singapore|
SVK|SK|703|Slovakia|
SVN|SI|705|Slovenia|
SLB|SB|90|Solomon Islands|
SOM|SO|706|Somalia|
ZAF|ZA|710|South Africa|G
SSD|SS|728|South Sudan|
ESP|ES|724|Spain|
LKA|LK|144|Sri Lanka|
SDN|SD|729|Sudan|
SUR|SR|740|Suriname|
SWE|SE|752|Sweden|
CHE|CH|756|Switzerland|
SYR|SY|760|Syria|
TWN|TW|158|Taiwan|
TJK|TJ|762|Tajikistan|
TZA|TZ|834|Tanzania|
THA|TH|764|Thailand|
TLS|TL|626|Timor-Leste|
TGO|TG|768|Togo|
TON|TO|776|Tonga|
TTO|TT|780|Trinidad & Tobago|
TUN|TN|788|Tunisia|
TUR|TR|792|Türkiye|G
TKM|TM|795|Turkmenistan|
TUV|TV|798|Tuvalu|
UGA|UG|800|Uganda|
UKR|UA|804|Ukraine|
ARE|AE|784|United Arab Emirates|
GBR|GB|826|United Kingdom|G
USA|US|840|United States|G
URY|UY|858|Uruguay|
UZB|UZ|860|Uzbekistan|
VUT|VU|548|Vanuatu|
VEN|VE|862|Venezuela|
VNM|VN|704|Vietnam|
YEM|YE|887|Yemen|
ZMB|ZM|894|Zambia|
ZWE|ZW|716|Zimbabwe|
"""


def _parse_countries(txt):
    out = {}
    for line in txt.strip().splitlines():
        p = line.split("|")
        if len(p) != 5:
            continue
        out[p[0]] = {"a2": p[1], "num": int(p[2]), "n": p[3], "g": p[4] == "G"}
    return out


COUNTRY = _parse_countries(_C)
A2_TO_A3 = {v["a2"]: k for k, v in COUNTRY.items()}
G20 = sorted(k for k, v in COUNTRY.items() if v["g"])
# Euro bölgesi (2026: Bulgaristan 1 Ocak 2026'dan beri üye) — BIS 'XM' serisi (ECB) bunlara uygulanır
EURO = ["AUT", "BEL", "BGR", "HRV", "CYP", "EST", "FIN", "FRA", "DEU", "GRC", "IRL", "ITA", "LVA", "LTU", "LUX",
        "MLT", "NLD", "PRT", "SVK", "SVN", "ESP"]
# Haritada kendi verisi olmayan bölgeler: Grönland → Danimarka (TradingView da böyle gösterir)
MAP_ALIAS = {"304": "DNK"}
# Kimliği olmayan (world-atlas'ta ISO kodu boş / -99) harita alanları → ad ile eşleşme
NAME_ALIAS = {"Kosovo": "XKX"}
IMF_ALIAS = {"UVK": "XKX", "WBG": "PSE"}
# Ülkeye özel kısa notlar (detayda gösterilir)
NOTES = {("rate", "USA"): "BIS uses the midpoint of the Fed's target range"}


def flag_emoji(a2):
    a2 = str(a2 or "").upper()
    if len(a2) != 2 or not a2.isalpha():
        return ""
    return chr(0x1F1E6 + ord(a2[0]) - 65) + chr(0x1F1E6 + ord(a2[1]) - 65)


# ----------------------------------------------------------------------
# Yardımcılar: sayı, dönem etiketi, yaş
# ----------------------------------------------------------------------
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _now():
    return datetime.now(timezone.utc)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def period_end(p):
    """'2026-09' / '2026-Q3' / '2026-11-18' / '2026' / '2026-S1' → dönemin son günü (date) ya da None."""
    p = str(p or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", p)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-?Q([1-4])$", p)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return date(y, 3 * q, 30 if q in (2, 3) else 31)
    m = re.match(r"^(\d{4})-?S([12])$", p)
    if m:
        y, s = int(m.group(1)), int(m.group(2))
        return date(y, 6, 30) if s == 1 else date(y, 12, 31)
    m = re.match(r"^(\d{4})-?M?(\d{2})$", p)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo = int(m.group(1)), int(m.group(2))
        nxt = date(y + (mo == 12), mo % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    m = re.match(r"^(\d{4})$", p)
    if m:
        return date(int(m.group(1)), 12, 31)
    return None


def period_label(p, est=False):
    """Okunur dönem: 'Sep 2026', 'Q3 2026', '18 Nov 2026', '2026' (IMF tahmini → '2026 est.')."""
    p = str(p or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", p)
    if m:
        return f"{int(m.group(3))} {_MON[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.match(r"^(\d{4})-?Q([1-4])$", p)
    if m:
        return f"Q{m.group(2)} {m.group(1)}"
    m = re.match(r"^(\d{4})-?S([12])$", p)
    if m:
        return f"H{m.group(2)} {m.group(1)}"
    m = re.match(r"^(\d{4})-?M?(\d{2})$", p)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{_MON[int(m.group(2)) - 1]} {m.group(1)}"
    if re.match(r"^\d{4}$", p):
        return p + (" est." if est else "")
    return p


def age_days(p, today=None):
    e = period_end(p)
    if e is None:
        return None
    t = today or _now()
    if isinstance(t, datetime):
        t = t.date()
    return (t - e).days


def _shift_months(p, n):
    """'2026-09' -12 → '2025-09'; '2026-Q3' -4 → '2025-Q3'."""
    p = str(p)
    m = re.match(r"^(\d{4})-(\d{2})$", p)
    if m:
        t = int(m.group(1)) * 12 + int(m.group(2)) - 1 + n
        return f"{t // 12:04d}-{t % 12 + 1:02d}"
    m = re.match(r"^(\d{4})-Q([1-4])$", p)
    if m:
        t = int(m.group(1)) * 4 + int(m.group(2)) - 1 + n
        return f"{t // 4:04d}-Q{t % 4 + 1}"
    return None


# ----------------------------------------------------------------------
# HTTP (testlerde _get değiştirilir) — TLS doğrulaması her zaman açık
# ----------------------------------------------------------------------
def _get(url, params=None, accept=None, timeout=20):
    """GET → (durum kodu, metin). Ağ / kütüphane yoksa (0, '')."""
    if requests is None:
        return 0, ""
    h = {"User-Agent": _UA, "Accept": accept or "application/json, text/csv;q=0.9, */*;q=0.5",
         "Accept-Language": "en-US,en;q=0.9"}
    try:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        return r.status_code, r.text or ""
    except Exception:
        return 0, ""


# ----------------------------------------------------------------------
# SDMX ayrıştırıcı: SDMX-CSV (kodlu ya da 'KOD: Etiket' başlıklı), yapıya özgü XML ve genel (generic) XML
# ----------------------------------------------------------------------
_ATTR = re.compile(r'([A-Za-z_][\w.\-]*)="([^"]*)"')


def _code(v):
    v = str(v or "").strip()
    return v.split(": ", 1)[0].strip() if ": " in v else v


def parse_sdmx(text):
    """Her gözlem bir sözlük: {'REF_AREA':…, 'FREQ':…, 'TIME_PERIOD':…, 'OBS_VALUE':…, diğer boyutlar…}."""
    t = (text or "").lstrip("\ufeff \r\n\t")
    if not t:
        return []
    if t.startswith("<"):
        return _parse_sdmx_xml(t)
    out = []
    try:
        rd = csv.reader(io.StringIO(t))
        head = next(rd, None)
    except csv.Error:
        return []
    if not head:
        return []
    cols = [str(h).split(":", 1)[0].strip().upper() for h in head]      # 'REF_AREA:Reference area' → REF_AREA
    labelled = any(":" in h for h in head)
    for row in rd:
        if not row or len(row) < len(cols):
            continue
        d = {}
        for c, v in zip(cols, row):
            d[c] = v.strip() if c == "OBS_VALUE" or not labelled else _code(v)
        out.append(d)
    return out


def _parse_sdmx_xml(t):
    out = []
    if "generic:" in t[:4000] or "<generic:" in t:
        for ser in re.finditer(r"<(?:\w+:)?Series>(.*?)</(?:\w+:)?Series>", t, re.S):
            body = ser.group(1)
            key = {}
            mk = re.search(r"<(?:\w+:)?SeriesKey>(.*?)</(?:\w+:)?SeriesKey>", body, re.S)
            if mk:
                for v in re.finditer(r"<(?:\w+:)?Value\b([^>]*)/?>", mk.group(1)):
                    a = dict(_ATTR.findall(v.group(1)))
                    if "id" in a:
                        key[a["id"].upper()] = a.get("value", "")
            for ob in re.finditer(r"<(?:\w+:)?Obs>(.*?)</(?:\w+:)?Obs>", body, re.S):
                ob_t = ob.group(1)
                md = re.search(r"<(?:\w+:)?ObsDimension\b([^>]*)/?>", ob_t)
                mv = re.search(r"<(?:\w+:)?ObsValue\b([^>]*)/?>", ob_t)
                if not (md and mv):
                    continue
                d = dict(key)
                d["TIME_PERIOD"] = dict(_ATTR.findall(md.group(1))).get("value", "")
                d["OBS_VALUE"] = dict(_ATTR.findall(mv.group(1))).get("value", "")
                out.append(d)
        return out
    for ser in re.finditer(r"<(?:\w+:)?Series\b([^>]*?)(/>|>(.*?)</(?:\w+:)?Series>)", t, re.S):
        key = {k.upper(): v for k, v in _ATTR.findall(ser.group(1))}
        for ob in re.finditer(r"<(?:\w+:)?Obs\b([^>]*?)/?>", ser.group(3) or ""):
            a = {k.upper(): v for k, v in _ATTR.findall(ob.group(1))}
            d = dict(key)
            d.update(a)
            out.append(d)
    return out


def _pkey(p):
    e = period_end(p)
    return e.toordinal() if e else -1


# ----------------------------------------------------------------------
# IMF DataMapper (WEO)
# ----------------------------------------------------------------------
IMF_URL = "https://www.imf.org/external/datamapper/api/v1/"
IMF_IND = {"gdp": "NGDP_RPCH", "infl": "PCPIPCH", "unemp": "LUR", "debt": "GGXWDG_NGDP"}


def parse_imf(js, k, cy):
    """IMF JSON → {iso3: [değer, yıl, 'I']}. Borçta son tamamlanan yıl, diğerlerinde cari yıl tercih edilir."""
    code = IMF_IND[k]
    vals = ((js or {}).get("values") or {}).get(code) or {}
    years = [cy - 1, cy] if k == "debt" else [cy, cy - 1]
    out = {}
    for iso, ser in vals.items():
        iso = IMF_ALIAS.get(iso, iso)
        if iso not in COUNTRY or not isinstance(ser, dict):
            continue
        for y in years:
            v = _num(ser.get(str(y)))
            if v is not None:
                out[iso] = [round(v, 2), str(y), "I"]
                break
    return out


def fetch_imf(cy=None):
    cy = cy or _now().year
    res, ok = {}, []

    def one(k):
        st_, txt = _get(IMF_URL + IMF_IND[k], params={"periods": f"{cy - 1},{cy}"}, timeout=20)
        if st_ != 200:
            return k, None
        try:
            return k, parse_imf(json.loads(txt), k, cy)
        except ValueError:
            return k, None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for k, d in ex.map(one, list(IMF_IND)):
            if d:
                res[k] = d
                ok.append(k)
    return res, len(ok) == len(IMF_IND)


# ----------------------------------------------------------------------
# BIS — merkez bankası politika faizleri
# ----------------------------------------------------------------------
BIS_URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/{key}/all"
BIS_CSV = "application/vnd.sdmx.data+csv;version=1.0.0, text/csv;q=0.9, */*;q=0.5"


def parse_bis(rows, today=None):
    """BIS gözlemleri → {iso3: [faiz, dönem, 'B'|'E']} (günlük seri aylıktan önce; euro üyelerine ECB faizi)."""
    today = today or _now()
    best = {}
    for r in rows:
        area = str(r.get("REF_AREA") or "").upper()
        v = _num(r.get("OBS_VALUE"))
        tp = str(r.get("TIME_PERIOD") or "")
        if not area or v is None or not tp:
            continue
        fr = str(r.get("FREQ") or "").upper()
        cur = best.get(area)
        key_ = (_pkey(tp), fr == "D")
        if cur is None or key_ > cur[0]:
            best[area] = (key_, v, tp)
    out = {}
    for area, (_, v, tp) in best.items():
        iso = A2_TO_A3.get(area)
        if iso:
            out[iso] = [round(v, 2), tp, "B"]
    xm = best.get("XM")
    if xm:
        xm_age = age_days(xm[2], today)
        for iso in EURO:
            own = out.get(iso)
            own_tp = best.get(COUNTRY[iso]["a2"], (None, None, ""))[2]
            # kendi serisi yoksa ya da ECB serisinden 60 günden fazla eskiyse (ör. euroya geçen ülke) → ECB faizi
            if own is None or (xm_age is not None and (age_days(own_tp, today) or 0) > xm_age + 60):
                out[iso] = [round(xm[1], 2), xm[2], "E"]
    return out


def fetch_bis(today=None):
    rows, ok = [], False
    for fr in ("D", "M"):
        url = BIS_URL.format(key=fr + ".")
        prm = {"lastNObservations": 5, "detail": "dataonly"}
        st_, txt = _get(url, params=prm, accept=BIS_CSV, timeout=25)
        if st_ != 200 or not txt.strip():
            st_, txt = _get(url, params=prm, accept="application/xml, */*;q=0.5", timeout=25)
        if st_ == 200 and txt.strip():
            got = parse_sdmx(txt)
            for r in got:
                r.setdefault("FREQ", fr)
            rows += got
            ok = ok or bool(got)
    return (parse_bis(rows, today) if rows else {}), ok


# ----------------------------------------------------------------------
# OECD — Key Short-Term Economic Indicators (en son aylık / çeyreklik açıklamalar)
# ----------------------------------------------------------------------
OECD_BASE = "https://sdmx.oecd.org/public/rest/"
OECD_FLOW = ("OECD.SDD.STES", "DSD_KEI@DF_KEI", "4.0")
OECD_DIMS = ["REF_AREA", "FREQ", "MEASURE", "UNIT_MEASURE", "ACTIVITY", "ADJUSTMENT", "TRANSFORMATION"]
OECD_MEAS = {"gdp": "B1GQ", "infl": "CP", "unemp": "UNEMP", "prod": "PRVM"}
OECD_MAX_AGE = {"gdp": 300, "infl": 200, "unemp": 240, "prod": 240}     # gün — daha eskiyse kullanılmaz
_GROWTH = ("GY", "G1", "GA", "GO", "GQ")


def _oecd_pref(k, d):
    """Seri tercih puanı (yüksek = iyi). None → bu gösterge için uygun değil."""
    tr = str(d.get("TRANSFORMATION") or "").upper()
    adj = str(d.get("ADJUSTMENT") or "").upper()
    act = str(d.get("ACTIVITY") or "").upper()
    fr = str(d.get("FREQ") or "").upper()
    unit = str(d.get("UNIT_MEASURE") or "").upper()
    if k == "unemp":
        if tr in _GROWTH or (unit and not unit.startswith("PT") and unit not in ("_Z", "PC")):
            return None             # kişi sayısı gibi seviye serileri değil, oran
        return (2 if fr == "M" else 1) * 10 + (3 if adj in ("Y", "S", "SA") else 1) + (2 if unit.startswith("PT") else 0)
    want_fr = "Q" if k == "gdp" else "M"
    sc = 20 if fr == want_fr else 5
    if k == "prod":
        sc += {"BTE": 6, "B-E": 6, "C": 3}.get(act, 0)
        sc += 2 if adj in ("Y", "S", "SA") else 1
    elif k == "infl":
        sc += 4 if act in ("_T", "_Z", "", "CP00", "TOT") else 0
        sc += 2 if adj in ("N", "_Z", "") else 1
    else:
        sc += 2 if adj in ("Y", "S", "SA") else 1
    if tr == "GY":
        return sc + 100                     # hazır 'bir yıl öncesine göre %' serisi
    if tr in _GROWTH:
        return None
    if unit in ("IX", "IDX", "XDC", "USD", "EUR", "NAC", "") or tr in ("_Z", "N", ""):
        return sc                           # seviye serisi → YoY kendimiz hesaplarız
    return None


def parse_oecd(rows, today=None):
    """OECD gözlemleri → {gösterge: {iso3: [değer, dönem, 'O'|'Oc']}}."""
    today = today or _now()
    series = {}
    for r in rows:
        area = str(r.get("REF_AREA") or "").upper()
        meas = str(r.get("MEASURE") or "").upper()
        if area not in COUNTRY:
            continue
        k = next((kk for kk, mm in OECD_MEAS.items() if mm == meas), None)
        if k is None:
            continue
        v = _num(r.get("OBS_VALUE"))
        tp = str(r.get("TIME_PERIOD") or "")
        if v is None or not tp:
            continue
        sk = (k, area) + tuple(str(r.get(d) or "") for d in OECD_DIMS[1:])
        ent = series.get(sk)
        if ent is None:
            ent = series[sk] = {"d": r, "obs": {}}
        ent["obs"][tp] = v
    best = {}
    for sk, ent in series.items():
        k, area = sk[0], sk[1]
        pref = _oecd_pref(k, ent["d"])
        if pref is None or not ent["obs"]:
            continue
        tr = str(ent["d"].get("TRANSFORMATION") or "").upper()
        cand = None
        for tp in sorted(ent["obs"], key=_pkey, reverse=True):
            if k == "unemp" or tr == "GY":
                if k == "unemp" and not 0 <= ent["obs"][tp] <= 60:
                    break
                cand = (round(ent["obs"][tp], 2), tp, "O")
                break
            back = _shift_months(tp, -4 if "Q" in tp else -12)
            base = ent["obs"].get(back) if back else None
            if base:
                cand = (round((ent["obs"][tp] / base - 1) * 100, 2), tp, "Oc")
                break
        if cand is None:
            continue
        a = age_days(cand[1], today)
        if a is None or a > OECD_MAX_AGE[k]:
            continue
        rank = (pref, _pkey(cand[1]))
        cur = best.get((k, area))
        if cur is None or rank > cur[0]:
            best[(k, area)] = (rank, cand)
    out = {k: {} for k in OECD_MEAS}
    for (k, area), (_, (v, tp, src)) in best.items():
        out[k][area] = [v, tp, src]
    return out


def _oecd_dims_from_structure(text):
    """Veri yapısı tanımından (DSD) boyut sırası: [(konum, kimlik)] → ['REF_AREA', 'FREQ', …]."""
    dims = []
    for m in re.finditer(r"<(?:\w+:)?Dimension\b([^>]*)>", text or ""):
        a = dict(_ATTR.findall(m.group(1)))
        if "id" in a and a.get("position", "").isdigit():
            dims.append((int(a["position"]), a["id"].upper()))
    return [d for _, d in sorted(set(dims))]


def _oecd_try(dims, meas, prm):
    agency, flow, ver = OECD_FLOW
    sel = {"FREQ": "M+Q", "MEASURE": meas}
    key = ".".join(sel.get(d, "") for d in dims)
    st_, txt = _get(f"{OECD_BASE}data/{agency},{flow},{ver}/{key}", params=prm, timeout=40)
    return st_, (parse_sdmx(txt) if st_ == 200 else [])


def fetch_oecd(today=None, dims=None):
    """Tek istek (OECD: saatte en çok 60 indirme). Anahtar reddedilirse (400/404) GSYH'siz denenir, yine
    reddedilirse boyut sırası veri yapısı tanımından okunup tekrar denenir. Dönüş: (veri, başarı, boyut sırası)."""
    today = today or _now()
    t = today.year * 12 + today.month - 1 - 16
    prm = {"startPeriod": f"{t // 12:04d}-{t % 12 + 1:02d}", "dimensionAtObservation": "AllDimensions",
           "format": "csvfile"}
    dims = list(dims or OECD_DIMS)
    meas_sets = ["+".join(OECD_MEAS.values()), "+".join(m for k, m in OECD_MEAS.items() if k != "gdp")]
    for meas in meas_sets:
        st_, rows = _oecd_try(dims, meas, prm)
        if rows:
            return parse_oecd(rows, today), True, dims
        if st_ not in (200, 400, 404):
            return {}, False, dims          # ağ / sunucu hatası → bir sonraki yenilemede yeniden
    agency, flow, ver = OECD_FLOW
    s2, xml = _get(f"{OECD_BASE}dataflow/{agency}/{flow}/{ver}", params={"references": "datastructure"},
                   accept="application/xml", timeout=30)
    got = _oecd_dims_from_structure(xml) if s2 == 200 else []
    if "MEASURE" in got and "REF_AREA" in got and got != dims:
        for meas in meas_sets:
            st_, rows = _oecd_try(got, meas, prm)
            if rows:
                return parse_oecd(rows, today), True, got
            if st_ not in (200, 400, 404):
                break
    return {}, False, dims


# ----------------------------------------------------------------------
# Dünya Bankası (yedek)
# ----------------------------------------------------------------------
WB_URL = "https://api.worldbank.org/v2/country/all/indicator/{code}"
WB_IND = {"gdp": ("NY.GDP.MKTP.KD.ZG", "W"), "infl": ("FP.CPI.TOTL.ZG", "W"), "unemp": ("SL.UEM.TOTL.ZS", "W"),
          "debt": ("GC.DOD.TOTL.GD.ZS", "Wc"), "prod": ("NV.IND.TOTL.KD.ZG", "Wp")}


def parse_wb(js, src, cy):
    out = {}
    rows = js[1] if isinstance(js, list) and len(js) > 1 and isinstance(js[1], list) else []
    for r in rows:
        iso = str((r or {}).get("countryiso3code") or "").upper()
        v = _num((r or {}).get("value"))
        y = str((r or {}).get("date") or "")
        if iso not in COUNTRY or v is None or not y.isdigit() or int(y) < cy - 4:
            continue
        if iso not in out or int(y) > int(out[iso][1][:4]):
            out[iso] = [round(v, 2), y, src]
    return out


def fetch_wb(cy=None):
    cy = cy or _now().year
    res, n_ok = {}, 0

    def one(k):
        code, src = WB_IND[k]
        st_, txt = _get(WB_URL.format(code=code), params={"format": "json", "mrnev": 1, "per_page": 500},
                        timeout=20)
        if st_ != 200:
            return k, None
        try:
            return k, parse_wb(json.loads(txt), src, cy)
        except ValueError:
            return k, None

    with ThreadPoolExecutor(max_workers=5) as ex:
        for k, d in ex.map(one, list(WB_IND)):
            if d:
                res[k] = d
                n_ok += 1
    return res, n_ok == len(WB_IND)


# ----------------------------------------------------------------------
# Birleştirme: hangi gösterge için hangi kaynak önce
# ----------------------------------------------------------------------
PRIORITY = {"gdp": ["oecd", "imf", "wb"], "infl": ["oecd", "imf", "wb"], "unemp": ["oecd", "imf", "wb"],
            "debt": ["imf", "wb"], "rate": ["bis"], "prod": ["oecd", "wb"]}
SRC_NAMES = {"oecd": "OECD", "imf": "IMF", "bis": "BIS", "wb": "World Bank"}
# Bu kadar günden eski değer 'last available' (son mevcut) diye işaretlenir (ör. Arjantin politika faizi)
STALE_DAYS = {"gdp": 800, "infl": 800, "unemp": 800, "debt": 1100, "rate": 400, "prod": 800}


def merge(sources):
    """sources: {'imf': {'data': {gösterge: {iso3: [v, dönem, kod]}}}, …} → {iso3: {gösterge: [v, dönem, kod]}}."""
    out = {}
    for k in IND_KEYS:
        for s in PRIORITY[k]:
            d = (((sources.get(s) or {}).get("data") or {}).get(k)) or {}
            for iso, val in d.items():
                if iso in COUNTRY and isinstance(val, (list, tuple)) and len(val) >= 3 and _num(val[0]) is not None:
                    out.setdefault(iso, {}).setdefault(k, list(val))
    return out


def build_payload(snap, today=None):
    """Bileşene giden yük: göstergeler, ülkeler (değer / dönem / kaynak / eski mi), kaynak durumu, zaman damgası."""
    today = today or _now()
    cy = today.year
    sources = (snap or {}).get("src") or {}
    merged = merge(sources)
    rows = []
    for iso, c in sorted(COUNTRY.items(), key=lambda kv: kv[1]["n"]):
        m = merged.get(iso, {})
        v, p, s, x = [], [], [], []
        for k in IND_KEYS:
            if k not in m:
                v.append(None)
                p.append("")
                s.append("")
                x.append(0)
                continue
            val, raw, src = m[k][0], str(m[k][1]), str(m[k][2])
            est = src == "I" and raw.isdigit() and int(raw) >= cy
            a = age_days(raw, today)
            v.append(round(float(val), 2))
            p.append(period_label(raw, est=est))
            s.append(src)
            x.append(1 if a is not None and a > STALE_DAYS[k] else 0)
        rows.append({"i": iso, "a2": c["a2"], "n": c["n"], "num": c["num"], "g": 1 if c["g"] else 0,
                     "v": v, "p": p, "s": s, "x": x})
    status = []
    for key in ("oecd", "imf", "bis", "wb"):
        e = sources.get(key) or {}
        n = sum(len(d) for d in (e.get("data") or {}).values() if isinstance(d, dict))
        status.append({"k": SRC_NAMES[key], "ok": bool(e.get("ok")), "n": n, "t": e.get("t") or 0,
                       "tried": e.get("tried") or 0})
    cover = {k: sum(1 for r in rows if r["v"][j] is not None) for j, k in enumerate(IND_KEYS)}
    notes = {f"{k}|{iso}": txt for (k, iso), txt in NOTES.items()}
    return {"v": MACRO_VERSION, "t": (snap or {}).get("t") or 0, "ind": INDICATORS, "c": rows,
            "src": SOURCES, "status": status, "cover": cover, "map_alias": MAP_ALIAS,
            "name_alias": NAME_ALIAS, "notes": notes, "missing": MISSING}


# ----------------------------------------------------------------------
# Önbellek: bellek + disk; eski veri arka planda yenilenir (sayfa beklemez)
# ----------------------------------------------------------------------
_LOCK = threading.Lock()
_ST = {"snap": None, "busy": False, "payload": None, "pt": None, "last_try": 0.0}


def _snap_path():
    return os.path.join(DATA_DIR, SNAP_NAME)


def load_snapshot():
    try:
        with open(_snap_path(), encoding="utf-8") as fh:
            js = json.load(fh)
        return js if isinstance(js, dict) and isinstance(js.get("src"), dict) else None
    except (OSError, ValueError):
        return None


def save_snapshot(snap):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = _snap_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _snap_path())
        return True
    except OSError:
        return False


def _count(data):
    return sum(len(d) for d in (data or {}).values() if isinstance(d, dict))


def refresh(prev=None, on_part=None, today=None):
    """Dört kaynağı paralel çeker; biten her kaynakta on_part(ara anlık görüntü) çağrılır.
    Başarısız kaynakta önceki (son başarılı) veri korunur; en az bir kaynak geldiyse diske yazılır."""
    from concurrent.futures import as_completed
    prev = prev or {}
    today = today or _now()
    now_t = time.time()
    old = dict(prev.get("src") or {})
    jobs = {"imf": lambda: fetch_imf(today.year), "bis": lambda: fetch_bis(today),
            "oecd": lambda: fetch_oecd(today, prev.get("oecd_dims")), "wb": lambda: fetch_wb(today.year)}
    src = {k: dict(v, ok=False) for k, v in old.items() if isinstance(v, dict)}
    dims = prev.get("oecd_dims")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fn): k for k, fn in jobs.items()}
        for f in as_completed(futs):
            k = futs[f]
            try:
                r = f.result()
            except Exception:
                r = None
            data, ok = (r[0], r[1]) if r else ({}, False)
            if k == "oecd" and r:
                dims = r[2]
            if k == "bis":
                data = {"rate": data} if data else {}
            if _count(data):
                ent = {"data": data, "ok": bool(ok), "t": now_t, "tried": now_t}
                if not ok and (old.get(k) or {}).get("data"):
                    md_ = dict(old[k]["data"])          # kısmi başarı → eksik göstergeler eski veriden
                    md_.update(data)
                    ent["data"] = md_
                src[k] = ent
            elif old.get(k):
                src[k] = dict(old[k], ok=False, tried=now_t)
            else:
                src[k] = {"data": {}, "ok": False, "t": 0, "tried": now_t}
            if on_part is not None:
                try:
                    on_part({"v": MACRO_VERSION, "t": now_t, "src": dict(src), "oecd_dims": dims})
                except Exception:
                    pass
    snap = {"v": MACRO_VERSION, "t": now_t, "src": src, "oecd_dims": dims}
    if any((e or {}).get("data") for e in src.values()):
        save_snapshot(snap)
    return snap


def _usable(snap):
    return bool(snap) and any((e or {}).get("data") for e in (snap.get("src") or {}).values())


def _set_snap(snap):
    with _LOCK:
        if _usable(snap) or not _usable(_ST["snap"]):
            _ST["snap"], _ST["payload"] = snap, None


def _bg_refresh():
    try:
        with _LOCK:
            prev = _ST["snap"]
        prev = prev if _usable(prev) else (load_snapshot() or {})
        _set_snap(refresh(prev, on_part=_set_snap))
    except Exception:
        pass
    finally:
        with _LOCK:
            _ST["busy"] = False


def start_refresh(min_gap=RETRY_FAIL):
    """Arka planda yenile — aynı anda tek yenileme; son denemeden min_gap saniye geçmeden yeniden denenmez."""
    with _LOCK:
        if _ST["busy"] or (_ST["last_try"] and time.time() - _ST["last_try"] < min_gap):
            return False
        _ST["busy"] = True
        _ST["last_try"] = time.time()
    threading.Thread(target=_bg_refresh, name="pulse-macro", daemon=True).start()
    return True


def get_macro(wait=15.0):
    """Bileşen yükü. Bellekte / diskte veri varsa HEMEN döner (6 saatten eskiyse arka planda yeniler).
    Hiç veri yoksa (ilk açılış) yenilemeyi başlatır ve en çok `wait` sn bekler — gelen ilk kaynaklarla döner
    (ör. OECD hâlâ yükleniyorsa IMF / BIS / Dünya Bankası ile). Hiçbir kaynak yoksa None."""
    with _LOCK:
        snap = _ST["snap"]
    if not _usable(snap):
        disk = load_snapshot()
        if _usable(disk):
            _set_snap(disk)
            snap = disk
    if not _usable(snap):
        start_refresh(min_gap=300)
        t0 = time.time()
        while wait > 0:
            with _LOCK:
                snap, busy = _ST["snap"], _ST["busy"]
            el = time.time() - t0
            if not busy or el >= wait or (_usable(snap) and el >= wait * 0.5):
                break
            time.sleep(0.2)
        with _LOCK:
            snap = _ST["snap"]
        if not _usable(snap):
            return None
    elif time.time() - float(snap.get("t") or 0) > TTL:
        start_refresh()
    with _LOCK:
        if _ST["payload"] is not None and _ST["pt"] == (id(snap), snap.get("t")):
            return _ST["payload"]
    p = build_payload(snap)
    with _LOCK:
        _ST["payload"], _ST["pt"] = p, (id(snap), snap.get("t"))
    return p


def is_loading():
    with _LOCK:
        return bool(_ST["busy"])


def reset_cache():
    with _LOCK:
        _ST.update({"snap": None, "busy": False, "payload": None, "pt": None, "last_try": 0.0})


# ----------------------------------------------------------------------
# Yük üzerinden yardımcılar (yedek görünüm + testler)
# ----------------------------------------------------------------------
def fmt_pct(v):
    return "—" if v is None else f"{v:.2f}%"


def top(payload, k, scope="g20", n=10, order="desc"):
    """Seçili göstergede ilk n ülke: [{'i','a2','n','v','p','s','rank'}]."""
    j = IND_KEYS.index(k)
    rows = [r for r in (payload or {}).get("c", []) if r["v"][j] is not None and (scope != "g20" or r["g"])]
    rows.sort(key=lambda r: (-r["v"][j] if order == "desc" else r["v"][j], r["n"]))
    return [{"i": r["i"], "a2": r["a2"], "n": r["n"], "v": r["v"][j], "p": r["p"][j], "s": r["s"][j],
             "rank": i + 1} for i, r in enumerate(rows[:n])]


def profile(payload, iso):
    """Bir ülkenin 6 göstergesi + sıralaması: [{'k','name','v','p','s','rank','of'}]."""
    rows = (payload or {}).get("c", [])
    me = next((r for r in rows if r["i"] == iso), None)
    if me is None:
        return None
    out = []
    for j, ind in enumerate(INDICATORS):
        v = me["v"][j]
        vals = sorted((r["v"][j] for r in rows if r["v"][j] is not None), reverse=True)
        rank = (vals.index(v) + 1) if v is not None else None
        out.append({"k": ind["k"], "name": ind["name"], "v": v, "p": me["p"][j], "s": me["s"][j],
                    "rank": rank, "of": len(vals)})
    return out


def bin_index(k, v):
    if v is None:
        return None
    steps = next(i["steps"] for i in INDICATORS if i["k"] == k)
    return sum(1 for s in steps if v >= s)


def status_text(payload):
    """'OECD ✓ · IMF ✓ · BIS ✓ · World Bank ✗' gibi kısa durum."""
    parts = []
    for s in (payload or {}).get("status", []):
        parts.append(s["k"] + (" ✓" if s["ok"] else (" · cached" if s["n"] else " ✗")))
    return " · ".join(parts)
