# Pulse Backtest-Lab (Branch `backtest-lab`)

Dieser Branch ist nur für Backtests der Short-Term-Strategien da. **`main` und die Live-App auf Streamlit bleiben
unberührt** — Streamlit deployt weiter aus `main`.

- `lab/fetch_data.py` holt Tageskerzen (Yahoo Finance, Ersatz Stooq) für alle Symbole der Bots.
- `.github/workflows/backtest-lab.yml` läuft nur auf diesem Branch: Daten holen → mit `lab/pubkey.pem`
  verschlüsseln → `lab/data/market.enc` (+ `market.key`). Im öffentlichen Repo liegen also keine lesbaren Kursdaten.
- `lab/data/manifest.json` zeigt, welche Symbole geladen wurden (Quelle, Zeitraum).
- Ergebnisse der Auswertung landen in `lab/results/`.

Der Branch kann nach der Auswertung jederzeit gelöscht werden (GitHub → Branches → Papierkorb-Symbol).
