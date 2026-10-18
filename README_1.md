# Swing Trade Dashboard

Koyu temalı, tek sayfa Streamlit arayüzü. Şu an **mock (sahte) veri** ile çalışır;
gerçek veriyi sonradan sadece `mock_data.py` üzerinden bağlarsın.

## Kurulum & çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

Tarayıcıda otomatik açılır (genelde http://localhost:8501).

## Dosyalar

| Dosya | Görev |
|-------|-------|
| `app.py` | Arayüz — sadece çizim yapar, veri üretmez |
| `mock_data.py` | **Tüm veri burada.** Gerçek veriye geçerken sadece bunu değiştir |
| `.streamlit/config.toml` | Koyu tema ayarı |
| `requirements.txt` | Bağımlılıklar |

## Bölümler (yukarıdan aşağı)

1. **Piyasa Özeti** — S&P 500 / Nasdaq / Dow Jones günlük % + mini grafik
2. **Filtrene Uyan Şirketler** — 20 şirket (logo + isim). "Detayı aç" → büyük
   candlestick + EMA'lar + S/R + metrikler. Grafiğin sağ üstündeki ⛶ ile tam ekran.
3. **Trading Strategy Picks** — EMA 20/50/100/200, ranked S/R zones, formasyon
   (trendline / bull flag / triangle) + volume, buy zone, stop/target, R/R.
4. **Long-Term Ucuz Şirketler** — Ticker, PEG, Forward PE, Profit Margin, EPS Next 5Y.

## Gerçek veriye geçiş

`mock_data.py` içindeki fonksiyonların **dönüş formatını koruyarak** içini değiştir:

- `get_index_summary()` → endeks fiyatı + intraday seri
- `get_ohlc(ticker)` → `yfinance.download(ticker, period="6mo")` (OHLCV kolonları aynı kalsın)
- `get_filtered_companies()` → kendi filtre motorunun ticker listesi
- `get_strategy_picks()` → TA motorunun sinyalleri
- `get_value_stocks()` → fundamental veri (PEG, Forward PE, Margin, EPS)

`app.py`'ye dokunmana gerek yok.

## Notlar

- **Logolar** Clearbit'ten (`logo.clearbit.com`) çekilir; internet gerekir. Çevrimdışı
  çalışacaksan `mock_data.logo_url()` fonksiyonunu local dosya döndürecek şekilde değiştir.
- "Sağa scroll" hissi için Strategy Picks yan yana 2 sütun halinde dizilir. Tek sütun
  istersen `app.py` içinde `PICKS_PER_ROW = 1` yap. (Streamlit'te gerçek yatay kaydırmalı
  grafik şeridi sınırlı olduğundan bu yol tercih edildi.)
