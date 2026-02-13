#!/usr/bin/env python3
"""Retry ERROR rows by scraping web.dev via agent-browser."""

import json, os, re, subprocess, sys, time, urllib.parse

import argparse

# Set via CLI args in main()
SPREADSHEET = None
ACCOUNT = None
SHEET_NAME = None

def get_access_token():
    creds = json.load(open("/home/node/.config/gogcli/credentials.json"))
    subprocess.run(["gog", "auth", "tokens", "export", ACCOUNT, "--out", "/tmp/gog-tok.json"],
                   capture_output=True)
    tok_data = json.load(open("/tmp/gog-tok.json"))
    import urllib.request
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

def batch_write_row(row, values, token):
    import urllib.request as ur
    range_str = f"'{SHEET_NAME}'!B{row}:N{row}" if SHEET_NAME else f"B{row}:N{row}"
    body = json.dumps({"range": range_str, "majorDimension": "ROWS", "values": [values]}).encode()
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/"
           f"{urllib.parse.quote(range_str)}?valueInputOption=RAW")
    req = ur.Request(url, data=body, method="PUT",
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with ur.urlopen(req, timeout=30) as resp:
        pass

def find_error_rows():
    """Find rows where column B or G (mobile CWV assessment) = ERROR."""
    r = subprocess.run(
        ["gog", "sheets", "get", SPREADSHEET, "A2:N10000", "--account", ACCOUNT, "--plain"],
        capture_output=True, text=True, timeout=30
    )
    errors = []
    for i, line in enumerate(r.stdout.strip().split("\n")):
        parts = line.split("\t")
        url = parts[0].strip() if parts else ""
        if not url:
            continue
        # Check if B column (index 1) is ERROR or empty
        b_val = parts[1].strip() if len(parts) > 1 else ""
        if b_val == "ERROR" or b_val == "":
            errors.append((i + 2, url))  # row number, url
    return errors

def parse_value(text):
    """Parse '2.1 s' → 2.1, '249 ms' → 249, '0.26' → 0.26"""
    text = text.strip()
    if text.endswith(' s'):
        return float(text[:-2])
    elif text.endswith(' ms'):
        return float(text[:-3])
    else:
        try:
            return float(text)
        except:
            return text

def scrape_webdev(url, strategy="mobile"):
    """Load web.dev in agent-browser, wait for results, extract CrUX data."""
    if not url.startswith("http"):
        url = f"https://{url}"
    
    form_factor = "mobile" if strategy == "mobile" else "desktop"
    encoded = urllib.parse.quote(url, safe='')
    webdev_url = f"https://pagespeed.web.dev/analysis?url={encoded}&form_factor={form_factor}"
    
    try:
        # Open the page
        subprocess.run(["agent-browser", "open", webdev_url], capture_output=True, timeout=15)
        
        # Wait for analysis to complete
        time.sleep(65)
        
        # Extract text
        result = subprocess.run(
            ["agent-browser", "eval", "document.body.innerText.substring(0, 3000)"],
            capture_output=True, text=True, timeout=15
        )
        text = result.stdout.strip().strip('"').replace('\\n', '\n')
        
        # Parse the CrUX metrics
        data = {}
        
        # LCP
        m = re.search(r'Largest Contentful Paint \(LCP\)\n([\d.]+\s*(?:s|ms))', text)
        if m:
            val = m.group(1)
            data['lcp'] = round(parse_value(val) if 'ms' not in val else parse_value(val)/1000, 2)
        
        # INP
        m = re.search(r'Interaction to Next Paint \(INP\)\n([\d.]+\s*(?:s|ms))', text)
        if m:
            val = m.group(1)
            data['inp'] = int(parse_value(val)) if 'ms' in val else int(parse_value(val)*1000)
        
        # CLS
        m = re.search(r'Cumulative Layout Shift \(CLS\)\n([\d.]+)', text)
        if m:
            data['cls'] = float(m.group(1))
        
        # FCP
        m = re.search(r'First Contentful Paint \(FCP\)\n([\d.]+\s*(?:s|ms))', text)
        if m:
            val = m.group(1)
            data['fcp'] = round(parse_value(val) if 'ms' not in val else parse_value(val)/1000, 2)
        
        # TTFB
        m = re.search(r'Time to First Byte \(TTFB\)\n([\d.]+\s*(?:s|ms))', text)
        if m:
            val = m.group(1)
            data['ttfb'] = round(parse_value(val) if 'ms' not in val else parse_value(val)/1000, 2)
        
        # CWV Assessment
        m = re.search(r'Core Web Vitals Assessment:\s*\n?\s*(Passed|Failed)', text)
        if m:
            data['assessment'] = "FAST" if m.group(1) == "Passed" else "SLOW"
        
        if 'lcp' in data:
            return data
        return None
        
    except Exception as e:
        print(f"  Browser error: {e}")
        return None

def main():
    global SPREADSHEET, ACCOUNT, SHEET_NAME
    
    parser = argparse.ArgumentParser(description="Retry ERROR rows via web.dev browser scraping")
    parser.add_argument("spreadsheet_id", help="Google Spreadsheet ID")
    parser.add_argument("--account", required=True, help="Google account email for Sheets API")
    args = parser.parse_args()
    
    SPREADSHEET = args.spreadsheet_id
    ACCOUNT = args.account
    
    # Detect sheet name
    try:
        r = subprocess.run(["gog", "sheets", "metadata", SPREADSHEET, "--account", ACCOUNT, "--json"],
                          capture_output=True, text=True, timeout=15)
        meta = json.loads(r.stdout)
        SHEET_NAME = meta["sheets"][0]["properties"]["title"]
    except:
        SHEET_NAME = None
    
    print("Finding error rows...", flush=True)
    errors = find_error_rows()
    print(f"Found {len(errors)} error rows to retry via web.dev scraping", flush=True)
    
    if not errors:
        print("No errors to retry!")
        return
    
    token = get_access_token()
    fixed = 0
    still_broken = 0
    
    for row, url in errors:
        print(f"[{row}] {url}", flush=True)
        
        # Scrape mobile
        print(f"  Scraping mobile...", flush=True)
        mobile = scrape_webdev(url, "mobile")
        time.sleep(5)
        
        # Scrape desktop
        print(f"  Scraping desktop...", flush=True)
        desktop = scrape_webdev(url, "desktop")
        time.sleep(5)
        
        if mobile or desktop:
            keys = ["lcp", "cls", "inp", "fcp", "ttfb", "assessment"]
            row_data = []
            for d in [mobile, desktop]:
                if d:
                    row_data += [str(d.get(k, "")) for k in keys]
                else:
                    row_data += ["", "", "", "", "", ""]
            row_data.append("Web.dev")
            
            batch_write_row(row, row_data, token)
            fixed += 1
            m_lcp = mobile.get("lcp", "?") if mobile else "?"
            d_lcp = desktop.get("lcp", "?") if desktop else "?"
            print(f"  → Fixed! M-LCP:{m_lcp}s D-LCP:{d_lcp}s", flush=True)
        else:
            still_broken += 1
            print(f"  → Still no data", flush=True)
    
    print(f"\n=== RETRY COMPLETE: {fixed} fixed, {still_broken} still broken ===", flush=True)

if __name__ == "__main__":
    main()
