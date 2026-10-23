# Pulse — Piyasa Paneli (Streamlit) · v3

Koyu temalı swing-trade paneli. Bölümler: **Piyasalar · Long Term · Short Term · Backtest · Forex & Haberler**.

## Dosyalar — hepsi birlikte yüklenmeli

| Dosya | Görev |
|-------|-------|
| `app.py` | Arayüz |
| `mock_data.py` | Veri katmanı: önce gerçek veri (Yahoo Finance, CNN, ForexFactory, Nasdaq), alınamazsa etiketli örnek veri |
| `engine.py` | İndikatörler, filtre motoru, swing tarayıcı, backtest |
| `chart.py` | Grafik bileşeninin Python tarafı (veri + indikatör hesabı, alarm kontrolü) |
| `pulse_chart/index.html` | Grafik arayüzü: çizim araçları, zoom, indikatör ve alarm panelleri |
| `requirements.txt` | Bağımlılıklar (`yfinance>=0.2.54` önemli) |
| `.streamlit/config.toml` | Koyu tema |

`pulse_chart/index.html` ayrı bir klasörde durmalı. GitHub'da yeni dosya oluştururken
ad kutusuna `pulse_chart/index.html` yazman klasörü de oluşturur.
Dosya sürümleri uyuşmazsa uygulama hangi dosyanın eski kaldığını ekranda söyler.

## Grafik

- **Çizim araçları** (sol şerit): Trend Tools (Lines, Channels, Pitchfork, Fibonacci),
  Chart Patterns (Elliott, Triangle, Head & Shoulders), Projection (Price/Date Range,
  Forecast, Long/Short Position), Brush (serbest çizim ve geometrik şekiller).
- **Zoom**: fare tekerleği, çift tıklama, tablette iki parmak; sürükleyerek kaydırma.
  Sağdaki fiyat ölçeğini dikey sürükleyerek daraltıp genişletebilirsin, çift tık otomatiğe döner.
- **Grafik türleri**: mum, içi boş mum, çubuk, çizgi, alan, Heikin Ashi, hacim mumları.
- **Indicators**: SMA 20/50/100/200, Nadaraya-Watson Envelope, Ranked S/R Zones, Hacim,
  RSI, MACD, WaveTrend, Divergence. Hepsi gerçek fiyat verisiyle hesaplanır ve ayarları
  değiştirilebilir.
- **Alert**: fiyat koşulu (keser / üstüne çıkar / altına iner) ile uygulama içi alarm.
- Çizimler sembol bazında, indikatör ayarları ve grafik türü oturum boyunca saklanır.
- Klavye: Ctrl+Z geri al, Ctrl+Y ileri al, Delete seçili çizimi sil, Esc aracı bırak.

## Veri

- Her panelde kaynak etiketi var: **● canlı veri**, **örnek veri** ya da **veri yok**.
- Gerçek veri gelmezse (ör. Yahoo geçici olarak yanıt vermiyorsa) kısa süre sonra yeniden denenir.
- Short Term filtresi ve backtest kuralları örnek kurallardır; değerlendirme gerçek fiyatlarla yapılır.
- İsteğe bağlı: Streamlit Cloud → *Settings → Secrets* içine `FINNHUB_API_KEY = "..."` eklenirse
  IPO ve bilanço takvimi Finnhub'dan çekilir.

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```
