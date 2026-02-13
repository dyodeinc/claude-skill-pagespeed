---
name: core-web-vitals
description: Run Google Core Web Vitals and PageSpeed audits against URLs. Use when asked to check site performance, CWV scores, LCP/CLS/INP/FCP/TTFB metrics, PageSpeed Insights, or bulk-audit URLs from a Google Sheet. Supports single URL, batch (multiple URLs), and Google Sheet modes with CrUX field data preferred, lab fallback, and browser scraping for errors.
---

# Core Web Vitals Skill

Audit website performance using Google's CrUX field data (real user metrics) and PageSpeed Insights API.

## Prerequisites

- `GOOGLE_PAGESPEED_API_TOKEN` env var (Google PageSpeed Insights API key)
- `gog` CLI for Google Sheets operations (alternative to service account auth)
- `agent-browser` CLI for web.dev scraping fallback

## Three Modes

### 1. Single URL
User provides one URL. Run the API, return formatted results inline.

### 2. Batch (multiple URLs)
User provides URLs separated by line breaks. Run each, return formatted table.

### 3. Google Sheet
User provides a Sheet URL. Read URLs from column A, write results to columns B-N with conditional formatting.

## Data Source Priority

1. **CrUX Field Data** (preferred) — Real user metrics from Chrome UX Report (28-day p75 values). This matches what web.dev shows prominently.
2. **Lab Data** (fallback) — Lighthouse synthetic test. Used when CrUX has insufficient traffic data.
3. **Browser Scraping** (error retry) — Load web.dev in agent-browser, wait for results, parse the page. Used when API times out.

**Important:** CrUX field data ≠ Lighthouse lab data. Field data reflects real users; lab data simulates a throttled mobile device. Always prefer field data — it's what Google uses for ranking signals.

## Metrics Collected

| Metric | Field (CrUX) | Good | Needs Improvement | Poor |
|--------|-------------|------|-------------------|------|
| LCP (s) | ✅ p75 | ≤ 2.5 | 2.5–4.0 | > 4.0 |
| CLS | ✅ p75 | ≤ 0.1 | 0.1–0.25 | > 0.25 |
| INP (ms) | ✅ p75 | ≤ 200 | 200–500 | > 500 |
| FCP (s) | ✅ p75 | ≤ 1.8 | 1.8–3.0 | > 3.0 |
| TTFB (s) | ✅ p75 | ≤ 0.8 | 0.8–1.8 | > 1.8 |

CWV Assessment: FAST / AVERAGE / SLOW (from CrUX overall_category)

## Mode 1: Single URL

```bash
curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=URL&strategy=mobile&category=performance&key=$GOOGLE_PAGESPEED_API_TOKEN"
```

Extract CrUX from `loadingExperience.metrics` (p75 values). Fall back to `lighthouseResult.audits` if no CrUX.

**Format response as:**
```
🌐 **example.com** — CWV: FAST ✅

📱 Mobile:
  LCP: 1.8s 🟢 | CLS: 0.05 🟢 | INP: 120ms 🟢
  FCP: 1.2s 🟢 | TTFB: 0.4s 🟢

🖥️ Desktop:
  LCP: 1.2s 🟢 | CLS: 0.02 🟢 | INP: 80ms 🟢
  FCP: 0.8s 🟢 | TTFB: 0.3s 🟢
```

Use 🟢 (good), 🟡 (needs improvement), 🔴 (poor) based on thresholds above.

## Mode 2: Batch URLs

Run Mode 1 for each URL. Format as a list of results. Use 4 parallel workers via ThreadPoolExecutor for speed.

## Mode 3: Google Sheet

Use `scripts/pagespeed-bulk.py` in this skill directory.

### Prerequisites
- `GOOGLE_PAGESPEED_API_TOKEN` env var (or pass `--api-key`)
- Google Sheets auth: either a service account JSON key (`--credentials`) or `gog` CLI (`--account`)
- The Google Sheet must be editable by the auth identity (share with service account email or gog account)
- Column A must contain URLs (starting at A2, A1 is header)

### Setup
1. Extract spreadsheet ID from the Google Sheet URL (the long string between `/d/` and `/edit`)
2. Set headers B1:N1 via Sheets API or manually:
   - B1: M-LCP (s), C1: M-CLS, D1: M-INP (ms), E1: M-FCP (s), F1: M-TTFB (s), G1: M-CWV
   - H1: D-LCP (s), I1: D-CLS, J1: D-INP (ms), K1: D-FCP (s), L1: D-TTFB (s), M1: D-CWV
   - N1: Data Source

### Run
```bash
# With service account
python3 -u scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials service-account.json

# With gog CLI
python3 -u scripts/pagespeed-bulk.py SPREADSHEET_ID --account EMAIL

# Resume from index N, custom workers
python3 -u scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials sa.json --start N --workers 6
```

### Monitor
```bash
tail -f /tmp/pagespeed.log
```

### Retry Errors (browser scraping)
After main run completes, retry ERROR rows via web.dev:
```bash
python3 -u scripts/pagespeed-retry-browser.py SPREADSHEET_ID --credentials sa.json
```

### Conditional Formatting
Apply via Google Sheets batchUpdate API (see references/conditional-formatting.md). Colors:
- Green: good threshold
- Yellow: needs improvement
- Red: poor threshold

Applied to all metric columns for all data rows.

## Key Learnings

- **gog CLI quirk:** Multiple positional values get concatenated into one cell. Always write ONE cell per update call, or use the Sheets API directly for batch row writes.
- **API timeouts:** Heavy Shopify sites often timeout (60-90s). Use browser scraping fallback.
- **CrUX vs Lab confusion:** Users expect web.dev numbers. Web.dev defaults to showing CrUX field data prominently. Always use CrUX when available.
- **Rate limits:** 25K requests/day, 400/100s with API key. Parallel workers (4) stay well under limits.
- **CLS values from CrUX:** Returned as percentile × 100 (e.g., 26 = 0.26). Divide by 100.
- **Batch Sheets API writes:** Use PUT to `spreadsheets/{id}/values/{range}?valueInputOption=RAW` for whole-row writes (much faster than per-cell gog CLI calls).
- **Read full sheet range:** Always check actual row count. Don't assume 200 rows.
