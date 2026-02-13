# Core Web Vitals — OpenClaw Skill

Audit website performance using Google's Core Web Vitals (CrUX field data) and PageSpeed Insights API. Built for [OpenClaw](https://github.com/openclaw/openclaw) agents.

## Features

- **Single URL** — Check one site, get formatted CWV results
- **Batch** — Paste multiple URLs, get results for all
- **Google Sheet** — Point at a sheet with URLs in column A, auto-fills metrics with color-coded conditional formatting
- **CrUX field data** preferred (real user metrics from Chrome UX Report)
- **Lab data** fallback when CrUX unavailable
- **Browser scraping** fallback for API errors (loads web.dev via headless browser)
- **Parallel processing** — 4 concurrent workers by default

## Metrics

| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| LCP (Largest Contentful Paint) | ≤ 2.5s | 2.5–4.0s | > 4.0s |
| CLS (Cumulative Layout Shift) | ≤ 0.1 | 0.1–0.25 | > 0.25 |
| INP (Interaction to Next Paint) | ≤ 200ms | 200–500ms | > 500ms |
| FCP (First Contentful Paint) | ≤ 1.8s | 1.8–3.0s | > 3.0s |
| TTFB (Time to First Byte) | ≤ 0.8s | 0.8–1.8s | > 1.8s |

## Prerequisites

- `GOOGLE_PAGESPEED_API_TOKEN` environment variable ([get one here](https://console.cloud.google.com/apis/credentials))
- [`gog` CLI](https://github.com/AriKimelman/gogcli) for Google Sheets read/write
- `agent-browser` CLI for web.dev scraping fallback (optional)
- Python 3.8+

## Usage

### Google Sheet Mode

Your Google Sheet must:
- Have URLs in **column A** (starting at row 2, row 1 is headers)
- Be **editable** by the Google account you specify

```bash
# Run bulk scan
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --account you@example.com

# Resume from a specific index
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --account you@example.com --start 150

# Custom worker count
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --account you@example.com --workers 6
```

The script writes results to columns B–N:

| Column | Metric |
|--------|--------|
| B | Mobile LCP (s) |
| C | Mobile CLS |
| D | Mobile INP (ms) |
| E | Mobile FCP (s) |
| F | Mobile TTFB (s) |
| G | Mobile CWV Assessment |
| H | Desktop LCP (s) |
| I | Desktop CLS |
| J | Desktop INP (ms) |
| K | Desktop FCP (s) |
| L | Desktop TTFB (s) |
| M | Desktop CWV Assessment |
| N | Data Source |

### Retry Errors via Browser Scraping

After the bulk scan, some URLs may show ERROR (API timeouts on heavy sites). Retry them by scraping web.dev:

```bash
python3 scripts/pagespeed-retry-browser.py SPREADSHEET_ID --account you@example.com
```

## How It Works

1. **API call** → Google PageSpeed Insights API v5 for each URL (mobile + desktop)
2. **CrUX extraction** → Pulls real-user p75 field data from `loadingExperience.metrics`
3. **Lab fallback** → If no CrUX data, extracts Lighthouse lab metrics
4. **Sheet write** → Writes full row via Sheets API (single HTTP call per row)
5. **Conditional formatting** → Applied via Sheets batchUpdate API using CWV thresholds

## License

MIT
