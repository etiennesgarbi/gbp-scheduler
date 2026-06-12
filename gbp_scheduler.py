#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║     GBP Post Scheduler - Basato sul metodo di Luigi Virginio     ║
║                     luigivirginio.com                            ║
╚══════════════════════════════════════════════════════════════════╝

Automatizza la programmazione di post su Google Business Profile.
Lo script legge un CSV e pubblica ogni post automaticamente (~50 sec/post).

SETUP:
    pip install playwright
    playwright install chrome

USO:
    python gbp_scheduler.py --client <slug>
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
from gbp_image import prepare_image

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright non trovato.")
    print("   Esegui: pip install playwright && playwright install chrome")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURAZIONE — usa .env per sovrascrivere i valori di default
# ──────────────────────────────────────────────────────────────────────────────
CSV_FILE       = os.getenv("GBP_CSV_FILE", "posts.csv")
CHROME_PROFILE = os.getenv("GBP_CHROME_PROFILE", "./chrome-profile")
GBP_URL        = "https://business.google.com"
DELAY_POST     = int(os.getenv("GBP_DELAY_POST", "5"))
HEADLESS       = os.getenv("GBP_HEADLESS", "false").lower() == "true"
# ──────────────────────────────────────────────────────────────────────────────

MONTHS_IT = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
    "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}
MONTHS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}


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
    """
    Trova il frame (iframe) che contiene il form del post.
    Il modulo GBP è annidato dentro un iframe nascosto → usa .nth(1).
    """
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
    """
    Naviga il calendario al mese/anno target.
    Usa force=True per bypassare il tooltip che copre 'Mese successivo'.
    """
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

            # ⚠️  force=True → bypassa il tooltip che copre il bottone
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

    # Clicca il giorno corretto (i giorni del mese precedente sono duplicati
    # nella griglia, quindi usiamo attributi data specifici quando possibile)
    day_btn = await find_el(frame, [
        f'button[data-date*="{dt.year}-{str(dt.month).zfill(2)}-{str(dt.day).zfill(2)}"]',
        f'[data-day="{dt.day}"]:not([aria-disabled="true"])',
        f'td[aria-label*=" {dt.day},"] button',
    ], timeout=5000)

    if day_btn:
        await day_btn.click()
        await asyncio.sleep(0.3)
    else:
        logger.warning(f"    ⚠️  Giorno {dt.day} non trovato")

    # Imposta l'ora
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
    post_type   = post.get("post_type", "update").strip().lower()
    offer_start = post.get("offer_start", "").strip()
    offer_end   = post.get("offer_end", "").strip()
    coupon_code = post.get("coupon_code", "").strip()

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
        # ── STEP 1: Apri il form "Aggiungi aggiornamento" ─────────────────────
        create_btn = await find_el(page, SELECTORS["ADD_UPDATE_BUTTON"])
        if not create_btn:
            msg = "Bottone 'Aggiungi aggiornamento' non trovato. Sei sulla pagina giusta?"
            logger.error(f"    ❌ {msg}")
            await save_failure_artifacts(msg)
            return False
        await create_btn.click()
        await asyncio.sleep(2)

        # ── STEP 2: Trova il frame con il form (iframe nascosto) ──────────────
        frame = await get_post_frame(page)
        if not frame:
            msg = "Form iframe non trovato"
            logger.error(f"    ❌ {msg}")
            await save_failure_artifacts(msg)
            return False

        # ── STEP 2b: Seleziona il tipo post (Offer se richiesto) ──────────────
        if post_type == "offer":
            offer_tab = await find_el(frame, SELECTORS["OFFER_TAB"], timeout=4000)
            if offer_tab:
                await offer_tab.click()
                await asyncio.sleep(1)
                logger.debug("    Tipo post: Offer")
            else:
                logger.warning("    ⚠️  Tab Offer non trovato, procedo come Update")

        # ── STEP 3: Compila titolo (obbligatorio per Offer, opzionale per Update)
        if title:
            title_el = await find_el(frame, SELECTORS["OFFER_TITLE_INPUT"] if post_type == "offer" else [], timeout=2000)
            if title_el:
                await title_el.click()
                await title_el.fill(title)
                await asyncio.sleep(0.3)

        # ── STEP 3b: Compila la descrizione ───────────────────────────────────
        desc_el = await find_el(frame, SELECTORS["DESCRIPTION_TEXTAREA"])
        if desc_el:
            await desc_el.click()
            await desc_el.fill(description)
            await asyncio.sleep(0.3)

        # ── STEP 4: Carica l'immagine ──────────────────────────────────────────
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
                    await asyncio.sleep(4)  # Attendi il completamento dell'upload
                except Exception as e:
                    logger.warning(f"    ⚠️  Upload immagine: {e}")

        # ── STEP 5: Aggiungi CTA con link UTM ──────────────────────────────────
        if cta_url:
            add_btn = await find_el(frame, SELECTORS["CTA_BUTTON"], timeout=4000)
            if add_btn:
                await add_btn.click()
                await asyncio.sleep(0.5)

                # Seleziona tipo di CTA (es. "Learn more", "Order online", ecc.)
                cta_opt = await find_el(frame, [
                    f'[value="{cta_type}"]',
                    f'option:has-text("{cta_type}")',
                    f'li:has-text("{cta_type}")',
                    f'[aria-label="{cta_type}"]',
                ], timeout=3000)
                if cta_opt:
                    await cta_opt.click()
                    await asyncio.sleep(0.3)

                # Inserisci l'URL (con parametri UTM)
                url_field = await find_el(frame, SELECTORS["CTA_URL_INPUT"], timeout=3000)
                if url_field:
                    await url_field.fill(cta_url)
                    await asyncio.sleep(0.3)

        # ── STEP 5b: Date e coupon per post Offer ─────────────────────────────
        if post_type == "offer":
            # Data inizio offerta
            if offer_start:
                try:
                    dt_s = datetime.strptime(offer_start, "%Y-%m-%d")
                    start_el = await find_el(frame, SELECTORS["OFFER_START_DATE"], timeout=3000)
                    if start_el:
                        await start_el.triple_click()
                        await start_el.fill(dt_s.strftime("%m/%d/%Y"))
                        await asyncio.sleep(0.3)
                except ValueError:
                    logger.warning(f"    ⚠️  offer_start formato non valido: {offer_start}")

            # Data fine offerta
            if offer_end:
                try:
                    dt_e = datetime.strptime(offer_end, "%Y-%m-%d")
                    end_el = await find_el(frame, SELECTORS["OFFER_END_DATE"], timeout=3000)
                    if end_el:
                        await end_el.triple_click()
                        await end_el.fill(dt_e.strftime("%m/%d/%Y"))
                        await asyncio.sleep(0.3)
                        logger.debug(f"    Data fine offerta: {offer_end}")
                except ValueError:
                    logger.warning(f"    ⚠️  offer_end formato non valido: {offer_end}")

            # Codice coupon opzionale
            if coupon_code:
                coupon_el = await find_el(frame, SELECTORS["OFFER_COUPON_INPUT"], timeout=3000)
                if coupon_el:
                    await coupon_el.fill(coupon_code)
                    await asyncio.sleep(0.3)

        # ── STEP 6: Programma la data (se fornita nel CSV) ─────────────────────
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")

                # Clicca "Programma per" / "Schedule for"
                sched_el = await find_el(frame, SELECTORS["SCHEDULE_TOGGLE"], timeout=4000)
                if sched_el:
                    await sched_el.click()
                    await asyncio.sleep(0.5)
                    await pick_date_time(frame, dt, logger)
                else:
                    logger.warning("    ⚠️  Opzione 'Programma' non trovata, pubblico subito")

            except ValueError:
                logger.warning(f"    ⚠️  Formato data non valido: '{date_str}' (usa YYYY-MM-DD HH:MM)")

        # ── STEP 7: Clicca "Pubblica" / "Programma" ────────────────────────────
        publish_btn = await find_el(frame, SELECTORS["PUBLISH_BUTTON"], timeout=5000)

        if publish_btn:
            await publish_btn.click()
            await asyncio.sleep(3)
            logger.info(f"    ✅ Pubblicato: {(title or description)[:55]}")
            return True
        else:
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


async def main():
    parser = argparse.ArgumentParser(description="GBP Post Scheduler")
    parser.add_argument("--client", default="default", help="Slug del cliente (es. miscusi)")
    parser.add_argument("--csv", default=os.getenv("GBP_CSV_FILE", "posts.csv"), help="Percorso CSV")
    args = parser.parse_args()
    client_slug = args.client
    csv_file_arg = args.csv
    chrome_profile_dir = f"./profiles/{client_slug}"

    check_and_exit(csv_file_arg)

    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    logger = setup_logging(run_ts)

    # ── Leggi il CSV ──────────────────────────────────────────────────────────
    csv_path = Path(csv_file_arg)
    if not csv_path.exists():
        logger.error(f"❌ File non trovato: {csv_file_arg}")
        logger.error("   Crea 'posts.csv' con colonne: title, description, date, image, cta_url, cta_type")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as f:
        posts = [r for r in csv.DictReader(f) if r.get("description", "").strip()]

    gbp_state.load_state(csv_file_arg, "single", posts)

    total = len(posts)
    if total == 0:
        logger.error("❌ Nessun post valido nel CSV.")
        sys.exit(1)

    est_min = total * 50 // 60
    logger.info(f"\n{'═'*55}")
    logger.info(f"  📋  Post trovati: {total}")
    logger.info(f"  ⏱️   Tempo stimato: ~{est_min} min ({total} × ~50 sec)")
    logger.info(f"  📁  Profilo Chrome: {Path(chrome_profile_dir).resolve()}")
    logger.info(f"{'═'*55}\n")

    async with async_playwright() as p:
        # ── Lancia Chrome con profilo persistente ─────────────────────────────
        #    channel="chrome"                → usa Chrome di sistema (non Chromium)
        #                                      Senza questo, Google blocca il login
        #                                      con "browser potrebbe non essere sicuro"
        #    launch_persistent_context()     → salva la sessione su disco
        #                                      Login una sola volta → valido per sempre
        context = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile_dir,
            channel="chrome",
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            viewport={"width": 1280, "height": 900},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # ── Controlla il login ─────────────────────────────────────────────────
        await page.goto(GBP_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            logger.warning("⚠️  Non sei loggato.")
            logger.info("   Accedi a Google nel browser aperto, poi torna qui e premi INVIO.")
            input()
            await page.goto(GBP_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)

        logger.info("ℹ️  Assicurati di essere sulla pagina della sede GBP corretta.")
        logger.info("   Premi INVIO per iniziare...\n")
        input()

        # ── Loop principale sui post ───────────────────────────────────────────
        ok_count   = 0
        fail_count = 0

        for i, post in enumerate(posts, 1):
            preview = (post.get("title") or post.get("description", "Senza titolo"))[:45]
            post_id = gbp_state.make_post_id(post.get("title",""), post.get("date",""), "single")

            if gbp_state.is_done(post_id):
                logger.info(f"[{i:>3}/{total}] ⏭️  Già pubblicato, salto: {preview}")
                continue

            logger.info(f"[{i:>3}/{total}] 📝  {preview}")

            success = await publish_with_retry(page, post, post_id, logger, run_ts, "single", i)
            if success:
                ok_count += 1
            else:
                fail_count += 1

            # Torna alla home GBP e aspetta prima del post successivo
            await page.goto(GBP_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(DELAY_POST)

        # ── Report finale ──────────────────────────────────────────────────────
        logger.info(f"\n{'═'*55}")
        logger.info(f"  🏁  COMPLETATO")
        logger.info(f"  ✅  Pubblicati: {ok_count}")
        logger.info(f"  ❌  Falliti:    {fail_count}")
        logger.info(f"  📝  Totale:     {total}")
        logger.info(f"{'═'*55}\n")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
