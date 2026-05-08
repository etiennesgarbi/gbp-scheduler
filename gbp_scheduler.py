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
    python gbp_scheduler.py
"""

import asyncio
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright non trovato.")
    print("   Esegui: pip install playwright && playwright install chrome")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURAZIONE — modifica qui prima di lanciare lo script
# ──────────────────────────────────────────────────────────────────────────────
CSV_FILE       = "posts.csv"         # Il tuo CSV con i post
CHROME_PROFILE = "./chrome-profile"  # Profilo Chrome persistente (login una sola volta)
GBP_URL        = "https://business.google.com"
DELAY_POST     = 5                   # Secondi di pausa tra un post e l'altro
HEADLESS       = False               # False = vedi il browser (consigliato)
# ──────────────────────────────────────────────────────────────────────────────

MONTHS_IT = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
    "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}
MONTHS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}


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


async def navigate_calendar(frame, month: int, year: int, max_steps: int = 30):
    """
    Naviga il calendario al mese/anno target.
    Usa force=True per bypassare il tooltip che copre 'Mese successivo'.
    """
    for _ in range(max_steps):
        try:
            header = frame.locator('[role="heading"], [aria-live="polite"]').first
            text = await header.inner_text(timeout=3000)
            parsed = parse_month_header(text)
            if not parsed:
                break
            cur_m, cur_y = parsed
            if cur_m == month and cur_y == year:
                return True

            if (cur_y, cur_m) < (year, month):
                btn = frame.locator(
                    '[aria-label*="next month" i], [aria-label*="mese successivo" i], '
                    'button[data-direction="1"]'
                ).first
            else:
                btn = frame.locator(
                    '[aria-label*="prev month" i], [aria-label*="mese precedente" i], '
                    'button[data-direction="-1"]'
                ).first

            # ⚠️  force=True → bypassa il tooltip che copre il bottone
            await btn.click(force=True)
            await asyncio.sleep(0.4)

        except Exception as e:
            print(f"    ⚠️  Calendario: {e}")
            break
    return False


async def pick_date_time(frame, dt: datetime):
    """Seleziona data e ora nel date picker di GBP."""
    await navigate_calendar(frame, dt.month, dt.year)
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
        print(f"    ⚠️  Giorno {dt.day} non trovato")

    # Imposta l'ora
    for selectors, value in [
        (['input[aria-label*="hour" i]', 'input[placeholder="HH"]', 'input[aria-label*="ora" i]'],
         str(dt.hour).zfill(2)),
        (['input[aria-label*="minute" i]', 'input[placeholder="MM"]', 'input[aria-label*="minuti" i]'],
         str(dt.minute).zfill(2)),
    ]:
        field = await find_el(frame, selectors, timeout=3000)
        if field:
            await field.triple_click()
            await field.fill(value)


async def publish_post(page, post: dict) -> bool:
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
        print("    ⚠️  Descrizione vuota, salto.")
        return False

    try:
        # ── STEP 1: Apri il form "Aggiungi aggiornamento" ─────────────────────
        create_btn = await find_el(page, [
            'button:has-text("Add update")',
            'button:has-text("Aggiungi aggiornamento")',
            '[aria-label*="Add update" i]',
            '[data-item-id="posts"] button',
        ])
        if not create_btn:
            print("    ❌ Bottone 'Aggiungi aggiornamento' non trovato. Sei sulla pagina giusta?")
            return False
        await create_btn.click()
        await asyncio.sleep(2)

        # ── STEP 2: Trova il frame con il form (iframe nascosto) ──────────────
        frame = await get_post_frame(page)
        if not frame:
            print("    ❌ Form iframe non trovato")
            return False

        # ── STEP 3: Compila la descrizione ────────────────────────────────────
        desc_el = await find_el(frame, [
            'textarea[placeholder*="news" i]',
            'textarea[placeholder*="What\'s new" i]',
            'textarea[placeholder*="novità" i]',
            '[contenteditable="true"]',
            'textarea',
        ])
        if desc_el:
            await desc_el.click()
            await desc_el.fill(description)
            await asyncio.sleep(0.3)

        # ── STEP 4: Carica l'immagine ──────────────────────────────────────────
        if image_path and Path(image_path).exists():
            photo_btn = await find_el(frame, [
                'button[aria-label*="photo" i]',
                'button[aria-label*="foto" i]',
                'button:has-text("Add photos")',
                'button:has-text("Aggiungi foto")',
            ], timeout=4000)
            if photo_btn:
                try:
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await photo_btn.click()
                    fc = await fc_info.value
                    await fc.set_files(image_path)
                    await asyncio.sleep(4)  # Attendi il completamento dell'upload
                except Exception as e:
                    print(f"    ⚠️  Upload immagine: {e}")
        elif image_path:
            print(f"    ⚠️  Immagine non trovata: {image_path}")

        # ── STEP 5: Aggiungi CTA con link UTM ──────────────────────────────────
        if cta_url:
            add_btn = await find_el(frame, [
                'button:has-text("Add a button")',
                'button:has-text("Aggiungi un pulsante")',
                '[aria-label*="Add a button" i]',
            ], timeout=4000)
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
                url_field = await find_el(frame, [
                    'input[type="url"]',
                    'input[placeholder*="URL" i]',
                    'input[placeholder*="link" i]',
                    'input[placeholder*="http" i]',
                ], timeout=3000)
                if url_field:
                    await url_field.fill(cta_url)
                    await asyncio.sleep(0.3)

        # ── STEP 6: Programma la data (se fornita nel CSV) ─────────────────────
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")

                # Clicca "Programma per" / "Schedule for"
                sched_el = await find_el(frame, [
                    'input[value*="SCHEDULED" i]',
                    'input[value*="schedule" i]',
                    'label:has-text("Schedule")',
                    'label:has-text("Programma")',
                    '[aria-label*="Schedule for" i]',
                ], timeout=4000)
                if sched_el:
                    await sched_el.click()
                    await asyncio.sleep(0.5)
                    await pick_date_time(frame, dt)
                else:
                    print("    ⚠️  Opzione 'Programma' non trovata, pubblico subito")

            except ValueError:
                print(f"    ⚠️  Formato data non valido: '{date_str}' (usa YYYY-MM-DD HH:MM)")

        # ── STEP 7: Clicca "Pubblica" / "Programma" ────────────────────────────
        publish_btn = await find_el(frame, [
            'button:has-text("Schedule")',
            'button:has-text("Programma")',
            'button:has-text("Publish")',
            'button:has-text("Pubblica")',
            'button[type="submit"]',
        ], timeout=5000)

        if publish_btn:
            await publish_btn.click()
            await asyncio.sleep(3)
            print(f"    ✅ Pubblicato: {(title or description)[:55]}")
            return True
        else:
            print("    ❌ Bottone 'Pubblica' non trovato")
            await page.screenshot(path=f"debug_{datetime.now().strftime('%H%M%S')}.png")
            return False

    except Exception as e:
        print(f"    ❌ Errore imprevisto: {e}")
        try:
            await page.screenshot(path=f"debug_error_{datetime.now().strftime('%H%M%S')}.png")
        except Exception:
            pass
        return False


async def main():
    # ── Leggi il CSV ──────────────────────────────────────────────────────────
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        print(f"❌ File non trovato: {CSV_FILE}")
        print("   Crea 'posts.csv' con colonne: title, description, date, image, cta_url, cta_type")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as f:
        posts = [r for r in csv.DictReader(f) if r.get("description", "").strip()]

    total = len(posts)
    if total == 0:
        print("❌ Nessun post valido nel CSV.")
        sys.exit(1)

    est_min = total * 50 // 60
    print(f"\n{'═'*55}")
    print(f"  📋  Post trovati: {total}")
    print(f"  ⏱️   Tempo stimato: ~{est_min} min ({total} × ~50 sec)")
    print(f"  📁  Profilo Chrome: {Path(CHROME_PROFILE).resolve()}")
    print(f"{'═'*55}\n")

    async with async_playwright() as p:
        # ── Lancia Chrome con profilo persistente ─────────────────────────────
        #    channel="chrome"                → usa Chrome di sistema (non Chromium)
        #                                      Senza questo, Google blocca il login
        #                                      con "browser potrebbe non essere sicuro"
        #    launch_persistent_context()     → salva la sessione su disco
        #                                      Login una sola volta → valido per sempre
        context = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
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
            print("⚠️  Non sei loggato.")
            print("   Accedi a Google nel browser aperto, poi torna qui e premi INVIO.")
            input()
            await page.goto(GBP_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)

        print("ℹ️  Assicurati di essere sulla pagina della sede GBP corretta.")
        print("   Premi INVIO per iniziare...\n")
        input()

        # ── Loop principale sui post ───────────────────────────────────────────
        ok_count   = 0
        fail_count = 0

        for i, post in enumerate(posts, 1):
            preview = (post.get("title") or post.get("description", "Senza titolo"))[:45]
            print(f"[{i:>3}/{total}] 📝  {preview}")

            success = await publish_post(page, post)
            if success:
                ok_count += 1
            else:
                fail_count += 1

            # Torna alla home GBP e aspetta prima del post successivo
            await page.goto(GBP_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(DELAY_POST)

        # ── Report finale ──────────────────────────────────────────────────────
        print(f"\n{'═'*55}")
        print(f"  🏁  COMPLETATO")
        print(f"  ✅  Pubblicati: {ok_count}")
        print(f"  ❌  Falliti:    {fail_count}")
        print(f"  📝  Totale:     {total}")
        print(f"{'═'*55}\n")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
