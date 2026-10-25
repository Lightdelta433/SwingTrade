# Pulse — Piyasa Paneli (Streamlit) · v3.2

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

- **Mum aralığı** (küçükten büyüğe): 1dk · 5dk · 15dk · 30dk · 1sa · 4sa · Gün · Hafta · Ay.
  Grafiğin üstünde, mum türü düğmesinin solundaki saat ikonundan da seçilebilir.
  4 saatlik mumlar saatlik veriden seans başından itibaren 4'erli toplanır; haftalık ve
  aylık mumlar günlükten türetilir.
- **Çizim araçları** (sol şerit): Trend Tools (Lines, Channels, Pitchfork, Fibonacci),
  Chart Patterns (Elliott, Triangle, Head & Shoulders), Projection (Price/Date Range,
  Forecast, Long/Short Position), Brush (serbest çizim ve geometrik şekiller).
  Projection kutuları yarı saydamdır, altındaki mumlar görünür kalır.
- **Renk**: bir çizimi tamamladığında ya da üstüne tıkladığında renk paleti açılır —
  12 hazır renk, özel renk seçici, kalınlık, düz/kesik çizgi, öne getir, kopyala, sil.
  İndikatörlerin renkleri de Indicators panelinden değiştirilir.
- **Zoom**: fare tekerleği, çift tıklama, tablette iki parmak.
  **Uzaklaştırma**: sağdaki ＋ / − düğmeleri, sağ tık, Shift + çift tık, iki parmakla çift dokunuş.
  ⟲ görünümü sıfırlar. Sürükleyerek kaydırma; sağdaki fiyat ölçeğini dikey sürükleyerek
  daraltıp genişletebilirsin, çift tık otomatiğe döner.
- **Tam ekran**: üst bardaki *Tam ekran* düğmesi (ya da F). Tarayıcı izin vermezse panel
  ekran boyuna büyür.
- **Grafik türleri**: mum, içi boş mum, çubuk, çizgi, alan, Heikin Ashi, hacim mumları.
- **Indicators** (arama kutusu var — isimle bul): SMA 20/50/100/200, Bollinger Bands,
  Supertrend, Volumatic VIDYA, Volatility Stop, Nadaraya-Watson Envelope, Ranked S/R Zones,
  Hacim, RSI, Stokastik, MACD, WaveTrend, ATR, Divergence. Hepsi gerçek fiyat verisiyle
  hesaplanır; periyot, eşik ve renkleri değiştirilebilir.
- **Alert**: fiyat koşulu (keser / üstüne çıkar / altına iner) ile uygulama içi alarm.
- Çizimler sembol bazında, indikatör ayarları ve grafik türü oturum boyunca saklanır.
- Klavye: Ctrl+Z geri al, Ctrl+Y ileri al, Delete seçili çizimi sil, Esc aracı bırak,
  F tam ekran, ← → kaydır, +/− zoom.

## Teknik Özet — A–Z notu

Piyasalar sayfasındaki Teknik Özet, **seçili grafik zaman dilimine göre** 0–100 arası bir
skor üretir ve bunu **A** (en güçlü alım) … **M/N** (nötr) … **Z** (en güçlü satım) harfine
çevirir. Altı grup, kural tabanlı puanlanır:

| Grup | Ağırlık | Nelere bakar |
|------|---------|--------------|
| Momentum | %25 | RSI(14) seviyesi ve yönü, MACD histogramı + kesişim yaşı, Stokastik %K/%D |
| Formasyon & uyumsuzluk | %20 | Çift dip/tepe, omuz-baş-omuz, üçgenler, bayrak; RSI uyumsuzlukları |
| Hacim | %20 | Göreli hacim, MFI, OBV eğimi |
| Risk / Ödül | %20 | En yakın S/R bandı ve SMA 50/200'e uzaklık; stop 0,5×ATR tabanlı |
| Trend & ortalamalar | %10 | SMA 20/50/100/200 dizilimi, Supertrend yönü, ADX gücü |
| Volatilite & konum | %5 | Bollinger %B, ATR uzaması, 52 haftalık aralıktaki yer |

Altındaki yorum da kural tabanlıdır: cümleler hesaplanan gerçek değerlerden kurulur,
dil modeli kullanılmaz. “Notun gerekçesi” bölümü her grubun neye baktığını ve kaç puan
kattığını gösterir. Yatırım tavsiyesi değildir.

## Short Term — iki mod

Üstteki anahtarla seçilir: **🤖 Yapay Zeka Fırsatları** (hazır strateji, her zaman orada) ya da
**Kendi Filtrem** (kendi koşullarını kurduğun tarayıcı).

### Yapay Zeka Trade Fırsatları — tarama zinciri

1. **Evren.** Nasdaq'ın tarayıcı servisinden tek istekte NASDAQ + NYSE'nin tamamı
   (fiyat, günlük değişim, hacim, piyasa değeri, sektör). S&P 500'ün tamamı bu kümenin içinde.
   Servis kapalıysa sınırlı evrene düşer ve bunu ekranda söyler.
2. **Ucuz filtreler.** Fiyat ≥ 3 $ · günlük değişim > %0,01 (pozitif) · piyasa değeri ≥ 300 M$.
3. **Sırala.** Kalanlar günlük hacme göre azalan sırada; ilk 60'ı için günlük OHLCV çekilir.
4. **Trend kapısı.** Fiyat hem 21 EMA hem 50 EMA üstünde olmalı.
5. **Bölge kapısı.** SPY ve QQQ 50 günlük EMA'nın üstünde olmalı; değilse strateji long aramaz.
6. **İlk 20.** Hacimde ilk 20 hisse formasyon analizine girer.
7. **15 dakikalık teyit.** Günlük kırılım seviyesi 15 dakikalık grafikte hacimle tutuyor mu.

### Formasyon algoritmaları (günlük grafik)

Hepsi pivot noktaları üzerinden çalışır (sol 3 / sağ 3 bar uç değer) ve her biri
**kırılacak seviyeyi** döndürür — 15 dakikalık teyit ve stop/hedef planı aynı seviyeyi kullanır.
Durum üç şekilde raporlanır: `kırılım` (kapanış seviyenin 0,25×ATR üstünde),
`geri test` (±0,35×ATR bandında), `oluşuyor`.

| Formasyon | Nasıl aranıyor |
|-----------|----------------|
| **Üçgen** | Son 3 tepeye ve son 3 dibe en küçük karelerle doğru uydurulur. Eğimler fiyatın yüzdesine çevrilir (%/bar), düzlük eşiği 0,045. Üst eğim negatif + alt eğim pozitif + bant genişliği %22'den fazla daraldıysa **simetrik**; üst düz + alt yükselen ise **yükselen** (boğa); üst alçalan + alt düz ise **alçalan** (ayı). Seviye = o barda üst (ya da alt) doğrunun değeri. |
| **Dikdörtgen** | Son 3 tepe birbirine %2,8 toleransla, son 3 dip de kendi arasında aynı toleransla yakınsa yatay kanal. Yükseklik fiyatın %2,5–%30'u arasında ve en az 15 bar sürmüş olmalı. Seviye = tavan (fiyat ortanın üstündeyse) ya da taban. |
| **Merdiven** | Son 3 tepe üst üste en az %1 artıyor **ve** son 3 dip de en az %1 artıyorsa yükselen merdiven; ikisi de azalıyorsa alçalan. Seviye = son zirve (ya da son dip). Güven üç basamaklık toplam harekete göre artar. |
| **Kırılım** | Önce 20 günlük, sonra 55 günlük zirve denenir. Kapanış zirvenin **0,25×ATR** üstündeyse kırılım sayılır. Güven: hacim ≥ 1,5× ortalama (+0,18), kapanış günün üst %35'inde (+0,12), kırılımdan önceki 11 barın aralığı ≤ 4,5×ATR — yani dar sıkışmadan çıkış (+0,10), 55 günlük zirve (+0,08). Kaç bar önce kırıldığı da hesaplanır; aşağı yönde aynı mantıkla dip kırılımı aranır. |

### 15 dakikalık teyit

`teyitli` = fiyat seviyenin üstünde **ve** seviyeyi kesen barın hacmi 20 barlık ortalamanın
1,3 katından fazla **ve** 15 dakikalık EMA9 > EMA21. Biri eksikse `bekleniyor`,
fiyat seviyenin altına döndüyse `bozuldu`.

### İşlem planı

- **Stop:** son günlük mumun altı, en yakın destek bandının altı ve kırılım seviyesinin
  0,5×ATR altı — hangisi daha aşağıdaysa, 0,08×ATR payla. Stop 3,2×ATR'den genişlerse
  2×ATR'ye çekilir.
- **TP1:** üstteki ilk S/R bandı (çok yakınsa bir sonraki, hiç yoksa 2R). Burada **%40** satılır.
- **TP2:** bir üstteki bant (yoksa 3,5R). Kalan **%60** trendi takip eder.
- TP1 görüldükten sonra kalan %60'ın stopu TP1 seviyesine çekilir.
- Her satır için R/R, risk yüzdesi ve stop/hedefin nereden geldiği yazılır.

### Kendi filtrem

Koşulları satır satır kurarsın; filtreni adlandırıp **kaydedebilir**, listeden geri
yükleyebilir, silebilirsin. Kayıtlar oturumda tutulur — kalıcı olması için JSON olarak
indirip "JSON'dan geri yükle" kutusundan geri verebilirsin.

## Hesap, tema ve bildirimler

Sağ üstteki **A** düğmesi hesap/ayar kutusunu açar: oturum bilgisi, **arka plan teması**
(Gece · Uzay · Orman · Okyanus · Gün batımı) ve önbellek temizleme.
Solundaki **🔔** bildirim kutusudur: yapay zeka taraması taze ve teyitli bir kırılım
bulduğunda oraya düşer, rozet okunmamış sayısını gösterir.
"Gün içi tazele" açıkken sayfa 3 dakikada bir yenilenip taramayı tekrarlar —
uygulama açıkken çalışır, kapalıyken tarama yapılmaz ve telefona bildirim gitmez.

## Veri

- Her panelde kaynak etiketi var: **● canlı veri**, **örnek veri** ya da **veri yok**.
  Etiket yoksa veri gerçektir.
- Gerçek veri gelmezse (ör. Yahoo geçici olarak yanıt vermiyorsa) kısa süre sonra yeniden denenir.
- Gerçek çekilenler: fiyat/OHLCV ve tüm grafikler, gün içi mumlar, şirket künyesi, haberler,
  endeksler, sektör performansı ve ısı haritası, yükselen/düşenler, değer taraması (Yahoo);
  Fear & Greed (CNN); ekonomik takvim (ForexFactory); IPO ve bilanço takvimi (Nasdaq).
  Bütün indikatörler, swing taraması, backtest ve pozisyon hesabı bu gerçek fiyatlardan hesaplanır.
- Kalıcı olarak örnek olan tek yer: Short Term → Açık İşlemlerim tablosunun başlangıçtaki
  üç satırı (“örnek” rozetli demo işlemler). Fiyatları canlıdır, giriş/stop/hedef uydurmadır.
- Short Term filtresi ve backtest kuralları örnek kurallardır; değerlendirme gerçek fiyatlarla yapılır.
- İsteğe bağlı: Streamlit Cloud → *Settings → Secrets* içine `FINNHUB_API_KEY = "..."` eklenirse
  IPO ve bilanço takvimi Finnhub'dan çekilir.

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```
