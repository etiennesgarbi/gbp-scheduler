# GBP Auto-Poster — Single & Multi Location

Automatizza la generazione e pubblicazione di post su Google Business Profile.

## File inclusi

| File | Scopo |
|------|-------|
| `gbp_scheduler.py` | Pubblica un CSV su una singola sede GBP |
| `gbp_multi.py` | Genera e pubblica post per più sedi |
| `genera_post.py` | Genera `posts.csv` via API Anthropic (singola sede) |
| `gbp_state.py` | Stato persistente SQLite — idempotenza |
| `gbp_validate.py` | Validazione pre-flight CSV |
| `gbp_selectors.py` | Selettori Playwright centralizzati |
| `gbp_generator.py` | Generazione post via Anthropic SDK + UTM builder |
| `gbp_image.py` | Preprocessing immagini con Pillow |
| `gbp_discover.py` | Auto-discovery sedi GBP via API Google |
| `gbp_metrics.py` | Raccolta metriche GBP mensili via API Google |

---

## Setup

### 1. Installa dipendenze
```bash
pip install -r requirements.txt
python3 -m playwright install chrome
```

### 2. Configura le variabili d'ambiente
```bash
cp .env.example .env
# Modifica .env e inserisci la tua ANTHROPIC_API_KEY
```

Variabili disponibili in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...        # Obbligatoria per generare post
GBP_CHROME_PROFILE=./chrome-profile # Profilo Chrome (default: ./chrome-profile)
GBP_HEADLESS=false                  # false = vedi il browser
GBP_DELAY_POST=5                    # Secondi di pausa tra un post e l'altro
GBP_DATA_INIZIO=2026-05-05          # Data di partenza post per gbp_multi
```

Per Sprint 3 (API Google), aggiungi anche:
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

---

## Modalità 1 — Una sede singola

### 1. Genera il CSV
```bash
python3 genera_post.py
```
Oppure crea manualmente `posts.csv` con colonne: `title, description, date, image, cta_url, cta_type`.

### 2. Valida il CSV
```bash
python3 gbp_validate.py posts.csv
```

### 3. Pubblica
```bash
python3 gbp_scheduler.py --client <slug>
```
Esempio: `python3 gbp_scheduler.py --client miscusi-roma`

Si apre Chrome → login Google → vai alla sede corretta → premi INVIO.

Lo script salta automaticamente i post già pubblicati (stato su SQLite).

---

## Modalità 2 — Più sedi, stesso account GBP

### 1. Compila `ristoranti.csv`
```csv
nome,citta,quartiere,keywords,cta_url
Miscusi Prati,Roma,Prati,"pasta fresca Prati Roma, ristorante pasta Prati",https://miscusi.com
Miscusi Trastevere,Roma,Trastevere,"pasta fresca Trastevere, ristorante pasta Trastevere",https://miscusi.com
```

### 2. Lancia
```bash
python3 gbp_multi.py --client <slug>
```
Esempio: `python3 gbp_multi.py --client miscusi`

Lo script fa:
1. Legge `ristoranti.csv`
2. Genera `posts_[sede].csv` per ogni sede via Anthropic SDK
3. Aggiunge UTM auto-generati a ogni `cta_url`
4. Valida ogni CSV prima di pubblicare
5. Apre `business.google.com/locations`
6. Seleziona ogni sede e pubblica i post con retry automatico (3 tentativi)

I profili Chrome sono isolati per cliente in `./profiles/<slug>/`.

---

## Sprint 3 — API Google

### Auto-discovery sedi
```bash
python3 gbp_discover.py --client <slug>
```
Genera `locations_<slug>.csv` con tutte le sedi dell'account GBP.

### Metriche mensili
```bash
python3 gbp_metrics.py --client <slug> --month YYYY-MM
```
Esempio: `python3 gbp_metrics.py --client miscusi --month 2026-04`

Genera `reports/metrics_<slug>_YYYY-MM.csv` con impressioni, click su sito, chiamate, richieste di indicazioni — per ogni sede, per ogni giorno del mese.

---

## Note importanti

- Usa Chrome di sistema, non Chromium
- Il profilo Chrome per ogni cliente è salvato in `./profiles/<slug>/`
- Non condividere le cartelle `profiles/` tra computer diversi
- `.env` non deve mai essere committato su git (è in `.gitignore`)
- I log sono salvati in `logs/gbp_YYYY-MM-DD.log`
- In caso di errore, screenshot e `error.txt` sono salvati in `logs/run_<ts>/<location>/<n>/`
- Lo stato SQLite in `state.db` garantisce idempotenza: i post già pubblicati vengono saltati
