#!/usr/bin/env python3
"""
Auto-discovery delle sedi GBP via API Google.
Genera locations_{client}.csv con account_id, location_id, nome, indirizzo, categoria, sito_web.
"""
import argparse
import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/business.manage"]
ACCOUNT_MGMT_API = "mybusinessaccountmanagement"
ACCOUNT_MGMT_VER = "v1"
BIZ_INFO_API = "mybusinessbusinessinformation"
BIZ_INFO_VER = "v1"


def get_credentials(client_slug: str) -> Credentials:
    """
    Ottieni/rinnova le credenziali OAuth2 per il client.
    Salva il token in profiles/{client}/google_token.json.
    """
    token_dir = Path(f"profiles/{client_slug}")
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / "google_token.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_secrets = {
                "installed": {
                    "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                }
            }
            secrets_path = token_dir / "client_secrets.json"
            secrets_path.write_text(json.dumps(client_secrets))
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def discover_locations(client_slug: str) -> str:
    """
    Scopre tutte le sedi GBP del cliente e genera locations_{client}.csv.
    Ritorna il path del CSV generato.
    """
    creds = get_credentials(client_slug)

    # Inizializza i servizi API
    acct_service = build(ACCOUNT_MGMT_API, ACCOUNT_MGMT_VER, credentials=creds)
    biz_service  = build(BIZ_INFO_API, BIZ_INFO_VER, credentials=creds)

    # Lista account
    accounts_resp = acct_service.accounts().list().execute()
    accounts = accounts_resp.get("accounts", [])
    print(f"  📋 Trovati {len(accounts)} account")

    rows = []
    for account in accounts:
        account_name = account["name"]
        account_id   = account_name.split("/")[-1]

        # Lista location per account
        loc_resp = biz_service.accounts().locations().list(
            parent=account_name,
            readMask="name,title,storefrontAddress,categories,websiteUri",
        ).execute()
        locations = loc_resp.get("locations", [])
        print(f"    → {account.get('accountName','?')}: {len(locations)} sedi")

        for loc in locations:
            loc_id   = loc["name"].split("/")[-1]
            title    = loc.get("title", "")
            address  = loc.get("storefrontAddress", {})
            addr_str = ", ".join(filter(None, [
                address.get("addressLines", [""])[0] if address.get("addressLines") else "",
                address.get("locality", ""),
                address.get("postalCode", ""),
            ]))
            primary_cat = ""
            cats = loc.get("categories", {})
            if cats.get("primaryCategory"):
                primary_cat = cats["primaryCategory"].get("displayName", "")
            website = loc.get("websiteUri", "")

            rows.append({
                "account_id":   account_id,
                "location_id":  loc_id,
                "nome":         title,
                "indirizzo":    addr_str,
                "categoria":    primary_cat,
                "sito_web":     website,
                "keywords":     "",
                "cta_url":      "",
            })

    output = f"locations_{client_slug}.csv"
    fieldnames = ["account_id","location_id","nome","indirizzo","categoria","sito_web","keywords","cta_url"]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Generato: {output} ({len(rows)} sedi)")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scopre le sedi GBP del cliente")
    parser.add_argument("--client", required=True, help="Slug del cliente (es. miscusi)")
    args = parser.parse_args()
    discover_locations(args.client)
