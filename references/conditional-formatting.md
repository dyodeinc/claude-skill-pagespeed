# Conditional Formatting for CWV Google Sheets

Apply via Google Sheets batchUpdate API. Requires an OAuth access token.

## Get Access Token

```python
import json, urllib.request, urllib.parse, subprocess, os

creds = json.load(open("/home/node/.config/gogcli/credentials.json"))
subprocess.run(["gog", "auth", "tokens", "export", "ACCOUNT_EMAIL", "--out", "/tmp/gog-tok.json"], capture_output=True)
tok_data = json.load(open("/tmp/gog-tok.json"))
data = urllib.parse.urlencode({
    "client_id": creds["client_id"],
    "client_secret": creds["client_secret"],
    "refresh_token": tok_data["refresh_token"],
    "grant_type": "refresh_token"
}).encode()
req = urllib.request.Request("https://oauth2.googleapis.com/token", data)
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())["access_token"]
os.remove("/tmp/gog-tok.json")
```

## Get Sheet ID

```python
# From gog CLI
gog sheets metadata SPREADSHEET_ID --account EMAIL --json
# Find the sheet's sheetId from properties
```

## Apply Rules

Build rules for each metric column. Three rules per column (red > yellow > green priority):

```python
green = {"red": 0.72, "green": 0.88, "blue": 0.72}
yellow = {"red": 1.0, "green": 0.95, "blue": 0.6}
red = {"red": 0.96, "green": 0.7, "blue": 0.7}

def make_range(col_idx, sheet_id, end_row):
    return {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": end_row,
            "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1}

def num_rules(col_idx, good_max, avg_max, sheet_id, end_row):
    """Red (> avg_max), Yellow (> good_max), Green (<= good_max)"""
    rules = []
    for val, color, typ in [
        (avg_max, red, "NUMBER_GREATER"),
        (good_max, yellow, "NUMBER_GREATER"),
        (good_max, green, "NUMBER_LESS_THAN_EQ")
    ]:
        rules.append({"addConditionalFormatRule": {"rule": {
            "ranges": [make_range(col_idx, sheet_id, end_row)],
            "booleanRule": {
                "condition": {"type": typ, "values": [{"userEnteredValue": str(val)}]},
                "format": {"backgroundColor": color}
            }
        }, "index": 0}})
    return rules

def text_rules(col_idx, sheet_id, end_row):
    """FAST=green, AVERAGE=yellow, SLOW=red, Passed=green, Failed=red"""
    rules = []
    for text, color in [("FAST", green), ("AVERAGE", yellow), ("SLOW", red),
                         ("Passed", green), ("Failed", red)]:
        rules.append({"addConditionalFormatRule": {"rule": {
            "ranges": [make_range(col_idx, sheet_id, end_row)],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]},
                "format": {"backgroundColor": color}
            }
        }, "index": 0}})
    return rules
```

## Column Mapping

| Column | Index | Metric | Good | NI |
|--------|-------|--------|------|----|
| B | 1 | M-LCP (s) | 2.5 | 4 |
| C | 2 | M-CLS | 0.1 | 0.25 |
| D | 3 | M-INP (ms) | 200 | 500 |
| E | 4 | M-FCP (s) | 1.8 | 3 |
| F | 5 | M-TTFB (s) | 0.8 | 1.8 |
| G | 6 | M-CWV | text | text |
| H | 7 | D-LCP (s) | 2.5 | 4 |
| I | 8 | D-CLS | 0.1 | 0.25 |
| J | 9 | D-INP (ms) | 200 | 500 |
| K | 10 | D-FCP (s) | 1.8 | 3 |
| L | 11 | D-TTFB (s) | 0.8 | 1.8 |
| M | 12 | D-CWV | text | text |
