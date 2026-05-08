#!/usr/bin/env python3
"""
Raccolta metriche di performance GBP via API Google.
Output: reports/metrics_{client}_{YYYY-MM}.csv
"""
import argparse
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "WEBSITE_CLICKS",
    "CALL_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
]


def get_credentials(client_slug: str) -> Credentials:
    """Riutilizza le credenziali salvate da gbp_discover.py."""
    from gbp_discover import get_credentials as _gc
    return _gc(client_slug)


def fetch_metrics(client_slug: str, month_str: str) -> str:
    """
    Raccoglie metriche mensili per tutte le sedi in locations_{client}.csv.
    month_str: YYYY-MM
    Ritorna il path del CSV generato.
    """
    loc_csv = f"locations_{client_slug}.csv"
    if not Path(loc_csv).exists():
        raise FileNotFoundError(f"File non trovato: {loc_csv} — esegui prima gbp_discover.py")

    # Calcola range date
    year, month = map(int, month_str.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(days=1)

    creds = get_credentials(client_slug)
    service = build("businessprofileperformance", "v1", credentials=creds)

    with open(loc_csv, newline="", encoding="utf-8") as f:
        locations = list(csv.DictReader(f))

    Path("reports").mkdir(exist_ok=True)
    output = f"reports/metrics_{client_slug}_{month_str}.csv"
    fieldnames = ["location_id", "nome", "data"] + METRICS

    rows = []
    for loc in locations:
        loc_id   = loc["location_id"]
        loc_name = loc["nome"]
        name     = f"locations/{loc_id}"

        try:
            resp = service.locations().fetchMultiDailyMetricsTimeSeries(
                location=name,
                body={
                    "dailyMetrics": METRICS,
                    "dailyRange": {
                        "startDate": {"year": start.year, "month": start.month, "day": start.day},
                        "endDate":   {"year": end.year,   "month": end.month,   "day": end.day},
                    },
                }
            ).execute()

            # Costruisci un dict data→metriche
            data_map: dict[str, dict] = {}
            for series in resp.get("multiDailyMetricTimeSeries", []):
                metric_name = series.get("dailyMetric", "")
                for point in series.get("timeSeries", {}).get("datedValues", []):
                    d = point.get("date", {})
                    key = f"{d.get('year')}-{str(d.get('month','0')).zfill(2)}-{str(d.get('day','0')).zfill(2)}"
                    data_map.setdefault(key, {})[metric_name] = point.get("value", 0)

            for date_key, metrics in sorted(data_map.items()):
                row = {"location_id": loc_id, "nome": loc_name, "data": date_key}
                for m in METRICS:
                    row[m] = metrics.get(m, 0)
                rows.append(row)

            print(f"  ✅ {loc_name}: {len(data_map)} giorni")
        except Exception as e:
            print(f"  ❌ {loc_name}: {e}")

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Report generato: {output} ({len(rows)} righe)")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Raccoglie metriche GBP mensili")
    parser.add_argument("--client", required=True, help="Slug del cliente")
    parser.add_argument("--month", required=True, help="Mese nel formato YYYY-MM")
    args = parser.parse_args()
    fetch_metrics(args.client, args.month)
