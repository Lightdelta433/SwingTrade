# Pulse — Piyasa Paneli (Streamlit) · v3

Koyu temalı swing-trade paneli. Bölümler: **Piyasalar · Long Term · Short Term · Backtest · Forex & Haberler**.

## Dosyalar — üçü birlikte yüklenmeli

| Dosya | Görev |
|-------|-------|
| `app.py` | Arayüz |
| `mock_data.py` | Veri katmanı: önce gerçek veri (Yahoo Finance, CNN, ForexFactory, Nasdaq), alınamazsa etiketli örnek veri |
| `engine.py` | İndikatörler, filtre motoru, swing tarayıcı, backtest |
| `requirements.txt` | Bağımlılıklar (`yfinance>=0.2.54` önemli) |
| `.streamlit/config.toml` | Koyu tema |

Dosya sürümleri uyuşmazsa uygulama hangi dosyanın eski kaldığını ekranda söyler.

## Veri

- Her panelde kaynak etiketi var: **● canlı veri**, **örnek veri** ya da **veri yok**.
- Gerçek veri gelmezse (ör. Yahoo geçici olarak yanıt vermiyorsa) 1–2 dakika içinde kendiliğinden yeniden denenir.
- Short Term filtresi ve backtest kuralları şimdilik örnek kurallardır; değerlendirme gerçek fiyatlarla yapılır.
- İsteğe bağlı: Streamlit Cloud → *Settings → Secrets* içine `FINNHUB_API_KEY = "..."` eklenirse IPO ve bilanço takvimi Finnhub'dan çekilir.

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```
