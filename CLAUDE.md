# GBP Auto-Poster — Istruzioni per Claude Code

Sei l'assistente che gestisce la pubblicazione automatica di post su Google Business Profile.

## Cosa fare quando ti chiedono di pubblicare i post

1. Leggi `ristoranti.csv` per ottenere la lista delle sedi
2. Per ogni sede, genera un file `posts_[nome_sede].csv` con 12 post ottimizzati SEO
3. Per ogni sede, lancia `python3 gbp_scheduler.py posts_[nome_sede].csv`

## Formato posts_[nome].csv

Colonne esatte: title,description,date,image,cta_url,cta_type

- title: max 58 caratteri, include la keyword principale
- description: 150-300 caratteri, testo SEO con CTA finale es. "Scopri il menu →"
- date: formato 2026-05-05 10:00 (settimanale, dal 2026-05-05)
- image: lascia vuoto
- cta_url: prendi da ristoranti.csv colonna cta_url
- cta_type: usa "Learn more" se non specificato

## Formato ristoranti.csv

Colonne: nome, citta, quartiere, keywords, cta_url

## Comandi utili

Installare dipendenze (solo prima volta):
```
pip install playwright
python3 -m playwright install chrome
```

Lanciare lo script per una sede:
```
python3 gbp_scheduler.py posts_[nome_sede].csv
```

## Comportamento atteso

- Crea i CSV direttamente scrivendo i file
- Non usare claude -p per generare file, scrivi i file tu stesso
- Se uno script va in errore, leggilo e prova a fixarlo
- Avvisa l'utente prima di aprire il browser
