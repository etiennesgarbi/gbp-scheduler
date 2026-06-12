"""
Selettori CSS/Playwright per Google Business Profile.
Ogni chiave: lista ordinata per robustezza (più stabile → meno stabile).
Aggiornare qui quando Google modifica la UI; mai inline negli script.
"""

SELECTORS: dict[str, list[str]] = {
    "ADD_UPDATE_BUTTON": [
        '[data-item-id="posts"] button',
        'button[aria-label*="post" i]',
        'button[aria-label*="aggiorn" i]',
        'button[aria-label*="update" i]',
        'button:has-text("Add update")',
        'button:has-text("Aggiungi aggiornamento")',
    ],
    "DESCRIPTION_TEXTAREA": [
        'textarea[placeholder*="news" i]',
        'textarea[placeholder*="What\'s new" i]',
        'textarea[placeholder*="novità" i]',
        '[contenteditable="true"]',
        'textarea',
    ],
    "PHOTO_BUTTON": [
        'button[aria-label*="photo" i]',
        'button[aria-label*="foto" i]',
        'button:has-text("Add photos")',
        'button:has-text("Aggiungi foto")',
    ],
    "CTA_BUTTON": [
        'button[aria-label*="Add a button" i]',
        'button:has-text("Add a button")',
        'button:has-text("Aggiungi un pulsante")',
    ],
    "CTA_URL_INPUT": [
        'input[type="url"]',
        'input[placeholder*="URL" i]',
        'input[placeholder*="link" i]',
        'input[placeholder*="http" i]',
    ],
    "SCHEDULE_TOGGLE": [
        'input[value*="SCHEDULED" i]',
        'input[value*="schedule" i]',
        'label:has-text("Schedule")',
        'label:has-text("Programma")',
        '[aria-label*="Schedule for" i]',
    ],
    "HOUR_INPUT": [
        'input[aria-label*="hour" i]',
        'input[placeholder="HH"]',
        'input[aria-label*="ora" i]',
    ],
    "MINUTE_INPUT": [
        'input[aria-label*="minute" i]',
        'input[placeholder="MM"]',
        'input[aria-label*="minuti" i]',
    ],
    "PUBLISH_BUTTON": [
        'button:has-text("Schedule")',
        'button:has-text("Programma")',
        'button:has-text("Publish")',
        'button:has-text("Pubblica")',
        'button[type="submit"]',
    ],
    "NEXT_MONTH_BTN": [
        '[aria-label*="next month" i]',
        '[aria-label*="mese successivo" i]',
        'button[data-direction="1"]',
    ],
    "PREV_MONTH_BTN": [
        '[aria-label*="prev month" i]',
        '[aria-label*="mese precedente" i]',
        'button[data-direction="-1"]',
    ],
    "CALENDAR_HEADING": [
        '[role="heading"]',
        '[aria-live="polite"]',
    ],
    "LOCATION_LINK": [
        'a[href*="locations"]',
        'td a',
    ],

    # ── Offer post ────────────────────────────────────────────────────
    "OFFER_TAB": [
        'button[aria-label*="offer" i]',
        'button[aria-label*="offerta" i]',
        'button:has-text("Offer")',
        'button:has-text("Offerta")',
        '[role="tab"]:has-text("Offer")',
        '[role="tab"]:has-text("Offerta")',
    ],
    "OFFER_TITLE_INPUT": [
        'input[aria-label*="offer title" i]',
        'input[aria-label*="titolo offerta" i]',
        'input[placeholder*="offer title" i]',
        'input[placeholder*="titolo" i]',
    ],
    "OFFER_START_DATE": [
        'input[aria-label*="start date" i]',
        'input[aria-label*="data inizio" i]',
        'input[placeholder*="MM/DD/YYYY"]',
    ],
    "OFFER_END_DATE": [
        'input[aria-label*="end date" i]',
        'input[aria-label*="data fine" i]',
        'input[aria-label*="data di fine" i]',
    ],
    "OFFER_COUPON_INPUT": [
        'input[aria-label*="coupon" i]',
        'input[placeholder*="coupon" i]',
        'input[aria-label*="codice" i]',
    ],
    "OFFER_LINK_INPUT": [
        'input[aria-label*="link to redeem" i]',
        'input[aria-label*="link per riscattare" i]',
        'input[placeholder*="redeem" i]',
    ],
}
