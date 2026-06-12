"""Validazione pre-flight del CSV prima di aprire il browser."""
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

VALID_CTA_TYPES = {"LEARN_MORE", "BOOK", "ORDER", "SHOP", "SIGN_UP", "CALL",
                   "Learn more", "Book", "Order online", "Shop", "Sign up", "Call"}
VALID_POST_TYPES = {"update", "offer"}
URL_RE = re.compile(r"^https://")
URL_IN_TEXT_RE = re.compile(r"https?://")

def validate_csv(path: str) -> list[dict]:
    """
    Valida un file CSV di post GBP.
    Ritorna lista di errori: [{row, field, error}].
    Se path non esiste, ritorna un errore unico.
    """
    errors: list[dict] = []
    p = Path(path)
    if not p.exists():
        return [{"row": 0, "field": "file", "error": f"File non trovato: {path}"}]

    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            title = row.get("title", "").strip()
            desc  = row.get("description", "").strip()
            date  = row.get("date", "").strip()
            image = row.get("image", "").strip()
            cta_url  = row.get("cta_url", "").strip()
            cta_type = row.get("cta_type", "").strip()

            # title
            if not title:
                errors.append({"row": i, "field": "title", "error": "Vuoto"})
            elif len(title) > 58:
                errors.append({"row": i, "field": "title", "error": f"Troppo lungo ({len(title)}/58 char)"})

            # description
            if not desc:
                errors.append({"row": i, "field": "description", "error": "Vuota"})
            elif len(desc) < 150:
                errors.append({"row": i, "field": "description", "error": f"Troppo corta ({len(desc)}/150 char min)"})
            elif len(desc) > 1500:
                errors.append({"row": i, "field": "description", "error": f"Troppo lunga ({len(desc)}/1500 char max)"})
            elif URL_IN_TEXT_RE.search(desc):
                errors.append({"row": i, "field": "description", "error": "Contiene URL nel testo"})

            # date
            if date:
                try:
                    dt = datetime.strptime(date, "%Y-%m-%d %H:%M")
                    if dt < datetime.now():
                        errors.append({"row": i, "field": "date", "error": f"Data nel passato: {date}"})
                except ValueError:
                    errors.append({"row": i, "field": "date", "error": f"Formato non valido (usa YYYY-MM-DD HH:MM): {date}"})

            # image
            if image:
                img_path = Path(image)
                if not img_path.exists():
                    errors.append({"row": i, "field": "image", "error": f"File non trovato: {image}"})
                else:
                    if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                        errors.append({"row": i, "field": "image", "error": "Formato non supportato (usa JPG/PNG)"})
                    size = img_path.stat().st_size
                    if size > 5 * 1024 * 1024:
                        errors.append({"row": i, "field": "image", "error": f"Troppo grande ({size//1024//1024}MB, max 5MB)"})
                    try:
                        from PIL import Image as PILImage
                        with PILImage.open(img_path) as im:
                            w, h = im.size
                            if w < 250 or h < 250:
                                errors.append({"row": i, "field": "image", "error": f"Dimensioni troppo piccole ({w}×{h}, min 250×250)"})
                    except ImportError:
                        pass  # Pillow non installato, skip dimensioni

            # cta_url
            if cta_url and not URL_RE.match(cta_url):
                errors.append({"row": i, "field": "cta_url", "error": f"URL non valido (deve iniziare con https://): {cta_url}"})

            # cta_type
            if cta_type and cta_type not in VALID_CTA_TYPES:
                errors.append({"row": i, "field": "cta_type", "error": f"Tipo non valido: '{cta_type}'. Usa: {', '.join(sorted(VALID_CTA_TYPES))}"})

            # post_type
            post_type = row.get("post_type", "update").strip().lower()
            if post_type and post_type not in VALID_POST_TYPES:
                errors.append({"row": i, "field": "post_type", "error": f"Tipo non valido: '{post_type}'. Usa: update, offer"})

            # offer_end — obbligatoria se post_type == offer
            offer_end = row.get("offer_end", "").strip()
            if post_type == "offer":
                if not offer_end:
                    errors.append({"row": i, "field": "offer_end", "error": "Obbligatoria per post di tipo offer (formato YYYY-MM-DD)"})
                else:
                    try:
                        dt_end = datetime.strptime(offer_end, "%Y-%m-%d")
                        if dt_end < datetime.now():
                            errors.append({"row": i, "field": "offer_end", "error": f"Data fine nel passato: {offer_end}"})
                    except ValueError:
                        errors.append({"row": i, "field": "offer_end", "error": f"Formato non valido (usa YYYY-MM-DD): {offer_end}"})

            # offer_start — opzionale, ma se presente deve essere valida
            offer_start = row.get("offer_start", "").strip()
            if offer_start:
                try:
                    datetime.strptime(offer_start, "%Y-%m-%d")
                except ValueError:
                    errors.append({"row": i, "field": "offer_start", "error": f"Formato non valido (usa YYYY-MM-DD): {offer_start}"})

    return errors

def check_and_exit(path: str) -> None:
    """Valida il CSV ed esce con exit code 1 se ci sono errori."""
    errors = validate_csv(path)
    if errors:
        print(f"\n❌ Validazione CSV fallita: {len(errors)} errori in '{path}'\n")
        print(f"  {'Riga':<6} {'Campo':<15} Errore")
        print(f"  {'-'*6} {'-'*15} {'-'*40}")
        for e in errors:
            print(f"  {e['row']:<6} {e['field']:<15} {e['error']}")
        print()
        sys.exit(1)
    print(f"✅ Validazione CSV OK: '{path}'")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", help="Percorso del CSV da validare")
    args = parser.parse_args()
    check_and_exit(args.csv_file)
