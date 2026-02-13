#!/usr/bin/env python3
"""PageSpeed Insights bulk scanner — parallel requests, CrUX field data.

Supports two auth modes for Google Sheets:
  1. Service account JSON key (--credentials path/to/key.json) — portable, recommended
  2. gog CLI (--account email) — for OpenClaw/environments with gog installed
"""

import json, os, subprocess, sys, time, urllib.request, urllib.parse, argparse, base64, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = os.environ.get("GOOGLE_PAGESPEED_API_TOKEN", "")
MAX_WORKERS = 4

# Globals set in main()
SPREADSHEET = None
ACCESS_TOKEN = None
SHEET_NAME = None
AUTH_MODE = None  # "service_account" or "gog"
SA_CREDENTIALS = None
GOG_ACCOUNT = None
TOKEN_LOCK = __import__('threading').Lock()


def _jwt_encode(header, payload, key_pem):
    """Create a signed JWT using RS256 (stdlib only, no pip deps)."""
    import struct
    # We need cryptography or jwt lib — fall back to subprocess openssl
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=')
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=')
    msg = h + b'.' + p
    
    # Write key to temp file, sign with openssl
    key_path = "/tmp/_sa_key.pem"
    with open(key_path, 'w') as f:
        f.write(key_pem)
    
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path],
        input=msg, capture_output=True
    )
    os.remove(key_path)
    
    sig = base64.urlsafe_b64encode(result.stdout).rstrip(b'=')
    return (msg + b'.' + sig).decode()


def get_access_token_sa():
    """Get access token via service account JWT assertion."""
    now = int(time.time())
    payload = {
        "iss": SA_CREDENTIALS["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    header = {"alg": "RS256", "typ": "JWT"}
    assertion = _jwt_encode(header, payload, SA_CREDENTIALS["private_key"])
    
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def get_access_token_gog():
    """Get access token via gog CLI (OpenClaw environments)."""
    creds = json.load(open("/home/node/.config/gogcli/credentials.json"))
    subprocess.run(["gog", "auth", "tokens", "export", GOG_ACCOUNT, "--out", "/tmp/gog-tok.json"],
                   capture_output=True, text=True)
    tok_data = json.load(open("/tmp/gog-tok.json"))
    data = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": tok_data["refresh_token"],
        "grant_type": "refresh_token"
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data)
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    os.remove("/tmp/gog-tok.json")
    return result["access_token"]


def get_access_token():
    if AUTH_MODE == "service_account":
        return get_access_token_sa()
    return get_access_token_gog()


def refresh_token():
    global ACCESS_TOKEN
    with TOKEN_LOCK:
        ACCESS_TOKEN = get_access_token()


def batch_write_row(row, values):
    global ACCESS_TOKEN
    range_str = f"'{SHEET_NAME}'!B{row}:N{row}" if SHEET_NAME else f"B{row}:N{row}"
    body = json.dumps({"range": range_str, "majorDimension": "ROWS", "values": [values]}).encode()
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/"
           f"{urllib.parse.quote(range_str)}?valueInputOption=RAW")
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=body, method="PUT",
                                        headers={"Authorization": f"Bearer {ACCESS_TOKEN}",
                                                 "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                refresh_token()
            else:
                print(f"  Sheet write error row {row}: {e}")
                return


def sheet_read_urls():
    """Read URLs from column A using Sheets API directly."""
    global ACCESS_TOKEN
    range_str = urllib.parse.quote("A2:A10000")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/{range_str}"
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return [row[0].strip() for row in data.get("values", []) if row and row[0].strip()]
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                refresh_token()
            else:
                raise


def get_sheet_name():
    """Detect first sheet name via Sheets API."""
    global ACCESS_TOKEN
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}?fields=sheets.properties.title"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data["sheets"][0]["properties"]["title"]
    except:
        return None


def extract_field_data(d):
    le = d.get("loadingExperience", {})
    fm = le.get("metrics", {})
    oc = le.get("overall_category")
    if not fm or not oc:
        return None
    lcp_ms = fm.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile")
    cls_raw = fm.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile")
    inp_ms = fm.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile")
    fcp_ms = fm.get("FIRST_CONTENTFUL_PAINT_MS", {}).get("percentile")
    ttfb_ms = fm.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE", {}).get("percentile")
    return {
        "lcp": round(lcp_ms / 1000, 2) if lcp_ms is not None else "",
        "cls": round(cls_raw / 100, 2) if cls_raw is not None else "",
        "inp": inp_ms if inp_ms is not None else "",
        "fcp": round(fcp_ms / 1000, 2) if fcp_ms is not None else "",
        "ttfb": round(ttfb_ms / 1000, 2) if ttfb_ms is not None else "",
        "assessment": oc,
    }


def extract_lab_data(d):
    lr = d.get("lighthouseResult")
    if not lr:
        return None
    a = lr.get("audits", {})
    try:
        return {
            "lcp": round(a["largest-contentful-paint"]["numericValue"] / 1000, 2),
            "cls": round(a["cumulative-layout-shift"]["numericValue"], 3),
            "inp": "",
            "fcp": round(a["first-contentful-paint"]["numericValue"] / 1000, 2),
            "ttfb": round(a.get("server-response-time", {}).get("numericValue", 0) / 1000, 2),
            "assessment": "",
        }
    except (KeyError, TypeError):
        return None


def run_pagespeed(url, strategy):
    if not url.startswith("http"):
        url = f"https://{url}"
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={urllib.parse.quote(url, safe='')}&strategy={strategy}"
        f"&category=performance&key={API_KEY}"
    )
    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=90) as resp:
            d = json.loads(resp.read())
        if "error" in d:
            return None, "Error"
        field = extract_field_data(d)
        if field:
            return field, "Field"
        lab = extract_lab_data(d)
        if lab:
            return lab, "Lab"
        return None, "Error"
    except Exception:
        return None, "Error"


def process_url(i, url, total):
    row = i + 2
    mobile, m_src = run_pagespeed(url, "mobile")
    desktop, d_src = run_pagespeed(url, "desktop")
    source = "Field" if (m_src == "Field" or d_src == "Field") else ("Lab" if (m_src == "Lab" or d_src == "Lab") else "Error")
    keys = ["lcp", "cls", "inp", "fcp", "ttfb", "assessment"]
    row_data = []
    if mobile:
        row_data += [str(mobile[k]) for k in keys]
    else:
        row_data += ["ERROR", "", "", "", "", "ERROR"]
    if desktop:
        row_data += [str(desktop[k]) for k in keys]
    else:
        row_data += ["ERROR", "", "", "", "", "ERROR"]
    row_data.append(source)
    batch_write_row(row, row_data)
    m_lcp = mobile["lcp"] if mobile else "ERR"
    d_lcp = desktop["lcp"] if desktop else "ERR"
    print(f"[{i+1}/{total}] {url} → M:{m_lcp}s D:{d_lcp}s [{source}]", flush=True)
    return i, source


def main():
    global SPREADSHEET, ACCESS_TOKEN, SHEET_NAME, AUTH_MODE, SA_CREDENTIALS, GOG_ACCOUNT, MAX_WORKERS, API_KEY

    parser = argparse.ArgumentParser(description="Bulk PageSpeed Insights scanner with Google Sheets output")
    parser.add_argument("spreadsheet_id", help="Google Spreadsheet ID (from the URL)")
    
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--credentials", help="Path to Google service account JSON key file")
    auth_group.add_argument("--account", help="Google account email (requires gog CLI)")
    
    parser.add_argument("--start", type=int, default=0, help="Start from URL index (0-based)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default: 4)")
    parser.add_argument("--api-key", help="PageSpeed API key (overrides GOOGLE_PAGESPEED_API_TOKEN env var)")
    args = parser.parse_args()

    SPREADSHEET = args.spreadsheet_id
    MAX_WORKERS = args.workers
    
    if args.api_key:
        API_KEY = args.api_key
    if not API_KEY:
        print("Error: PageSpeed API key required. Set GOOGLE_PAGESPEED_API_TOKEN or use --api-key", file=sys.stderr)
        sys.exit(1)

    if args.credentials:
        AUTH_MODE = "service_account"
        SA_CREDENTIALS = json.load(open(args.credentials))
        print(f"Auth: Service account ({SA_CREDENTIALS['client_email']})", flush=True)
    else:
        AUTH_MODE = "gog"
        GOG_ACCOUNT = args.account
        print(f"Auth: gog CLI ({GOG_ACCOUNT})", flush=True)

    ACCESS_TOKEN = get_access_token()
    SHEET_NAME = get_sheet_name()
    if SHEET_NAME:
        print(f"Sheet: {SHEET_NAME}", flush=True)

    urls = sheet_read_urls()
    total = len(urls)
    start_idx = args.start
    print(f"Found {total} URLs, starting from index {start_idx}, workers={MAX_WORKERS}", flush=True)

    work = [(i, url) for i, url in enumerate(urls) if i >= start_idx]
    done = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, i, url, total): (i, url) for i, url in work}
        for future in as_completed(futures):
            try:
                idx, source = future.result()
                done += 1
                if source == "Error":
                    errors += 1
                if done % 25 == 0:
                    print(f"--- Progress: {done}/{len(work)} done, {errors} errors ---", flush=True)
            except Exception as e:
                done += 1
                errors += 1
                i, url = futures[future]
                print(f"[{i+1}/{total}] {url} → EXCEPTION: {e}", flush=True)

    print(f"\n=== COMPLETE: {done} URLs processed, {errors} errors ===", flush=True)


if __name__ == "__main__":
    main()
