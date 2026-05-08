# GBP Auto-Poster — Single & Multi Location

Automatizza la generazione e pubblicazione di post su Google Business Profile.

## File inclusi
- `gbp_scheduler.py` → pubblica un CSV su una singola sede GBP
- `gbp_multi.py` → genera e pubblica post per più sedi da un unico account GBP
- `genera_post.py` → opzionale, genera `posts.csv` via API Anthropic
- `posts.csv` → esempio CSV per una sede singola
- `ristoranti.csv` → elenco sedi per la modalità multi-location

---

## Setup

Installa dipendenze:
```bash
pip install playwright
python3 -m playwright install chrome
```

Se vuoi usare Claude Code in locale, assicurati che il comando `claude` sia già installato e funzioni.

---

## Modalità 1 — Una sede singola

### 1. Genera il CSV con Claude Code
```bash
claude "Genera 12 post GBP per [nome attività] a [città]. Keyword: [lista keyword]. Title max 58 caratteri, description 150-300 caratteri SEO con CTA. Date settimanali dal 2026-05-05 10:00. Salva in posts.csv con colonne: title,description,date,image,cta_url,cta_type. Lascia image e cta_url vuote."
```

### 2. Aggiungi i link in `cta_url`
Apri `posts.csv` con Excel/Numbers/Sheets e inserisci il link con UTM.

### 3. Pubblica
```bash
python3 gbp_scheduler.py
```
Si apre Chrome → login Google → vai alla sede corretta → premi INVIO.

---

## Modalità 2 — Più sedi, stesso account GBP

Questa è la modalità consigliata se hai un unico account Google Business Profile con più sedi.

### 1. Compila `ristoranti.csv`
Struttura:
```csv
nome,citta,quartiere,keywords,cta_url
Miscusi Prati,Roma,Prati,"pasta fresca Prati Roma, ristorante pasta Prati, cucina italiana Prati",https://miscusi.com?utm_source=gbp&utm_medium=post&utm_campaign=prati
Miscusi Trastevere,Roma,Trastevere,"pasta fresca Trastevere Roma, ristorante pasta Trastevere, cucina italiana Trastevere",https://miscusi.com?utm_source=gbp&utm_medium=post&utm_campaign=trastevere
```

### 2. Lancia tutto
```bash
python3 gbp_multi.py
```

Lo script fa questo:
1. Legge `ristoranti.csv`
2. Usa Claude Code per creare `posts_[sede].csv` per ogni sede
3. Apre `business.google.com/locations`
4. Seleziona la sede
5. Pubblica i post
6. Passa alla sede successiva

---

## Keyword research

Prima di generare i post, fai keyword research per ogni sede.
Esempi:
- pasta fresca Roma Prati
- ristorante pasta Trastevere
- cucina italiana Parioli
- dove mangiare pasta fresca Roma centro

---

## Test consigliato

Prima di lanciare 12 post per sede:
1. fai generare **1 solo post**
2. prova su una sola sede
3. verifica che venga creato e programmato correttamente
4. poi scala a 12+ post e a tutte le sedi

---

## Note importanti

- Usa Chrome di sistema, non Chromium
- Il login Google viene salvato nella cartella `chrome-profile`
- Non condividere `chrome-profile` tra computer diversi
- Se Google cambia interfaccia, potrebbero servire piccoli aggiustamenti ai selettori
