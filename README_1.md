# Pulse — Market Dashboard (Streamlit) · v3.6

Koyu temalı swing-trade paneli. **Arayüz İngilizce** (v3.5). Bölümler: **Markets · Valuation ·
Long Term · Short Term · Backtest · Forex & News**. Eski Türkçe bağlantılar
(`?sec=Piyasalar` vb.) yeni bölümlere yönlenir.

Sayılar İngilizce biçimde gösterilir (1,234.56 · +6.76%), tarihler "Oct 26, 2026" şeklinde.
Koddaki açıklama satırları Türkçe kaldı; yalnızca ekranda görünen metinler çevrildi.

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

- **Lookback period ve mum aralığı ayrı.** Üstteki *Lookback period* (1D · 5D · 1M · 3M · 6M ·
  YTD · 1Y · 2Y · 5Y · MAX) grafikte görünen dönemi seçer; yanındaki *Candle interval*
  (1m · 5m · 15m · 30m · 1H · 4H · 1D · 1W · 1M) o dönemin hangi mumlarla çizileceğini.
  Örnek: 1M + 4H = son bir ayın 4 saatlik mumları. Grafik açılışta tam o dönemi gösterir,
  geriye kaydırırsan daha eski veri de vardır. Altta dönemin açılış/yüksek/düşük/kapanışı ve
  **dönem getirisi** yazar. Yahoo'nun gün içi veri sınırı (1m ≈ 7 gün, 5–30m ≈ 60 gün,
  1H/4H ≈ 2 yıl) lookback'ten kısaysa grafik eldeki veriyi gösterir ve bunu bir notla söyler.
  Aynı kontrol Forex grafiğinde de var. Mum aralığı grafiğin içindeki saat ikonundan da seçilebilir.
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

## Değer Analizi

Seçili sembolün değerlemesi; hepsi şirketin **yayımladığı finansal tablolardan** hesaplanır
(yıllık gelir tablosu, bilanço, nakit akışı — Yahoo Finance). ETF, endeks ve pariteler için tablo
yayımlanmadığından o sembollerde yalnızca fiyat tabanlı bölümler çalışır.

**Değer Notu (A–Z).** Teknik Özet'teki mantığın değerleme hâli — A ucuz, Z pahalı:

| Grup | Ağırlık | Nelere bakar |
|------|---------|--------------|
| Rakiplere göre çarpan | %25 | F/K, ileri F/K ve FD/FAVÖK'ün rakip medyanına primi |
| Kendi geçmişine göre | %15 | Son yılların F/K dağılımında bugünkü konum (yüzdelik dilim) |
| Büyüme | %20 | Ciro ve EPS bileşik büyümesi + analistlerin bu mali yıl EPS büyümesi beklentisi |
| Bilanço & kalite | %20 | Piotroski F, Altman Z, süreklilik kontrolleri, borç/özkaynak |
| Nakit üretimi | %20 | Serbest nakit akışı getirisi, nakit akışı/net kâr, hisse adedi değişimi |

**01 Temel Veriler.** Yıl yıl çubuk grafikler: gelir tablosu, marjlar, nakit akışı, bilanço,
büyüme oranları (ciro ve EPS, bir önceki yıla göre), borç ve nakit, hissedar getirisi (geri alım +
temettü). Altında cari oran, net borç/FAVÖK, faiz karşılama, aktif kârlılığı, kazanç kalitesi.

**02 Valuation Model — şirket tipine göre değerleme (v3.6).** Önce şirket dört tipten birine
otomatik atanır; tip panelin başında gerekçeleriyle (endüstri, ciro büyümesi, capex/ciro, Ar-Ge/ciro,
beta, temettü verimi, marj aralığı) yazar ve *Valuation model* kutusundan elle değiştirilebilir
(hisse başına saklanır).

Sınıflandırma sırası: (1) elle derlenmiş rakip grubu — ör. Memory → Cyclical, GPU/foundry/ekipman/
analog → Capital Intensive, bulut-yazılım ve internet → Growth Tech, ilaç → Defensive; (2) Yahoo endüstrisi
(çelik, petrol, kimya, otomotiv, havayolu, banka → Cyclical; içecek, ev ürünleri, tütün, kamu hizmetleri,
REIT, sigorta → Defensive; yazılım, internet → Growth Tech; yarı iletken, donanım, telekom, havacılık-uzay
→ Capital Intensive); (3) ikisi de yoksa finansal ölçütler. Düzeltmeler: büyümesi %25+ ve Ar-Ge'si
%10+ olan "defansif" (ör. LLY) → Growth; betası 1,5+ olan "defansif" endüstri şirketi (ör. SoFi) →
ölçütlere göre; büyümesi %10'un altında, Ar-Ge'si düşük "growth" endüstrisi şirketi → temettü/capex'e göre.

İskonto oranı **CAPM**: ABD 10 yıllık tahvil faizi (canlı, `^TNX`) + beta × %5 hisse risk primi.
Firma düzeyindeki yöntemlerde WACC (özkaynak/borç ağırlığı, borç maliyeti = faiz gideri ÷ borç, %21 vergi).

| Tip | Yöntemler (değer aralığı) | Kontroller |
|-----|---------------------------|------------|
| Cyclical & Commodity | Döngü ortası kâr (medyan net marj × trend ciro × döngü ortası P/E), P/B ↔ döngü ortası ROE | Marjın kendi aralığındaki yeri, 90 günlük tahmin revizyonu, P/B'nin geçmişteki yeri, net borç/FAVÖK, zarar yılları |
| Defensive | 2 aşamalı temettü indirgeme, temettü verimi bandı, P/E'nin kendi geçmişi, serbest nakit akışı DCF | Ciro ve EPS büyümesi hızlanıyor mu, brüt/faaliyet/net marj eğilimi, kâr sürekliliği, dağıtım oranı, FCF'nin temettüyü karşılaması, net borç/FAVÖK, temettü büyümesi |
| Growth Tech | Hedef marj DCF (ciro azalan hızla büyür, FCF marjı hedefe yaklaşır), rakiplerde EV/Satış ~ büyüme doğrusu | Rule of 40, büyüme eğilimi, brüt marj, Ar-Ge, hisse bazlı ödeme, seyreltme, nakit pisti, tekrarlayan gelir göstergesi; ters DCF: fiyatın ima ettiği büyüme |
| Capital Intensive & Hardware | FD/FAVÖK (rakip + kendi geçmişi), ROIC − WACC ekonomik kâr, sahip kazancı DCF (bakım capex'i ≈ amortisman) | Net borç/FAVÖK ve eğilimi, borç/özkaynak, faiz karşılama, **kâr büyümesi vs borç büyümesi**, FCF sürekliliği, FAVÖK marjı istikrarı, capex yoğunluğu, ROIC vs WACC, **tekrarlayan gelir göstergesi** |

*Tekrarlayan gelir göstergesi*: Yahoo abonelik payı vermediği için bilançodaki ertelenmiş gelir
(peşin tahsil edilen abonelik/bakım) ciroya oranlanır ve büyümesi ciro büyümesiyle karşılaştırılır.

**Harman değer**: yöntemlerin ağırlıklı ortalaması (ağırlıklar tabloda). Sonucu bugünkü fiyatın 6
katından uzak olan yöntem bozuk girdiye işaret ettiği için harmana katılmaz ("excluded"). "Market-implied
path" (analist EPS × bugünkü ileri çarpan) yalnızca referanstır. Grafikler: yöntem aralıkları (futbol sahası)
ve tipe özel tek grafik — Cyclical: uzun dönem fiyat döngüleri; Defensive: temettü verimi bandı ve 10Y faiz;
Growth: hedef marj DCF patikası; Capital: FAVÖK, toplam borç ve net borç/FAVÖK.

**Döngü zamanlaması (Cyclical).** İki bağımsız tahmin: (1) fiyat döngüsü — uzun fiyat geçmişinde en az
%25–45'lik (oynaklığa göre) dönüşlerle bulunan tepe/diplerin medyan süresinden sıradaki dönüş penceresi;
(2) kâr döngüsü — analistlerin FY0/FY+1 EPS büyümesi (yavaşlıyorsa kâr zirvesi yakın), marjın kendi
aralığındaki yeri ve tahmin revizyonları; fiyat genelde kâr dönüşünden 3–9 ay önce döner. İki pencere
örtüşürse tek pencere, örtüşmezse ikisi ayrı gösterilir. Aşama: Early/Mid/Late upswing, Early downswing
(fiyat kârdan önce dönmüş), Downswing, Bottoming. Kâr zirvesi tahmini değer patikasının varsayılan zirve
yılı olur. Bu bir tarih kehaneti değil, aralıktır.

**Analist tahmini değer patikası** (açılır bölüm, Cyclical'da açık gelir). Mali yıl bazında kurulur ve
çarpanla kâr hep aynı döneme aittir:

* **EPS:** ilk iki yıl analistlerin mali yıl tahminleri (`0y` = içinde bulunulan mali yıl,
  `+1y` = sonraki). Taban = ortalama, kötümser = en düşük, iyimser = en yüksek tahmin. Sonraki
  yıllar uzun vade büyümesiyle ilerler. Çeyreklik `earningsGrowth` (son çeyrek ÷ geçen yılın aynı
  çeyreği) beklenti olmadığı için kullanılmaz.
* **Döngüsel mod** (bellek, yarı iletken ekipman, otomotiv, petrol, çelik… ve geçmişi döngüsel
  çıkan hisselerde varsayılan açık): kâr seçilen mali yılda zirve yapar, sonraki iki yılda seçilen
  oranda geriler, sonra döngü ortasına doğru toparlanır. Varsayılan düşüş şirketin kendi geçmiş
  döngülerinden gelir (%30–80 aralığına sınırlı).
* **Değer:** her yıl = o andaki çarpan × **önümüzdeki 12 ayın EPS'i**. Çarpan bugünkü fiyata
  kalibre edilir — taban senaryo bugünkü fiyattan başlar. İstenirse rakiplerin ileri F/K medyanı,
  kendi F/K medyanı ya da elle girilen bir çarpana 3 yılda kayar. İleri kâr kullanıldığı için
  döngüsellerde fiyat, kâr zirvesinden önce tepe yapar.
* **Model Ayarları** paneli: döngüsel mod, kâr zirvesi yılı, zirve sonrası düşüş, uzun vade büyüme,
  hedef çarpan, piyasanın ufku (1–2 yıl). Ayarlar hisse başına saklanır.

Grafikler: değer patikası (kötümser–iyimser aralığı dolgulu), yıl yıl değer + çarpan tablosu,
mali yıl EPS tablosu (analist / model etiketli), **duyarlılık ızgarası** (döngüselde zirve sonrası
düşüş × hedef çarpan, değilse uzun vade büyüme × hedef çarpan), EPS geçmişi ve projeksiyonu
(kâr zirvesi işaretli), patikanın yapı taşları (ileri EPS çubukları + çarpan çizgisi),
**nakit akışı iskontosu** (10 yıllık DCF + **ters DCF**) ve **tarihsel F/K bandı**.

**03 Rakiplere Göre Konum.** Rakipler önce elle derlenmiş sektör gruplarından gelir — aynı ürünü
satan, gerçekten rekabet eden şirketler, yabancı borsalardakiler dahil. Örneğin Micron için
SK Hynix (`000660.KS`), Samsung Electronics (`005930.KS`), Nanya (`2408.TW`), SanDisk (`SNDK`),
Kioxia (`285A.T`). Grupta olmayan hisselerde NASDAQ'ın endüstri sınıfı, o da yoksa sektör ETF'i
kullanılır. Kaynak başlığın altında yazar; **Rakipleri düzenle** ile liste değiştirilebilir
(hisse başına saklanır). Yabancı şirketlerin piyasa değeri dolara çevrilir. Borsada işlem görmeyen
şirketler (ör. CXMT) eklenemez.
Büyüme / çarpan haritasında yatay eksen **ileri EPS büyümesi** (önümüzdeki mali yıl tahmini ÷ son
12 ay EPS), dikey eksen ileri F/K, daire büyüklüğü piyasa değeri; kesikli çizgi rakiplerin eğilimi.
Tabloda F/K, ileri F/K, PEG (ileri), FD/FAVÖK, ileri EPS büyümesi ve net marj rakip medyanına göre
renklendirilir. Altında hissenin kendi tarihsel F/K bandındaki yeri, ileri F/K çubukları ve
büyüme / net marj karşılaştırması.

**04 Döngüsellik.** Beta, düşüşte/yükselişte yakalama oranı (SPY referans), yıllık oynaklık,
ciro ve EPS büyümesinin oynaklığı, son %15+ düşüş dönemleri ve toparlanma süreleri.
Grafikler: hisse ile S&P 500'ün son 3 yılı (başlangıç = 100), zirveden uzaklık (hisse ve endeks
yan yana) ve ay bazında ortalama getiri (mevsimsellik). Bunlardan "Savunmacı / Karma / Döngüsel / Yüksek döngüsel"
etiketi çıkar.

**05 Bilanço Sürekliliği.** Piotroski F-skoru (9 kontrol, tek tek sonuçlarıyla), Altman Z-skoru
(bileşenleriyle) ve süreklilik listesi — ciro, net kâr, serbest nakit akışı ve özkaynak kaç yıl
üst üste aynı yönde gitmiş. Grafikler: kârlılık eğilimi (özkaynak ve aktif kârlılığı, net marj)
ve Altman Z'nin bileşen katkıları.

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

## Forex & Haberler

Üstteki altı kartın (Dolar Endeksi, ABD 10Y, Altın, Brent, Dolar/TL, Bitcoin) ve sağdaki parite
listesinin tamamı tıklanabilir: tıklayınca sayfa aşağıdaki **Forex Piyasası** grafiğine kayar ve o
sembol açılır, seçili kart vurgulanır. Parite listesinde bu makro semboller için ayrıca bir
**Makro** kategorisi var.

## Hesap, tema ve bildirimler

Sağ üstteki **A** düğmesi hesap/ayar kutusunu açar: oturum bilgisi, **arka plan teması**
(Gece · Uzay · Orman · Okyanus · Gün batımı) ve önbellek temizleme.
Solundaki **🔔** bildirim kutusudur: yapay zeka taraması taze ve teyitli bir kırılım
bulduğunda oraya düşer, rozet okunmamış sayısını gösterir.
"Gün içi tazele" açıkken sayfa 3 dakikada bir yenilenip taramayı tekrarlar —
uygulama açıkken çalışır, kapalıyken tarama yapılmaz ve telefona bildirim gitmez.

## Veri

- **Haberler yalnızca gerçek kaynaklardan gelir.** Zincir: yfinance → Yahoo Finance RSS →
  Google News RSS. Üçü de boş dönerse uydurma başlık üretilmez, "haber bulunamadı" yazar.
  Habere tıklayınca kaynağın sitesi yeni sekmede açılır.
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
