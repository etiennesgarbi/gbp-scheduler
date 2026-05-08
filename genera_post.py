#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          STEP 1 — Genera post GBP con Claude API                 ║
╚══════════════════════════════════════════════════════════════════╝

Prende le keyword e genera automaticamente i post ottimizzati per
Google Business Profile, salvandoli in posts.csv pronti da pubblicare.

SETUP:
    pip install anthropic

USO:
    python genera_post.py
"""

import csv
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

try:
    import anthropic
except ImportError:
    print("❌ Libreria mancante. Esegui: pip install anthropic")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
#  CONFIGURAZIONE — modifica qui
# ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Le tue keyword (aggiungine quante vuoi)
KEYWORDS = [
    "pasta fresca Roma",
    "pasta fresca artigianale",
    "cucina italiana Roma",
    "ristorante pasta Roma",
    "pasta fatta a mano",
]

# Info sulla tua attività (personalizza!)
BUSINESS_INFO = """
Nome attività: Miscusi
Tipo: Ristorante di pasta fresca artigianale
Città: Roma
Tone of voice: amichevole, autentico, appassionato
Obiettivo post: portare clienti in locale e far prenotare online
Sito web: miscusi.com
"""

# Data primo post e frequenza
DATA_INIZIO   = "2026-05-05"   # formato YYYY-MM-DD
ORA_INIZIO    = "10:00"
FREQUENZA     = "settimanale"  # settimanale o bisettimanale

OUTPUT_CSV    = "posts.csv"
# ──────────────────────────────────────────────────────────────────


def genera_post_con_claude(keywords: list, business_info: str) -> list:
    """Chiama Claude API e genera i post GBP."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    keyword_list = "\n".join(f"- {k}" for k in keywords)

    prompt = f"""Sei un esperto di Local SEO e copywriting per Google Business Profile (GBP).

ATTIVITÀ:
{business_info}

KEYWORD TARGET:
{keyword_list}

ISTRUZIONI:
Genera {len(keywords)} post per Google Business Profile, uno per ogni keyword.
Ogni post deve:
1. Essere ottimizzato per la keyword target (includila naturalmente nel testo)
2. Avere un tono autentico, non commerciale
3. Includere una CTA implicita ma efficace
4. Rispettare i limiti di GBP: title max 58 caratteri, description max 300 caratteri

Per ogni post restituisci ESATTAMENTE questo formato JSON (array):
[
  {{
    "keyword": "la keyword usata",
    "title": "Titolo del post (max 58 caratteri)",
    "description": "Descrizione del post (150-300 caratteri, include keyword e CTA)",
    "cta_type": "scegli tra: Learn more, Book, Order online, Call now, Sign up, Get offer"
  }},
  ...
]

Rispondi SOLO con il JSON valido, nessun testo prima o dopo."""

    print("🤖 Chiamo Claude API per generare i post...")

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    # Pulisci il JSON se Claude aggiunge markdown
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    import json
    posts = json.loads(response_text)
    return posts


def salva_csv(posts: list, data_inizio: str, ora: str, frequenza: str, output: str):
    """Salva i post nel CSV con date programmate."""
    start = datetime.strptime(f"{data_inizio} {ora}", "%Y-%m-%d %H:%M")
    delta = timedelta(weeks=1) if frequenza == "settimanale" else timedelta(weeks=2)

    rows = []
    for i, post in enumerate(posts):
        date = start + (delta * i)
        rows.append({
            "title":       post.get("title", ""),
            "description": post.get("description", ""),
            "date":        date.strftime("%Y-%m-%d %H:%M"),
            "image":       "",
            "cta_url":     "",   # ← aggiungi il tuo URL con UTM dopo
            "cta_type":    post.get("cta_type", "Learn more"),
        })

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title","description","date","image","cta_url","cta_type"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def main():
    print(f"\n{'═'*55}")
    print(f"  🚀  Generatore post GBP con Claude API")
    print(f"  📝  Keyword: {len(KEYWORDS)}")
    print(f"  📅  Dal: {DATA_INIZIO} | Frequenza: {FREQUENZA}")
    print(f"{'═'*55}\n")

    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY non trovata!")
        print("   Copia .env.example in .env e inserisci la tua chiave API.")
        print("   Ottienila su: https://console.anthropic.com")
        sys.exit(1)

    # Genera i post con Claude
    posts = genera_post_con_claude(KEYWORDS, BUSINESS_INFO)
    print(f"✅ Claude ha generato {len(posts)} post\n")

    # Salva il CSV
    rows = salva_csv(posts, DATA_INIZIO, ORA_INIZIO, FREQUENZA, OUTPUT_CSV)

    print(f"📄 CSV salvato: {OUTPUT_CSV}\n")
    print("Post generati:")
    for r in rows:
        print(f"  [{r['date'][:10]}] {r['title'][:55]}")

    print(f"\n{'═'*55}")
    print(f"  ✅  Fatto! Ora:")
    print(f"  1. Apri {OUTPUT_CSV} e aggiungi i tuoi URL nella colonna 'cta_url'")
    print(f"  2. (Opzionale) Aggiungi le immagini nella colonna 'image'")
    print(f"  3. Lancia: python3 gbp_scheduler.py")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    main()
