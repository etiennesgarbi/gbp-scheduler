"""
Generazione contenuti GBP via Anthropic SDK.
Sostituisce subprocess claude -p usato in gbp_multi.py.
"""
import csv
import json
import os
import re as _re
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Inizializza il client Anthropic (lazy singleton)."""
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY non trovata in .env")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _parse_json(text: str) -> list[dict]:
    """Estrae JSON da una risposta che potrebbe contenere markdown."""
    # Prova JSON diretto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Cerca blocco ```json ... ``` o ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if match:
        return json.loads(match.group(1))
    raise ValueError(f"Nessun JSON valido trovato nella risposta:\n{text[:200]}")


import re


def _validate_posts(posts: Any) -> list[dict]:
    """Valida la struttura della lista di post generati."""
    if not isinstance(posts, list):
        raise ValueError("La risposta deve essere una lista JSON")
    required = {"title", "description", "cta_type"}
    for i, p in enumerate(posts):
        if not isinstance(p, dict):
            raise ValueError(f"Post {i}: deve essere un oggetto")
        missing = required - p.keys()
        if missing:
            raise ValueError(f"Post {i}: campi mancanti {missing}")
    return posts


def generate_posts(
    nome: str,
    citta: str,
    quartiere: str,
    keywords: str,
    cta_url: str,
    data_inizio: str,
    n: int = 12,
) -> list[dict]:
    """
    Genera n post GBP per una sede usando l'Anthropic SDK.
    Ritorna lista di dict con chiavi: title, description, date, image, cta_url, cta_type.
    Riprova fino a 2 volte se il JSON non è valido.
    """
    client = _get_client()
    system = (
        "Sei un esperto di local SEO e marketing per ristoranti italiani. "
        "Rispondi SEMPRE e SOLO con un array JSON valido, senza testo prima o dopo, "
        "senza blocchi markdown. Il JSON deve essere parsabile direttamente con json.loads()."
    )
    user = (
        f"Genera esattamente {n} post GBP per '{nome}', ristorante di pasta fresca "
        f"a {quartiere}, {citta}. Keywords: {keywords}. "
        f"Regole: title max 58 char, description 150-300 char con CTA finale, "
        f"nessun URL nella description. "
        f"Date settimanali a partire da {data_inizio} alle 10:00 (formato YYYY-MM-DD HH:MM). "
        f"cta_url per tutti: {cta_url}. "
        f"cta_type: usa LEARN_MORE, BOOK, ORDER, SHOP o SIGN_UP. "
        f"Colonna image: lascia stringa vuota. "
        f"Formato risposta: array JSON con oggetti aventi chiavi: "
        f"title, description, date, image, cta_url, cta_type."
    )

    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            msg = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = msg.content[0].text
            posts = _parse_json(raw)
            return _validate_posts(posts)
        except Exception as e:
            last_error = e
            if attempt < 2:
                continue
    raise RuntimeError(f"Generazione fallita dopo 2 tentativi: {last_error}")


def generate_and_save_csv(
    nome: str,
    citta: str,
    quartiere: str,
    keywords: str,
    cta_url: str,
    data_inizio: str,
    n: int = 12,
) -> str:
    """
    Genera i post e li salva in posts_{slug}.csv.
    Ritorna il path del file salvato.
    """
    posts = generate_posts(nome, citta, quartiere, keywords, cta_url, data_inizio, n)
    slug = nome.replace(" ", "_").replace("|", "").replace("/", "").lower().strip("_")
    output = f"posts_{slug}.csv"
    fieldnames = ["title", "description", "date", "image", "cta_url", "cta_type"]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(posts)
    return output


def slugify(text: str, max_len: int = 50) -> str:
    """Converte testo in slug URL-safe."""
    text = text.lower().strip()
    text = _re.sub(r"[àáâãäå]", "a", text)
    text = _re.sub(r"[èéêë]", "e", text)
    text = _re.sub(r"[ìíîï]", "i", text)
    text = _re.sub(r"[òóôõö]", "o", text)
    text = _re.sub(r"[ùúûü]", "u", text)
    text = _re.sub(r"[^a-z0-9\s-]", "", text)
    text = _re.sub(r"[\s_-]+", "-", text)
    text = text.strip("-")
    return text[:max_len]


def build_utm_url(
    base_url: str,
    location_name: str,
    post_title: str,
    primary_keyword: str,
) -> str:
    """
    Costruisce URL con parametri UTM standardizzati.
    utm_source=gbp, utm_medium=post, utm_campaign={location_slug},
    utm_content={post_slug}, utm_term={keyword_slug}
    """
    location_slug = slugify(location_name)
    post_slug = slugify(post_title, max_len=30)
    keyword_slug = slugify(primary_keyword.split(",")[0].strip())
    separator = "&" if "?" in base_url else "?"
    return (
        f"{base_url}{separator}"
        f"utm_source=gbp&utm_medium=post"
        f"&utm_campaign={location_slug}"
        f"&utm_content={post_slug}"
        f"&utm_term={keyword_slug}"
    )
