# Pulse — Market Dashboard (Streamlit) · v4.4

## Neu in v4.4 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Keine neuen Secrets.

* **Unternehmensübersicht:** Der Aufklapper heißt nur noch „About the company — details“. Die graue
  Quellenzeile („Sources: …“) über „Chart controls · period statistics“ ist entfernt.
* **Valuation:** Entfernt sind das Diagramm *Growth and Net Margin*, das Diagramm *Target-Margin DCF Path*
  und die Methode *Target-margin DCF* samt Erläuterung unter der Methods-Tabelle – aus Layout **und**
  Berechnung. *Forward P/E Comparison* steht jetzt in voller Breite.
  **Folge:** Beim Typ *Growth Tech* kommt der Fair Value nur noch aus „EV/Sales vs growth (peers)“. Gibt es
  zu wenige Vergleichsfirmen, zeigt Pulse dort keinen Mischwert.
* **Short Term – Karte der gewählten Aktie:** Unter Ticker, Firmenname und Status-Badge (z. B. BREAKOUT)
  stehen nur noch zwei Badges: der Formationsname (z. B. „20-day high breakout“) und „15m · confirmed“.
  Die Detailzeilen darunter sind entfernt.
* **Short Term – Filterleiste** (Universe, Price ≥ $3, Daily change +, Market cap ≥ $300M, Above 21 & 50 EMA,
  Top 20 by volume): volle Breite, sechs gleich breite Spalten, bündig mit dem Regime-Banner.
* **Demo:**
  * **Order ticket mit freier Suche:** Ticker oder Firmenname eintippen und direkt handeln – die Watchlist
    ist dafür nicht nötig. Darunter stehen Kurs, Orderwert, Cash danach und der eigene Bestand; „Quick
    pick“ füllt das Feld mit einem Klick aus Bestand oder Watchlist.
  * **Open positions** neu gestaltet: Zahlen rechtsbündig, Gewinn/Verlust grün bzw. rot mit Prozent-Badge,
    Summenzeile, „Sell all“ als dezenter Button in eigener Spalte.
  * **Settings:** Überschrift, „Account currency“ und „Starting balance of the demo account“ sind getrennte
    Blöcke mit festem Abstand; die Überlappung mit den Währungsschaltern ist behoben. Dieselbe Korrektur
    gilt für die anderen Kopfzeilen auf der Demo-Seite und für „Bot Profit“.

---

# Pulse — Market Dashboard (Streamlit) · v4.3

## Neu in v4.3 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Keine neuen Secrets nötig.

* **Neues Design.** Karten haben farbige Verlaufsrahmen (je nach Theme), rundere Ecken und einen leichten
  Schein beim Darüberfahren. Buttons, Eingabefelder, Aufklapper und Umschalter sind abgerundet, der
  Haupt-Button hat einen Farbverlauf, Überschriften einen farbigen Akzent. Das Night-Theme hat jetzt einen
  dezenten farbigen Hintergrund. Alle sechs Themes (auch Weiß) haben eigene Rahmenfarben.
* **Menü links.** Markets, Valuation, Long Term, Short Term, Demo, Backtest und Forex & News stehen
  untereinander in einer Seitenleiste, gruppiert in *Main Menu*, *Trading* und *Other*. Darunter zeigt
  eine kleine Karte den Stand des Demokontos und die Zahl der laufenden Bots. Die Leiste lässt sich
  einklappen; auf schmalen Bildschirmen erscheinen die Reiter zusätzlich oben.
* **Neuer Reiter „Demo“ (Demokonto mit Spielgeld, echte Kurse).**
  * Links **Settings**: Startbetrag 10.000 / 25.000 / 50.000 / 100.000 / 500.000 in **$ oder €**. Ein
    Wechsel startet das Konto neu (Watchlist und Bots bleiben, Bots werden pausiert).
  * **Eigene Watchlist**: Firmen per Ticker oder Namen hinzufügen und entfernen (bis 40). Handelbar sind
    Aktien, ETFs und Krypto in USD oder EUR.
  * **Order ticket**: manuell kaufen und verkaufen, sofort zum letzten echten Kurs. Bei einem €-Konto wird
    mit dem aktuellen EUR/USD-Kurs umgerechnet.
  * Dazu Kontostand, Equity-Kurve, offene Positionen und der Handelsverlauf.
* **Short Term: automatische Trading-Bots.** Der Block ersetzt „My Open Trades“ (das manuelle Journal ist
  darunter eingeklappt noch da).
  * **Active bots**: Tabelle mit Wert, Gesamt-P/L, Tagesschnitt, letzter Prüfung und Status; Pause, Fortsetzen
    und Löschen direkt in der Zeile. Bis zu 8 Bots laufen gleichzeitig, jeder mit eigenen Positionen.
  * **New bot**: Strategie = **AI-Opportunities-Filter** oder **einer deiner eigenen Filter** (der aktuelle
    oder ein gespeicherter); Suchbereich = Demo-Watchlist oder ganzer Markt-Scan. Einstellbar sind Risiko je
    Trade, maximale Positionen, maximale Positionsgröße, Mindest-Chance/Risiko, Trailing-Stop und Haltedauer.
  * **Prüfung alle 15 Minuten**, jeweils kurz nach Schluss der 15-Minuten-Kerze:
    * *Kauf*, wenn die Strategie vollständig erfüllt ist. Beim AI-Filter heißt das: bullische Formation mit
      Ausbruch oder Retest, Kurs über EMA 21 / 50, 15-Minuten-Bestätigung, Chance/Risiko hoch genug, SPY und
      QQQ über ihrer 50-Tage-EMA. Stückzahl = Konto × Risiko % ÷ (Einstieg − Stop).
    * *Verkauf*: Stop-Loss; 40 % bei TP1 (der Stop rückt dann auf den Einstieg); der Rest bei TP2 oder über
      den ATR-Trailing-Stop; spätestens nach der maximalen Haltedauer. Nach einem Stop wartet der Bot einen
      Tag, bevor er dieselbe Aktie wieder kauft.
    * Gekauft wird nur während der US-Handelszeit; offene Positionen werden immer überwacht.
  * **Bot Profit** (Tagesgewinne als Säulen, All / 1w / 1m) und **Asset allocation** (Ring: Cash und
    Positionen) stehen rechts daneben, darunter die offenen Bot-Positionen und das Bot-Protokoll.
  * Neue Benachrichtigung **„Bot trades“**: jeder automatische Kauf und Verkauf, auf Wunsch per Push / E-Mail.

**Wichtig zu den Bots**

* Sie handeln ausschließlich im **Demokonto**. Pulse ist mit keinem Broker verbunden; es wird kein echtes
  Geld bewegt.
* Mit Beispieldaten (wenn Yahoo nicht antwortet) wird nie gehandelt.
* Die Kurse von Yahoo sind bis zu 15 Minuten verzögert; Ausführungen sind deshalb Näherungen ohne Gebühren
  und Slippage.
* **Streamlit Community Cloud legt die App schlafen, wenn sie längere Zeit niemand öffnet.** Dann prüfen
  auch die Bots nicht. Solange die App wach ist (ein Tab offen genügt), laufen sie alle 15 Minuten weiter,
  auch wenn du auf einer anderen Seite bist.

---

# Pulse — Market Dashboard (Streamlit) · v4.2

## Neu in v4.2 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Alle Secrets aus v4.0 / v4.1 gelten weiter; zwei neue sind optional (unten).

* **Fundamentals: Quartale per Klick.** Ein Klick auf ein Geschäftsjahr in *Income Statement*, *Margins*,
  *Cash Flow* oder *Balance Sheet* ersetzt die 4-Jahres-Übersicht an dieser Stelle durch eine große
  Detailansicht: Q1–Q4 dieses Jahres, nur für die angeklickte Kategorie, in voller Breite. Sie enthält ein
  Säulendiagramm (Vorjahresquartal als Raute, noch nicht berichtete Quartale als Schätzbereich), Kacheln mit
  den Jahreswerten und eine Tabelle mit Veränderung zum Vorquartal und zum Vorjahresquartal (Margen in
  Prozentpunkten). Oben kannst du die Kategorie und das Jahr direkt wechseln. **✕ Close** oder ein erneuter
  Klick auf dasselbe Jahr bringt die 4-Jahres-Übersicht zurück. Die Bilanz-Quartale kommen aus den
  SEC-Meldungen (10-Q / 10-K), sonst aus Yahoo.
* **Short Term: keine Überlappungen mehr im Chart.**
  * Level, Stop, TP1 und TP2 stehen als farbige Schilder **direkt auf der Preisachse**. Die Achse wird so
    breit wie das längste Schild, damit nichts abgeschnitten wird.
  * Liegen Preise eng beieinander, werden die Schilder sauber versetzt und mit einer feinen Linie mit ihrem
    Preis verbunden. Das gilt auch für das Schild mit dem letzten Kurs.
  * Order-Block-, Support/Resistance-, Gap-, Dark-Pool- und Alarm-Beschriftungen laufen in einer eigenen
    Spalte am rechten Rand. Dort überlappen sie sich nie und sind jeweils mit ihrer Zone verbunden.
  * In der Standardansicht lässt der Chart rechts so viel Platz frei, dass diese Spalte keine Kerzen
    verdeckt. Wird es eng, nimmt sie automatisch die Kurzform (z. B. „Bull OB 2.4×“).
  * Die Y-Achse bezieht die Plan-Levels, nahe Order Blocks und Dark-Pool-Levels immer mit ein. Am Rand
    bleibt genug Abstand, damit kein Schild halb herausragt. Bei manuell gezoomter Achse wird ein Level
    außerhalb des Bildes mit ▲ / ▼ am Rand angezeigt.
  * Der Short-Term-Chart wächst mit der Bildschirmhöhe (ca. 84 % des sichtbaren Fensters, mindestens 700 px,
    Kursbereich mindestens 470 px). Passen die Beschriftungen trotzdem nicht hinein, wird er automatisch
    höher (bis 1180 px).
  * Formations-Beschriftungen suchen sich einen freien Platz.
* **Sentiment-Modul: Nachrichten + Community → ein Gesamtwert.**
  * **Market Sentiment** fasst Nachrichten und Community zu einem Wert von −100 bis +100 zusammen
    (Bullish ≥ +15, Bearish ≤ −15, sonst Neutral). Gewichtet wird nach Datenmenge. Darunter stehen der
    News- und der Community-Teilwert sowie eine Konfidenz („High“, wenn beide Seiten genug Daten haben und
    übereinstimmen).
  * **Live-News-Scanner** (alle 10 Minuten, auch automatisch, solange die Seite offen ist): Google News
    (Firmensuche, 7 Tage), Yahoo Finance, Seeking Alpha (Analysen / Blogs), Nasdaq und SEC EDGAR 8-K
    (offizielle Firmenmeldungen, nach Item gelesen, z. B. 2.05 Restrukturierung oder 4.02 korrigierte
    Abschlüsse). Optional kommen Finnhub Company News, Alpha Vantage (Nachrichten mit eigenem
    Sentiment-Score) und Brave News Search dazu.
  * Jede Meldung wird als *News*, *Press release*, *Blog / analysis* oder *Filing* markiert und nach
    Formulierungen bewertet, etwa „beats estimates“, „raises guidance“, „downgrade“, „cuts outlook“ oder
    „probe“. Neue Meldungen zählen stärker (Halbwertszeit ≈ 1 Tag), Pressemitteilungen etwas weniger.
    Doppelte Schlagzeilen aus mehreren Quellen werden zusammengelegt.
  * **X ohne X-API:** Ist der X-Zugang gesperrt oder nicht vorhanden, sucht Pulse über die Brave-Websuche
    nach aktuellen X-Posts zum Ticker und bewertet sie. Daneben laufen Finnhub Social Sentiment, Reddit
    (r/wallstreetbets, r/stocks, r/options) und StockTwits wie in v4.1.
  * **Hype-Indikator (getrennt von Bullish / Bearish):** eine Skala von 0–100 mit den Stufen Quiet, Normal,
    Elevated, High und Viral. Er speist sich aus diesen Treibern, die einzeln angezeigt werden:
    * Reddit-Rang und Anstieg der Erwähnungen (ApeWisdom)
    * Top 50 auf r/wallstreetbets (Tradestie)
    * Nachrichtenfluss im Vergleich zum 7-Tage-Schnitt (Google-News-Trend)
    * Tempo der X- und StockTwits-Nachrichten
    * StockTwits-Trendliste

    Bei *High* oder *Viral* erscheint über dem Bereich ein hervorgehobenes Banner.
  * **Im Hintergrund:** Der Monitor scannt die Watchlist-Aktien reihum. Wird eine davon *Viral*, kommt auf
    Wunsch eine Benachrichtigung, höchstens einmal pro Tag. Die neue Option heißt **„Viral buzz“** in den
    Benachrichtigungs-Einstellungen.
  * Unter **Sources & status** siehst du für jede Quelle, ob sie antwortet, wie viele Treffer sie liefert
    und welcher Schlüssel fehlt. Fällt eine Quelle aus, wird sie in wachsenden Abständen automatisch erneut
    versucht; die übrigen liefern weiter.

### Neue optionale Secrets (v4.2)

```toml
ALPHAVANTAGE_API_KEY = "…"   # alphavantage.co → kostenloser Key (25 Abfragen/Tag) — News mit Sentiment-Score
BRAVE_SEARCH_KEY     = "…"   # api-dashboard.search.brave.com — News-Suche + X-Posts per Websuche
# schon aus v4.1: FINNHUB_API_KEY (jetzt auch Company News), X_BEARER_TOKEN
```

Ohne diese Schlüssel funktioniert alles mit Google News, Yahoo, Seeking Alpha, Nasdaq, SEC, Reddit,
StockTwits, ApeWisdom und Tradestie. StockGeist ist **nicht** eingebaut: Die API-Endpunkte ließen sich nicht
öffentlich prüfen. ApeWisdom, Tradestie, Finnhub Social Sentiment und Alpha Vantage decken denselben Zweck ab.

---

# Pulse — Market Dashboard (Streamlit) · v4.1

## Neu in v4.1 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Die Secrets aus v4.0 (unten) gelten unverändert weiter.

* **Earnings-Box unter dem Chart.** Sie steht nicht mehr über dem Chart, sondern direkt darunter, und ist
  deutlich kleiner: eine Zeile je Box statt einer Tabelle. Die Details (Analystenspanne, Anzahl der
  Analysten, Vorjahreswert, Veränderung zum Vorjahr) erscheinen beim Darüberfahren mit der Maus. Bei ≤ 5
  Tagen bleibt die Box rot.
* **Order Blocks haben eigene Farben.** Order Blocks sind jetzt violett (bullish) und pink (bearish) und
  zusätzlich schraffiert; Rechteck-Formationen sind türkis, die übrigen Formationen bleiben gelb,
  Support- und Widerstandszonen grün und rot. Unter dem Short-Term-Chart steht eine kleine Farblegende.
* **Sentiment: X und Ausweichquellen.** Mit `X_BEARER_TOKEN` wird X direkt gelesen. Ist der Zugang
  gesperrt oder das Limit erreicht, sagt die Anzeige das samt nächstem Versuch und probiert es automatisch
  in wachsenden Abständen erneut (5 min → 1 h). Währenddessen liefert **Finnhub Social Sentiment**
  (`FINNHUB_API_KEY`) die X- und Reddit-Zahlen, sodass die Stimmung weiter gemessen wird. Reddit und
  StockTwits laufen wie bisher und werden nach einem Fehler ebenfalls automatisch erneut versucht.
* **Benachrichtigungs-Einstellungen bleiben erhalten.** Jedes Häkchen im Menü (Price Alerts, Earnings
  Ahead, Earnings Results, Economic Data, Impulse Levels sowie Push / E-Mail / Browser) wird sofort im
  Konto gespeichert — auf dem Server und, wenn `[pulse_store]` eingerichtet ist, im privaten GitHub-Repo.
  Nach einem Neuladen, einem Neustart der App oder auf einem anderen Gerät sind sie wieder da. Neu ist
  **Impulse Levels**: frische Ausbrüche aus dem AI-Scan gehen auf Wunsch auch aufs Handy.
* **Quarterly Results als großes Diagramm.** Statt der Tabelle für ein einzelnes Jahr gibt es jetzt ein
  durchgehendes Säulendiagramm über alle Geschäftsjahre (4, 6, 8 Jahre oder alle). Oben wählst du, welche
  Kennzahlen die Säulen zeigen (Umsatz, Bruttogewinn, operatives Ergebnis, Nettogewinn, operativer
  Cashflow, Free Cashflow) und welche Reihe als Linie auf der rechten Achse läuft (EPS oder eine Marge).
  Noch nicht berichtete Quartale sind blass. Ein Klick auf eine Säule öffnet die Detailtabelle dieses
  Geschäftsjahres (aufklappbar unter dem Diagramm).
* **Earnings-Kalender nur mit der Watchlist.** Die Wochenübersicht zeigt ausschließlich Unternehmen von
  deiner Watchlist, mit erwartetem EPS und — bei bereits berichteten Tagen — dem tatsächlichen Wert samt
  Abweichung und ▲ / ▼. Ist die Watchlist leer, sagt der Kalender das.

---

# Pulse — Market Dashboard (Streamlit) · v4.0

## Neu in v4.0 (Deutsch) — bitte zuerst lesen

**Dateien dieser Version (alle hochladen, dann *Reboot app*):** `app.py`, `engine.py`, `mock_data.py`,
`chart.py`, **`backend.py` (neu)** und **`pulse_chart/index.html` (geändert)**. `requirements.txt` bleibt gleich.

### Secrets (Streamlit → App → Settings → Secrets)

Nur der erste Block ist nötig, damit Logins dauerhaft halten. Alles andere ist optional.

```toml
# 1) Dauerhafter Speicher — behebt „Passwort falsch“ nach Neustarts
[pulse_store]
repo  = "DEIN-GITHUB-NAME/pulse-data"     # privates Repository (mit README angelegt)
token = "github_pat_…"                     # Fine-grained Token: nur dieses Repo, Contents: Read and write

# 2) E-Mail (Code bei „Forgot password?“, Benachrichtigungen per E-Mail)
[pulse_mail]
user = "absender@gmail.com"
app_password = "abcd efgh ijkl mnop"       # Google-Konto → 2-Step Verification → App-Passwort

# 3) Owner-Schlüssel (Notfall: Owner-Login zurücksetzen)
[pulse_admin]
key = "mindestens-8-zeichen"

# 4) Impressum: Name und Anschrift (die beiden Kontakt-E-Mails stehen immer im Footer)
[pulse_imprint]
name = "Vorname Nachname"
address = "Straße 1, 12345 Ort"
# phone = "+49 …"

# 5) Optional: bezahlte Datenquellen
UNUSUAL_WHALES_TOKEN = "…"                 # Dark-Pool-Daten im Short-Term-Chart
X_BEARER_TOKEN = "…"                       # X (Twitter) für die Sentiment-Analyse
REDDIT_CLIENT_ID = "…"                     # falls Reddit den Server ohne App-Schlüssel blockiert
REDDIT_CLIENT_SECRET = "…"
```

### Login

* **Ursache des Fehlers „Passwort falsch“:** Streamlit Cloud löscht die Festplatte der App bei jedem Neustart
  und wenn die App einschläft. Logins lagen bisher nur dort (oder als alter Stand in den Secrets). Nach einem
  Neustart galt deshalb wieder ein altes Passwort, oder das Konto war weg. Mit `[pulse_store]` liegen Logins,
  Watchlist, Alarme und Einstellungen in einem privaten GitHub-Repository und überstehen Neustarts.
* Ohne `[pulse_store]` funktioniert alles wie bisher, aber nur bis zum nächsten Neustart. Der Owner sieht
  dazu einen Hinweis unter **A → Storage & email**.
* Die Passwortprüfung akzeptiert dasselbe Passwort auch dann, wenn ein Gerät Umlaute anders kodiert oder ein
  Leerzeichen anhängt. Die Fehlermeldung sagt jetzt, ob die E-Mail unbekannt oder das Passwort falsch ist.
* **Passwort vergessen:** E-Mail eingeben → 6-stelliger Code per E-Mail (15 Minuten gültig, einmal
  verwendbar) → neues Passwort. Den früheren Wiederherstellungscode gibt es nicht mehr.
* Einstellungen gehören jetzt zum Konto (nicht mehr zum Browser-Link): Watchlist, Alarme, Zeichnungen,
  Filter, Theme, Value-Path-Einstellungen, Benachrichtigungen.

### Benachrichtigungen (🔔 → „Send to my device“)

* **Wann:** Kursalarm ausgelöst (Glocken-Werkzeug im Chart) · Earnings einer Watchlist-Aktie in ≤ 5 Tagen und
  am Tag selbst · Earnings veröffentlicht (Beat / Miss mit Zusammenfassung: EPS, Umsatz, Net Income,
  Kursreaktion) · wichtige Wirtschaftsdaten veröffentlicht (Währungen aus dem Kalender).
* **Wohin:** Push aufs Handy / den Computer über die kostenlose App **ntfy** (Topic aus den Einstellungen
  abonnieren), E-Mail (wenn `[pulse_mail]` gesetzt ist), Pop-up im Browser solange Pulse offen ist.
* Geprüft wird alle 2 Minuten auf dem Server. **Grenze:** Streamlit legt die App nach etwa 12 Stunden ohne
  Besuch schlafen, dann wird nichts geprüft, bis jemand die Seite wieder öffnet.

### Earnings

* **Unternehmensübersicht (Markets und Valuation):** nächster Termin mit Tageszeit (vor Börsenöffnung /
  nach Börsenschluss), bestätigt oder erwartet, erwartetes EPS (Spanne, Analystenzahl), erwarteter Net
  Income (EPS-Schätzung × verwässerte Aktien), erwarteter Umsatz. Bei ≤ 5 Tagen ist der ganze Hinweis rot.
  Daneben der letzte Bericht mit **BEAT / MISS / IN LINE**. Quellen: Nasdaq-Earnings-Kalender und Yahoo
  Finance. Es werden keine Beispieldaten angezeigt; fehlt eine Quelle, steht das dort.
* **Earnings Calendar (Markets):** Montag bis Freitag, je Tag „Before Open“ und „After Close“, größte
  Unternehmen zuerst, Watchlist umrandet, Logos farbig, Wochenauswahl oben rechts. Die laufende Woche bleibt
  bis Freitagabend stehen und wechselt am Samstag (US-Zeit).

### Markets, Charts, Support & Resistance

* Der Chart läuft über die volle Breite und ist höher. Die Textzeilen im Chart (OHLC, SMAs, „Ranked S/R“)
  sind aus; im Indikator-Menü lassen sie sich als „Value legend“ wieder einschalten.
* Support & Resistance: nur noch Pivot, R1, S1 und das nächste offene Gap. Im Chart höchstens 4 Zonen
  (die nächste über und unter dem Kurs zuerst) und 2 Gaps.

### Short Term

* Klick auf eine Zeile springt zum **großen Chart** der Aktie. Eingezeichnet werden das Pattern aus der
  Tabelle (Dreieck, Rechteck, Staircase, Breakout) mit seinen Pivot-Punkten, die Plan-Linien (Level, Stop,
  Ziele), **Order Blocks** und **Käufe / Verkäufe mit mindestens doppeltem Durchschnittsvolumen** (▲ / ▼).
* **Unusual Whales:** Mit `UNUSUAL_WHALES_TOKEN` kommen die großen Dark-Pool-Abschlüsse der letzten 5
  Handelstage dazu (Preisniveaus im Chart, Summen am / über dem Ask und am / unter dem Bid). Die Daten gibt
  es bei Unusual Whales nur über eine kostenpflichtige API; ohne Token steht dort „Not connected“.
* **Community Sentiment:** Reddit (Finanz-Subreddits), StockTwits und, mit `X_BEARER_TOKEN`, X. Ergebnis:
  Bullish / Bearish / Neutral mit Score von −100 bis +100, dazu Hype (Reddit-Erwähnungen in 24 h, Veränderung,
  Rang; StockTwits-Beobachter). Aktualisierung alle 10 Minuten.

### Valuation

* **Value Path:** Startwerte kommen aus den neuesten Berichten des Unternehmens (SEC 10-Q / 10-K: letzte
  12 Monate, letzte Bilanz). Unter „Data basis“ stehen Wert, Zeitraum und Quelle jeder Zahl. Die
  Standardwerte für Peak- und Trough-Marge, Umsatzrückgang und Langfrist-Wachstum stammen aus den gemeldeten
  Jahren des Unternehmens. Ist die Datenquelle nicht erreichbar, wird die Bewertung angehalten statt mit
  Beispieldaten zu rechnen.
* Layout: Value-Path-Chart über die volle Breite, die beiden Tabellen darunter nebeneinander.

### Layout und Footer

* Kleinere Abstände zwischen allen Boxen, vor allem auf Laptops; Boxen in einer Zeile enden auf gleicher Höhe.
* Footer mit Impressum, Haftungsausschluss und Datenschutz-Kurzinfo auf jeder Seite, auch auf der Login-Seite.

---

*(Ab hier die bisherige Dokumentation, auf Türkisch.)*


Swing-trade paneli (koyu temalar + **White** açık tema). **Arayüz İngilizce** (v3.5). Bölümler: **Markets · Valuation ·
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
Dosya sürümleri uyuşmazsa uygulama hangi dosyanın eski kaldığını ekranda söyler — v3.7'den
itibaren `pulse_chart/index.html` de kontrol edilir (dosyanın başında `<meta name="pulse-ui">`).
Grafikte Türkçe yazı görüyorsan sunucudaki `index.html` eskidir.

## Giriş — kimlik doğrulama (v3.8, v3.9'da çok kullanıcılı)

Uygulama her açılışta **Pulse giriş ekranıyla** başlar (tasarım: *Pulse – App Entry*).

**v3.9 — sahip (owner) ve arkadaşlar:** ilk kurulumu yapan hesap **owner** olur. Owner sağ üstteki **A** kutusunda
**Users** bölümünü görür:

* **Add user:** arkadaşın e-postası → tek seferlik **geçici şifre** gösterilir. Arkadaş ilk girişte kendi
  şifresini seçer (ve kendi kurtarma kodunu alır).
* **Reset password:** arkadaş şifresini / kurtarma kodunu unuttuysa listeden seç → *Reset password* → yeni
  geçici şifre. Eski şifre ve eski geçici şifre hemen geçersiz olur; arkadaş geçici şifreyle girer ve
  **New password** ekranında yeni şifresini belirler. Owner hiçbir zaman arkadaşın şifresini görmez.
* **Remove user:** hesabı siler; açık oturumu da kapanır.
* **Owner kendi girişini unuttuysa:** kurtarma koduyla (*Forgot email or password?*) ya da Secrets'a eklenen
  **owner anahtarıyla**: `[pulse_admin]` altında `key = "en-az-8-karakter"` (veya `PULSE_ADMIN_KEY`). Bu
  anahtar sıfırlama ekranındaki "Recovery code (or owner key)" kutusuna yazılınca owner hesabı yeni
  e-posta/şifreyle sıfırlanır.
* Kalıcı saklama için Users altındaki *Keep logins after app restarts* bloğu tüm hesapları
  `[[pulse_users]]` olarak verir (yalnızca karmalar). Eski `[pulse_auth]` bloğu da owner olarak okunur.

* **İlk açılış:** henüz giriş bilgisi yoksa "First start" ekranı çıkar — e-posta ve şifre (en az 8
  karakter, iki kez) **bir kez** belirlenir. Ardından **kurtarma kodu** (ör. `K7QM-4TXR-9WPA-HN3E`)
  yalnızca bir kez gösterilir; indirilebilir. "I have saved my recovery code" işaretlenince uygulama açılır.
* **Sonraki açılışlar:** tam olarak bu e-posta ve şifreyle giriş gerekir (e-posta büyük/küçük harf
  duyarsız). Yeni sekme / yeni açılış her zaman giriş ister; açık oturumda **15 dakika** işlem yapılmazsa
  da yeniden giriş istenir. Oturum tarayıcıya bağlıdır — `?sid=` bağlantısını başka cihaza kopyalamak girişi
  atlatmaz. Çıkış: sağ üstteki **A** kutusunda *Sign out*.
* **Tarayıcıya kaydetme:** alanlar şifre yöneticisi için işaretli (`autocomplete="username"` /
  `current-password` / `new-password`). Başarılı girişten sonra Chrome / Edge "Şifre kaydedilsin mi?" diye
  sorar; sonraki açılışlarda alanlar otomatik dolar. **Giriş yine yalnızca *Sign in* düğmesine (ya da
  Enter'a) basınca olur** — otomatik doldurma uygulamayı kendiliğinden açmaz.
* **Şifremi / e-postamı unuttum:** giriş ekranındaki **Forgot email or password?** → kurtarma kodu + yeni
  e-posta + yeni şifre → *Reset and save*. Yeni bir kurtarma kodu gösterilir, sonra yeni bilgilerle giriş
  yapılır. Kod yanlışsa hiçbir şey değişmez.
* **Güvenlik:** şifre ve kurtarma kodu düz metin saklanmaz (PBKDF2-SHA256, 240.000 tur, rastgele tuz).
  Art arda 5 yanlış denemeden sonra giriş ve sıfırlama giderek uzayan sürelerle (30 sn → 15 dk) kilitlenir.
* **Nerede saklanır:** sunucuda `.pulse_auth.json`. **Streamlit Community Cloud'da bu dosya uygulama yeniden
  başlatılınca / yeniden deploy edilince silinir** — o zaman ilk kurulum ekranı yeniden çıkar. Kalıcı olması
  için kurulumdan sonra gösterilen bloğu (yalnızca karmalar, şifrenin kendisi değil) *App settings → Secrets*
  içine yapıştır:

  ```toml
  [[pulse_users]]
  email = "sen@ornek.com"
  role = "owner"
  password_hash = "pbkdf2_sha256$240000$…"
  recovery_hash = "pbkdf2_sha256$240000$…"

  [[pulse_users]]
  email = "arkadas@ornek.com"
  role = "user"
  password_hash = "pbkdf2_sha256$240000$…"
  recovery_hash = "pbkdf2_sha256$240000$…"

  [pulse_admin]
  key = "sadece-senin-bildigin-anahtar"
  ```

  Secrets doluysa uygulama ilk kurulum istemez. Sıfırlama yapılırsa yeni bilgiler dosyaya yazılır ve
  Secrets'taki bloğu yenisiyle değiştirmen istenir (yoksa yeniden başlatmadan sonra eski giriş geri gelir).
* **Kurtarma kodu da kaybolduysa:** arkadaşlar için owner *Reset password* yapar. Owner için: owner anahtarı;
  o da yoksa Secrets'taki `[[pulse_users]]` / `[pulse_auth]` bloklarını silip uygulamayı *Reboot* et (dosya da
  silinir) → ilk kurulum ekranı yeniden açılır.

Girişten sonra ilk sayfa hesaplanırken açılış ekranı ("Loading market data…") gösterilir.

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
  ⟲ görünümü sıfırlar. **Kaydırma her yöne**: grafiği sürükle (yukarı/aşağı da), sağdaki
  **▲ / ▼** düğmeleri, klavyede **↑ / ↓**, **Shift + tekerlek**; trackpad'de iki parmak sağa-sola ve
  yukarı-aşağı kaydırır, sıkıştırma (pinch) zoom yapar. Dikey kaydırınca otomatik ölçek kapanır,
  **A** düğmesi geri açar. Sağdaki fiyat ölçeğini dikey sürükleyerek daraltıp genişletebilirsin.
- **Tam ekran**: üst bardaki *Tam ekran* düğmesi (ya da F). Tarayıcı izin vermezse panel
  ekran boyuna büyür.
- **Grafik türleri**: mum, içi boş mum, çubuk, çizgi, alan, Heikin Ashi, hacim mumları.
- **Indicators** (arama kutusu var — isimle bul): SMA 20/50/100/200, Bollinger Bands,
  Supertrend, Volumatic VIDYA, Volatility Stop, Nadaraya-Watson Envelope, Ranked S/R Zones,
  **Price Gaps** (v3.7), Hacim, RSI, Stokastik, MACD, WaveTrend, ATR, Divergence.
- **Price Gaps**: doldurulmamış fiyat boşlukları kesikli kutu olarak çizilir — fiyatın altındaki
  boşluk destek (yeşil), üstündeki direnç (kırmızı). Kısmen dolan boşluk daralır, tamamen dolan
  silinir. Varsayılan: son 260 mum, en az %0,25 boşluk, en fazla 8 kutu. Hepsi gerçek fiyat verisiyle
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

**Yarım mum hacmi (v3.7).** Haftalık/aylık mumda (ve seans içindeki günlük mumda) son mum henüz
bitmediği için hacmi, mumun tamamlanan kısmına bölünerek tahmin edilir ("on pace, the bar is 25%
complete"). Ayın 5'inde aylık hacmin "ortalamanın 0,1 katı" görünmesi bu yüzden düzeldi.

**Indicators tablosu (v3.7) — grafikteki göstergeler değerlendirilir.** Grafikte açık olan her
gösterge kendi ayarlarıyla (periyot, eşik) Buy / Neutral / Sell olarak puanlanır ve yanında kısa
gerekçesi yazar: SMA'lar (fiyat üstünde mi + ortalama yükseliyor mu), Bollinger (%B, bant
daralması), Supertrend / VIDYA / Volatility Stop (yön ve kaç mumdur sürüyor), Nadaraya-Watson
(zarf dışı mı), Ranked S/R (desteğe / dirence yakınlık), RSI, MACD, Stokastik, WaveTrend, ATR
(volatilite, nötr), Divergence (son 15 mum), Hacim. **Varsayılanların dışında bir gösterge
eklemediysen** zaman dilimine göre otomatik bir set eklenir ("auto" etiketli):

| Zaman dilimi | Otomatik set |
|---|---|
| Gün içi (1m–1H) | EMA 9, EMA 21, seans VWAP, RSI 14, Stokastik, MACD, Bollinger, Hacim |
| Swing (4H, 1D) | RSI 14, MACD, Stokastik, Bollinger, ADX 14, SMA 20/50/200, Supertrend, Hacim |
| Pozisyon (1W, 1M) | SMA 10, SMA 40, RSI 14, MACD, ADX 14, Bollinger, Hacim |

**Support & Resistance** paneli klasik pivotların altında günlük grafikteki **doldurulmamış fiyat
boşluklarını** (son 12 ay) da listeler: aralık, fiyata uzaklık, tarih, boyut ve rolü (destek/direnç).

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

**Quarterly Results (v3.9).** Gelir tablosu / marj / nakit akışı / bilanço grafiklerinde **bir yıla tıklayınca**
(ya da paneldeki yıl seçiciden) o mali yılın **Q1–Q4 sonuçları** açılır: ciro (QoQ, YoY), brüt kâr ve marj,
faaliyet kârı ve marj, net kâr ve marj, seyreltilmiş EPS (YoY), faaliyet nakit akışı, capex, serbest nakit
akışı ve yanında yıllık toplam. Kaynak: **SEC 10-Q / 10-K** (companyfacts — birkaç yıl geriye); 4. çeyrek
10-K'da ayrı yer almadığı için **yıl − ilk üç çeyrek** olarak türetilir, nakit akışları yılbaşından bugüne
(YTD) farklarıyla hesaplanır (Δ işareti). SEC verisi yoksa Yahoo'nun son ~5 çeyreği. İçinde bulunulan yılda
henüz açıklanmamış çeyrekler **expected** (analist EPS/ciro ortalaması, aralık ve analist sayısıyla) ya da
*no estimate* olarak açıkça işaretlenir. Tıklama Streamlit ≥ 1.35 ister; eski sürümde yıl seçici çalışır.

**Analyst Ratings & Expectations (v3.9, Fundamentals'ın en altında).** Konsensüs notu ve dağılımı (Strong Buy …
Strong Sell, 3 ay önceye göre değişim), 12 aylık hedef fiyat aralığı (düşük · ortalama · yüksek, bugünkü fiyatın
yeri, ortalamaya göre potansiyel), beklentiler tablosu (bu çeyrek / gelecek çeyrek / bu mali yıl / gelecek mali
yıl: EPS tahmini ve aralığı, EPS YoY, ciro tahmini, ciro YoY, analist sayısı), son 90 günde tahmin revizyonları
(yukarı/aşağı) ve son not değişiklikleri (kurum, tarih, eski → yeni not, hedef fiyat).

**Where the Revenue Comes From (v3.7).** Gelirin hangi iş kolundan geldiği şirketin SEC'e verdiği
son yıllık raporun (10-K / 20-F) XBRL verisinden okunur: **ürün / hizmet** (ör. Subscription vs
Professional Services), **iş segmentleri** ve **coğrafya** — son mali yıl tutarı, toplam içindeki
payı, yıllık büyümesi; satırın üstüne gelince 3 yıllık geçmişi. Abonelik / tekrarlayan gelir satırı
varsa payı ayrıca yazılır. Yanda **Operating metrics**: şirketin raporlarında etiketlediği müşteri,
abone, üye, mağaza gibi sayılar ve **kalan edim yükümlülükleri (RPO — sözleşmesi yapılmış ama
henüz faturalanmamış gelir)** ile **ertelenmiş gelir**; 10-Q daha yeniyse ondan alınır, yıllık
değişimiyle. Sınırlar: yalnızca SEC'e rapor veren şirketler (yabancı borsalar, ETF'ler yok); pek
çok şirket abone / ARR gibi metrikleri yalnızca bilanço sunumunda verir — XBRL'de etiketli değilse
görünmez, panel bunu söyler. SEC her istekte bir tanıtıcı (User-Agent) ister; istersen Streamlit
*Secrets* içine `SEC_USER_AGENT = "Adın e-posta@adresin"` ekleyebilirsin.

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

**Değer patikası — sürücü modeli (v3.9).** Patika artık yalnızca EPS büyümesiyle değil, şirketin
tablolarından kurulan bir **sürücü modeliyle** hesaplanır (açılır bölüm: *Value path (revenue · margin · debt ·
capex model)*; Cyclical'da açık gelir):

* **Ciro** her yıl önceki yıl × (1 + **YoY büyüme**). Analist yıllarında analist ciro tahmini; sonrasında
  ayarlar. **Model Settings → Revenue growth per year** satırında her mali yıl için büyüme **elle yazılabilir**
  (ör. döngüsel şirkette "FY2028 %35, FY2029 %20"); girilen değer "your input" olarak saklanır, *Reset* ile
  varsayılana döner. Varsayılanlar: döngüselde zirveye kadar **Upswing growth**, zirveden sonra *Revenue drop
  after peak* (iki yılda), sonra **Long-term growth** (dipten sonraki trend büyümesi); döngüsel olmayanda
  Long-term growth.
* **Faaliyet marjı:** analist yıllarında analist EPS'ini veren marj (EPS = konsensüs). Sonra döngüsel olmayanda
  3 yılda **Target op. margin**'e; döngüselde zirveye doğru **Peak op. margin**'e, düşüşte ciro düştükçe
  **Trough op. margin**'e (faaliyet kaldıracı: EPS ciroden daha çok düşer).
* **Faiz:** net borç × borç maliyeti (net nakitte risksiz faizle faiz geliri) · **vergi:** son yılların
  medyanı · **hisse sayısı:** *Shares / yr %* (− = geri alım, + = seyreltme) → **EPS**.
* **Capex % revenue**, D&A ve işletme sermayesi (ciro değişiminin %5'i) → **serbest nakit akışı**; FCF'nin
  dağıtılmayan kısmı **net borcu** azaltır (net borç / FAVÖK tabloda).
* **Valuation lens:** P/E (EPS × F/K), EV/EBIT ((EBIT × çarpan − net borç) ÷ hisse — borç ve nakit doğrudan
  etki eder) ya da **Blend** (ikisinin ortalaması, varsayılan). İki çarpan da bugünkü fiyata FY0 ile
  kalibre edilir → FY0 değeri ≈ bugünkü fiyat.
* **Model Drivers** tablosu her yılı satır satır gösterir: ciro, büyüme ve kaynağı, marj, EBIT, net faiz,
  net kâr, hisse, EPS, EPS YoY, capex, FCF, net borç, net borç/FAVÖK, P/E değeri, EV/EBIT değeri ve sonuç
  (Bear/Base/Bull seçilebilir). Kötümser: en düşük analist tahminleri, büyüme 3 puan (veya %30) düşük,
  model marjları −%10, çarpan −%15; iyimser tersi.
* Döngüsel zirve kuralı aynen geçerli: seçilen *Earnings peak* yılında EPS ve değer tam zirvede.
* Şirketin finansal tabloları yoksa eski EPS modeli (aşağıda) kullanılır.

**EPS modeli (v3.8, tablolar yoksa yedek)** — **mali yıl bazında ve yıllık (YoY) büyümeyle**:

* **Değer_FY = o mali yılın EPS'i × çarpan.** Kâr ve çarpan aynı yıla aittir; grafikte her nokta mali yıl
  sonuna oturur. Çarpan bugünkü fiyata içinde bulunulan mali yılın (FY0) EPS'iyle kalibre edilir, bu yüzden
  FY0 değeri = bugünkü fiyat. Çok yıllık ortalama / "piyasanın ufku" penceresi ve CAGR kaldırıldı;
  tabloda her yıl için **YoY** değişim (EPS ve değer) yazar.
* **EPS:** ilk iki yıl analistlerin mali yıl tahminleri (`0y`, `+1y`; taban = ortalama, kötümser = en düşük,
  iyimser = en yüksek). Sonraki her yıl = önceki yıl × (1 + **Long-term growth (YoY)**). Kaydırıcı artık
  **−%20 … %150** (güçlü büyüme dönemleri için %100 üstü). Varsayılan: son analist yılının YoY büyümesi,
  yoksa son raporlanan yılın EPS büyümesi.
* **Döngüsel mod — zirve tam seçilen yılda:** *Earnings peak* (FY0 … FY0+4) hangi yıl seçilirse değer
  patikasının en yüksek noktası **tam o yıldır** (her üç senaryoda; çeyrek görünümünde o yılın 4. çeyreği).
  Zirveye kadar EPS azalmaz (gerekirse "held" etiketiyle önceki yılın üstünde tutulur), zirveden sonra
  seçilen oranda iki yılda geriler ve ufuk içinde zirvenin altında kalır. Zirveden sonraki yıllar için
  analist tahmini daha yüksek olsa bile düşüş modeli geçerlidir ("post-peak" etiketi; Micron'da zirve FY2028
  seçilince FY2029'dan itibaren değer düşer). Hedef çarpana kayış döngüselde zirveden sonra başlar; bu kayış
  bir yılı zirvenin üstüne itseydi o yıl zirvenin hemen altına çekilir ve not düşülür.
* **Model Settings:** döngüsel mod, kâr zirvesi yılı, zirve sonrası düşüş, uzun vade büyüme (YoY), hedef
  çarpan (v3.9'da + yıl yıl ciro büyümesi, marjlar, yükseliş büyümesi, hisse değişimi, capex, mercek).
  Ayarlar hisse başına saklanır.

**Quarter by Quarter (v3.8).** Değer patikasının altında: önce **mali yılı** seç (FY2026 · reported, FY2027,
FY2028 …), sonra **çeyreği** (Full year · Q1 · Q2 · Q3 · Q4). Seçim değer grafiğinde de vurgulanır (yıl
gölgeli, çeyrek elmas işaretli; noktalı çizgi çeyrek çeyrek değer). Tabloda her çeyrek için: bitiş tarihi,
EPS (tahminlerde kötümser–iyimser aralığı), **QoQ** (önceki çeyreğe göre), **YoY** (geçen yılın aynı
çeyreğine göre), ciro, TTM EPS, değer (TTM EPS × o tarihteki çarpan; 4. çeyrek = yıllık değer; geçmiş
çeyreklerde gerçek hisse fiyatı) ve **kaynak**:

| Kaynak | Ne demek |
|---|---|
| reported | Şirketin açıkladığı EPS (Yahoo `earnings_history`, analist tahminiyle aynı baz; yoksa GAAP) — beklenti ve sürpriz yüzdesiyle |
| analyst | Henüz açıklanmadı: sıradaki iki çeyrek için analist ortalaması (analist sayısı, en düşük–en yüksek, ciro tahmini, sonraki bilanço tarihi) |
| model | Henüz açıklanmadı ve analist çeyrek tahmini yok: o yılın EPS'inden bilinen çeyrekler çıkarılır, kalan geçen yılın aynı çeyrekleri oranında dağıtılır (her çeyrek aynı YoY büyür). Toplam = yıllık EPS |

Gelecek bir çeyrek seçildiğinde ("2027'ye tıklayınca") rakamın bir **beklenti** olduğu ve nereden geldiği
açıkça yazar.

Grafikler: değer patikası (kötümser–iyimser aralığı dolgulu), yıl yıl değer + çarpan tablosu,
mali yıl EPS tablosu (analist / model etiketli), **duyarlılık ızgarası** (döngüselde zirve sonrası
ciro düşüşü × hedef F/K, değilse uzun vade büyüme × hedef F/K; sürücü modeliyle), EPS geçmişi ve projeksiyonu
(kâr zirvesi işaretli), **nakit akışı iskontosu** (10 yıllık DCF + **ters DCF**) ve **tarihsel F/K
bandı**. (v3.7'de *Valuation Range by Method* ve *Building Blocks of the Path* grafikleri kaldırıldı;
yöntem aralıkları Methods tablosunda duruyor.)

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
üst üste aynı yönde gitmiş. (v3.7'de kârlılık eğilimi ve Altman Z bileşen katkısı grafikleri kaldırıldı.)

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

**Ekonomik takvim (v3.8).** Gün ve önem (Impact) filtrelerinin yanında **para birimi seçimi**:
*Currencies* kutusunda USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, CNY, TRY alt alta, bayrak ve adıyla listelenir;
istediğini işaretle (ör. yalnızca USD), *All / Majors / None* hızlı seçim. Seçim kaydedilir. Açıklanan
değer (**Actual**) yayından sonra kendiliğinden gelir: ForexFactory takvimine TradingView'in ekonomik takvim
akışından açıklanan değer eklenir (aynı para birimi, ±75 dk, başlık / beklenti eşleşmesi); bölüm açıkken
2 dakikada bir yenilenir. Actual **yeşil** = beklentiden iyi, **kırmızı** = kötü (işsizlik oranı ve
işsizlik başvurularında düşük değer iyidir). Yayın saati geçmiş ama değer henüz yoksa *pending…*.
TradingView akışı resmi bir API değildir; ulaşılamazsa takvim yine görünür, yalnızca Actual boş kalır.

**Haber görselleri (v3.7).** Haberin kaynağı bir görsel veriyorsa (Yahoo haber küçük resmi, RSS
`media:content`) öne çıkan haberde ve listede gösterilir. Görsel yoksa ya da yüklenemezse yer
tutucu konmaz: öne çıkan haberde görsel alanı hiç çıkmaz, listede paritenin mini grafiği görünür.

## Hesap, tema ve bildirimler

Sağ üstteki **A** düğmesi hesap/ayar kutusunu açar: oturum bilgisi, *Sign out*, **arka plan
teması** (Night · Space · Forest · Ocean · Sunset · **White**) ve önbellek temizleme.
**White** açık temadır: sayfa, paneller, yazılar, Plotly grafikleri ve fiyat grafiği (mumlar,
eksenler, menüler) açık renge geçer; yeşil/kırmızı tonlar beyaz zeminde okunacak şekilde
koyulaşır. Tablolar (st.dataframe) renk tersine çevrilerek açık gösterilir.
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
  gelir kırılımı ve operasyonel göstergeler (SEC EDGAR XBRL);
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
