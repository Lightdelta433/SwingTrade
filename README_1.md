# Pulse — Market Dashboard (Streamlit) · v5.11

## Neu in v5.11 (Deutsch) — ☀️ Pre-Market / 🌙 After-Hours mit festen Uhrzeiten · Short Term nur mit deinen Mustern

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`, `macro.py`, `worker.py`,
`broker.py` und `pulse_chart/index.html` — dann *Reboot app*. `pulse_macro/index.html` (5.9) und
`pulse_list/index.html` (5.3) sind unverändert. Keine neuen Secrets, keine neuen Pakete. Läuft der Worker auf dem
VPS, dort dieselben Dateien austauschen und `pulse-worker` neu starten.

### ☀️ / 🌙 — warum die Zeilen wieder fehlten
* *Ursache:* Die Minutenkerzen von Yahoo (mit Vor- und Nachbörse) kamen an, aber Pulse hat beim Aufräumen die
  Zeitzone entfernt. Danach war nicht mehr erkennbar, ob eine Kerze vor- oder nachbörslich war — die Zeile blieb leer.
  Im Detailkopf hing sie zusätzlich an Yahoos „info“-Abfrage, die Streamlit Cloud oft bremst.
* *Jetzt:* Die Zeitzone bleibt erhalten, und der Detailkopf nutzt dieselben Minutenkerzen wie Watchlist und Tabellen
  (Yahoo-„info“ nur noch als Reserve). Kommen die Minutenkerzen eines Tages nicht, springt ein Ersatz mit
  5-Minuten-Kerzen der letzten 5 Tage ein.

### Feste deutsche Uhrzeiten (MEZ / MESZ, schaltet automatisch)
| Uhrzeit | Anzeige |
|---|---|
| 10:00 → US-Börsenstart (15:30) | ☀️ vorbörslicher Kurs + % zum letzten Schlusskurs |
| 15:30 → Börsenschluss (22:00) | regulärer Kurs, keine Zusatzzeile |
| 22:00 → 24:00 | offizieller Schlusskurs („At close“), keine Zusatzzeile |
| 00:00 → 10:00 | 🌙 nachbörslicher Kurs + % zum Schlusskurs (bis 02:00 live, danach der letzte Nachbörse-Kurs) |
| Wochenende / US-Feiertag | 🌙 der letzten Sitzung, bis am nächsten Handelstag um 10:00 ☀️ übernimmt |

* *Nahtloser Übergang:* Gab es ab 10:00 noch keinen vorbörslichen Handel, zeigt ☀️ den letzten Nachbörse-Kurs
  (Tooltip: „no pre-market trade yet“), bis der erste Pre-Market-Kurs kommt.
* Die Wochen mit versetzter Zeitumstellung (März, Ende Oktober) sind eingerechnet: Dann startet der US-Handel schon
  um 14:30, und ☀️ endet entsprechend früher. Halbe Handelstage (z. B. 27.11.) und US-Feiertage kommen aus dem
  Börsenkalender in Pulse.
* Nur US-Aktien und ETFs (SPY, QQQ … ja). Reine Indizes (^GSPC, ^VIX …), Devisen, Futures, Krypto und Nicht-US-Börsen
  (.DE …) bekommen keine Zeile.
* Überall gleiches Format **☀️ 126.10 (+0.46%)**: direkt unter dem großen Kurs im Markets- und Valuation-Kopf (dort mit
  „Pre-market · 13:12“, deutsche Uhrzeit), in Watchlists, Indexkarten, Short-Term-Listen, Bot- und Demo-Tabellen, im
  Trade-Journal und bei „Cheap Companies“. Top Movers springen zu denselben Zeiten automatisch auf ☀️ bzw. 🌙.

### Short Term: nur noch deine Chart-Muster (Strategie „Pattern breakout“)
* **Long:** Bull Flag, Bull Pennant (auch in Keilform mit zwei fallenden Linien), symmetrisches Dreieck, Rechteck /
  Range mit Ausbruch nach oben, Ausbruch über eine mehrfach getestete Widerstandslinie (mit kräftiger grüner Kerze).
* **Short:** absteigendes Dreieck (Bruch der Unterstützung), Range-Ausbruch nach unten, Kopf-Schulter (Bruch der
  Nackenlinie).
* **Raus:** Treppe, aufsteigendes Dreieck, 20-/55-Tage-Ausbruch; auch der Bestätigungs-Check „Chart patterns“ nutzt
  nur noch diese Muster.
* **Kerzen vor dem Trade = Bonus:** Hammer, Shooting Star, Bullish / Bearish Engulfing, Morning / Evening Star,
  Dragonfly Doji, Three White Soldiers, Rising / Falling Three Methods — geprüft auf den letzten 3 Tageskerzen und den
  letzten 15-Minuten-Kerzen. Passt eine Kerze zur Trade-Richtung: höherer Score, 🕯 in der Liste, „Candle signal“ ✓
  in den Checks, Markierung im Chart. Keine Kerze: kein Bonus, aber auch kein Abzug.
* **Liste:** Long und Short zusammen (LONG- / SHORT-Chip). Shorts kommen nur aus Aktien mit Tagesminus, unter EMA21 und
  EMA50 und mit einem bärischen Muster. Regime: Longs, wenn S&P 500 und Nasdaq über ihrer 50-Tage-EMA liegen, Shorts,
  wenn beide darunter liegen — sonst nur zur Info.
* **Chart:** Das Muster wird gezeichnet (Fahnenstange grün, Flaggen- und Dreieckslinien, Nackenlinie) plus 🕯-Marke.
* **Bots:** Beim neuen Musterausbruch-Bot gibt es „Direction“: *Long only* (Standard, wie bisher) oder *Long + short*.
  Bestehende Bots bleiben Long only. Ist das Positionslimit knapp, werden Signale mit Kerzen-Bonus zuerst gekauft.
  Mit einem Cash-Konto beim Broker sind keine Leerverkäufe möglich.
* Die anderen Short-Term-Strategien zeigen die Kerzenzeile ebenfalls (nur Bonus). Das Trade-Journal behandelt
  Short-Einträge jetzt richtig (Seite, G/V, Trefferquote).
* *Ehrlich:* In meiner Testumgebung gibt es kein Internet. Geprüft ist alles mit Testdaten (gebaute Muster und Kerzen,
  nachgebaute Yahoo-Minutenkerzen mit Zeitzonen, Wochenende, Feiertag, Zeitumstellung). Die Mustererkennung ist
  regelbasiert: Nicht jedes Muster, das du mit dem Auge siehst, wird erkannt — und umgekehrt.

## Neu in v5.10 (Deutsch) — Reiter „Valuation“: Fair Value und Peer-Vergleich repariert

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`, `macro.py`, `worker.py`,
`broker.py` und `pulse_chart/index.html` — dann *Reboot app*. `pulse_macro/index.html` (5.9) und
`pulse_list/index.html` (5.3) sind unverändert. Keine neuen Secrets, keine neuen Pakete.

### Ratios and quality
* Die drei Zeilen ohne Erklärung haben jetzt eine: **Return on assets** „above 10% shows strong asset efficiency“,
  **Buybacks (last year)** „capital returned via share repurchases“, **Dividends (last year)** „cash distributions
  paid to shareholders“.

### Blended Fair Value — warum „Not enough data“ kam und was jetzt passiert
* *Ursache:* Für „Growth“-Firmen (z. B. GOOGL, MSFT) gab es nur **eine** Methode (EV/Sales gegen Peers). Kamen
  keine Peer-Daten an, blieb nichts übrig.
* *Jetzt:* ein fester Kern aus vier Methoden, gewichtet: **DCF** auf Basis Free Cash Flow mit WACC aus CAPM (35 %),
  **Forward-P/E-Multiple** (30 %), **EV/EBITDA-Multiple** (20 %) und **PEG** (wachstumsbereinigtes KGV, 15 %).
  Die Multiples nehmen den Mittelwert aus Peer-Median und der eigenen Historie der Aktie; fehlt beides, gelten
  Marktdurchschnitte (KGV 18, EV/EBITDA 14, PEG 1,5).
* *Wie die Methoden zusammenkommen:* Bei „Growth“ kommen die vier Kern-Methoden immer dazu. Bei „Capital“
  (z. B. AAPL, NVDA) kommen Forward-KGV und PEG dazu (DCF und EV/EBITDA hat dieser Typ schon). Bei „Defensive“
  und „Cyclical“ springen die Kern-Methoden nur ein, wenn die eigenen Methoden zu wenig liefern.
* *Mehrstufige Daten:* Jede Eingabe hat Ersatzquellen — SEC-Daten der letzten 12 Monate → Yahoo-Finanztabellen
  (letztes Geschäftsjahr) → Yahoo-Basisdaten (TTM-EPS, Forward-EPS) → Analystenkonsens → als letzte Stufe eine
  Schätzung aus dem Gewinntrend (dann steht ein Hinweis auf der Karte).
* Auf der Karte: Fair Value, **Undervalued / Overvalued x %** als farbige Marke, jede Methode mit eigenem Wert und
  Gewicht (Mauszeiger auf die Zeile zeigt die Rechnung), die verwendeten Eingaben mit Quelle.

### Growth / Multiple Map, Multiples Comparison, Forward P/E Comparison
* *Ursache der Striche:* Alle Kennzahlen eines Peers kamen aus **einem** Yahoo-Aufruf. Auf Streamlit Cloud bremst
  Yahoo solche Aufrufe oft (Rate Limit), dann war die ganze Zeile leer.
* *Jetzt:* Yahoo wird bei einer Bremsung einmal kurz erneut gefragt, nur noch mit 3 parallelen Abfragen. Fehlt danach
  etwas, rechnet Pulse selbst aus dem Live-Kurs und den SEC-Daten der letzten 12 Monate: **P/E**, **EV/EBITDA**
  (Börsenwert + Schulden − Cash, geteilt durch EBIT + Abschreibungen), **Net Margin**, **Umsatzwachstum**,
  **Börsenwert** (NASDAQ). Fehlt die Analysten-Prognose, wird Forward-EPS aus dem Trend geschätzt → **Forward P/E**,
  **Forward EPS Growth** und **PEG**. Die letzten guten Yahoo-Werte werden bis zu 2 Tage als Reserve gehalten.
* In der Tabelle: **\*** = von Pulse aus SEC-Daten + Kurs berechnet, **≈** = aus dem Gewinntrend geschätzt (ohne
  Analystenprognose); die Legende steht unter der Tabelle. Zellen sind jetzt farbig hinterlegt: grün = günstiger /
  besser als der Peer-Median, rot = teurer / schwächer (±8 % gilt als gleichauf). Der Peer-Median steht unten.
* Bubble-Chart: x = Forward EPS Growth, y = Forward P/E, Kreisgröße = Börsenwert, Punkte beschriftet, die gewählte
  Aktie blau mit hellem Rand; geschätzte Punkte etwas blasser. Das Balkendiagramm darunter zeigt die gestrichelte
  Peer-Median-Linie.
* Verlustfirmen (z. B. SNAP) haben weiterhin kein KGV / Forward-KGV — dort bleibt der Strich, das ist richtig so.
* *Ehrlich:* In meiner Testumgebung gibt es kein Internet. Ich habe alles mit Testdaten geprüft, auch für den Fall,
  dass Yahoo komplett ausfällt. Ob Yahoo und SEC bei dir antworten, siehst du erst in der App. Ausländische Peers
  (z. B. `005930.KS`) haben keine SEC-Daten; fällt dort Yahoo aus, bleiben sie leer.

## Neu in v5.9 (Deutsch) — Global Macro Overview im Reiter „Markets“

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`, `worker.py`, `broker.py`,
`pulse_chart/index.html` und **neu** `macro.py` sowie der Ordner `pulse_macro/` mit `index.html` — dann
*Reboot app*. `pulse_list/index.html` ist unverändert (5.3). Keine neuen Secrets, keine neuen Pakete.
Der Karten-Baustein steckt zusätzlich eingebettet in `chart.py`: Fehlt der Ordner `pulse_macro/`, läuft die
Karte trotzdem. Nur `macro.py` ist Pflicht für das neue Modul (ohne sie zeigt der Bereich einen Upload-Hinweis,
der Rest der App läuft normal).

### Wo und was
* *Markets → direkt unter „Upcoming IPOs“* (linke Hauptspalte, links neben „Watchlist News“): **Global Macro
  Overview**. Das Modul passt sich der Spaltenbreite an (auch auf dem Handy) und überlappt weder die Tabelle
  darüber noch die News-Spalte.
* **6 Reiter:** GDP Growth YoY (Türkis), Inflation YoY (Hellgelb → Rot), Interest Rates (Hell- → Dunkelgrün),
  Unemployment (Hell- → Dunkelviolett), Debt to GDP (Hellrosa → Magenta), Production YoY (Hell- → Dunkelblau).
  Ein Klick wechselt **sofort** Karte, Farb-Legende und Rangliste — ohne Seiten-Reload (alles läuft im Browser).
* **Weltkarte (Choropleth)** im Pulse-Dark-Design, ohne Zahlen auf der Karte; die Farbtöne sind so gewählt, dass auch
  die dunkelsten Stufen auf dem dunklen Hintergrund sichtbar bleiben. Grau = keine Daten. Beim Überfahren:
  Flagge, Land, Wert, Stichtag und Quelle (z. B. „Denmark · 5.70 % · Sep 2026 · OECD“). Grönland zeigt wie bei
  TradingView die Werte von Dänemark.
* **Farb-Legende** darunter mit Prozentstufen: BIP 0 · 3 · 6 · 8 · 10 %, Inflation 0 · 2 · 4 · 6 · 10 %,
  Leitzins 3 · 5 · 7 · 12 · 25 %, Arbeitslosigkeit 3 · 5 · 7 · 10 · 15 %, Schulden 30 · 50 · 70 · 90 · 110 %,
  Produktion 0 · 3 · 6 · 10 · 15 %.
* **Top 10** direkt unter der Legende im Raster (Flagge + Land links, Wert rechtsbündig — wie bei TradingView),
  umschaltbar **G20 / World** und **▼ Highest / ▲ Lowest**.
* **Länder-Profil:** Klick auf ein Land (Karte *oder* Liste) öffnet „🇮🇳 India — Macro profile“ mit **← Back** und
  **✕** (auch Esc): alle 6 Kennzahlen nebeneinander, jeweils mit Stichtag, Quelle und Rang (z. B. „#2/54 · G20 #1“).
  Klick auf eine Kachel färbt die Karte nach dieser Kennzahl.
* **Merkt sich alles:** gewählter Reiter, G20/World und Sortierung werden im Konto gespeichert — auf jedem Gerät
  öffnet die Karte wieder so, wie du sie verlassen hast.

### Woher die Zahlen kommen (alles offizielle, kostenlose Quellen — nichts wird geschätzt)
* **OECD** (Key Short-Term Economic Indicators): die **neuesten Monats-/Quartalswerte** für BIP-Wachstum YoY,
  Inflation YoY, Arbeitslosenquote und Industrieproduktion YoY — OECD-Länder und mehrere G20-Länder. Diese haben
  Vorrang.
* **BIS:** Leitzinsen von rund 40 Zentralbanken; die **EZB-Rate** gilt für alle 21 Euro-Länder (seit 1.1.2026
  inkl. Bulgarien). Nicht von der BIS erfasste Länder bleiben beim Leitzins grau. Argentinien hat seit Juli 2025 keinen
  offiziellen Leitzins mehr → letzter Wert (29 %) mit Hinweis „last available value“. USA: die BIS nutzt die Mitte
  der Fed-Zielspanne.
* **IMF World Economic Outlook:** wo OECD fehlt, BIP / Inflation / Arbeitslosigkeit als Jahreswert des laufenden
  Jahres (**„2026 est.“** = IMF-Schätzung), Staatsschulden/BIP für das letzte abgeschlossene Jahr — ca. 190 Länder.
* **Weltbank:** letzte Lücken (Jahreswerte); bei der Produktion ersatzweise „Industrie-Wertschöpfung, jährlich“ —
  im Tooltip ausdrücklich so gekennzeichnet.
* Die Daten werden alle 6 Stunden im Hintergrund erneuert (die Seite wartet nicht) und in
  `.pulse_data/macro_snapshot.json` gespeichert. Fällt eine Quelle kurz aus, bleiben ihre letzten Werte stehen.
* *Ehrlich:* Werte können von TradingView abweichen — TradingView nutzt teils nationale Statistikämter und andere
  Abgrenzungen (z. B. Japans Schuldenquote, US-Leitzins als Obergrenze statt Mitte). Bei jedem Wert stehen Stichtag
  und Quelle, damit du siehst, wie aktuell er ist. In meiner Testumgebung gibt es kein Internet: Logik, Karte und
  Klicks sind mit Testdaten geprüft, die echten Abrufe passieren erst in deiner App.
* Die Länderformen (Natural Earth über `world-atlas`) und Flaggen lädt der Browser von cdn.jsdelivr.net. Falls ein
  Netzwerk das blockiert: Karte zeigt einen Hinweis, Rangliste und Profile funktionieren weiter. Optional kannst du
  `countries-110m.json` aus dem npm-Paket `world-atlas` in den Ordner `pulse_macro/` legen — dann wird die Karte von
  dort geladen.

## Neu in v5.8 (Deutsch)

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`,
`pulse_chart/index.html` und **neu** `worker.py`, `broker.py`, der Ordner `deploy/` (`Dockerfile`,
`docker-compose.yml`, zwei `.service`-Dateien, `windows/start_pulse.bat`, `windows/start_worker.bat`),
`.dockerignore` und die geänderte `.gitignore` — dann *Reboot app*. `pulse_list/index.html` ist unverändert (5.3).
Keine neuen Pflicht-Secrets. Auf Streamlit Cloud werden `worker.py`, `broker.py` und `deploy/` nicht benutzt —
sie sind für den Betrieb rund um die Uhr auf PC / VPS / Docker.

### 1) Neue Strategie: Divergence (viele Indikatoren)
* *Swing & Short Term → Strategy → 🔀 Divergence.* Nach der Methode von „Divergence for Many Indicators“
  (LonesomeTheBlue, TradingView): Pulse sucht bestätigte Swing-Tiefs/-Hochs des Kurses und prüft für **12
  Indikatoren**, ob sie dem Kurs widersprechen — RSI, MACD-Linie, MACD-Histogramm, Stochastik, CCI, Momentum,
  OBV, VW-MACD (volumengewichtet), Chaikin Money Flow, MFI, Williams %R und WaveTrend.
* **Regulär** (Kurs tieferes Tief, Indikator höheres Tief → Umkehr) und **versteckt** (Kurs höheres Tief, Indikator
  tieferes Tief → Trendfortsetzung), bullisch und bärisch, also **Long und Short**. Zwischen den beiden Punkten
  darf nichts die Verbindungslinie schneiden („Sichtlinie“). Nur bestätigte Pivots, der Endpunkt ist die Vorkerze
  und auf der letzten Kerze muss Indikator oder Schlusskurs drehen → **kein Repainting, kein Blick in die Zukunft**
  (per Test geprüft: abgeschnittene Daten liefern exakt dieselben Signale).
* **Signal**, wenn mindestens *N* Indikatoren gleichzeitig divergieren (Standard 3 von 12). Stop knapp hinter dem
  Divergenz-Extrem (0,2 ATR Puffer; kein Trade, wenn der Stop weiter als 3 ATR weg wäre), **TP1 = Nackenlinie**
  (das Swing-Hoch zwischen den beiden Tiefs, mindestens 1,5 R; 40 % werden dort verkauft, Stop auf Einstand),
  **TP2 = 3 R**.
* **⚙️ Divergence settings** über der Tabelle: Mindestanzahl, regulär/versteckt, Pivot-Quelle (Close oder
  High/Low), Pivot-Periode, wie viele Pivots / Kerzen zurück, Indikator-Auswahl, Stop-Grenze, TP1/TP2, optional nur
  in Richtung des 200-Tage-Durchschnitts. Unter *Indicator lengths* stehen alle Längen **und eine Tabelle, was
  jeder Indikator misst und warum seine Divergenz zählt**.
* Rechts beim ausgewählten Signal: **Divergence breakdown** — jeder beteiligte Indikator mit Typ und Wert am ersten
  und zweiten Swing, dazu, welche Indikatoren *nicht* divergieren. Die Checkliste hat eigene Zeilen (Anzahl,
  Volumen-Bestätigung durch OBV/VW-MACD/CMF/MFI, Typ, Länge, RSI an der Wende).
* **Chart:** die Divergenz-Linien mit Indikatorliste, Signal-Kerze, Stop / TP1 / TP2. In den Chart-Einstellungen
  (*Indikatoren → Divergence*) gibt es zusätzlich die Quelle **„Many indicators (12)“** mit Mindestanzahl — die
  Labels zeigen dann z. B. „▲×4“.
* **Backtest:** Strategie „🔀 Divergence for many indicators“ mit denselben Einstellungen, Long/Short/Both. Neu:
  Tabelle **„Which indicators worked on this symbol“** — Gewinnquote und Profit-Faktor je Indikator.
* **Bot:** „🔀 Divergence…“ im Bot-Formular nutzt genau die Einstellungen der Divergence-Tabelle.

### 2) Pairs Trading + Pair Lab
* *Strategy → ⚖️ Pairs.* Zwei Werte mit gleichem Geschäft laufen auseinander und wieder zusammen. Ist der
  Spread gedehnt (z-Score jenseits ±2), wird der billige gekauft und der teure leerverkauft — β-gewichtet,
  dollar-neutral. Beide Beine werden zusammen geschlossen, wenn der Spread zurück am Mittelwert ist
  (Stop bei |z| ≥ 3,5, Zeitstopp 30 Tage).
* **Datensatz:** 69 Kandidaten-Paare mit Begründung — US-Aktien gleicher Branche (KO/PEP, V/MA, HD/LOW,
  XOM/CVX, SPGI/MCO, WM/RSG, VMC/MLM …), ETFs (EWA/EWC, GDX/GDXJ, GLD/SLV, HYG/JNK …), Futures (Gold/Silber,
  WTI/Brent, Mais/Weizen, Soja/Sojaschrot), BTC/ETH und deutsche Aktien (BMW/Mercedes, Allianz/Munich Re,
  Deutsche Bank/Commerzbank, RWE/E.ON, Adidas/Puma). Das sind **Hypothesen** — welche Paare wirklich
  funktionieren, entscheidet der Test. Alternativ: alle Kombinationen deiner Watchlist oder eigene Paare.
* **▶ Run analysis** lädt die echten Tageskurse und testet jedes Paar: rollierender Hedge-Faktor und z-Score
  (jeden Tag nur aus vergangenen Daten), Einstieg zum nächsten Eröffnungskurs, Kommission auf beiden Beinen.
  Dazu **Engle-Granger-Kointegrationstest** (p-Werte aus 144 000 Simulationen, deckungsgleich mit MacKinnon:
  1 % −3,90 · 5 % −3,34 · 10 % −3,04), **Halbwertszeit** der Rückkehr und Rendite-Korrelation.
* **Rangliste nach Gewinnquote**, dazu Trades, Profit-Faktor, Ø-Trade, Max-Drawdown, CAGR, p-Wert, Halbwertszeit,
  aktueller z und Signal. **„Usable“** = kointegriert (p ≤ 5 %), Halbwertszeit 2–40 Tage, ≥ 6 Trades,
  Gewinnquote ≥ 60 %, Profit-Faktor ≥ 1,2, Drawdown besser als −25 %. **„Watch“** = Backtest gut, aber die
  statistische Bindung schwach (oder umgekehrt). Gewinnquote der 1. und 2. Testhälfte separat (Stabilität).
* **⬇ Download the full dataset (CSV)** — alle Paare mit allen Kennzahlen. Detailansicht pro Paar: normierte
  Kurse, z-Score mit Ein-/Ausstiegsbändern und Trades, Trade-Liste, Positionsbeispiel.
* *Ehrlich:* Die Gewinnquoten konnte ich vorab nicht ausrechnen — in meiner Umgebung ist Yahoo Finance gesperrt.
  Die App rechnet sie beim ersten Klick mit echten Kursen (ca. 1 Minute, danach 6 h im Cache).

### 3) Momentum-Rotation
* *Strategy → 🔄 Rotation.* Jeden Monat wird die Liste nach 3/6/12-Monats-Rendite gerankt, die stärksten N
  werden gleichgewichtet gehalten, wer herausfällt, wird verkauft. **Absolutes Momentum** (nur positive Werte),
  **Marktfilter** (Benchmark unter dem 200-Tage-Schnitt → alles in den sicheren Hafen), **Puffer** gegen unnötige
  Umschichtungen, optional „letzten Monat überspringen“ und volatilitätsbereinigt.
* Universen: **UCITS-ETFs auf Xetra** (MSCI World, S&P 500, Nasdaq-100, DAX, Euro Stoxx 50, EM, Russell 2000,
  Gold; Hafen: Euro-Staatsanleihen — für EU-Anleger kaufbar), US-Sektor-ETFs, Asset-Klassen, Nasdaq-100-Leader,
  deutsche Large Caps, Watchlist oder eigene Liste.
* Rangliste heute mit Aktion (Buy/Hold/Sell), Risk-on/off-Banner, **Backtest gegen die Benchmark** (CAGR,
  Max-Drawdown, Sharpe, Gewinnmonate, Umschlag, Zeit im Hafen) und Verlauf der Körbe.

### 4) Neue Bots
* **⚖️ Pairs-Bot:** eröffnet beide Beine zusammen (geht das zweite nicht, wird das erste sofort rückgängig
  gemacht), keine Stops auf den Beinen — der Spread entscheidet. Max. offene Paare und Größe pro Paar einstellbar,
  ein Symbol gehört immer nur einem offenen Paar. Der z-Score nutzt den letzten 15-Minuten-Kurs. Schließt du ein
  Bein von Hand, schließt der Bot das andere. Vorbelegt mit den „Usable“-Paaren des letzten Pair-Lab-Laufs
  (Knopf *Create a pairs bot with the usable pairs*).
* **🔄 Rotations-Bot:** kauft den ersten Korb beim nächsten Check, danach zu Monatsbeginn; jede Order, sobald ihre
  Börse offen ist. Anteil am Konto einstellbar. *Rebalance now* in der Bot-Zeile erzwingt eine Umschichtung.
* Bot-Zeilen zeigen offene Paare (mit Einstiegs-z) bzw. den aktuellen Korb.

### 5) Rund um die Uhr: `worker.py`
* Streamlit Community Cloud schläft nach ~12 h ohne Besuch ein — dann laufen keine Bots. Lösung: die App selbst
  hosten und **`worker.py` daneben** starten. Der Worker erledigt Alarme, Bilanz-/Makro-Hinweise, SL/TP und
  Limit-Orders (alle 30 s) und die Bots (15-Minuten-Takt) — auch wenn kein Browser offen ist.
* Beide Prozesse laufen mit **`PULSE_SHARED=1`** und teilen den Datenordner: Lesen erkennt Änderungen des anderen
  Prozesses, jede Lese-Ändern-Schreiben-Aktion ist per Datei-Lock abgesichert (Test: 4 Prozesse × 150 gleichzeitige
  Buchungen → keine verlorene), Benachrichtigungen des Workers erscheinen auch in der Glocke. Läuft ein Worker,
  pausiert der Monitor der Oberfläche automatisch; im Bot-Bereich steht „24/7 worker ✓“.
* Start: **Docker** `docker compose -f deploy/docker-compose.yml up -d --build` · **Linux-VPS** die beiden
  `deploy/*.service`-Dateien (systemd) · **Windows** `deploy\windows\start_pulse.bat` und `start_worker.bat`
  (Autostart über die Aufgabenplanung „Bei Anmeldung“). `python worker.py --check` zeigt die Einstellungen,
  `--once` macht genau einen Durchlauf (für Cron).

### 6) Pulse merkt sich alles
* Neben Watchlist, Alarmen, **Zeichnungen**, Chart-Einstellungen und gespeicherten Filtern landen jetzt auch alle
  Einstellungen der Seiten (Strategie-Auswahl, Divergence-/Pair-Lab-/Rotations-Einstellungen, Backtest-Felder,
  Zeiträume …), das Trade-Journal, die Filterzeilen, der letzte Backtest und die letzten Pair-Lab-/Rotations-Läufe
  im Konto. Beim nächsten Login — auf jedem Gerät — öffnet Pulse die **zuletzt benutzte Seite** mit diesen
  Einstellungen. Dauerhaft über Neustarts hinweg nur mit festem Speicher: selbst gehostet ist das der Datenordner,
  auf Streamlit Cloud das GitHub-Repo aus *Account → Storage & email*.

### 7) IBKR-Brücke (experimentell, standardmäßig aus)
* `broker.py` kopiert Bot-Orders eines bestimmten Demo-Kontos an Interactive Brokers (TWS / IB Gateway,
  `pip install ib_async`). Schutz: nur das per `PULSE_BROKER_ACCOUNT` benannte Demo-Konto, Mengen-Faktor,
  Höchstwert pro Order, max. Orders pro Tag, nur Paper-Port 7497 außer mit `PULSE_BROKER_LIVE=1`, Notbremse
  (Datei `STOP_TRADING` im Datenordner), `PULSE_BROKER=log` als Trockenlauf. Nur US-Aktien/ETFs und Xetra.
  Schritt-für-Schritt-Anleitung im separaten Guide. Erst wochenlang auf Paper laufen lassen.

### 8) Korrekturen
* WaveTrend-Backtest: Die 40-%-Teilmitnahme an der NW-Mittellinie wurde bisher übersprungen — jetzt wie im
  Live-Plan und beim Bot. (Backtest-Ergebnisse dieser Strategie ändern sich dadurch.)
* Backtest-Engine: Kursziele funktionieren jetzt auch für Short-Trades.
* Die Farblegende unter dem Strategie-Chart beschreibt Ichimoku und WaveTrend korrekt (vorher stand dort die
  Flaggen-Legende).

## Neu in v5.7 (Deutsch)

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`,
`pulse_chart/index.html` (außer `app.py` ändert sich überall nur die Versionsnummer, alle müssen aber auf 5.7
stehen) — dann *Reboot app*. `pulse_list/index.html` ist unverändert (5.3). v5.7 enthält alles aus v5.4–v5.6.

### Risk & exposure: UI-Korrekturen
* **Abstand:** Zwischen der Box *Open risk* und der Box *Buying power* liegen jetzt 12 px, die Kästen gehen nicht
  mehr ineinander über.
* **Loss-Limit-Text bleibt in der Spalte:** Der Betrag („$105.00 / $5,000“) steht in einer eigenen Zeile, darunter
  kompakt „2.1 % used“ links und „98 % left“ rechts, dann der Balken. Nichts ist mehr auf eine Zeile gezwungen,
  auch bei schmalen Fenstern ragt nichts ins rechte Panel. Titel „Circuit breaker“ und Status-Badge brechen nicht
  mehr mitten im Wort um; wird es eng, rutscht das Badge als Ganzes in die nächste Zeile.
* **Farben für Realised / Open:** Unter dem Balken gilt jetzt: Gewinn grün mit „+“, Verlust rot mit „−“
  (z. B. „Realised since Mon 16.11. −$120“), exakt null neutral weiß ohne Vorzeichen („$0“). Vorher war auch $0
  und ein Verlust grün eingefärbt. Beträge unter 1 werden mit Cent angezeigt (z. B. „−$0.40“), damit ein kleiner
  Verlust nicht als „$0“ erscheint. Gleiche Regel für den *Open*-Wert daneben. Rot ist das App-weite Rot `#F87171`.

## Neu in v5.6 (Deutsch)

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`,
`pulse_chart/index.html` (bei `chart.py`, `mock_data.py` und `pulse_chart/index.html` ändert sich nur die
Versionsnummer) — dann *Reboot app*. `pulse_list/index.html` ist unverändert (5.3). v5.6 enthält alles aus v5.4
und v5.5; wenn du die noch nicht hochgeladen hast, reicht dieses Paket. Keine neuen Secrets.

### Börsenzeiten: Orders außerhalb der Handelszeit werden vorgemerkt
* Beim Absenden prüft Pulse, ob die **Heimatbörse** des Wertpapiers gerade regulär handelt:
  US-Aktien/ETFs (NYSE / NASDAQ) 15:30–22:00 MEZ, XETRA / Frankfurt 09:00–17:30, Euronext (Paris, Amsterdam,
  Brüssel, Lissabon, Dublin), Mailand, Madrid, Wien, Helsinki jeweils 09:00–17:30 MEZ. Wochenenden und die
  Börsenfeiertage 2026/2027 sind hinterlegt (USA inkl. Halbtage nach Thanksgiving und an Heiligabend, Europa
  inkl. 24.12. und 31.12.). Gerechnet wird in der Ortszeit der Börse, die Wochen mit abweichender Zeitumstellung
  (USA/Europa) stimmen also automatisch. Krypto handelt rund um die Uhr, Gold/Silber/Öl-Futures nach CME-Zeiten
  (So 18:00 – Fr 17:00 New Yorker Zeit, also Mo 0:00 – Fr 23:00 MEZ, mit täglicher Pause 23:00–0:00 MEZ).
* Ist die Börse zu, zeigt das Order Ticket einen gelben Hinweis („NYSE / NASDAQ is closed · opens 15:30 CET“) und
  der Knopf heißt **„Queue for the open“**. Die Order wird **nicht** in *Open positions* gebucht, sondern landet
  in **Pending orders** (über den offenen Positionen) als *BUY AT OPEN* bzw. *SELL AT OPEN* — mit Symbol,
  Stückzahl, Order-Typ (Market), **geplanter Summe** und Status *„Waits for the NYSE / NASDAQ open · 15:30 CET“*.
* Das benötigte Kapital wird als **reservierte Buying Power** geblockt: Die Cash-Kachel zeigt „$2,000 reserved“,
  *Buying power* im Risk-Panel sinkt entsprechend, und neue Käufe können das reservierte Geld nicht nutzen.
  Solange die Börse zu ist, gibt es **keinen Open P/L** — das Geld ist ja noch nicht investiert.
* **× Cancel** storniert die vorgemerkte Order jederzeit vor Börsenstart und gibt das Kapital sofort frei.
* **Bei Börsenöffnung** wird sie automatisch zum aktuellen Eröffnungs-/Marktkurs ausgeführt (Prüfung im Live-Takt
  alle 20 Sekunden, auch beim Seitenaufruf, und bei jedem 15-Minuten-Botlauf), verschwindet aus *Pending orders*
  und steht dann in *Open positions* und der Trade History („Queued at NYSE / NASDAQ open“). Ein beim Absenden
  gesetzter Stop-Loss / Take-Profit wird mit übernommen. Reicht das Cash zum Eröffnungskurs nicht (der Kurs kann
  über Nacht steigen), bleibt die Order mit Hinweis stehen.
* **Limit-Orders** füllen ebenfalls nur noch in der regulären Sitzung (Status außerhalb: „… closed — fills in the
  session“).
* **Bots** prüfen jetzt jedes Symbol gegen seine eigene Börse: Aktien nur in deren Handelszeit, Krypto und Futures
  auch außerhalb der US-Sitzung (vorher waren alle Bots an die US-Sitzung gebunden). Bots nutzen dabei nur freies,
  nicht reserviertes Cash.
* *Grenzen:* Die Feiertagslisten decken 2026 und 2027 ab — danach gelten nur Wochenenden und Uhrzeiten, bis die
  Liste ergänzt wird. „Cover all“ für Short-Positionen und SL/TP-Ausstiege laufen weiter wie bisher (ohne
  Börsenzeiten-Prüfung). Ausgeführt wird, solange Pulse läuft: Schläft die App auf Streamlit Cloud um 15:30
  (niemand hatte sie länger offen), füllt die Order beim ersten Check nach dem Aufwachen — zum dann aktuellen Kurs,
  nicht rückwirkend zum Eröffnungskurs.

### Ichimoku: Frische-Filter & Signal-Abstufung nach Kerzen-Alter
* Das Alter eines Signals zählt jetzt ab dem **initialen Kumo-Ausbruch** — der ersten Tageskerze, deren Schlusskurs
  die Wolke (Senkou A & B) verlässt (= Kerze 1). Kreuzen Tenkan/Kijun oder die Chikou erst später, altert das Signal
  trotzdem ab diesem Ausbruch.
* **Kerze 1–3:** *Strong breakout · armed (candle 2 of 3)* — Chip **STRONG · ARMED**, volle Signalstärke für den
  Neueinstieg. Bots dürfen in diesen drei Kerzen einsteigen (vorher nur Tag 1–2).
* **Kerze 4–10:** *Mature trend · aging (candle 6)* — Chip **AGING** (orange). Kein frisches Einstiegssignal mehr:
  offene Trades halten (Ausstieg bei Schluss jenseits der Kijun) oder auf den Kijun-Pullback warten. Bots steigen
  nicht ein; der Trade-Plan zeigt den Einstieg an der Kijun.
* **Ab Kerze 11:** *Trend above the cloud · no breakout signal* — Chip **NO SIGNAL** (neutral). Als Folge-Setup
  bleibt der **Kijun Bounce (Second Entry)** — er wird unabhängig vom Ausbruchsalter erkannt (Chip **KIJUN BOUNCE**).
* Damit es keine Verwechslung gibt: Der bisherige gelbe Chip „ARMED“ (Signal da, aber Marktregel nicht erfüllt
  oder zu weit von der Kijun) heißt auf dem Ichimoku-Board jetzt **ON HOLD**.
* Gilt für Long und Short, im klassischen Modus und für Stufe 2 im gestaffelten Modus. Der **Backtest** nimmt nur
  noch frische Ausbrüche (Kerze 1–3), die Einstiegspunkte im Chart ebenfalls; die Checkliste zeigt „Age of the
  breakout: candle 2 of 3“. Die Wartezeile ohne Signal nennt ebenfalls das Alter („Above the cloud — no fresh
  signal (candle 14)“).
* Die Ichimoku-Auswertung läuft auf Tageskerzen — „Kerze“ heißt hier also Handelstag.

## Neu in v5.5 (Deutsch)

**Dateien:** hochladen — `app.py`, `backend.py`, `chart.py`, `engine.py`, `mock_data.py`,
`pulse_chart/index.html` und (neu) `pulse_list/index.html` — dann *Reboot app*. v5.5 enthält alles aus v5.4
(Zahnrad, 8 Kacheln, Positionsrechner, Risk-Panel, Circuit Breaker); wenn du v5.4 noch nicht hochgeladen hast,
reicht dieses Paket. `pulse_list/index.html` steckt auch eingebettet in `chart.py` — wer die Datei im Repo nicht
anlegen will, kann sie weglassen. Keine neuen Secrets.

### Loss-Limit-Balken: vierstufige Health-Skala
* **Verbleibende Account Health = 100 % − verbrauchtes Limit.** Der Balken wechselt die Farbe in vier Stufen:
  **100–75 % dunkelgrün** (`#0E9F6E`, optimal) · **75–50 % hellgrün** (`#34D399`) · **50–25 % gelb/amber**
  (`#F5B544`, Warnbereich) · **25–0 % rot** (`#F87171`, kurz vor ACCOUNT BREACHED).
* Das **Status-Badge** oben rechts im Circuit-breaker-Block zeigt dieselbe Stufe samt Prozentwert:
  *HEALTHY · 92 %* → *GOOD · 61 %* → *WARNING · 36 %* → *CRITICAL · 12 %* → *BREACHED*.
* Beide wechseln weich: `transition: background-color .3s ease, width .3s ease` — Breite und Farbe folgen sofort,
  wenn sich offener P/L oder realisierte Verluste ändern (die Seite rechnet den Periodenverlust bei jedem Lauf neu).
* Unter dem Balken steht jetzt „63.7 % used · 36 % left“ in einer Zeile.

### Open-risk-Warnung zentriert
Der gelbe Hinweis („1 position without a stop-loss …“) sitzt jetzt **innerhalb** der Open-risk-Box, über die volle
Breite zentriert (`text-align:center; width:100%; display:block`), ohne linke Einrückung — direkt unter
*$0.00 / 0.00 % of equity*.

### Position size: Unternehmens-Auswahl + heller Live-Kurs
* Neues **Auswahlfeld „Company“** über die ganze Breite der Karte, mit Dropdown-Pfeil. Die Liste enthält das
  Symbol aus dem Order Ticket, deine offenen Positionen und die Demo-Watchlist; in neueren Streamlit-Versionen
  kannst du zusätzlich einen beliebigen Ticker eintippen (ältere Versionen zeigen nur die Liste).
* Auswahl ist **freiwillig**: mit `— no company (manual) —` trägst du Einstieg und Stop weiter komplett von Hand
  ein, genau wie bisher.
* Nach der Auswahl erscheint der **Live-Kurs in hellem Weiß** (`#F8FAFC`, Tagesveränderung in Grün/Rot) statt im
  dunklen Grau, und der Einstiegspreis folgt ihm, solange *„Use live price as entry“* an ist. Der Stop wird vom
  Order Ticket übernommen, wenn dort für dasselbe Symbol ein Stop-Loss gesetzt ist.
* **„Use in order ticket →“** schreibt jetzt auch das gewählte Unternehmen ins Order Ticket (zusätzlich zu
  Stückzahl, Seite *Buy* und Stop-Loss).

### Pending Orders: echte Limit-Orders
* Das Order Ticket hat einen neuen Schalter **Market / Limit**. Bei *Limit* gibst du den Wunschkurs ein; darunter
  steht, wie weit er entfernt ist („Waits until AAPL falls to 190.00 (−5.00 % from 200.00). Good until you cancel
  it.“). Stop-Loss und Take-Profit beziehen sich dann auf den Limitkurs.
* Die Order wandert in die Karte **Pending orders** unter dem Order Ticket: Symbol, BUY/SELL LIMIT, Stückzahl,
  Limit, aktueller Kurs mit Abstand in %, SL/TP, Zeitpunkt, Status und **Cancel**. Pro Konto bis zu 20 Orders,
  sie bleiben liegen, bis sie ausgeführt oder storniert werden (GTC).
* **Ausführung:** Kauf füllt bei Kurs ≤ Limit, Verkauf bei Kurs ≥ Limit — geprüft im Live-Takt des Monitors
  (alle 20 Sekunden, auch beim Seitenaufruf) und zusätzlich bei jedem 15-Minuten-Botlauf. Gefüllt wird zum
  **besseren** Kurs: steht der Markt schon bei 188, während dein Kauflimit 190 ist, bekommst du 188.
  Stop-Loss / Take-Profit werden beim Füllen automatisch gesetzt, und du bekommst eine Push-/E-Mail-Meldung
  (wenn Bot-Benachrichtigungen an sind).
* Reicht beim Füllen das Cash nicht (oder wurde die Position vorher verkauft), bleibt die Order mit rotem
  Hinweistext liegen, statt still zu verschwinden.
* **Circuit Breaker:** Bei *ACCOUNT BREACHED* lassen sich keine neuen Limit-Orders aufgeben, bestehende
  **Kauf-Limits bleiben geparkt** („Blocked — account breached“), **Verkaufs-Limits füllen weiter** — Risiko
  verringern bleibt immer erlaubt.

### Watchlist: Pre-Market & After-Hours
Die vor- und nachbörslichen Kurse stehen in der Watchlist schon seit v5.0 unter der jeweiligen Zeile (rechts
ausgerichtet, ☀️ / 🌙 + Kurs + Veränderung gegenüber dem regulären Schluss, Quelle: 1-Minuten-Kerzen mit
`prepost=True`). Neu ist nur das **Kürzel PRE / AFTER** neben dem Symbol, damit auf einen Blick klar ist, welche
Session gemeint ist. Drag & Drop und die ↑ / ↓-Sortierung bleiben unverändert.
*Grenze:* Die Zeile erscheint nur, wenn es in der laufenden Extended-Hours-Session wirklich einen Handel gab —
ohne vorbörslichen Umsatz liefert Yahoo keinen Kurs, dann bleibt die Zeile leer.

## Neu in v5.4 (Deutsch)

**Dateien:** hochladen — `app.py`, `backend.py`, `engine.py`, `mock_data.py`, `chart.py`,
`pulse_chart/index.html` (bei den letzten vier ändert sich nur die Versionsnummer, sie müssen aber zusammen
mit den anderen auf 5.4 stehen) — dann *Reboot app*. `pulse_list/index.html` ist unverändert (5.2, steckt
außerdem eingebettet in `chart.py`). Keine neuen Secrets.

### Demo: Zahnrad bündig mit der Kontoauswahl
* Das Zahnrad ist jetzt ein **17-px-Symbol** (gezeichnet statt Emoji, übernimmt die Themenfarbe) ohne
  Innenabstand — es wird nicht mehr vom Rand abgeschnitten, der versteckte Aufklapp-Pfeil nimmt keinen Platz
  mehr weg.
* Box und Auswahlfeld „Main account · $25,000“ haben **dieselbe Höhe (44 px), dieselbe Rahmenstärke und
  denselben Radius**; Ober- und Unterkante liegen exakt auf einer Linie.

### Demo: 8 Kennzahlen im festen 4 × 2-Raster
* Raster `repeat(4, 1fr)` mit 12 px Abstand — alle acht Kacheln gleich breit, hoch, gleicher Rahmen und Radius
  (auf dem Handy 2 × 4).
* **Win rate:** profitable geschlossene Trades ÷ alle geschlossenen Trades des Kontos (jeder Verkauf / jede
  Short-Eindeckung mit Ergebnis in der Trade History; Teilverkäufe zählen einzeln). Grün ab 50 %, darunter rot,
  0,0 % ohne Trades. Rechts klein „3 / 5“.
* **Risk-reward:** `1 : X.XX` = durchschnittlicher Gewinner ÷ durchschnittlicher Verlierer (rechts klein
  „Ø $110 / $75“). Ohne geschlossene Trades `1 : 0.00`, nur Gewinner bisher `1 : —`. Grün ab 1,0.
* Beide Werte sind kontoabhängig und ändern sich sofort, wenn ein Trade von Hand, per Stop-Loss oder
  Take-Profit geschlossen wird.

### Demo: linke Spalte unter „Manage bots →“ (zwei Karten, 16 px Abstand)
**Position size (Risiko- & Positionsrechner)**
* Schalter **„Use order-ticket price & stop“** (Standard an): Einstieg = Live-Kurs des Symbols im Order
  Ticket, Stop = dessen Stop-Loss (wenn eingeschaltet) — dann schreibgeschützt. Aus: beide Felder frei.
  Einstieg und Stop stehen nebeneinander, damit die Spalte kurz bleibt.
* **Max. Risiko pro Trade:** `% of equity` (Standard 1,0 %) oder fester Betrag in Kontowährung.
* Ausgabe live: **Positionsgröße** (Stück; Krypto mit 4 Nachkommastellen), **Positionswert**, **Risikobetrag**
  (+ % des Kontos) und Stop-Abstand. Reicht das freie Cash nicht, wird die Größe darauf begrenzt (mit Hinweis).
  EUR-Konten rechnen US-Werte mit dem EUR/USD-Kurs um.
* **„Use in order ticket →“** trägt Stückzahl, Seite *Buy* und den Stop-Loss (Schalter an) ins Order Ticket ein.

**Risk & exposure**
* **Open risk:** um wie viel das Konto fällt, wenn jeder Stop ab dem aktuellen Kurs ausgelöst wird (Betrag und
  % des Kontos). Positionen ohne Stop werden gelb gesondert genannt („ungeschützt“).
* **Buying power:** freies Cash plus Balken „gebunden vs. frei“ (Auslastung in %).

**🚨 Prop-Firm Circuit Breaker (Verlustlimit)**
* Pro Konto: Schalter an/aus, Zeitraum **Weekly** (ab Montag 00:00) oder **Monthly** (ab dem 1.), Limit als
  **fester Betrag** oder **% des Startkapitals**. Jedes Konto — auch jedes neue — startet mit **5.000** in seiner
  Währung, Schalter an.
* **Periodenverlust = realisierte Ergebnisse im Zeitraum + offener P/L aller Positionen.** Fortschrittsbalken
  „$1,240 / $5,000“: grün, ab 70 % gelb/orange, ab 90 % rot.
* Wird das Limit erreicht → **ACCOUNT BREACHED – loss limit exceeded**: rotes Banner im Risk-Panel und über dem
  Order Ticket, **alle Bots des Kontos sofort pausiert** (auch im Hintergrund beim nächsten 15-Minuten-Lauf;
  im Bot-Bereich steht „by circuit breaker“), **Buy/Sell und „Place order“ deaktiviert**, Bots lassen sich nicht
  wieder starten, neue Bots werden pausiert angelegt. Push-/E-Mail-Hinweis, falls Bot-Benachrichtigungen an sind.
* Die Sperre bleibt, auch wenn sich der Kurs erholt — bis du das Limit **ausschaltest**, **erhöhst** (es wird
  sofort neu geprüft) oder **„Account reset / start over“** drückst (Häkchen zur Bestätigung; löscht Positionen
  und Historie, die Limit-Einstellungen bleiben, Bots bleiben pausiert).
* Offene Positionen behalten ihre Stop-Loss-/Take-Profit-Orders und können in der Positionstabelle weiterhin
  geschlossen werden (Risiko verringern bleibt erlaubt).

### Hinweise
* UI-Texte sind wie im Rest der App englisch („Use in order ticket →“, „Account reset / start over“).
* Im Repo liegt die Anleitung derzeit als `README_1.md`; diese `README.md` kann sie ersetzen.

## Neu in v5.3 (Deutsch)

**Dateien:** alle hochladen — `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`,
`pulse_chart/index.html`, `pulse_list/index.html` — dann *Reboot app*. Keine neuen Secrets. Die
Drag-&-Drop-Verbesserungen aus v5.2 sind in diesem Paket enthalten (in deinem Repo lag noch 5.1).
Tipp: per *Add file → Upload files* (Drag & Drop) hochladen, nicht in den Web-Editor einfügen.

### Top Movers: breites Screening inkl. Pre-Market, Small-/Mid-Caps und Europa
* **Ganzes handelbares Universum statt nur Large-Caps:** Yahoos Screener *day gainers / losers*, *most
  actives*, *small-cap gainers*, *aggressive small caps*, *growth technology*, *most shorted* plus eigene
  Abfragen **ohne Mindest-Börsenwert und ohne 5-$-Grenze** (USA: NYSE / NASDAQ / AMEX · Europa: DE, GB, FR, NL,
  IT, ES, CH, Skandinavien, BE, AT, IE, PT, PL) plus die Werte, die bei Yahoo gerade *trending* sind.
  Varianten, Rechte, Units und ETFs werden aussortiert.
* **Vor- und nachbörslich:** `preMarketChangePercent` / `postMarketChangePercent` aus den Yahoo-Kursdaten
  (fehlen sie, werden sie aus den 1-Minuten-Kerzen mit Pre/Post-Market ergänzt). Bewegungen wie +20 % bis
  +400 % oder −20 % bis −60 % werden nicht mehr als „Datenfehler“ verworfen.
* **Sortierung strikt nach der größten absoluten Veränderung** der gewählten Sitzung, bei Gleichstand nach
  relativem Volumen (heutiges Volumen ÷ 3-Monats-Schnitt). Umschalter **Session / ☀️ Pre-market / 🌙
  After-hours** — automatisch passend zur Uhrzeit vorausgewählt.
* **Filter:** Markt (alle / USA / Europa), Größe (Small < 2 Mrd. $, Mid 2–10 Mrd. $, Large > 10 Mrd. $) und
  relatives Volumen (≥ 1,5× / 3× / 5×) für echte High-Momentum-Werte. Chips zeigen *small*, *penny* (< 1 $) und
  *EU*; in der Sitzungsansicht steht die vor-/nachbörsliche Bewegung zusätzlich darunter.
* **Live:** Das Panel lädt sich alle 90 Sekunden selbst neu (nur das Panel, nicht die Seite).
* *Ehrliche Grenzen:* Yahoo bietet keinen Screener, der direkt nach Pre-Market-Prozent sucht. Vorbörsliche
  Kandidaten kommen deshalb aus den Screenern (inkl. Small-Caps) und den Trending-Werten — ein Wert, der
  vorbörslich aus dem Nichts explodiert, erscheint, sobald er bei Yahoo trendet. Das Pre-Market-Volumen ist
  nicht Teil der Screener-Daten, der Volumenfilter gilt daher für die reguläre Sitzung.

### Earnings-Kalender: zusätzlich Magnificent 7 + 10 Mega-Caps
Neben deinen Watchlist-Werten (★) erscheinen immer: **Magnificent 7** (AAPL, MSFT, GOOGL, AMZN, NVDA, META,
TSLA — Schildchen *M7*) und **10 weitere Mega-Caps** (AVGO, TSM, BRK-B, LLY, JPM, WMT, V, ORCL, MA, NFLX —
Schildchen *MEGA*). Auch bei leerer Watchlist ist der Kalender damit nie leer.

### Filter nur noch bei Strategie 1
Regime-Filter und alle anderen Zusatzfilter gelten jetzt **nur für die erste Strategie** (🤖 Pattern breakout).
Bei Double Donchian, Flag, Ichimoku und WaveTrend entfallen überall:
* **Short Term:** keine Regime-Box, kein Vorfilter „Kurs ≥ 3 $ / Tagesplus / Börsenwert ≥ 300 Mio. $“, keine
  15-Minuten-Bestätigung. Gescannt werden die 150 liquidesten Aktien (nach Handelsvolumen in $) — die Strategie
  sucht ihr eigenes Setup in allen. Statt der 15-Min-Spalte steht dort die Richtung (LONG / SHORT).
* **Bots:** kein Regime-Filter, keine 15-Min-Bestätigung, kein Mindest-Bestätigungsscore, kein Mindest-
  Chance/Risiko — die Optionen erscheinen im Formular nur noch für die AI-Strategie. Bestehende Bots
  ignorieren alte Einstellungen dazu automatisch.
* **Backtest:** der Block „Confirmations“ (Wochentrend, ADX, Marktregime) ist weg.
* Die Bestätigungs-Checks (Trend, Indikatoren, Formationen) bleiben als **reine Information** sichtbar.

### Ichimoku: nur Gold, Silber, Öl und Bitcoin — Long **und** Short
* **Short Term** zeigt eine feste Marktübersicht: Gold (GC=F), Silber (SI=F), Rohöl WTI (CL=F), Bitcoin
  (BTC-USD). Jeder Markt steht immer in der Liste — ohne Signal mit dem Hinweis, wo der Kurs zur Wolke steht und
  was er für Long bzw. Short bräuchte.
* **Shorts überall:** Scan, Bots und Backtest — gespiegelte Regeln (Schluss unter der Wolke, Tenkan unter Kijun,
  Chikou darunter, Ausstieg beim Schluss über dem Kijun; Kijun-Bounce auch short).
* **Markt-Presets automatisch:** Gold/Silber 9/26/52 mit Wochen-Wolken-Regel (Long nur bei Wochenschluss über,
  Short nur unter der Wochen-Wolke), Öl 9/26/52 mit ADX ≥ 20, Bitcoin mit wählbarer Variante 9/26/52 · 10/30/60 ·
  20/60/120 (Standard 10/30/60). Diese Marktregeln sind jetzt **Teil der Ichimoku-Regeln selbst** (kein
  allgemeiner Filter mehr) und im Backtest abschaltbar. Hinweis: Gold/Silber waren in deiner ursprünglichen
  Vorgabe „nur long“ — jetzt handeln sie beide Richtungen; im Backtest kannst du „Long only“ wählen.
* **Backtest:** Wahl der Ichimoku-Strategie setzt sofort das Gold-Preset inkl. Instrument; jedes Preset
  wechselt das Instrument mit (GC=F, SI=F, CL=F, BTC-USD). Der Bitcoin-Varianten-Vergleich bleibt.

### Neu: deine Variante als zweiter Ichimoku-Modus — „Staged Kumo entry“
1. **Stufe 1 · in die Wolke:** Schluss wieder innerhalb der Wolke, nachdem der Kurs darunter geschlossen hatte
   → **⅓ der Position** (Short: Eintritt in die Wolke von oben).
2. **Stop für Stufe 1:** knapp unter der Wolkenunterkante (Short: über der Oberkante) — raus, wenn ein Schluss
   wieder aus der Wolke fällt.
3. **Stufe 2 · aus der Wolke:** Schluss über der Wolke (Short: darunter) → die **restlichen ⅔** (fehlte Stufe 1,
   werden nur die ⅔ eröffnet).
4. **Trailing:** Nach Stufe 2 laufen beide Teile mit dem Kijun — raus beim ersten Schluss auf der anderen Seite.
Umschaltbar in Short Term, im Bot-Formular und im Backtest. Der Backtest führt beide Teile als eigene Trades
(Seite „LONG · ⅓ / ⅔“), Ausstiegsgrund „Back out of the cloud“ bzw. „Close beyond Kijun“ — so siehst du direkt,
ob deine Staffelung auf Gold, Silber, Öl und Bitcoin besser abschneidet als der klassische Kumo-Breakout.

### Demo-Konto: Shorts, Futures, Bitcoin-Bruchteile
* **Short-Positionen** (für den Ichimoku-Bot): Der Positionswert wird als Sicherheit reserviert, fällt der Kurs,
  steigt der Gewinn. Stop liegt darüber und wird nur **nach unten** nachgezogen (Kijun bzw. Wolkenkante).
  Positionen und Historie zeigen *SHORT* / *COVER*, „Cover all“ schließt eine Short-Position von Hand. Shorts
  werden vom Bot verwaltet (das SL/TP-Formular gilt für Long-Positionen).
* **Stufe 2 wird zur bestehenden Position nachgekauft**, der gemeinsame Stop geht nie zurück.
* **Gold-, Silber- und Öl-Futures** sind handelbar (in Einheiten zum Futures-Preis — keine Kontraktgrößen oder
  Hebel), **Bitcoin in Bruchteilen** (4 Nachkommastellen), damit der Bot bei hohen Kursen überhaupt kaufen kann.
* Für die Wochen-Wolke laden Ichimoku-Bots jetzt 5 Jahre Tagesdaten (1 Jahr reichte dafür nicht).

**Getestet:** Meine frühere Testumgebung war nach einer Pause weg — ich habe sie neu aufgebaut. Streamlit,
Plotly und yfinance laufen dabei als Attrappen; die echte App wird pro Seite komplett durchlaufen (Markets,
Short Term, Demo, Backtest). Geprüft u. a.: Movers-Sortierung strikt nach |%|, automatische Pre-Market-Ansicht,
Markt-/Größen-/RVOL-Filter, Aussortieren von Varianten/Units/ETFs, Duplikate mit Pre-Market-Feld; Earnings mit
M7/MEGA/★ und leerer Watchlist; Ichimoku-Übersicht mit vier Märkten in beiden Modi; Donchian ohne Regime vs. AI
mit Regime; Bot-Formular je Strategie und Anlegen eines Ichimoku-Bots; Demo-Short mit Stufe-2-Nachkauf, Stop nur
nach unten, Eindecken mit korrekter Abrechnung; Backtest beider Modi long/short/beide inkl. Stufen und
Varianten-Vergleich. Ehrliche Grenzen: Die Yahoo-Abfragen sind gegen nachgebildete Antworten getestet (die
Feldnamen gegen die yfinance-Dokumentation geprüft), nicht gegen Live-Daten — Netzwerk ist hier gesperrt. Kurse
in den Tests sind synthetisch. Alle Module kompilieren auf Python 3.11.

---

## Neu in v5.2 (Deutsch)

**Dateien:** alle hochladen — `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`,
`pulse_chart/index.html`, **`pulse_list/index.html` (neu, 5.2)** — dann *Reboot app*. Keine neuen Secrets.
Tipp: per *Add file → Upload files* (Drag & Drop) hochladen, nicht in den Web-Editor einfügen.

### Watchlist-Sortierung per Drag & Drop: exakte Verschiebung statt Index-Tausch
Gilt für **beide** sortierbaren Listen — die Watchlist (Markets) und die Demo-Watchlist.

* **Exakte Array-Verschiebung (splice):** Beim Loslassen wird das gezogene Unternehmen an seinem alten
  Index entfernt und genau am Ziel-Index eingefügt —
  `const [moved] = list.splice(fromIndex, 1); list.splice(toIndex, 0, moved);`.
  Steht AAPL unter NVDA und wird eine Position nach oben über NVDA gezogen, rutscht NVDA genau eine Position
  nach unten. Von Platz 5 auf Platz 1 rücken die Plätze 1–4 um genau eine Stelle nach unten, alles danach
  bleibt unverändert. Die ↑/↓-Pfeile und die Tastatur nutzen dieselbe Funktion.
* **Was vorher falsch war:** Das Ziel wurde aus der *Mitte der gezogenen Zeile* berechnet, nicht aus der
  Position des Zeigers. Wer eine Zeile am Rand anfasste, landete eine Position daneben; zusätzlich rutschten
  die anderen Zeilen während des Ziehens weg, sodass die Zeile unter dem Zeiger nicht die Ziel-Zeile war.
  Im Test: 5 → 1 landete auf Platz 2, 1 → 0 bewirkte nichts, 0 → 4 landete auf Platz 3.
* **Jetzt gilt:** Ziel = die Zeile **unter dem Zeiger/Finger** — egal, wo man die Zeile angefasst hat. Die
  anderen Zeilen bleiben beim Ziehen still stehen.
* **Deutliche Drop-Zone-Vorschau:** Eine blaue Einfügelinie zeigt während des Ziehens exakt die Lücke, in die
  das Unternehmen einsortiert wird (beim Hochziehen über der Ziel-Zeile, beim Runterziehen darunter), links
  mit der **neuen Platznummer**. Die gezogene Zeile schwebt mit Schatten am Zeiger, ihr alter Platz bleibt
  blass und gestrichelt sichtbar. Über dem eigenen Platz verschwindet die Linie (= keine Änderung).
* **Abbrechen:** `Esc` während des Ziehens bricht ab, ebenso wenn der Browser die Geste übernimmt
  (z. B. Scrollen auf dem iPad).
* **Lange Listen:** Am oberen/unteren Rand scrollt die Liste von selbst weiter, auch wenn der Zeiger
  stillsteht — gleich schnell auf jedem Gerät.
* **Kein Zurückspringen:** Kommt direkt nach dem Verschieben noch eine verspätete Darstellung mit der alten
  Reihenfolge an (z. B. von einem laufenden Kurs-Update), bleibt die neue Reihenfolge stehen; frische Kurse
  werden trotzdem übernommen. Kurs-Updates, die *während* des Ziehens eintreffen, werden nach dem Loslassen
  angewendet.
* **Gespeichert wird ebenfalls exakt:** Die Verschiebung wird auch auf der gespeicherten Liste per ID
  nachvollzogen. Wurde in der Zwischenzeit (z. B. in einem anderen Tab) ein Unternehmen hinzugefügt oder
  entfernt, bleibt es an seinem Platz — früher wäre es ans Ende gerutscht.
* **Upload-sicher:** Liegt im Repo noch eine ältere `pulse_list/index.html` (z. B. 5.0), nutzt die App
  automatisch die in `chart.py` eingebettete neue Version. Die eingebettete Kopie steht weiterhin in kurzen
  Zeilen (max. 124 Zeichen).

**Getestet:** Im echten Browser alle 64 Start→Ziel-Kombinationen für beide Listen mit gemischten
Zeilenhöhen (☀️/🌙-Zeile), zufälligen Greif- und Ablagepunkten (Rand/Mitte, Logo/Name/Griff) — jede
Verschiebung exakt gleich splice; deine beiden Beispiele; Linie + Platznummer für jede Ziel-Zeile;
Esc und Gesten-Abbruch; 16-Zeilen-Liste mit Auto-Scroll über den sichtbaren Bereich hinaus; Touch
(Gedrückthalten + Ziehen); helles Design; verspätete Darstellungen. Dazu die bisherige Listen-Suite,
66 Szenarien in 4 Modi (u. a. exakte Verschiebung für jede Listenlänge ≤ 7 und jedes Start/Ziel-Paar,
gleichzeitiges Hinzufügen/Entfernen, Haupt- und Demo-Liste, alte Ordner-Datei) und 28 Chart-Schritte.
Alle Module kompilieren auf Python 3.9 und 3.11.

---

## Neu in v5.1 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`, `pulse_chart/index.html`
hochladen, dann *Reboot app*. `pulse_list/index.html` ist unverändert (bleibt auf 5.0). Keine neuen Secrets.

### Zwei neue Strategien — in Short Term, bei den Bots und im Backtest

**☁️ Ichimoku — Kumo-Breakout mit Kijun-Trail (und Kijun-Bounce)**
1. *Einstieg (Breakout, alles auf Schlusskursbasis):* Schlusskurs **über der Wolke** (über Senkou A **und**
   B), **Tenkan über Kijun**, **Chikou-Bestätigung** (heutiger Schluss über dem Schluss vor 26 Kerzen) und
   **nicht hinterherlaufen**: höchstens 2 ATR Abstand zum Kijun.
2. *Stop:* anfangs knapp unter dem Kijun (Kijun − 0,25 ATR).
3. *Trailing/Ausstieg:* Kein Kursziel — raus, **sobald ein Schlusskurs unter dem Kijun liegt** (verkauft wird
   zur nächsten Eröffnung, wie es auf Tageskerzen realistisch ist).
4. *Zweiter Einstieg (Kijun-Bounce):* Läuft der Trend (Kurs über der Wolke, Chikou frei), wird der Rücksetzer
   an den Kijun gekauft, sobald der Kurs **wieder über dem Tenkan schließt**. Abschaltbar.
5. *Markt-Presets* (im Bot-Formular und im Backtest wählbar): **Gold/Silber** 9/26/52, nur long, zusätzlich
   Wochenschluss über der Wochen-Wolke · **Öl** 9/26/52 long **und** short (gespiegelt), ADX > 20 ·
   **Bitcoin**: drei Varianten 9/26/52, 10/30/60, 20/60/120 — der Backtest kann sie **direkt vergleichen**
   (Checkbox „Compare the three Bitcoin variants“): gleiche Regeln, gleicher Zeitraum, eine Tabelle mit
   Trades/Trefferquote/Netto/Buy & Hold/Drawdown/Profitfaktor. Genau das, was deine zitierten Tests sagen:
   das Signal allein reicht nicht, der Vorteil kommt aus Filter, Stop und Trailing — hier sieht man es.
6. *Hinweis zu den Bots:* Der Bot zieht den Stop täglich auf den aktuellen Kijun nach (nur nach oben, nie
   runter) — eine Sicherheits-Vereinfachung der exakten „Schluss unter Kijun“-Regel. Der **Backtest**
   rechnet die exakte Regel.

**🌊 WaveTrend — Crosses + Volumen + Nadaraya-Watson-Envelope** (Design war mir überlassen; so funktioniert
sie am besten):
1. *Ausverkauf:* WaveTrend (10/21) unter −53 — es wird nur der ausgewaschene Rücksetzer gekauft, nicht jedes
   Kreuz.
2. *Am Band:* Der Kurs berührt oder unterschreitet das **untere Nadaraya-Watson-Band** (Gauß-Kernel,
   ±2,5-faches mittleres Fehlerband). Wichtig: **Endpoint-Methode ohne Repainting** — jede Kerze wird nur aus
   ihrer eigenen Vergangenheit gerechnet; das klassische NW-Envelope malt rückwirkend um und würde im
   Backtest schummeln (im Test nachgewiesen: Werte ändern sich nicht, wenn Zukunftsdaten dazukommen).
3. *Auslöser:* WaveTrend kreuzt über seine Signallinie **und** das Volumen liegt mindestens 1,2× über dem
   20-Tage-Schnitt — ohne Volumen kein Kauf.
4. *Ziele:* TP1 an der **NW-Mittellinie** (40 % Verkauf, Stop auf Einstand), Rest läuft zum oberen Band.
5. *Stop:* unter dem Tief des Rücksetzers; Ausstieg außerdem, wenn WaveTrend über null wieder nach unten
   kreuzt.

Beide Strategien haben wie die bisherigen: eigene Erklärkarte mit Regel-Schritten, Scan-Tabelle mit
Status (Breakout/Armed/Kijun-Bounce …), bewertete Bestätigungs-Checks (Multi-Timeframe, Indikatoren,
Formationen, Markt), eigene **Chart-Einzeichnung** (Wolke, Tenkan/Kijun, Breakout-/Bounce-Punkte bzw.
NW-Envelope, Mittellinie, Cross-Punkte, Stop) und volle **Bot**- und **Backtest**-Unterstützung
(im Backtest-Chart inklusive Wolke bzw. NW-Bändern und Exit-Gründen „Close below the Kijun“ /
„WaveTrend cross down“).

### Aufgeräumte, professionellere Charts
* **Kerzen zuerst:** Levels, Zonen und Formations-Flächen liegen jetzt **hinter** den Kerzen (zweistufiges
  Zeichnen) — keine zugedeckten Kerzen mehr. Linien von Formationen sind dünner gedeckelt und leicht
  transparent.
* **Dezentere Levels:** Support/Resistance feiner gestrichelt und blasser, Zonen-Füllungen und
  Stärke-Balken deutlich zurückgenommen.
* **Keine Label-Überlappung:** Alle Beschriftungen (Levels, Formationen, Strategie-Linien) laufen durch
  eine Spur-Verwaltung, die sie automatisch versetzt statt übereinander zu stapeln.
* **Bei aktiver Strategie-Zeichnung** wird zusätzlich entrümpelt: höchstens 3 starke Zonen, nur offene
  Order-Blocks — die Strategie steht im Vordergrund.

**Getestet:** 65 Szenarien in 4 Modi (online/offline × neue/alte Streamlit-Version) — darunter die
Ichimoku-Mathematik gegen Handrechnung (Wolken-Verschiebung ohne Blick in die Zukunft), alle vier
Einstiegsregeln einzeln, Bounce an- und abschaltbar, ATR-Abstandsregel, Presets inkl. automatischem
Umschalten der Felder, der Bitcoin-Varianten-Vergleich, die exakte Kijun-Exit-Regel im Backtest
(Schluss unter Kijun → Verkauf zur nächsten Eröffnung), Short-Spiegelung, Wochen-Wolken-Filter nur mit
abgeschlossenen Wochen, NW-Repaint-Freiheit, Volumen-Pflicht beim WaveTrend-Kauf und die kompletten
Bot-Abläufe (Kauf mit Kijun-Trail, Stop-Anhebung mit Log-Eintrag, Verkauf als „Trailing Stop“).
Dazu 28 Chart-Schritte im echten Browser und Render-Checks der neuen Zeichnungen („label problems:
none“). Ehrliche Einschränkungen: Der Plotly-Backtest-Chart läuft in der Testumgebung nur gegen eine
Attrappe, und die Chart-Screenshots nutzen synthetische Kursdaten.

---

## Neu in v5.0 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`, `pulse_chart/index.html` **und
`pulse_list/index.html`** hochladen (die alte `pulse_list`-Datei unbedingt ersetzen — liegt dort eine alte
Version, wird sie weiter benutzt), dann *Reboot app*. Keine neuen Secrets.
Neu: Die Listen-Komponente ist jetzt zusätzlich **in `chart.py` eingebaut** — fehlt der Ordner `pulse_list`
komplett, schreibt die App sie beim Start selbst. Drag & Drop funktioniert also in jedem Fall, und der alte
Hinweis „Upload pulse_list/index.html …“ ist entfernt.

### Vor- und nachbörsliche Kurse (wie TradingView)
* **Überall:** Markets (Indexkarten, großer Kurs-Kopf, Top Movers, Watchlist), Short Term (Tabelle und
  Detailkarte), Valuation-Kopf, Long Term (neue Spalte „Pre / post market“ bei den Cheap Companies) und
  Demo Account (Demo-Watchlist, Open Positions unter „Last“, Order Ticket neben „Price“).
* **Kennzeichnung:** ☀️ (gelb/orange) = Pre-Market 04:00–09:30 ET · 🌙 (blau/violett) = After-Hours ab
  16:00 ET. Nachts und am Wochenende bleibt der letzte 🌙-Kurs stehen — wie bei TradingView.
* **Darstellung:** Der reguläre Kurs steht groß darüber bzw. daneben (im Kopf mit „At close“, solange die
  Börse zu ist); die ☀️/🌙-Zeile zeigt Kurs + absolute und prozentuale Veränderung **gegenüber dem regulären
  Schlusskurs**, grün bei +, rot bei −, immer einzeilig (kein Umbruch, keine Überlappung, 12 px Abstand,
  in Tabellen rechtsbündig). Fährt man mit der Maus darüber, steht dort auch die Uhrzeit des letzten
  außerbörslichen Trades (ET).
* **Datenquelle:** letzte 1-Minuten-Kerze inklusive Pre/Post (höchstens ~60 s alt). Ausreißer über ±60 %
  werden verworfen; ohne Daten erscheint einfach keine Zeile. Mock-Kurse bekommen nie eine ☀️/🌙-Zeile.
* **Wichtig:** Gehandelt (Demo-Orders, SL/TP) wird weiterhin zum regulären bzw. Live-Kurs — die
  ☀️/🌙-Zeilen sind reine Anzeige.

### Tagesprozente repariert
Bisher konnten Kurs und Tagesprozent aus verschiedenen Quellen stammen — am deutlichsten im großen
Kurs-Kopf: Dort kam der Kurs nachbörslich schon vom After-Hours-Handel, der Prozentsatz aber vom regulären
Tag (oder umgekehrt). Jetzt gilt überall: **Kurs und Prozent sind immer dasselbe Paar** (letzter regulärer
Kurs ÷ Vortagesschluss), auch in den Short-Term-Zeilen (dort kommt das Prozent jetzt aus denselben
Tageskerzen wie der Kurs statt aus dem älteren Börsen-Screener). Alles Außerbörsliche steht getrennt in der
☀️/🌙-Zeile.

### Watchlist: flüssiges Sortieren
* **Ziehen am ganzen Eintrag:** Festhalten direkt auf Logo, Name oder Kurs — mit der Maus beginnt das
  Ziehen nach 6 px Bewegung (ein normaler Klick öffnet weiter den Chart), auf iPad/Handy mit
  **Gedrückthalten (~0,3 s) und Ziehen**; schnelles Wischen scrollt die Liste ganz normal. Der ⋮⋮-Griff
  zieht wie bisher sofort.
* Beim Ziehen hebt sich die Zeile mit Schatten und leichtem Zoom ab, die anderen Einträge weichen per
  Transition aus; am Rand scrollt die Liste automatisch weiter.
* **↑ / ↓ ohne Seiten-Reload:** Die Pfeile (und das Ziehen) sortieren nur noch innerhalb der Liste um und
  speichern die Reihenfolge **still** — die Seite wird nicht mehr neu aufgebaut und springt nicht mehr an
  den Anfang. Gespeichert wird sofort (Profil bzw. Demo-Konto) und bleibt beim Neuladen erhalten.
* Gilt für die Markets-Watchlist und „My demo watchlist“ im Demo Account.

### Demo Account: Zahnrad-Button
Der ⚙-Button neben dem Konto-Dropdown ist jetzt ein sauberes 44 × 44-px-Quadrat auf Höhe des Dropdowns,
das Zahnrad exakt zentriert (kein gequetschter Rand, der Dropdown-Pfeil im Button ist ausgeblendet).

**Getestet:** 63 Szenarien in 4 Modi (online/offline × neue/alte Streamlit-Version) — darunter
Seansphasen-Logik, ☀️/🌙 auf jeder Seite, Prozent-Konsistenz im Kopf und in den Short-Term-Zeilen,
stilles Sortieren ohne Rerun und die Byte-Gleichheit der eingebetteten Komponente; Browser-Test der Liste
(Ziehen am Logo/Namen mit Maus und Touch-Longpress, Wisch-Scroll bleibt erhalten, Klick öffnet weiter,
☀️/🌙-Zeile ohne Überlappung bei 330–760 px); 28 Chart-Schritte; Abstands-Tests. Die ☀️/🌙-Zeilen in den
Screenshots sind simulierte Daten (die Testumgebung hat keinen Live-Pre/Post-Feed).

---

## Neu in v4.9 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`, `pulse_chart/index.html` hochladen,
dann *Reboot app*. `pulse_list/index.html` ist unverändert. Keine neuen Secrets.

### Wählbare Strategien
In **Short Term**, bei den **Bots** und im **Backtest** kann jetzt gewählt werden, welche Strategie läuft:
*Pattern breakout* (die bisherige AI-Suche), **Double Donchian** und **Flag after a strong advance**.

**Doppelter Donchian (120 / 20)**
1. *Richtung:* Ein Schlusskurs über dem 120-Tage-Hoch gibt die Long-Seite frei. Sie bleibt frei, bis der
   Kurs unter dem 120-Tage-Tief schließt.
2. *Einstieg:* Solange die Richtung frei ist, wird jeder Schlusskurs über dem 20-Tage-Hoch gekauft.
3. *Stop:* am 20-Tage-Tief. Er wird täglich auf das neue 20-Tage-Tief angehoben und fällt nie.
4. *Ausstieg:* kein Kursziel – die Position endet, wenn der Kurs auf das nachgezogene 20-Tage-Tief fällt.

**Flagge nach starkem Anstieg**
1. *Anstieg:* mindestens 30 % in höchstens 40 Handelstagen (der „Mast“).
2. *Flagge:* 5 bis 15 enge Kerzen. Von mir ergänzt, weil die Definition das offen ließ: Rücksetzer höchstens
   25 % vom Hoch, höchstens die Hälfte des Anstiegs wird abgegeben, die Kerzen sind kleiner als im Anstieg.
3. *Einstieg:* Schlusskurs über dem Basis-Hoch mit mindestens 1,5-fachem Volumen (20-Tage-Schnitt).
4. *Stop:* knapp unter dem Tief der Flagge.
5. *Ausstieg (von mir ergänzt):* 40 % bei 2R, der Stop geht dann auf den Einstieg; der Rest läuft bis zum
   „Measured Move“ (Höhe des Anstiegs, ab dem Ausbruch gerechnet).

Alle Kanäle und Niveaus werden nur aus *früheren* Kerzen berechnet (kein Blick in die Zukunft).

### Short Term
* Unter „AI Opportunities“ gibt es den Umschalter **Strategy**. Jede Strategie zeigt ihre Regeln als
  nummerierte, farbige Schritte – in denselben Farben wie die Linien im Chart.
* Die Liste zeigt frische Ausbrüche zuerst (BREAKOUT / RETEST), danach Titel, die auf den Auslöser warten
  (ARMED = Richtung frei, 20-Tage-Hoch noch nicht gebrochen; FORMING = Flagge läuft noch) und laufende
  Trend-Trades (IN TREND).
* **Im Chart eingezeichnet:** beim Donchian das 120-Tage-Hoch (violett), das 20-Tage-Hoch (gelb, Kauf-
  Auslöser), das 20-Tage-Tief (rot gestrichelt, Stop), die grün hinterlegte Phase „Richtung frei“ sowie
  Kauf- und Verkaufspunkte der Regel; bei der Flagge der Mast, die Flaggen-Box, die Auslöse-Linie und der
  Stop. Jedes Teil trägt eine Beschriftung.
* **Confirmation checks:** jede Chance bekommt eine Prüfliste mit Punktzahl (0–100). Geprüft werden
  mehrere Zeitebenen (Wochentrend, Lage in der 52-Wochen-Spanne, Tagestrend, 15-Minuten-Chart), Indikatoren
  (ADX, RSI, MACD, Ausbruchs-Volumen, relative Stärke zum S&P 500, Stop-Abstand), Formationen und
  Niveaus (weitere Chartmuster, Platz bis zum nächsten Widerstand, Qualität der Flagge bzw. Alter des
  Trendsignals) und das Marktumfeld. Der Score der Liste = 40 % Setup-Qualität + 60 % Bestätigung.
  Die Prüfliste gibt es auch bei der bisherigen AI-Suche (eingeklappt; deren Score bleibt unverändert).

### Bots
* Im Formular „New bot“ stehen die beiden Strategien zur Auswahl; die Regeln werden direkt angezeigt.
* Neu: **Min. confirmation score** – der Bot kauft nur, wenn die Prüfliste diese Punktzahl erreicht.
* Der Donchian-Bot kauft ohne Kursziel, hebt den Stop täglich auf das neue 20-Tage-Tief an und verkauft
  nur dort (in der History „Trailing Stop triggered“). Mindest-R/R, ATR-Trailing und maximale Haltedauer
  gelten für ihn nicht. Der Flaggen-Bot kauft nur Ausbrüche mit Volumenschub.

### Backtest
* Neuer Schritt **Strategy**: „Custom rules“ (wie bisher), „Double Donchian“ oder „Flag after a strong
  advance“. Alle Parameter sind einstellbar (Kanal-Längen, Mindest-Anstieg, Flaggen-Länge, Volumen, erstes
  Ziel), beim Donchian auch Long / Short / beides.
* **Confirmations** zum Zuschalten: Wochen-Aufwärtstrend, ADX ≥ 20, S&P 500 über dem 50-Tage-EMA – so
  lässt sich prüfen, ob eine Bestätigung das Ergebnis wirklich verbessert.
* Im Preis-Chart werden die Kanäle bzw. Mast und Flagge mitgezeichnet; die Trade-Liste nennt den
  Ausstiegsgrund (Channel stop, Target 1 · 40 %, Target 2, Break-even stop). Gespeicherte Strategien
  merken sich Strategie und Parameter.

**Getestet:** 61 Szenarien in 4 Modi (online/offline × neue/alte Streamlit-Version), darunter Regeln,
Zustände, Stop-Nachziehen, Bot-Kauf und -Verkauf sowie Backtests beider Strategien; die Zeichnungen wurden
im echten Chart im Browser gerendert (keine überlappenden Beschriftungen); Abstands-Test der neuen Blöcke bei
1100 / 420 / 330 px. Nicht im Browser prüfbar war hier das Plotly-Preisdiagramm des Backtests (Plotly ist in
meiner Testumgebung nicht installiert) – es ist nur über die Test-Attrappe abgedeckt.

---

# Pulse — Market Dashboard (Streamlit) · v4.8

## Neu in v4.8 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py`, `pulse_chart/index.html` und
**neu: der Ordner `pulse_list` mit der Datei `index.html`** (auf GitHub: *Add file → Create new file*, als Namen
`pulse_list/index.html` eingeben und den Inhalt einfügen, oder den Ordner hochladen) — dann *Reboot app*.
Keine neuen Secrets. Fehlt `pulse_list/index.html`, funktionieren die Watchlists weiter mit ↑ / ↓-Pfeilen
und zeigen einen Hinweis zum Hochladen.

### Watchlist: eigene Reihenfolge
* **Drag & Drop** über den dezenten Griff **⋮⋮** links neben Logo/Ticker – mit der Maus und auf dem Handy
  per Finger. Die anderen Zeilen rücken beim Ziehen sichtbar zur Seite; am oberen/unteren Rand scrollt die
  Liste automatisch weiter.
* **Kompakte Pfeile ↑ / ↓** rechts in jeder Zeile verschieben einen Eintrag um genau eine Position (oben bzw.
  unten ausgegraut). Tastatur: Griff anklicken, dann ↑ / ↓ / Pos1 / Ende.
* Gilt für die **Watchlist in Markets** (Klick auf Name/Preis öffnet weiterhin den Chart) und die
  **Demo-Watchlist** (pro Konto, mit × zum Entfernen).
* **Sofort gespeichert:** Hauptliste im Profil (eingeloggt → dauerhafter GitHub-Speicher, sonst in der
  Sitzung), Demo-Liste im jeweiligen Demo-Konto. Die Reihenfolge bleibt beim Neuladen, beim Wechsel der
  Reiter und beim Wechsel der Demo-Konten exakt erhalten; neu hinzugefügte Ticker landen am Ende.
* Auf schmalen Bildschirmen blendet die Demo-Liste rechte Spalten (z. B. „In account“) aus, statt Zahlen
  abzuschneiden.

### Demo Account: Stop-Loss & Take-Profit
* **Order Ticket (Kauf):** zwei getrennte Schalter **Take profit** und **Stop loss**. Eingeschaltet erscheint
  jeweils ein Preisfeld mit **− / +** (Schrittweite passend zum Kurs) und direkter Eingabe; Vorschlag +5 % bzw.
  −3 %. Direkt darunter steht dynamisch das erwartete Ergebnis **„Result: +$X.XX“ / „Result: −€X.XX“**
  (Stückzahl × Abstand zum aktuellen Kurs, in der Kontowährung, mit Prozent).
* **Stop-Typ:** *Regular* (fester Preis) oder *Trailing* (nachziehender Stop: der Abstand zum Kurs bleibt
  gleich, der Stop steigt mit jedem neuen Hoch und fällt nie). In der Tabelle mit ↗ markiert.
* Ungültige Werte (SL über bzw. TP unter dem aktuellen Kurs) werden direkt am Feld markiert und nicht
  angenommen.
* **Open Positions:** jede Position hat neben „Sell all“ einen Knopf **„SL / TP“**. Er öffnet den Bereich
  *Stop loss / take profit for open positions* mit genau dieser Position: dieselben Schalter, Felder und
  Ergebnis-Zeilen. **Schalter aus = Order sofort gelöscht**; Änderungen mit *Save orders* übernehmen. Das geht
  auch für Bot-Positionen – deine Werte ersetzen dann den Plan des Bots.
* **Automatische Schließung zum Live-Kurs:** Sobald der Kurs das TP- oder SL-Niveau erreicht oder
  überschreitet, wird die Position glattgestellt. Geprüft wird mit dem letzten 1-Minuten-Kurs (höchstens
  ~40 s alt): auf dem Server alle 30 Sekunden, beim Öffnen der Seite und alle 30 Sekunden, solange der Demo-
  Reiter offen ist. (Bisher: alle 15 Minuten auf geschlossenen 15-Minuten-Kerzen.)
* **Trade History** bekommt den Trade sofort, im Feld **WHY** mit „Take Profit hit“, „Stop Loss triggered“
  oder „Trailing Stop triggered“. **Cash** und **Realised P/L** werden im selben Moment aktualisiert; eine
  offene Demo-Seite lädt sich selbst neu und zeigt eine Meldung. Mit aktivierter Benachrichtigung „Demo
  trades“ kommt zusätzlich Push / E-Mail.
* Manuelle Demo-Orders werden jetzt ebenfalls zum 1-Minuten-Kurs ausgeführt.
* Hinweis: Streamlit Cloud legt die App nach längerer Inaktivität schlafen. Solange sie läuft, werden die
  Orders auch ohne geöffnete Seite überwacht; nach dem Aufwachen wird sofort zum aktuellen Kurs geprüft.

**Getestet:** alle 59 Szenarien in 4 Modi (online/offline × neue/alte Streamlit-Version), Browser-Test der
sortierbaren Liste (Maus- und Touch-Drag, Pfeile, Tastatur, Entfernen, Öffnen, Breiten 300–760 px, helles
Theme – keine Überschneidungen) und Abstands-Test der SL/TP-Bereiche bei 760 / 600 / 360 px.

---

# Pulse — Market Dashboard (Streamlit) · v4.7

## Neu in v4.7 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Keine neuen Secrets.

* **Mehrere Demo-Konten.** Im Reiter *Demo* steht links oben die Kontoauswahl *Paper trading account* mit
  allen Konten (Name · aktueller Wert) und als letzter Eintrag **„+ Create account…“**. Dort vergibst du
  einen eigenen Namen (z. B. FundedAccount, Swing-Depot, CFD EUR), wählst die Währung ($ / €) und das
  Startkapital (10.000 / 25.000 / 50.000 / 100.000 / 500.000). Bis zu 12 Konten, Namen sind eindeutig.
* **Kein Datenverlust beim Wechseln.** Jedes Konto hat seinen eigenen Kontostand, offene Positionen,
  Stop-Loss/Take-Profit-Orders, Handelsverlauf, Equity-Kurve, Watchlist **und eigene Bots**. Beim Wechsel
  wird nur das aktive Konto umgestellt – nichts wird zurückgesetzt. Alles liegt im selben dauerhaften
  Speicher wie dein Profil (GitHub-Store aus v4.0) und übersteht Neustarts von Streamlit Cloud.
  Dein bisheriges Demokonto wird automatisch als **„Main account“** übernommen.
* **Zahnrad ⚙ neben der Auswahl:** das aktive Konto **umbenennen**, **zurücksetzen** (mit neuer Währung /
  neuem Startkapital; Name, Watchlist und Bots bleiben, Bots pausiert; andere Konten unberührt) oder
  **dauerhaft löschen** (mit Bestätigung; das letzte Konto lässt sich nicht löschen, nur zurücksetzen).
* **Stop-Loss / Take-Profit für manuelle Orders.** Im Order Ticket beim Kauf optional SL und TP angeben;
  sie werden wie die Bot-Orders alle 15 Minuten auf den geschlossenen 15-Minuten-Kerzen geprüft. Die
  Tabelle *Open positions* zeigt SL / TP, und unter „Stop-loss / take-profit for your manual positions“
  lassen sie sich nachträglich ändern oder entfernen.
* **Bots:** Neue Bots gehören zum aktiven Konto; der 15-Minuten-Lauf bedient alle Konten. Short Term und
  die Karte im Seitenmenü zeigen, welches Konto gerade aktiv ist; Bot-Benachrichtigungen nennen den
  Kontonamen.
* **Spacing:** Kontoauswahl, Zahnrad-Menü und Formular wurden im Browser-Nachbau (mit einem 32 Zeichen
  langen Kontonamen, auch bei schmaler Spalte) auf Überschneidungen geprüft – keine gefunden; „Create
  account“ und „Cancel“ stehen untereinander, damit in der schmalen Spalte nichts abgeschnitten wird.

---

# Pulse — Market Dashboard (Streamlit) · v4.6

## Neu in v4.6 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Keine neuen Secrets.

* **Ursache der „klebenden“ / überlappenden Elemente behoben (alle Seiten).** Streamlit gibt jedem
  Markdown-Block einen negativen unteren Rand (−1 rem), um den Absatzabstand auszugleichen. Pulse baut fast
  alles aus HTML-Blöcken ohne Absatz – dadurch wurde das jeweils nächste Element nach oben gezogen, und mit
  dem engen Abstand aus v4.0 ragte es einige Pixel hinein (Kennzahlen-Leiste in den Tabellenkopf, Banner in
  die Badges, Text in Eingabefelder). Jetzt ist der Rand neutralisiert: Zwischen zwei Elementen liegt überall
  genau der Blockabstand (0,75 rem, auf Laptops 0,65 rem).
  Außerdem entfernt: drei Stellen mit negativem Abstand (Hinweiszeile unter den Wachstums-Eingaben im
  Value-Path, Fear-&-Greed-Beschriftung unter dem Tacho, „Peer source“ in Valuation) und der negative Rand
  unter allen Diagrammen. Lange Texte brechen in schmalen Spalten um, statt in Nachbar-Buttons zu laufen.
* **Demo-Bereich (und Bot-Bereich in Short Term) luftiger:** Abstand zwischen allen Elementen 1,05 rem,
  Beschriftungen haben Abstand zu ihren Feldern, Zeilen in Konto-Box und Tabellen sind höher.
* **Short Term – Regime-Banner:** eigener Block direkt **unter** den Regime-Filter-Badges (S&P 500, Nasdaq),
  16 px Abstand nach unten, Text bricht sauber um und bleibt im Banner.
* **Short Term – Kennzahlen-Leiste:** 16 px Abstand zum Tabellenkopf (SYMBOL, PATTERN, PRICE …).

---

# Pulse — Market Dashboard (Streamlit) · v4.5

## Neu in v4.5 (Deutsch)

**Dateien:** `app.py`, `engine.py`, `mock_data.py`, `chart.py`, `backend.py` und `pulse_chart/index.html` —
alle hochladen, dann *Reboot app*. Keine neuen Secrets.

* **Valuation: Sektion „Methods“ entfernt.** Die ganze Tabelle mit allen Zeilen (EV/EBITDA, Owner-earnings
  DCF, ROIC vs WACC, Mid-cycle earnings, Dividend discount, Market-implied path …) ist aus der Oberfläche
  **und** aus der Render-Logik raus. Die Referenzzeile *Market-implied path* wird gar nicht mehr berechnet.
  Der Prüf-Block (z. B. „Debt, Profit Growth & Consistency“) steht jetzt in voller Breite direkt unter der
  Modellauswahl.
  **Beibehalten:** *Blended Fair Value* samt Gewichtung — dort stehen weiterhin die beitragenden Methoden
  mit ihrem Anteil, weil du dir diese Erklärung in v4.0 ausdrücklich gewünscht hast. Sag Bescheid, wenn
  auch diese Zeilen verschwinden sollen.
* **Short Term, Detailkarte:** Unter „Sell 40 % at TP1 …“ ist jetzt deutlich mehr Abstand. „Why this
  opportunity is listed“ sitzt in einer eigenen, voll breiten Zeile; beim Ausklappen schiebt es den Button
  „Add to trade journal“ sauber nach unten, ohne in den Text darüber zu ragen.

---

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
