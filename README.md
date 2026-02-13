# Core Web Vitals — Claude Skill

Audit website performance using Google's Core Web Vitals (CrUX field data) and PageSpeed Insights API. Works as a skill for Claude Code, OpenClaw, Codex, or any AI agent that supports SKILL.md.

## Features

- **Single URL** — Check one site, get formatted CWV results
- **Batch** — Paste multiple URLs, get results for all
- **Google Sheet** — Point at a sheet with URLs in column A, auto-fills metrics with color-coded conditional formatting
- **CrUX field data** preferred (real user metrics from Chrome UX Report)
- **Lab data** fallback when CrUX unavailable
- **Browser scraping** fallback for API errors (loads web.dev via headless browser)
- **Parallel processing** — 4 concurrent workers by default
- **No pip dependencies** — Uses Python stdlib only

## Metrics

| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| LCP (Largest Contentful Paint) | ≤ 2.5s | 2.5–4.0s | > 4.0s |
| CLS (Cumulative Layout Shift) | ≤ 0.1 | 0.1–0.25 | > 0.25 |
| INP (Interaction to Next Paint) | ≤ 200ms | 200–500ms | > 500ms |
| FCP (First Contentful Paint) | ≤ 1.8s | 1.8–3.0s | > 3.0s |
| TTFB (Time to First Byte) | ≤ 0.8s | 0.8–1.8s | > 1.8s |

## Prerequisites

### 1. PageSpeed Insights API Key
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select existing)
3. Enable the **PageSpeed Insights API**: [Enable here](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com)
4. Go to **APIs & Services → Credentials → Create Credentials → API Key**
5. Set as environment variable: `export GOOGLE_PAGESPEED_API_TOKEN=your_key_here`

### 2. Google Sheets Access (only needed for Google Sheet mode)

*Not required for single URL or batch mode — those just need the PageSpeed API key above.*

**Option A: Service Account (recommended for portability)**
1. In Google Cloud Console, go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**, give it a name, click **Done**
3. Click the service account → **Keys → Add Key → Create new key → JSON**
4. Save the downloaded JSON file (e.g., `service-account.json`)
5. **Share your Google Sheet** with the service account email (the `client_email` in the JSON) — give it **Editor** access

**Option B: gog CLI (for OpenClaw/local environments)**
- Install and authenticate [gog CLI](https://github.com/AriKimelman/gogcli)
- Use `--account your@email.com` instead of `--credentials`

### 3. Python 3.8+

No pip dependencies required — uses Python standard library only. Requires `openssl` CLI for service account JWT signing.

## Usage

### Google Sheet Mode

Your Google Sheet must have URLs in **column A** starting at row 2 (row 1 = headers).

```bash
# With service account
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials service-account.json

# With gog CLI
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --account you@example.com

# Resume from a specific index
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials sa.json --start 150

# Custom worker count
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials sa.json --workers 6

# Override API key
python3 scripts/pagespeed-bulk.py SPREADSHEET_ID --credentials sa.json --api-key YOUR_KEY
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
| N | Data Source (Field/Lab/Web.dev/Error) |

### Retry Errors via Browser Scraping

After the bulk scan, some URLs may show ERROR (API timeouts on heavy sites). Retry by scraping web.dev:

```bash
python3 scripts/pagespeed-retry-browser.py SPREADSHEET_ID --credentials sa.json
```

*Note: Browser retry requires `agent-browser` CLI.*

## Performance

- ~2.5 URLs/minute with 4 parallel workers
- API rate limit: 25,000 requests/day, 400/100s (not the bottleneck)
- Bottleneck is Google's Lighthouse analysis time (30-90s per URL per strategy)
- 1,000 URLs ≈ 6-7 hours

## License

MIT
