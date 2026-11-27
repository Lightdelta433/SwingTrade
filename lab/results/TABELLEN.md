# Backtest-Tabellen (alle getesteten Varianten)

Daten: Yahoo-Tageskerzen 2003–25.11.2026, Auswertung ab 2006. Gebühren 0,1 % je Seite. Winrate = Anteil der Positionen mit Gewinn (Teilverkäufe zu einer Position zusammengefasst). „Bot (live)“ = Ausstiege wie im Live-Bot (Stop, 40 % bei TP1 + Stop auf Einstieg, 2 × ATR-Trailing, 15-Tage-Limit; Donchian/Ichimoku ohne Limit). „App-Backtest“ = wie der Backtest-Tab der App. Top-60 = nur Tage, an denen die Aktie zu den 60 liquidesten des Universums gehörte (wie der Bot-Scan).

## Double Donchian

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| App-Backtest | 7610 | 40.8 % | +2.37 % | +14.98 % / -6.32 % | 1.63 | +0.14 | 50 |
| Bot (live) | 7610 | 40.8 % | +2.37 % | +14.98 % / -6.32 % | 1.63 | +0.14 | 50 |
| Bot · Top-60-Universum | 3521 | 40.7 % | +1.41 % | +11.86 % / -5.77 % | 1.41 | +0.10 | 51 |
| Bot · + SPY>200T | 7177 | 40.8 % | +2.33 % | +14.74 % / -6.23 % | 1.63 | +0.15 | 50 |
| Bot · Top-60 + SPY>200T | 3324 | 40.6 % | +1.36 % | +11.68 % / -5.71 % | 1.40 | +0.10 | 50 |
| Bot · Richtung 50 statt 120 | 8499 | 41.1 % | +2.48 % | +15.51 % / -6.62 % | 1.63 | +0.15 | 50 |
| Bot · Ausstieg 10-Tage-Tief | 10735 | 38.7 % | +0.69 % | +8.83 % / -4.45 % | 1.25 | +0.05 | 25 |
| Bot · Einstieg 55-Tage-Hoch | 5842 | 41.8 % | +2.60 % | +14.84 % / -6.20 % | 1.72 | +0.14 | 51 |
| Bot · 55/20 + SPY>200T | 5536 | 42.1 % | +2.67 % | +14.76 % / -6.11 % | 1.75 | +0.15 | 51 |

Depot-Simulation (Bot-Größen: höchstens 5 Positionen à 20 %, 1 % Risiko je Trade, Top-60):

| Depot | Rendite p. a. | Max. Drawdown | Sharpe | Trades | Winrate |
|---|---|---|---|---|---|
| Bot (live) | +2.4 % | -31.9 % | 0.30 | 697 | 39.0 % |
| 20/20 · 5 Pos. à 20 % (live) | +2.4 % | -31.9 % | 0.30 | 697 | 39.0 % |
| 20/20 · 10 Pos. à 10 %, 1 % Risiko | +5.8 % | -30.7 % | 0.50 | 1284 | 42.4 % |
| 20/20 · 10 Pos. à 10 % · stärkstes 6-M-Momentum zuerst | +4.6 % | -31.1 % | 0.41 | 1317 | 40.5 % |
| 55/20 · 5 Pos. à 20 % | +2.7 % | -25.1 % | 0.36 | 664 | 40.7 % |
| 55/20 · 10 Pos. à 10 % · Momentum zuerst | +4.7 % | -21.5 % | 0.44 | 1215 | 41.6 % |

## Flagge

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| App-Backtest | 433 | 47.3 % | +9.27 % | +35.15 % / -14.00 % | 2.26 | +0.53 | 95 |
| Bot (live) | 490 | 48.8 % | +0.94 % | +9.90 % / -7.60 % | 1.24 | +0.01 | 14 |
| Bot · Top-60-Universum | 129 | 49.6 % | +1.24 % | +9.84 % / -7.23 % | 1.34 | +0.02 | 14 |
| Bot · + SPY>200T | 402 | 49.0 % | +1.29 % | +10.47 % / -7.53 % | 1.34 | +0.03 | 14 |
| Bot · ohne 15-Tage-Limit | 446 | 47.1 % | +7.30 % | +31.38 % / -14.13 % | 1.98 | +0.41 | 66 |
| Bot · Trail 3 ATR, ohne Zeitlimit | 442 | 47.1 % | +7.34 % | +31.51 % / -14.14 % | 1.98 | +0.41 | 69 |
| Bot · Anstieg ≥ 20 % | 844 | 49.5 % | +0.71 % | +7.98 % / -6.42 % | 1.22 | +0.03 | 14 |
| Bot · Volumen ≥ 1,2× | 771 | 49.7 % | +0.70 % | +9.39 % / -7.88 % | 1.18 | +0.03 | 14 |
| Bot · ≥20 % + Vol 1,2× + SPY>200T | 1164 | 49.1 % | +0.63 % | +7.76 % / -6.25 % | 1.20 | +0.03 | 14 |
| Bot live (Zusatz) | 490 | 48.8 % | +0.94 % | +9.90 % / -7.60 % | 1.24 | +0.01 | 14 |
| ohne Zeitlimit · Top-60 (Zusatz) | 120 | 50.0 % | +8.87 % | +31.25 % / -13.51 % | 2.31 | +0.51 | 70 |
| Zeitlimit 30 T (Zusatz) | 476 | 48.5 % | +2.13 % | +14.42 % / -9.46 % | 1.44 | +0.09 | 24 |
| Zeitlimit 45 T (Zusatz) | 462 | 48.9 % | +2.75 % | +17.29 % / -11.16 % | 1.48 | +0.14 | 32 |
| Zeitlimit 60 T (Zusatz) | 457 | 48.1 % | +3.27 % | +19.78 % / -12.05 % | 1.52 | +0.19 | 39 |
| ohne Zeitlimit (Zusatz) | 446 | 47.1 % | +7.30 % | +31.38 % / -14.13 % | 1.98 | +0.41 | 66 |
| ohne Zeitlimit · Trail = 10-Tage-Tief nach TP1 (Zusatz) | 446 | 47.1 % | +7.31 % | +31.40 % / -14.13 % | 1.98 | +0.41 | 65 |
| ohne Zeitlimit · ohne TP2 (Rest nur Trailing 3 ATR) (Zusatz) | 441 | 46.9 % | +6.87 % | +30.61 % / -14.14 % | 1.92 | +0.41 | 70 |
| ohne Zeitlimit · + SPY>200T (Zusatz) | 372 | 47.0 % | +7.04 % | +30.44 % / -13.75 % | 1.97 | +0.41 | 59 |
| TP1 1,5R · ohne Zeitlimit (Zusatz) | 453 | 51.7 % | +5.72 % | +24.12 % / -13.95 % | 1.85 | +0.31 | 51 |

Depot-Simulation (Bot-Größen: höchstens 5 Positionen à 20 %, 1 % Risiko je Trade, Top-60):

| Depot | Rendite p. a. | Max. Drawdown | Sharpe | Trades | Winrate |
|---|---|---|---|---|---|
| Bot (live) | +0.1 % | -7.4 % | 0.06 | 130 | 50.0 % |
| Bot live | +0.1 % | -7.4 % | 0.06 | 130 | 50.0 % |
| ohne Zeitlimit | +2.9 % | -9.3 % | 0.70 | 117 | 50.4 % |

## WaveTrend + NW

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| App-Backtest | 1382 | 56.3 % | +0.52 % | +7.52 % / -8.50 % | 1.14 | +0.05 | 19 |
| Bot (live) | 1385 | 52.6 % | +0.08 % | +6.16 % / -6.65 % | 1.03 | +0.02 | 11 |
| Bot · Top-60-Universum | 631 | 52.8 % | +0.04 % | +5.52 % / -6.07 % | 1.02 | -0.02 | 12 |
| Bot · + Aktie > 200T | 306 | 56.2 % | -0.02 % | +4.61 % / -5.97 % | 0.99 | +0.11 | 12 |
| Bot · + SPY>200T | 598 | 49.8 % | -0.69 % | +4.22 % / -5.57 % | 0.75 | -0.04 | 11 |
| Bot · mit WT-Ausstieg (wie Karte) | 1385 | 52.5 % | +0.08 % | +6.17 % / -6.65 % | 1.02 | +0.02 | 11 |
| Bot · ohne 15-Tage-Limit | 1377 | 58.5 % | +0.66 % | +8.29 % / -10.08 % | 1.16 | +0.05 | 27 |
| Bot · ohne Volumenbedingung | 2267 | 52.0 % | -0.10 % | +5.77 % / -6.46 % | 0.97 | -0.03 | 11 |
| Bot · ohne Vol. + Aktie>200T | 480 | 56.7 % | +0.08 % | +4.42 % / -5.60 % | 1.03 | +0.08 | 12 |
| Bot · Überverkauft −40 statt −53 | 1514 | 52.6 % | +0.06 % | +6.11 % / -6.67 % | 1.02 | +0.01 | 11 |
| Bot · −40 + Aktie>200T | 386 | 55.4 % | -0.06 % | +4.84 % / -6.15 % | 0.98 | +0.06 | 12 |
| Bot live (Zusatz) | 1385 | 52.6 % | +0.08 % | +6.16 % / -6.65 % | 1.03 | +0.02 | 11 |
| alles bei TP1 (NW-Mitte) verkaufen (Zusatz) | 1385 | 53.4 % | +0.20 % | +6.28 % / -6.74 % | 1.06 | +0.02 | 9 |
| alles bei TP1 · ohne Zeitlimit (Zusatz) | 1377 | 59.5 % | +0.77 % | +8.30 % / -10.30 % | 1.18 | +0.05 | 20 |
| nur wenn VIX > 20 (Zusatz) | 924 | 53.8 % | +0.41 % | +7.24 % / -7.54 % | 1.12 | +0.05 | 11 |
| nur wenn SPY < 50-Tage-Linie (Zusatz) | 1044 | 54.7 % | +0.42 % | +6.74 % / -7.19 % | 1.13 | +0.04 | 11 |
| VIX > 20 · alles bei TP1 · ohne Zeitlimit (Zusatz) | 918 | 59.2 % | +1.13 % | +9.84 % / -11.49 % | 1.24 | +0.06 | 21 |
| Zeitlimit 10 T (Zusatz) | 1387 | 46.5 % | -0.68 % | +5.55 % / -6.09 % | 0.79 | -0.03 | 9 |
| ohne Zeitlimit (Zusatz) | 1377 | 58.5 % | +0.66 % | +8.29 % / -10.08 % | 1.16 | +0.05 | 27 |

Depot-Simulation (Bot-Größen: höchstens 5 Positionen à 20 %, 1 % Risiko je Trade, Top-60):

| Depot | Rendite p. a. | Max. Drawdown | Sharpe | Trades | Winrate |
|---|---|---|---|---|---|
| Bot (live) | -1.0 % | -30.3 % | -0.17 | 464 | 51.3 % |
| Bot live | -1.0 % | -30.3 % | -0.17 | 464 | 51.3 % |
| VIX > 20 · alles bei TP1 · ohne Zeitlimit | -0.1 % | -26.9 % | 0.01 | 459 | 58.8 % |

## Divergence

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| Long · App-Backtest | 25150 | 30.9 % | +0.79 % | +11.97 % / -4.20 % | 1.27 | +0.10 | 20 |
| Long · Bot (live) | 32543 | 38.1 % | +0.24 % | +6.35 % / -3.53 % | 1.11 | +0.01 | 8 |
| Long · Bot · Top-60 | 13338 | 38.0 % | +0.07 % | +5.46 % / -3.23 % | 1.04 | -0.04 | 8 |
| Long · Bot · + SPY>200T | 24640 | 38.1 % | +0.19 % | +5.66 % / -3.18 % | 1.10 | +0.02 | 8 |
| Short · App-Backtest | 29707 | 21.0 % | -0.83 % | +9.25 % / -3.51 % | 0.70 | -0.33 | 16 |
| Short · Bot (live) | 36274 | 29.8 % | -0.49 % | +5.77 % / -3.15 % | 0.78 | -0.23 | 7 |
| Short · Bot · nur SPY<200T | 7196 | 30.4 % | -0.68 % | +7.77 % / -4.37 % | 0.78 | -0.20 | 8 |
| Long+Short · Bot (live, wie Bot) | 55729 | 33.9 % | -0.12 % | +6.14 % / -3.34 % | 0.95 | -0.11 | 8 |
| Long · Bot · 200T-Trendfilter | 17656 | 39.0 % | +0.15 % | +5.36 % / -3.18 % | 1.08 | +0.02 | 8 |
| Long · Bot · ≥ 5 Indikatoren | 15707 | 38.2 % | +0.23 % | +6.29 % / -3.52 % | 1.10 | -0.01 | 8 |
| Long · Bot · nur reguläre Div. | 11544 | 38.9 % | +0.45 % | +7.36 % / -3.94 % | 1.19 | +0.03 | 8 |
| Long · Bot · ≥5 Ind. + Trend | 8817 | 38.6 % | +0.08 % | +5.28 % / -3.19 % | 1.04 | +0.00 | 8 |
| Long alle · Bot live (Zusatz) | 32543 | 38.1 % | +0.24 % | +6.35 % / -3.53 % | 1.11 | +0.01 | 8 |
| Long alle · ohne Zeitlimit (Zusatz) | 27246 | 31.1 % | +0.69 % | +11.38 % / -4.14 % | 1.24 | +0.09 | 17 |
| Long alle · ohne Zeitlimit · Top-60 (Zusatz) | 11285 | 30.5 % | +0.32 % | +9.80 % / -3.85 % | 1.12 | +0.02 | 19 |
| Long alle · Einstieg erst über Neckline (Zusatz) | 4679 | 44.9 % | +1.17 % | +13.77 % / -9.08 % | 1.23 | +0.10 | 50 |
| Long alle · Neckline-Einstieg · ohne Zeitlimit (Zusatz) | 4679 | 44.9 % | +1.17 % | +13.77 % / -9.08 % | 1.23 | +0.10 | 50 |
| Long alle · Neckline-Einstieg · Top-60 (Zusatz) | 1933 | 44.2 % | +0.72 % | +11.86 % / -8.09 % | 1.16 | +0.07 | 54 |
| Long regulär · Bot live (Zusatz) | 11544 | 38.9 % | +0.45 % | +7.36 % / -3.94 % | 1.19 | +0.03 | 8 |
| Long regulär · ohne Zeitlimit (Zusatz) | 10786 | 31.7 % | +1.16 % | +13.63 % / -4.64 % | 1.37 | +0.12 | 19 |
| Long regulär · ohne Zeitlimit · Top-60 (Zusatz) | 4192 | 31.6 % | +0.67 % | +11.35 % / -4.25 % | 1.23 | +0.03 | 20 |
| Long regulär · Einstieg erst über Neckline (Zusatz) | 1662 | 44.4 % | +1.06 % | +15.81 % / -10.72 % | 1.18 | +0.09 | 59 |
| Long regulär · Neckline-Einstieg · ohne Zeitlimit (Zusatz) | 1662 | 44.4 % | +1.06 % | +15.81 % / -10.72 % | 1.18 | +0.09 | 59 |
| Long regulär · Neckline-Einstieg · Top-60 (Zusatz) | 646 | 41.8 % | +0.18 % | +13.65 % / -9.49 % | 1.03 | +0.02 | 67 |

Depot-Simulation (Bot-Größen: höchstens 5 Positionen à 20 %, 1 % Risiko je Trade, Top-60):

| Depot | Rendite p. a. | Max. Drawdown | Sharpe | Trades | Winrate |
|---|---|---|---|---|---|
| Long · Bot (live) | -14.3 % | -96.2 % | -0.68 | 4536 | 32.5 % |

## Ichimoku (Gold, Silber, Öl, Bitcoin · Long + Short)

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| GC=F · App (Modus 0) | 104 | 25.0 % | +0.29 % | +5.33 % / -1.39 % | 1.27 | +0.10 | 13 |
| GC=F · Bot (Kijun-Intraday-Stop) | 113 | 21.2 % | +0.16 % | +5.09 % / -1.17 % | 1.18 | -0.07 | 10 |
| GC=F · App gestaffelt (Modus 1) | 159 | 27.7 % | +0.04 % | +3.47 % / -1.28 % | 1.04 | -0.04 | 11 |
| GC=F · Auto-Stufe walk-forward | 146 | 24.0 % | -0.24 % | +3.04 % / -1.27 % | 0.76 | -0.29 | 10 |
| SI=F · App (Modus 0) | 84 | 19.0 % | +0.00 % | +10.37 % / -2.44 % | 1.00 | +0.14 | 12 |
| SI=F · Bot (Kijun-Intraday-Stop) | 90 | 15.6 % | +0.03 % | +11.04 % / -2.00 % | 1.02 | +0.09 | 10 |
| SI=F · App gestaffelt (Modus 1) | 145 | 29.0 % | +0.22 % | +6.40 % / -2.30 % | 1.14 | -0.85 | 13 |
| SI=F · Auto-Stufe walk-forward | 98 | 23.5 % | -0.16 % | +7.34 % / -2.46 % | 0.92 | -1.20 | 12 |
| CL=F · App (Modus 0) | 88 | 29.5 % | +1.73 % | +13.59 % / -3.24 % | 1.76 | +0.25 | 18 |
| CL=F · Bot (Kijun-Intraday-Stop) | 94 | 26.6 % | +1.73 % | +13.84 % / -2.66 % | 1.88 | +0.26 | 14 |
| CL=F · App gestaffelt (Modus 1) | 112 | 19.6 % | -0.41 % | +9.89 % / -2.93 % | 0.83 | -0.06 | 13 |
| CL=F · Auto-Stufe walk-forward | 86 | 24.4 % | +0.85 % | +13.33 % / -3.18 % | 1.35 | +0.20 | 15 |
| BTC-USD · App (Modus 0) | 101 | 28.7 % | +5.46 % | +28.24 % / -3.71 % | 3.06 | +1.23 | 16 |
| BTC-USD · Bot (Kijun-Intraday-Stop) | 113 | 28.3 % | +5.05 % | +25.92 % / -3.20 % | 3.20 | +1.21 | 12 |
| BTC-USD · App gestaffelt (Modus 1) | 175 | 29.7 % | +2.93 % | +18.73 % / -3.75 % | 2.11 | +1.00 | 14 |
| BTC-USD · Auto-Stufe walk-forward | 145 | 27.6 % | +2.68 % | +19.36 % / -3.68 % | 2.01 | +0.65 | 13 |
| ALLE · App | 377 | 25.7 % | +1.95 % | +15.23 % / -2.65 % | 1.99 | +0.45 | 15 |
| ALLE · Bot live | 410 | 23.2 % | +1.84 % | +15.29 % / -2.22 % | 2.08 | +0.40 | 12 |
| ALLE · gestaffelt | 591 | 27.1 % | +0.85 % | +10.08 % / -2.57 % | 1.46 | +0.06 | 13 |
| ALLE · Auto-Stufe | 475 | 25.1 % | +0.87 % | +11.17 % / -2.58 % | 1.45 | -0.10 | 12 |
| ALLE · Bot · ohne Kijun-Bounce | 133 | 24.8 % | +2.79 % | +19.17 % / -2.61 % | 2.42 | +0.62 | 16 |
| ALLE · Bot · max. 1 ATR vom Kijun | 240 | 21.7 % | +1.14 % | +10.96 % / -1.57 % | 1.93 | +0.34 | 8 |
| ALLE · Bot · Schlusskurs-Regel | 377 | 25.7 % | +1.95 % | +15.23 % / -2.65 % | 1.99 | +0.45 | 15 |
| ALLE · Bot · Schlusskurs + ohne Bounce | 127 | 31.5 % | +3.63 % | +18.24 % / -3.09 % | 2.72 | +0.73 | 21 |

## Momentum-Rotation

| Universum · Variante | Rendite p. a. | Max. DD | Sharpe | Gewinnmonate | Haltedauern | davon Gewinner | Benchmark p. a. | Benchmark Max. DD | Zeitraum |
|---|---|---|---|---|---|---|---|---|---|
| ucits · Bot-Einstellung | +9.5 % | -21.0 % | 0.72 | 65 % | 72 | 61 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · Top 2 | +9.2 % | -22.5 % | 0.68 | 62 % | 67 | 63 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · Top 4 | +7.6 % | -20.6 % | 0.63 | 63 % | 90 | 53 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · ohne Puffer | +9.2 % | -19.7 % | 0.72 | 65 % | 116 | 60 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · Puffer 2 | +8.0 % | -22.3 % | 0.62 | 62 % | 66 | 55 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · 12-1-Momentum (nur 12 M, letzter Monat übersprungen) | +6.5 % | -27.1 % | 0.53 | 61 % | 66 | 55 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · 6+12 Monate | +7.8 % | -20.2 % | 0.62 | 64 % | 73 | 58 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · Volatilitäts-bereinigt | +9.2 % | -17.7 % | 0.74 | 64 % | 87 | 61 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · ohne Markt-Filter | +10.4 % | -32.0 % | 0.73 | 66 % | 64 | 67 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| ucits · ohne absolutes Momentum | +9.8 % | -21.0 % | 0.75 | 65 % | 73 | 62 % | +12.6 % | -33.6 % | 2012-01-06 – 2026-11-26 |
| us_sectors · Bot-Einstellung | +7.2 % | -29.8 % | 0.57 | 62 % | 108 | 53 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · Top 2 | +7.1 % | -35.9 % | 0.54 | 59 % | 82 | 52 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · Top 4 | +8.1 % | -26.4 % | 0.67 | 66 % | 115 | 53 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · ohne Puffer | +6.6 % | -33.7 % | 0.54 | 61 % | 141 | 50 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · Puffer 2 | +8.5 % | -26.4 % | 0.67 | 67 % | 76 | 50 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · 12-1-Momentum (nur 12 M, letzter Monat übersprungen) | +8.4 % | -26.8 % | 0.67 | 67 % | 88 | 52 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · 6+12 Monate | +8.0 % | -30.1 % | 0.63 | 66 % | 95 | 53 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · Volatilitäts-bereinigt | +8.4 % | -28.8 % | 0.68 | 63 % | 113 | 56 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · ohne Markt-Filter | +7.2 % | -32.4 % | 0.51 | 62 % | 103 | 54 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| us_sectors · ohne absolutes Momentum | +7.2 % | -29.8 % | 0.58 | 62 % | 106 | 53 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · Bot-Einstellung | +6.2 % | -24.1 % | 0.55 | 61 % | 85 | 48 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · Top 2 | +5.8 % | -25.5 % | 0.48 | 57 % | 68 | 46 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · Top 4 | +7.0 % | -19.8 % | 0.64 | 62 % | 96 | 51 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · ohne Puffer | +6.1 % | -21.6 % | 0.54 | 59 % | 124 | 51 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · Puffer 2 | +6.5 % | -23.8 % | 0.57 | 62 % | 67 | 51 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · 12-1-Momentum (nur 12 M, letzter Monat übersprungen) | +4.1 % | -23.2 % | 0.40 | 56 % | 87 | 51 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · 6+12 Monate | +7.0 % | -19.6 % | 0.62 | 58 % | 84 | 50 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · Volatilitäts-bereinigt | +7.1 % | -18.1 % | 0.65 | 56 % | 87 | 53 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · ohne Markt-Filter | +7.5 % | -23.2 % | 0.60 | 62 % | 82 | 50 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |
| assets · ohne absolutes Momentum | +6.1 % | -24.1 % | 0.54 | 62 % | 88 | 48 % | +12.3 % | -34.1 % | 2011-11-14 – 2026-11-25 |

## Pairs trading (walk-forward, monatliche Auswahl wie der Bot)

| Variante | Trades | Winrate | Ø Trade | Profit-Faktor | Ø Tage | In-sample-Winrate der Auswahl |
|---|---|---|---|---|---|---|
| Bot (live, walk-forward) | 528 | 57.0 % | +0.03 % | 1.04 | 24 | 70 % |
| Einstieg |z| ≥ 2,5 | 358 | 57.5 % | +0.14 % | 1.19 | 23 | 70 % |
| Stop |z| ≥ 3 | 588 | 53.1 % | -0.02 % | 0.97 | 20 | 70 % |
| max. 15 Handelstage | 622 | 52.6 % | +0.03 % | 1.04 | 17 | 70 % |
| Ausstieg z ±0,5 | 583 | 58.7 % | -0.01 % | 0.99 | 18 | 70 % |

## Pattern breakout (AI-Bot, walk-forward, ohne 15-Min-Bestätigung)

| Variante | Trades | Winrate | Ø Trade | Ø Gewinn / Ø Verlust | Profit-Faktor | Ø R | Ø Tage |
|---|---|---|---|---|---|---|---|
| Bot (live, ohne 15-Min) | 7630 | 46.7 % | +0.29 % | +5.22 % / -4.03 % | 1.13 | +0.03 | 11 |
| nur frische Ausbrüche (≤ 1 Tag) | 4492 | 45.7 % | +0.34 % | +5.33 % / -3.86 % | 1.16 | +0.02 | 11 |
| ohne Markt-Filter | 8713 | 45.9 % | +0.14 % | +5.17 % / -4.13 % | 1.06 | +0.00 | 11 |
| alle Werte (ohne Top-40) | 11618 | 46.0 % | +0.21 % | +5.03 % / -3.90 % | 1.10 | +0.02 | 11 |
| R/R ≥ 2 | 6938 | 46.7 % | +0.31 % | +5.22 % / -3.99 % | 1.15 | +0.03 | 11 |
| ohne 15-Tage-Limit, Trail 3 ATR | 5756 | 38.7 % | +1.07 % | +11.30 % / -5.39 % | 1.33 | +0.14 | 31 |
| frisch ≤1 + ohne Zeitlimit + Trail 3 ATR | 3789 | 38.7 % | +1.08 % | +10.73 % / -5.01 % | 1.35 | +0.13 | 28 |
| nur mit Kerzen-Bonus | 1706 | 47.9 % | +0.48 % | +5.19 % / -3.86 % | 1.24 | +0.03 | 11 |
| + SPY > 200T | 7166 | 46.8 % | +0.30 % | +5.09 % / -3.93 % | 1.14 | +0.03 | 11 |

