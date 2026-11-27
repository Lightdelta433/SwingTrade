"""Pulse backtest lab — Tagesdaten holen (läuft in GitHub Actions, nicht in der App).

Lädt Tageskerzen (Open/High/Low/Close/Adj Close/Volume, auto_adjust=False wie die App) für alle Symbole, die die
acht Short-Term-Strategien im Bot benutzen, und schreibt sie als eine CSV-Datei (gzip). Der Workflow verschlüsselt
die Datei danach mit lab/pubkey.pem — im öffentlichen Branch liegen also keine lesbaren Kursdaten.
Quelle: Yahoo Finance über yfinance; wenn Yahoo ein Symbol nicht liefert, Stooq als Ersatz.
"""
import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.request

import pandas as pd

START = "2003-01-01"
OUT = os.path.join(os.path.dirname(__file__), "out")

# US-Aktien: große, liquide Werte quer durch alle Sektoren + volatile Wachstumswerte + Werte, die
# schlecht gelaufen sind (gegen Survivorship-Bias, soweit Yahoo sie noch hat)
US = """AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO BRK-B JPM V MA UNH XOM LLY JNJ PG HD COST ABBV MRK CVX PEP KO WMT
BAC ADBE CRM NFLX AMD INTC CSCO ORCL QCOM TXN AMAT MU IBM NKE DIS MCD SBUX BA CAT DE GE HON LMT RTX UPS FDX GS MS
C WFC AXP BLK SCHW PYPL T VZ TMUS CMCSA PFE ABT TMO DHR MDT BMY GILD AMGN CVS CI ELV MO PM F GM UBER ABNB SHOP
XYZ PLTR COIN MSTR SMCI ARM SNOW CRWD PANW NOW INTU ISRG LRCX KLAC MRVL ON ADI NXPI DELL HPQ WBD SNAP ROKU ZM
DOCU RIVN LCID NIO BABA PDD JD SOFI HOOD AFRM DKNG RBLX U NET DDOG MDB TTD ENPH FSLR OXY SLB HAL COP EOG DVN
MRNA BIIB REGN VRTX NEM FCX AAL DAL UAL CCL RCL NCLH MAR LVS WYNN CLF AA MARA RIOT CVNA CHWY ETSY W PINS LYFT
SPOT TGT LOW TJX BKNG CMG LULU APA MGM EXPE EBAY GME AMC BBY KSS M GAP HPE WDC STX ADSK""".split()

# ETFs: Markt, Sektoren, Anleihen, Rohstoffe (Regime-Filter, Rotation in US-Varianten, Paare)
ETF = """SPY QQQ IWM DIA XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC SMH SOXX ARKK GLD SLV TLT IEF SHY EFA EEM DBC
VNQ HYG JNK GDX GDXJ USO BNO KRE KBE IJR EWA EWC EWG EWQ""".split()

# Ichimoku-Märkte des Bots + Rotation (UCITS auf Xetra) + Indizes
OTHER = """GC=F SI=F CL=F BTC-USD EUNL.DE SXR8.DE SXRV.DE EXS1.DE SXRT.DE IS3N.DE ZPRR.DE 4GLD.DE EUNH.DE ^VIX
^GSPC""".split()

# Paar-Kandidaten des Bots (Gruppen "US stocks" und "ETFs" — genau die, die der Bot automatisch prüft)
PAIRS = """KO PEP PG CL KMB MDLZ HSY MO PM GIS CAG WMT COST HD LOW MCD YUM V MA JPM BAC GS MS C WFC SPGI MCO ICE CME
MMC AON CB TRV ADP PAYX XOM CVX COP EOG SLB HAL VLO MPC KMI WMB BP SHEL UNP CSX UPS FDX CAT DE LMT NOC GD LHX WM
RSG DAL UAL MAR HLT NUE STLD FCX SCCO LIN APD VMC MLM SHW PPG AMAT LRCX KLAC TXN ADI TMO DHR UNH ELV ABT MDT MRK
PFE DUK SO AEP XEL T VZ PSA EXR O NNN AVB EQR EWA EWC GDX GDXJ GLD SLV USO BNO KRE KBE HYG JNK IWM IJR EWG
EWQ""".split()


def universe():
    seen, out = set(), []
    for s in US + ETF + OTHER + PAIRS:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _clean(df):
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    keep = [c for c in ("Open", "High", "Low", "Close", "Adj Close", "Volume") if c in df.columns]
    df = df[keep].dropna(subset=[c for c in ("Open", "High", "Low", "Close") if c in keep])
    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    return df if len(df) >= 30 else None


def from_yahoo(syms):
    import yfinance as yf
    got = {}
    for k in range(0, len(syms), 20):
        chunk = syms[k:k + 20]
        for attempt in range(3):
            try:
                raw = yf.download(chunk, start=START, interval="1d", auto_adjust=False, actions=False,
                                  group_by="ticker", threads=True, progress=False)
                break
            except Exception as ex:                      # Ratenlimit → kurz warten
                print("download error", chunk[0], type(ex).__name__, ex, flush=True)
                raw = None
                time.sleep(10 * (attempt + 1))
        for s in chunk:
            df = None
            try:
                if raw is not None and len(raw):
                    df = _clean(raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw)
            except Exception:
                df = None
            if df is not None:
                got[s] = df
        time.sleep(1.5)
    miss = [s for s in syms if s not in got]
    for s in miss:                                       # einzeln nachladen
        for attempt in range(2):
            try:
                df = _clean(yf.Ticker(s).history(start=START, interval="1d", auto_adjust=False, actions=False))
                if df is not None:
                    got[s] = df
                break
            except Exception as ex:
                print("history error", s, type(ex).__name__, ex, flush=True)
                time.sleep(5)
        time.sleep(0.5)
    return got


def _stooq_code(s):
    if s.endswith(".DE"):
        return s[:-3].lower() + ".de"
    if s.startswith("^") or "=" in s or s.endswith("-USD"):
        return {"^VIX": "^vix", "^GSPC": "^spx", "GC=F": "gc.f", "SI=F": "si.f", "CL=F": "cl.f",
                "BTC-USD": "btcusd"}.get(s)
    return s.lower().replace("-", ".") + ".us"


def from_stooq(s):
    code = _stooq_code(s)
    if not code:
        return None
    url = "https://stooq.com/q/d/l/?s=%s&i=d" % code
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
        txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as ex:
        print("stooq error", s, type(ex).__name__, flush=True)
        return None
    if not txt.startswith("Date"):
        return None
    df = pd.read_csv(io.StringIO(txt), parse_dates=["Date"], index_col="Date")
    df = df[df.index >= START]
    return _clean(df)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
    syms = universe()
    print("symbols:", len(syms), flush=True)
    data = {}
    src = {}
    try:
        data = from_yahoo(syms)
        src = {s: "yahoo" for s in data}
    except Exception as ex:
        print("yfinance failed:", type(ex).__name__, ex, flush=True)
    for s in [s for s in syms if s not in data]:
        df = from_stooq(s)
        if df is not None:
            data[s], src[s] = df, "stooq"
        time.sleep(0.3)
    man = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sym", "date", "open", "high", "low", "close", "adj", "volume"])
    for s in syms:
        df = data.get(s)
        if df is None:
            man.append({"sym": s, "src": "missing", "rows": 0})
            continue
        for d, r in zip(df.index, df.itertuples(index=False)):
            w.writerow([s, d.strftime("%Y-%m-%d"), "%.6g" % r[0], "%.6g" % r[1], "%.6g" % r[2], "%.6g" % r[3],
                        "%.6g" % r[4], "%d" % (r[5] if r[5] == r[5] else 0)])
        man.append({"sym": s, "src": src[s], "rows": int(len(df)), "first": str(df.index[0].date()),
                    "last": str(df.index[-1].date())})
    with gzip.open(os.path.join(OUT, "market.csv.gz"), "wt", encoding="utf-8") as f:
        f.write(buf.getvalue())
    ok = sum(1 for m in man if m["rows"])
    with open(os.path.join(os.path.dirname(__file__), "data", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"fetched_utc": time.strftime("%Y-%m-%d %H:%M"), "start": START, "symbols": len(syms),
                   "ok": ok, "items": man}, f, indent=1)
    print("ok %d / %d" % (ok, len(syms)), flush=True)
    if ok < len(syms) * 0.5:
        sys.exit("too few symbols downloaded")


if __name__ == "__main__":
    main()
