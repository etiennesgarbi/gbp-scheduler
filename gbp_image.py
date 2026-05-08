"""Validazione e preprocessing immagini per GBP."""
import hashlib
from pathlib import Path
from typing import Union

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

CACHE_DIR = Path("cache/images")
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_DIMS = (1200, 900)
MIN_DIMS = (250, 250)


def prepare_image(path: Union[str, Path]) -> Path:
    """
    Valida e preprocessa un'immagine per GBP.
    - Valida formato (JPG/PNG)
    - Se < 250×250: ValueError
    - Se > 1200×900: resize proporzionale
    - Se > 5MB: comprimi progressivamente (quality 85→70→60)
    - Salva in cache/images/{hash}.jpg, ritorna il path
    """
    if not HAS_PILLOW:
        raise ImportError("Pillow non installato. Esegui: pip install pillow")

    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Immagine non trovata: {src}")
    if src.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError(f"Formato non supportato: {src.suffix} (usa JPG/PNG)")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Hash per cache
    h = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    cached = CACHE_DIR / f"{h}.jpg"
    if cached.exists():
        return cached

    with Image.open(src) as img:
        # Converti in RGB se necessario (PNG con trasparenza)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        w, h_img = img.size
        if w < MIN_DIMS[0] or h_img < MIN_DIMS[1]:
            raise ValueError(
                f"Immagine troppo piccola: {w}×{h_img} (min {MIN_DIMS[0]}×{MIN_DIMS[1]})"
            )

        # Resize se troppo grande
        if w > MAX_DIMS[0] or h_img > MAX_DIMS[1]:
            img.thumbnail(MAX_DIMS, Image.LANCZOS)

        # Comprimi progressivamente finché < 5MB
        for quality in (85, 70, 60):
            img.save(cached, "JPEG", quality=quality, optimize=True)
            if cached.stat().st_size <= MAX_SIZE_BYTES:
                break
        else:
            raise ValueError(f"Impossibile comprimere l'immagine sotto 5MB: {src}")

    return cached
