#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         GBP Multi-Sede Scheduler                                 ║
║  Legge ristoranti.csv e pubblica post su ogni sede GBP           ║
╚══════════════════════════════════════════════════════════════════╝

FLUSSO:
  1. Legge ristoranti.csv (lista sedi + keyword + cta_url)
  2. Per ogni sede: genera posts_[nome].csv con Claude Code
  3. Naviga al profilo GBP della sede
  4. Pubblica tutti i post

SETUP:
    pip install playwright
    python3 -m playwright install chrome

USO:
    python gbp_multi.py
"""

import asyncio
import csv
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

import gbp_state
from gbp_validate import check_and_exit

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Esegui: pip install playwright && python3 -m playwright install chrome")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────
RISTORANTI_CSV  = "ristoranti.csv"
CHROME_PROFILE  = "./chrome-profile"
GBP_LOCATIONS   = "https://business.google.com/locations"
DATA_INIZIO     = "2026-05-05"
DELAY_POST      = 5
HEADLESS        = False
# ──────────────────────────────────────────────────────────────────

MONTHS_IT = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
             "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
MONTHS_EN = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
             "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}

def parse_month_header(text):
    parts = text.strip().lower().split()
    if len(parts) < 2: return None
    month = MONTHS_EN.get(parts[0]) or MONTHS_IT.get(parts[0])
    try: return (month, int(parts[-1])) if month else None
    except ValueError: return None

async def find_el(ctx, selectors, timeout=6000):
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

async def navigate_calendar(frame, month, year, max_steps=30):
    for _ in range(max_steps):
        try:
            header = frame.locator('[role="heading"], [aria-live="polite"]').first
            text = await header.inner_text(timeout=3000)
            parsed = parse_month_header(text)
            if not parsed: break
            cur_m, cur_y = parsed
            if cur_m == month and cur_y == year: return True
            if (cur_y, cur_m) < (year, month):
                btn = frame.locator('[aria-label*="next month" i], [aria-label*="mese successivo" i]').first
            else:
                btn = frame.locator('[aria-label*="prev month" i], [aria-label*="mese precedente" i]').first
            await btn.click(force=True)
            await asyncio.sleep(0.4)
        except Exception: break
    return False

async def pick_date_time(frame, dt):
    await navigate_calendar(frame, dt.month, dt.year)
    await asyncio.sleep(0.3)
    day_btn = await find_el(frame, [
        f'button[data-date*="{dt.year}-{str(dt.month).zfill(2)}-{str(dt.day).zfill(2)}"]',
        f'[data-day="{dt.day}"]:not([aria-disabled="true"])',
    ], timeout=5000)
    if day_btn:
        await day_btn.click()
        await asyncio.sleep(0.3)
    for selectors, value in [
        (['input[aria-label*="hour" i]', 'input[placeholder="HH"]'], str(dt.hour).zfill(2)),
        (['input[aria-label*="minute" i]', 'input[placeholder="MM"]'], str(dt.minute).zfill(2)),
    ]:
        field = await find_el(frame, selectors, timeout=3000)
        if field:
            await field.triple_click()
            await field.fill(value)

async def publish_post(page, post):
    description = post.get("description","").strip()
    date_str    = post.get("date","").strip()
    image_path  = post.get("image","").strip()
    cta_url     = post.get("cta_url","").strip()
    cta_type    = post.get("cta_type","Learn more").strip()
    if not description: return False
    try:
        create_btn = await find_el(page, [
            'button:has-text("Add update")','button:has-text("Aggiungi aggiornamento")',
            '[aria-label*="Add update" i]',
        ])
        if not create_btn: return False
        await create_btn.click()
        await asyncio.sleep(2)
        frame = await get_post_frame(page)
        if not frame: return False
        desc_el = await find_el(frame, [
            'textarea[placeholder*="news" i]','[contenteditable="true"]','textarea',
        ])
        if desc_el:
            await desc_el.click()
            await desc_el.fill(description)
            await asyncio.sleep(0.3)
        if image_path and Path(image_path).exists():
            photo_btn = await find_el(frame, ['button[aria-label*="photo" i]','button:has-text("Add photos")'], timeout=4000)
            if photo_btn:
                try:
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await photo_btn.click()
                    fc = await fc_info.value
                    await fc.set_files(image_path)
                    await asyncio.sleep(4)
                except Exception as e:
                    print(f"    ⚠️  Immagine: {e}")
        if cta_url:
            add_btn = await find_el(frame, ['button:has-text("Add a button")','button:has-text("Aggiungi un pulsante")'], timeout=4000)
            if add_btn:
                await add_btn.click()
                await asyncio.sleep(0.5)
                url_field = await find_el(frame, ['input[type="url"]','input[placeholder*="URL" i]'], timeout=3000)
                if url_field:
                    await url_field.fill(cta_url)
                    await asyncio.sleep(0.3)
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                sched_el = await find_el(frame, [
                    'input[value*="SCHEDULED" i]','label:has-text("Schedule")','label:has-text("Programma")',
                ], timeout=4000)
                if sched_el:
                    await sched_el.click()
                    await asyncio.sleep(0.5)
                    await pick_date_time(frame, dt)
            except ValueError:
                print(f"    ⚠️  Formato data non valido: {date_str}")
        publish_btn = await find_el(frame, [
            'button:has-text("Schedule")','button:has-text("Programma")',
            'button:has-text("Publish")','button:has-text("Pubblica")','button[type="submit"]',
        ], timeout=5000)
        if publish_btn:
            await publish_btn.click()
            await asyncio.sleep(3)
            return True
        return False
    except Exception as e:
        print(f"    ❌ {e}")
        return False

def genera_csv_con_claude(nome, citta, quartiere, keywords, cta_url, data_inizio):
    """Usa Claude Code -p per ottenere il CSV come testo, poi lo salva Python."""
    output_csv = f"posts_{nome.replace(' ', '_').lower()}.csv"
    prompt = (
        f"Genera esattamente 12 righe CSV per post GBP di {nome}, "
        f"ristorante di pasta fresca a {quartiere}, {citta}. "
        f"Keyword da usare nei testi: {keywords}. "
        f"Ogni title max 58 caratteri, description 150-300 caratteri SEO con CTA finale. "
        f"Date settimanali dal {data_inizio} alle 10:00. "
        f"cta_url per tutte le righe: {cta_url}. "
        f"Rispondi SOLO in formato CSV puro, nessun testo prima o dopo. "
        f"Prima riga = intestazione esatta: title,description,date,image,cta_url,cta_type. "
        f"La colonna image lasciala vuota."
    )
    print(f"  🤖 Claude Code genera post per {nome}...")
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ Errore Claude Code: {result.stderr[:150]}")
        return None
    output = result.stdout.strip()
    if not output:
        print("  ❌ Claude non ha restituito nulla")
        return None
    # Rimuove eventuale blocco markdown ```csv ... ```
    lines = [l for l in output.split("\n") if not l.strip().startswith("```")]
    output = "\n".join(lines).strip()
    with open(output_csv, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"  ✅ CSV salvato: {output_csv}")
    return output_csv

async def processa_sede(page, ristorante, csv_file):
    """Naviga al profilo GBP della sede e pubblica i post."""
    nome = ristorante["nome"]

    # ── Seleziona la sede dalla lista locations ──────────────────────
    await page.goto(GBP_LOCATIONS, wait_until="domcontentloaded")
    await asyncio.sleep(2)

    # Cerca la sede per nome e clicca su di essa
    sede_link = await find_el(page, [
        f'a:has-text("{nome}")',
        f'[aria-label*="{nome}" i]',
        f'td:has-text("{nome}")',
    ], timeout=8000)

    if sede_link:
        await sede_link.click()
        await asyncio.sleep(2)
    else:
        print(f"  ⚠️  Sede '{nome}' non trovata automaticamente.")
        print(f"  👆 Selezionala manualmente nel browser, poi premi INVIO...")
        input()

    # ── Leggi e pubblica i post ──────────────────────────────────────
    with open(csv_file, newline="", encoding="utf-8") as f:
        posts = [r for r in csv.DictReader(f) if r.get("description","").strip()]

    gbp_state.load_state(csv_file, nome, posts)

    total = len(posts)
    ok = fail = 0
    for i, post in enumerate(posts, 1):
        preview = post.get("title", post.get("description",""))[:45]
        post_id = gbp_state.make_post_id(post.get("title",""), post.get("date",""), nome)

        if gbp_state.is_done(post_id):
            print(f"    [{i}/{total}] ⏭️  Già pubblicato, salto: {preview}")
            continue

        print(f"    [{i}/{total}] {preview}")
        success = await publish_post(page, post)
        gbp_state.update_post(post_id, "published" if success else "failed")
        if success: ok += 1
        else: fail += 1
        await page.goto(GBP_LOCATIONS, wait_until="domcontentloaded")
        await asyncio.sleep(DELAY_POST)
        # Riseleziona la sede
        sede_link = await find_el(page, [f'a:has-text("{nome}")'], timeout=5000)
        if sede_link:
            await sede_link.click()
            await asyncio.sleep(2)

    return ok, fail

async def main():
    if not Path(RISTORANTI_CSV).exists():
        print(f"❌ File non trovato: {RISTORANTI_CSV}")
        sys.exit(1)

    with open(RISTORANTI_CSV, newline="", encoding="utf-8") as f:
        ristoranti = list(csv.DictReader(f))

    print(f"\n{'═'*55}")
    print(f"  🏪  Sedi trovate: {len(ristoranti)}")
    print(f"  📅  Data inizio: {DATA_INIZIO}")
    print(f"{'═'*55}\n")

    # ── FASE 1: Genera CSV per ogni sede con Claude Code ─────────────
    csv_files = {}
    for r in ristoranti:
        csv_file = genera_csv_con_claude(
            r["nome"], r["citta"], r["quartiere"],
            r["keywords"], r["cta_url"], DATA_INIZIO
        )
        if csv_file:
            check_and_exit(csv_file)
            csv_files[r["nome"]] = csv_file

    if not csv_files:
        print("❌ Nessun CSV generato. Controlla Claude Code.")
        sys.exit(1)

    print(f"\n✅ CSV generati per {len(csv_files)} sedi. Pronti per pubblicare.\n")

    # ── FASE 2: Pubblica su GBP per ogni sede ────────────────────────
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            channel="chrome",
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://business.google.com", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            print("⚠️  Fai il login Google nel browser, poi premi INVIO.")
            input()

        total_ok = total_fail = 0
        for r in ristoranti:
            nome = r["nome"]
            if nome not in csv_files:
                print(f"\n⏭️  Salto {nome} (CSV non generato)")
                continue
            print(f"\n{'─'*55}")
            print(f"  📍  {nome} — {r['quartiere']}, {r['citta']}")
            print(f"{'─'*55}")
            ok, fail = await processa_sede(page, r, csv_files[nome])
            total_ok += ok
            total_fail += fail
            print(f"  ✅ {ok} pubblicati  ❌ {fail} falliti")

        print(f"\n{'═'*55}")
        print(f"  🏁  COMPLETATO")
        print(f"  ✅  Totale pubblicati: {total_ok}")
        print(f"  ❌  Totale falliti:    {total_fail}")
        print(f"{'═'*55}\n")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
