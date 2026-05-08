#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         GBP Multi-Sede Scheduler                                 ║
║  Legge ristoranti.csv e pubblica post su ogni sede GBP           ║
╚══════════════════════════════════════════════════════════════════╝

FLUSSO:
  1. Legge ristoranti.csv (lista sedi + keyword + cta_url)
  2. Per ogni sede: genera posts_[nome].csv con Claude SDK
  3. Naviga al profilo GBP della sede
  4. Pubblica tutti i post

SETUP:
    pip install playwright
    python3 -m playwright install chrome

USO:
    python gbp_multi.py --client <slug>
"""

import argparse
import asyncio
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import gbp_state
from gbp_validate import check_and_exit
from gbp_selectors import SELECTORS
from gbp_generator import generate_and_save_csv, generate_posts, build_utm_url
from gbp_image import prepare_image

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Esegui: pip install playwright && python3 -m playwright install chrome")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
RISTORANTI_CSV  = "ristoranti.csv"
CHROME_PROFILE  = os.getenv("GBP_CHROME_PROFILE", "./chrome-profile")
GBP_LOCATIONS   = "https://business.google.com/locations"
DATA_INIZIO     = os.getenv("GBP_DATA_INIZIO", "2026-05-05")
DELAY_POST      = int(os.getenv("GBP_DELAY_POST", "5"))
HEADLESS        = os.getenv("GBP_HEADLESS", "false").lower() == "true"
# ──────────────────────────────────────────────────────────────────

MONTHS_IT = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
             "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
MONTHS_EN = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
             "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}


def setup_logging(run_ts: str) -> logging.Logger:
    """Configura logging: console INFO + file DEBUG."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"gbp_{run_ts[:10]}.log"

    logger = logging.getLogger("gbp")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # Console: INFO
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)

        # File: DEBUG
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)

    return logger


def parse_month_header(text: str):
    """Converte 'April 2026' o 'Aprile 2026' → (mese, anno)"""
    parts = text.strip().lower().split()
    if len(parts) < 2:
        return None
    month = MONTHS_EN.get(parts[0]) or MONTHS_IT.get(parts[0])
    try:
        return (month, int(parts[-1])) if month else None
    except ValueError:
        return None


async def find_el(ctx, selectors: list, timeout: int = 6000):
    """Prova più selettori, ritorna il primo visibile."""
    chunk = max(1, timeout // len(selectors))
    for sel in selectors:
        try:
            el = ctx.locator(sel).first
            await el.wait_for(state="visible", timeout=chunk)
            return el
        except PlaywrightTimeout:
            continue
    return None


async def get_post_frame(page):
    """Trova il frame (iframe) che contiene il form del post."""
    for idx in [1, 0, 2]:
        try:
            iframe = page.locator("iframe").nth(idx)
            await iframe.wait_for(state="attached", timeout=3000)
            frame = await iframe.content_frame()
            if frame:
                await frame.locator("textarea, [contenteditable]").first.wait_for(timeout=2000)
                return frame
        except Exception:
            continue
    return None


async def navigate_calendar(frame, month: int, year: int, logger: logging.Logger, max_steps: int = 30):
    """Naviga il calendario al mese/anno target."""
    for _ in range(max_steps):
        try:
            header = frame.locator(", ".join(SELECTORS["CALENDAR_HEADING"])).first
            text = await header.inner_text(timeout=3000)
            parsed = parse_month_header(text)
            if not parsed:
                break
            cur_m, cur_y = parsed
            if cur_m == month and cur_y == year:
                return True
            if (cur_y, cur_m) < (year, month):
                btn = frame.locator(", ".join(SELECTORS["NEXT_MONTH_BTN"])).first
            else:
                btn = frame.locator(", ".join(SELECTORS["PREV_MONTH_BTN"])).first
            await btn.click(force=True)
            await asyncio.sleep(0.4)
        except Exception as e:
            logger.warning(f"    ⚠️  Calendario: {e}")
            break
    return False


async def pick_date_time(frame, dt: datetime, logger: logging.Logger):
    """Seleziona data e ora nel date picker di GBP."""
    await navigate_calendar(frame, dt.month, dt.year, logger)
    await asyncio.sleep(0.3)
    day_btn = await find_el(frame, [
        f'button[data-date*="{dt.year}-{str(dt.month).zfill(2)}-{str(dt.day).zfill(2)}"]',
        f'[data-day="{dt.day}"]:not([aria-disabled="true"])',
    ], timeout=5000)
    if day_btn:
        await day_btn.click()
        await asyncio.sleep(0.3)
    else:
        logger.warning(f"    ⚠️  Giorno {dt.day} non trovato")
    for selectors, value in [
        (SELECTORS["HOUR_INPUT"], str(dt.hour).zfill(2)),
        (SELECTORS["MINUTE_INPUT"], str(dt.minute).zfill(2)),
    ]:
        field = await find_el(frame, selectors, timeout=3000)
        if field:
            await field.triple_click()
            await field.fill(value)


async def publish_post(
    page,
    post: dict,
    logger: logging.Logger,
    run_ts: str,
    location: str,
    index: int,
) -> bool:
    """
    Pubblica o programma un singolo post su GBP.
    Colonne CSV: title, description, date (YYYY-MM-DD HH:MM), image, cta_url, cta_type
    """
    title       = post.get("title", "").strip()
    description = post.get("description", "").strip()
    date_str    = post.get("date", "").strip()
    image_path  = post.get("image", "").strip()
    cta_url     = post.get("cta_url", "").strip()
    cta_type    = post.get("cta_type", "Learn more").strip()

    if not description:
        logger.warning("    ⚠️  Descrizione vuota, salto.")
        return False

    slug = (title or description)[:30].replace(" ", "_").replace("/", "-")

    async def save_failure_artifacts(reason: str) -> None:
        """Salva screenshot e error.txt in caso di fallimento."""
        artifact_dir = Path("logs") / f"run_{run_ts}" / location / f"{index}_{slug}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(artifact_dir / "screenshot.png"))
            logger.debug(f"    Screenshot salvato: {artifact_dir}/screenshot.png")
        except Exception as ss_err:
            logger.debug(f"    Screenshot fallito: {ss_err}")
        (artifact_dir / "error.txt").write_text(reason, encoding="utf-8")

    try:
        create_btn = await find_el(page, SELECTORS["ADD_UPDATE_BUTTON"])
        if not create_btn:
            msg = "Bottone 'Aggiungi aggiornamento' non trovato"
            logger.error(f"    ❌ {msg}")
            await save_failure_artifacts(msg)
            return False
        await create_btn.click()
        await asyncio.sleep(2)

        frame = await get_post_frame(page)
        if not frame:
            msg = "Form iframe non trovato"
            logger.error(f"    ❌ {msg}")
            await save_failure_artifacts(msg)
            return False

        desc_el = await find_el(frame, SELECTORS["DESCRIPTION_TEXTAREA"])
        if desc_el:
            await desc_el.click()
            await desc_el.fill(description)
            await asyncio.sleep(0.3)

        if image_path:
            try:
                image_path = str(prepare_image(image_path))
            except Exception as img_err:
                logger.warning(f"    ⚠️  Preprocessing immagine fallito: {img_err}")
                image_path = ""
        if image_path and Path(image_path).exists():
            photo_btn = await find_el(frame, SELECTORS["PHOTO_BUTTON"], timeout=4000)
            if photo_btn:
                try:
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await photo_btn.click()
                    fc = await fc_info.value
                    await fc.set_files(image_path)
                    await asyncio.sleep(4)
                except Exception as e:
                    logger.warning(f"    ⚠️  Immagine: {e}")

        if cta_url:
            add_btn = await find_el(frame, SELECTORS["CTA_BUTTON"], timeout=4000)
            if add_btn:
                await add_btn.click()
                await asyncio.sleep(0.5)
                url_field = await find_el(frame, SELECTORS["CTA_URL_INPUT"], timeout=3000)
                if url_field:
                    await url_field.fill(cta_url)
                    await asyncio.sleep(0.3)

        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                sched_el = await find_el(frame, SELECTORS["SCHEDULE_TOGGLE"], timeout=4000)
                if sched_el:
                    await sched_el.click()
                    await asyncio.sleep(0.5)
                    await pick_date_time(frame, dt, logger)
                else:
                    logger.warning("    ⚠️  Opzione 'Programma' non trovata, pubblico subito")
            except ValueError:
                logger.warning(f"    ⚠️  Formato data non valido: {date_str}")

        publish_btn = await find_el(frame, SELECTORS["PUBLISH_BUTTON"], timeout=5000)
        if publish_btn:
            await publish_btn.click()
            await asyncio.sleep(3)
            logger.info(f"    ✅ Pubblicato: {(title or description)[:55]}")
            return True
        msg = "Bottone 'Pubblica' non trovato"
        logger.error(f"    ❌ {msg}")
        await save_failure_artifacts(msg)
        return False

    except Exception as e:
        msg = f"Errore imprevisto: {e}"
        logger.error(f"    ❌ {msg}")
        await save_failure_artifacts(msg)
        return False


async def publish_with_retry(
    page,
    post: dict,
    post_id: str,
    logger: logging.Logger,
    run_ts: str,
    location: str,
    index: int,
    max_attempts: int = 3,
) -> bool:
    """
    Tenta di pubblicare un post con backoff esponenziale.
    Attese: 5s dopo il 1° fallimento, 15s dopo il 2°.
    """
    delays = [0, 5, 15]
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            wait = delays[attempt - 1]
            logger.warning(f"    ⏳ Tentativo {attempt}/{max_attempts} dopo {wait}s...")
            await asyncio.sleep(wait)
            await page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2)
        success = await publish_post(page, post, logger, run_ts, location, index)
        if success:
            gbp_state.update_post(post_id, "published")
            return True
    gbp_state.update_post(post_id, "failed", error=f"Fallito dopo {max_attempts} tentativi")
    return False


def genera_csv_per_sede(nome: str, citta: str, quartiere: str, keywords: str, cta_url: str, data_inizio: str, logger: logging.Logger) -> str | None:
    """
    Genera il CSV dei post per una sede tramite Anthropic SDK.
    Applica UTM auto-generati a ciascun cta_url prima di salvare.
    """
    import csv as csv_module
    logger.info(f"  🤖 Anthropic SDK genera post per {nome}...")
    try:
        posts = generate_posts(nome, citta, quartiere, keywords, cta_url, data_inizio)
        primary_keyword = keywords.split(",")[0].strip() if keywords else nome

        # Applica UTM a ogni post
        for post in posts:
            base = post.get("cta_url") or cta_url
            if base:
                post["cta_url"] = build_utm_url(base, nome, post.get("title", ""), primary_keyword)

        slug = nome.replace(" ", "_").replace("|", "").replace("/", "").lower().strip("_")
        output_csv = f"posts_{slug}.csv"
        fieldnames = ["title", "description", "date", "image", "cta_url", "cta_type"]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv_module.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(posts)

        logger.info(f"  ✅ CSV salvato: {output_csv}")
        return output_csv
    except Exception as e:
        logger.error(f"  ❌ Errore generazione CSV: {e}")
        return None


async def processa_sede(page, ristorante: dict, csv_file: str, logger: logging.Logger, run_ts: str) -> tuple[int, int]:
    """Naviga al profilo GBP della sede e pubblica i post."""
    nome = ristorante["nome"]

    # ── Seleziona la sede dalla lista locations ──────────────────────
    await page.goto(GBP_LOCATIONS, wait_until="domcontentloaded")
    await asyncio.sleep(2)

    sede_link = await find_el(page, [
        f'a:has-text("{nome}")',
        f'[aria-label*="{nome}" i]',
        f'td:has-text("{nome}")',
    ], timeout=8000)

    if sede_link:
        await sede_link.click()
        await asyncio.sleep(2)
    else:
        logger.warning(f"  ⚠️  Sede '{nome}' non trovata automaticamente.")
        logger.info(f"  👆 Selezionala manualmente nel browser, poi premi INVIO...")
        input()

    # ── Leggi e pubblica i post ──────────────────────────────────────
    with open(csv_file, newline="", encoding="utf-8") as f:
        posts = [r for r in csv.DictReader(f) if r.get("description", "").strip()]

    gbp_state.load_state(csv_file, nome, posts)

    total = len(posts)
    ok = fail = 0
    for i, post in enumerate(posts, 1):
        preview = post.get("title", post.get("description", ""))[:45]
        post_id = gbp_state.make_post_id(post.get("title", ""), post.get("date", ""), nome)

        if gbp_state.is_done(post_id):
            logger.info(f"    [{i}/{total}] ⏭️  Già pubblicato, salto: {preview}")
            continue

        logger.info(f"    [{i}/{total}] {preview}")
        success = await publish_with_retry(page, post, post_id, logger, run_ts, nome, i)
        if success:
            ok += 1
        else:
            fail += 1
        await page.goto(GBP_LOCATIONS, wait_until="domcontentloaded")
        await asyncio.sleep(DELAY_POST)
        # Riseleziona la sede
        sede_link = await find_el(page, [f'a:has-text("{nome}")'], timeout=5000)
        if sede_link:
            await sede_link.click()
            await asyncio.sleep(2)

    return ok, fail


async def main():
    parser = argparse.ArgumentParser(description="GBP Post Scheduler")
    parser.add_argument("--client", default="default", help="Slug del cliente (es. miscusi)")
    parser.add_argument("--csv", default=os.getenv("GBP_CSV_FILE", "posts.csv"), help="Percorso CSV (solo gbp_scheduler)")
    args = parser.parse_args()
    client_slug = args.client
    chrome_profile_dir = f"./profiles/{client_slug}"

    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    logger = setup_logging(run_ts)

    if not Path(RISTORANTI_CSV).exists():
        logger.error(f"❌ File non trovato: {RISTORANTI_CSV}")
        sys.exit(1)

    with open(RISTORANTI_CSV, newline="", encoding="utf-8") as f:
        ristoranti = list(csv.DictReader(f))

    logger.info(f"\n{'═'*55}")
    logger.info(f"  🏪  Sedi trovate: {len(ristoranti)}")
    logger.info(f"  📅  Data inizio: {DATA_INIZIO}")
    logger.info(f"{'═'*55}\n")

    # ── FASE 1: Genera CSV per ogni sede con Claude Code ─────────────
    csv_files = {}
    for r in ristoranti:
        csv_file = genera_csv_per_sede(
            r["nome"], r["citta"], r["quartiere"],
            r["keywords"], r["cta_url"], DATA_INIZIO,
            logger,
        )
        if csv_file:
            check_and_exit(csv_file)
            csv_files[r["nome"]] = csv_file

    if not csv_files:
        logger.error("❌ Nessun CSV generato. Controlla Claude Code.")
        sys.exit(1)

    logger.info(f"\n✅ CSV generati per {len(csv_files)} sedi. Pronti per pubblicare.\n")

    # ── FASE 2: Pubblica su GBP per ogni sede ────────────────────────
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile_dir,
            channel="chrome",
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://business.google.com", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            logger.warning("⚠️  Fai il login Google nel browser, poi premi INVIO.")
            input()

        total_ok = total_fail = 0
        for r in ristoranti:
            nome = r["nome"]
            if nome not in csv_files:
                logger.info(f"\n⏭️  Salto {nome} (CSV non generato)")
                continue
            logger.info(f"\n{'─'*55}")
            logger.info(f"  📍  {nome} — {r['quartiere']}, {r['citta']}")
            logger.info(f"{'─'*55}")
            ok, fail = await processa_sede(page, r, csv_files[nome], logger, run_ts)
            total_ok += ok
            total_fail += fail
            logger.info(f"  ✅ {ok} pubblicati  ❌ {fail} falliti")

        logger.info(f"\n{'═'*55}")
        logger.info(f"  🏁  COMPLETATO")
        logger.info(f"  ✅  Totale pubblicati: {total_ok}")
        logger.info(f"  ❌  Totale falliti:    {total_fail}")
        logger.info(f"{'═'*55}\n")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
