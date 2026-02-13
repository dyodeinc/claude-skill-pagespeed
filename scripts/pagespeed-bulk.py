#!/usr/bin/env python3
"""PageSpeed Insights bulk scanner — parallel requests, CrUX field data."""

import json, os, subprocess, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

SPREADSHEET = "13h8LYIVJTsoV_60YO4W6W4HdKGkyW34YwkpBj7r5cA0"
API_KEY = os.environ["GOOGLE_PAGESPEED_API_TOKEN"]
ACCOUNT = "tim@dyode.com"
MAX_WORKERS = 4  # parallel URL processing

def get_access_token():
    creds = json.load(open("/home/node/.config/gogcli/credentials.json"))
    r = subprocess.run(["gog", "auth", "tokens", "export", "tim@dyode.com", "--out", "/tmp/gog-tok.json"],
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

ACCESS_TOKEN = get_access_token()
TOKEN_LOCK = __import__('threading').Lock()

def refresh_token():
    global ACCESS_TOKEN
    with TOKEN_LOCK:
        ACCESS_TOKEN = get_access_token()

def batch_write_row(row, values):
    global ACCESS_TOKEN
    range_str = f"'domains_export (4)'!B{row}:N{row}"
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
    r = subprocess.run(
        ["gog", "sheets", "get", SPREADSHEET, "A2:A1400", "--account", ACCOUNT, "--plain"],
        capture_output=True, text=True, timeout=30
    )
    return [line.strip() for line in r.stdout.strip().split("\n") if line.strip()]

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
        with urllib.request.urlopen(req, timeout=60) as resp:
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
    except Exception as e:
        return None, "Error"

def process_url(i, url, total):
    """Process a single URL (both mobile + desktop). Thread-safe."""
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
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    urls = sheet_read_urls()
    total = len(urls)
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
