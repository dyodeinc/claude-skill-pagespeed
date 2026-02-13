# Core Web Vitals — Claude Skill

Audit website performance using Google's Core Web Vitals (CrUX field data) and PageSpeed Insights API. Works as a skill for Claude Code, OpenClaw, Codex, or any AI agent that supports SKILL.md.

## Features

- **Single URL** — Check one site, get formatted CWV results
- **Compare** — Two URLs side-by-side with winner highlighted per metric
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
5. Copy the example env file and add your key:
   ```bash
   cp .env.example .env
   ```
6. Edit `.env` and replace `your_api_key_here` with your actual key
7. The scripts auto-load `.env` — no manual export needed

### 2. Google Sheets Access (only needed for Google Sheet mode)

*Not required for single URL or batch mode — those just need the PageSpeed API key above.*

**Option A: Service Account (recommended for portability)**
1. In Google Cloud Console, go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**, give it a name, click **Done**
3. Click the service account → **Keys → Add Key → Create new key → JSON**
4. Save the downloaded JSON file (e.g., `service-account.json`)
5. **Share your Google Sheet** with the service account email (the `client_email` in the JSON) — give it **Editor** access

**Option B: gog CLI**
- Install and authenticate [gog CLI](https://github.com/openclaw/gog) — a Google Workspace CLI for Gmail, Calendar, Drive, and Sheets
- Use `--account your@email.com` instead of `--credentials`

### 3. Python 3.8+

No pip dependencies required — uses Python standard library only. Requires `openssl` CLI for service account JWT signing.

## Usage

### Example Prompts

When this skill is installed, your AI agent will automatically use it when you ask about site performance:

**Single URL:**
> `/core-web-vitals rothys.com`
> or: "Check the Core Web Vitals for rothys.com"

```
🌐 rothys.com — CWV: AVERAGE 🟡

📱 Mobile:
  LCP: 2.2s 🟢 | CLS: 0.00 🟢 | INP: 138ms 🟢
  FCP: 2.0s 🟡 | TTFB: 0.5s 🟢

🖥️ Desktop:
  LCP: 2.7s 🟡 | CLS: 0.01 🟢 | INP: 73ms 🟢
  FCP: 1.8s 🟢 | TTFB: 0.4s 🟢

📊 Data: CrUX field (28-day p75)
```

**Compare two sites:**
> `/core-web-vitals rothys.com, skims.com`
> or: "Compare the performance of skims.com vs rothys.com"

```
⚔️ CWV Comparison: rothys.com vs skims.com

| Metric       | rothys.com  | skims.com   | Winner     |
|--------------|-------------|-------------|------------|
| 📱 M-LCP    | 2.2s 🟢    | 2.1s 🟢    | ✅ skims   |
| 📱 M-CLS    | 0.00 🟢    | 0.26 🔴    | ✅ rothys  |
| 📱 M-INP    | 138ms 🟢   | 249ms 🟡   | ✅ rothys  |
| 📱 M-FCP    | 2.0s 🟡    | 1.4s 🟢    | ✅ skims   |
| 📱 M-TTFB   | 0.5s 🟢    | 0.8s 🟢    | ✅ rothys  |
| 🖥️ D-LCP   | 2.7s 🟡    | 1.8s 🟢    | ✅ skims   |
| 🖥️ D-CLS   | 0.01 🟢    | 0.03 🟢    | ✅ rothys  |
| 🖥️ D-INP   | 73ms 🟢    | 95ms 🟢    | ✅ rothys  |
| 🖥️ D-FCP   | 1.8s 🟢    | 1.2s 🟢    | ✅ skims   |
| 🖥️ D-TTFB  | 0.4s 🟢    | 0.5s 🟢    | ✅ rothys  |

Overall: rothys.com wins 6/10 metrics
CWV: rothys AVERAGE 🟡 vs skims FAILED 🔴
```

**Shopify Theme QA (compare before/after theme changes):**
> `/core-web-vitals brandname.myshopify.com?preview_theme_id=111111, brandname.myshopify.com?preview_theme_id=222222`
> or: "Compare CWV before and after theme changes for brandname.myshopify.com"

```
🔍 Shopify Theme QA: brandname.myshopify.com

| Metric       | Before (111111) | After (222222) | Change     |
|--------------|----------------|----------------|------------|
| 📱 M-LCP    | 2.1s 🟢       | 2.8s 🟡       | ⚠️ +0.7s  |
| 📱 M-CLS    | 0.05 🟢       | 0.12 🟡       | ⚠️ +0.07  |
| 📱 M-INP    | 150ms 🟢      | 145ms 🟢      | 🎉 -5ms   |
| ...          |                |                |            |

Summary: 2 regressions ⚠️ | 1 improvement 🎉 | 7 unchanged
🚨 Do not publish — CWV regression detected (LCP crossed green→yellow)
```

*Why two preview URLs?* Shopify preview themes are inherently slower than the live site due to preview mode overhead. Comparing the live URL against a preview URL would always show false regressions. Instead, compare the **production theme in preview mode** (before) against the **development theme in preview mode** (after) for an apples-to-apples comparison that isolates the actual impact of your code changes.

**Batch (multiple URLs):**
> `/core-web-vitals dyode.com, rothys.com, allbirds.com`
> or: "Check CWV for dyode.com, rothys.com, and allbirds.com"

```
📊 Batch CWV Results

| Site          | M-LCP | M-CLS | M-INP  | M-FCP | CWV     |
|---------------|-------|-------|--------|-------|---------|
| dyode.com     | 1.8s 🟢 | 0.02 🟢 | 95ms 🟢 | 1.2s 🟢 | FAST ✅  |
| rothys.com    | 2.2s 🟢 | 0.00 🟢 | 138ms 🟢 | 2.0s 🟡 | AVG 🟡  |
| allbirds.com  | 3.1s 🟡 | 0.08 🟢 | 210ms 🟡 | 2.4s 🟡 | SLOW 🔴 |

📊 Data: CrUX field (28-day p75) | Mobile results shown
```

**Google Sheet:**
> `/core-web-vitals https://docs.google.com/spreadsheets/d/abc123/edit`
> or: "Run PageSpeed audits on all URLs in this sheet: https://docs.google.com/spreadsheets/d/abc123/edit"

```
📋 Starting bulk CWV audit...
  Sheet: "Sheet1" | 1,305 URLs found
  Workers: 4 parallel | Est. time: ~8 hours
  Auth: Service account (cwv-bot@project.iam.gserviceaccount.com)

  Writing results to columns B-N with conditional formatting.
  Progress updates every 25 URLs.

  ✅ Complete: 1,247 processed | 42 CrUX field | 1,163 lab | 42 errors
  🔄 Running browser retry on 42 error rows...
```

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

## Roadmap

Future improvements under consideration:

- [ ] **Historical tracking** — Run the same URLs weekly, store results, show trends ("LCP improved 0.3s since last week")
- [ ] **Lighthouse recommendations** — Parse top 3 actionable audit items (render-blocking resources, image optimization, etc.)
- [ ] **Threshold alerts** — Flag URLs that crossed from green to yellow/red since last run
- [ ] **CSV/Markdown export** — Alternative output formats for batch mode beyond Google Sheets
- [ ] **Progress spinner** — Better visual feedback during long-running API calls

Have an idea? [Open an issue](https://github.com/dyodeinc/claude-skill-pagespeed/issues).

## License

MIT
