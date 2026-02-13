#!/usr/bin/env python3
"""Single/batch PageSpeed audit — outputs formatted results to stdout.

Usage:
  python3 pagespeed-single.py example.com
  python3 pagespeed-single.py site-a.com site-b.com          # compare mode
  python3 pagespeed-single.py site1.com site2.com site3.com   # batch mode
  python3 pagespeed-single.py --api-key YOUR_KEY example.com  # inline key
  python3 pagespeed-single.py --local example.com             # local Puppeteer mode
  python3 pagespeed-single.py --local --mobile example.com    # local mobile mode
"""

import json, os, sys, urllib.request, urllib.parse, argparse, subprocess

def _load_dotenv():
    """Auto-load .env files — search cwd, parents, skill dir, home."""
    candidates = [os.path.join(os.getcwd(), ".env")]
    # Walk up from cwd to find .env in parent dirs
    d = os.getcwd()
    for _ in range(10):
        parent = os.path.dirname(d)
        if parent == d:
            break
        candidates.append(os.path.join(parent, ".env"))
        d = parent
    # Skill root (parent of scripts/)
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    # Home dir
    candidates.append(os.path.join(os.path.expanduser("~"), ".env"))
    
    for path in candidates:
        if os.path.isfile(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        val = val.strip().strip('"').strip("'")
                        os.environ.setdefault(key.strip(), val)
            break

_load_dotenv()
API_KEY = os.environ.get("GOOGLE_PAGESPEED_API_TOKEN", "")
TIMEOUT = 120

THRESHOLDS = {
    # Core Web Vitals (field-comparable)
    "lcp":  (2.5, 4.0),
    "cls":  (0.1, 0.25),
    "inp":  (200, 500),  # API mode only
    "fcp":  (1.8, 3.0),
    "ttfb": (0.8, 1.8),
    # Lab-only metrics (local mode)
    "tbt":  (0.2, 0.6),   # Total Blocking Time (seconds for consistency)
    "si":   (3.4, 5.8),   # Speed Index (seconds)
    "tti":  (3.8, 7.3),   # Time to Interactive (seconds)
}

def indicator(metric, value):
    if value == "" or value is None:
        return "—"
    good, poor = THRESHOLDS[metric]
    if value <= good:
        return "🟢"
    elif value <= poor:
        return "🟡"
    return "🔴"

def fmt(metric, value):
    if value == "" or value is None:
        return "N/A"
    if metric == "inp":
        return f"{int(value)}ms"
    elif metric in ["tbt", "si"]:  # Lab metrics in seconds, display as ms
        return f"{int(value * 1000)}ms" if isinstance(value, (int, float)) else "N/A"
    elif metric == "cls":
        return f"{value:.2f}"
    else:
        return f"{value:.1f}s"

def fetch(url, strategy, max_retries=3):
    if not url.startswith("http"):
        url = f"https://{url}"
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={urllib.parse.quote(url, safe='')}&strategy={strategy}"
        f"&category=performance&key={API_KEY}"
    )
    # Permanent errors that won't succeed on retry
    PERMANENT_ERRORS = ["404", "403", "DNS", "ENOTFOUND", "CERT_", "SSL", "Name or service not known"]

    def is_permanent(err_str):
        return any(pe.lower() in err_str.lower() for pe in PERMANENT_ERRORS)

    import time
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
                if "error" not in data:
                    if attempt > 1:
                        print(f"  ✅ Succeeded on attempt {attempt}", file=sys.stderr)
                    return data
                last_error = data.get("error", {}).get("message", "Unknown API error")
        except Exception as e:
            last_error = str(e)
        if is_permanent(last_error):
            print(f"  ⛔ Permanent error ({last_error}), skipping retries", file=sys.stderr)
            return {"error": last_error}
        if attempt < max_retries:
            wait = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
            print(f"  ⚠️ Attempt {attempt} failed ({last_error}), retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
    return {"error": last_error or "All retries failed"}

def extract(data):
    le = data.get("loadingExperience", {})
    m = le.get("metrics", {})
    oc = le.get("overall_category")
    if m and oc:
        return {
            "lcp": round(m.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile", 0) / 1000, 2),
            "cls": round(m.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile", 0) / 100, 2),
            "inp": m.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile"),
            "fcp": round(m.get("FIRST_CONTENTFUL_PAINT_MS", {}).get("percentile", 0) / 1000, 2),
            "ttfb": round(m.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE", {}).get("percentile", 0) / 1000, 2),
            "cwv": oc,
            "source": "CrUX field",
        }, None
    # Lab fallback
    a = data.get("lighthouseResult", {}).get("audits", {})
    if not a:
        return None, "API error or timeout"
    try:
        return {
            "lcp": round(a["largest-contentful-paint"]["numericValue"] / 1000, 2),
            "cls": round(a["cumulative-layout-shift"]["numericValue"], 3),
            "inp": None,
            "fcp": round(a["first-contentful-paint"]["numericValue"] / 1000, 2),
            "ttfb": round(a.get("server-response-time", {}).get("numericValue", 0) / 1000, 2),
            "cwv": "N/A",
            "source": "Lab",
        }, None
    except (KeyError, TypeError):
        return None, "Parse error"

CWV_EMOJI = {"FAST": "✅", "AVERAGE": "🟡", "SLOW": "🔴", "N/A": "—"}

def print_single(url, mobile, desktop):
    m_cwv = mobile.get("cwv", "N/A") if mobile else "ERROR"
    d_cwv = desktop.get("cwv", "N/A") if desktop else "ERROR"
    best_cwv = m_cwv if m_cwv != "N/A" else d_cwv
    print(f"\n🌐 **{url}** — CWV: {best_cwv} {CWV_EMOJI.get(best_cwv, '❓')}\n")
    
    for label, data, emoji in [("📱 Mobile", mobile, "📱"), ("🖥️ Desktop", desktop, "🖥️")]:
        if data:
            src = f" *({data['source']})*" if data.get("source") != "CrUX field" else ""
            is_local = data.get('source') == 'Local (Puppeteer)'
            
            # CWV metrics (always available)
            cwv_metrics = []
            for k in ["lcp", "cls", "fcp", "ttfb"]:
                v = data.get(k)
                cwv_metrics.append(f"{k.upper()}: {fmt(k, v)} {indicator(k, v) if v is not None else ''}")
            
            print(f"{label}{src}:")
            print(f"  CWV: {' | '.join(cwv_metrics)}")
            
            # Lab metrics (local mode only)
            if is_local:
                lab_metrics = []
                for k in ["tbt", "si", "tti"]:
                    v = data.get(k)
                    lab_metrics.append(f"{k.upper()}: {fmt(k, v)} {indicator(k, v) if v is not None else ''}")
                print(f"  Lab: {' | '.join(lab_metrics)}")
            else:
                # API mode: show INP if available
                inp = data.get("inp")
                if inp is not None:
                    print(f"  INP: {fmt('inp', inp)} {indicator('inp', inp)}")
        else:
            print(f"{label}: ❌ No data available")
    print(f"\n📊 Data: {mobile.get('source') if mobile else 'N/A'} (mobile) | {desktop.get('source') if desktop else 'N/A'} (desktop)")

def print_compare(url_a, a_mob, a_desk, url_b, b_mob, b_desk):
    print(f"\n⚔️ **CWV Comparison: {url_a} vs {url_b}**\n")
    print(f"| Metric | {url_a} | {url_b} | Winner |")
    print(f"|--------|{'---' * 5}|{'---' * 5}|--------|")
    
    wins = {url_a: 0, url_b: 0}
    
    for prefix, a_data, b_data in [("📱", a_mob, b_mob), ("🖥️", a_desk, b_desk)]:
        if not a_data or not b_data:
            continue
        for k in ["lcp", "cls", "inp", "fcp", "ttfb"]:
            va, vb = a_data[k], b_data[k]
            fa = f"{fmt(k, va)} {indicator(k, va)}" if va is not None else "N/A"
            fb = f"{fmt(k, vb)} {indicator(k, vb)}" if vb is not None else "N/A"
            if va is not None and vb is not None:
                if va < vb:
                    winner = f"✅ {url_a}"
                    wins[url_a] += 1
                elif vb < va:
                    winner = f"✅ {url_b}"
                    wins[url_b] += 1
                else:
                    winner = "Tie"
            else:
                winner = "—"
            label = f"{prefix} {k.upper()}"
            print(f"| {label} | {fa} | {fb} | {winner} |")
    
    total = wins[url_a] + wins[url_b]
    leader = url_a if wins[url_a] >= wins[url_b] else url_b
    print(f"\n**Overall: {leader} wins {wins[leader]}/{total} metrics**")
    
    a_cwv = a_mob["cwv"] if a_mob else "?"
    b_cwv = b_mob["cwv"] if b_mob else "?"
    print(f"**CWV: {url_a} {a_cwv} {CWV_EMOJI.get(a_cwv, '?')} vs {url_b} {b_cwv} {CWV_EMOJI.get(b_cwv, '?')}**")

def main():
    parser = argparse.ArgumentParser(description="PageSpeed Insights CWV audit")
    parser.add_argument("urls", nargs="+", help="One or more URLs to audit")
    parser.add_argument("--api-key", help="PageSpeed API key (overrides env var)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output raw JSON instead of formatted text")
    parser.add_argument("--timeout", type=int, default=120, help="API timeout in seconds (default: 120)")
    parser.add_argument("--local", action="store_true", help="Use local Puppeteer measurement instead of Google API")
    parser.add_argument("--mobile", action="store_true", help="Include mobile measurement (local mode only)")
    args = parser.parse_args()

    # If --local flag is passed, shell out to pagespeed-local.js
    if args.local:
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_script = os.path.join(script_dir, "pagespeed-local.js")
        
        if not os.path.isfile(local_script):
            print(f"Error: Local script not found: {local_script}", file=sys.stderr)
            print("Run: cd /home/node/clawd/skills/core-web-vitals && npm install puppeteer web-vitals", file=sys.stderr)
            sys.exit(1)
        
        # Build command
        cmd = ["node", local_script]
        if args.mobile:
            cmd.append("--mobile")
        if args.json_output:
            cmd.append("--json")
        cmd.extend(args.urls)
        
        # Execute and exit with same code
        result = subprocess.run(cmd, cwd=script_dir)
        sys.exit(result.returncode)

    global API_KEY, TIMEOUT
    if args.api_key:
        API_KEY = args.api_key
    if not API_KEY:
        print("Error: Set GOOGLE_PAGESPEED_API_TOKEN or use --api-key", file=sys.stderr)
        sys.exit(1)
    TIMEOUT = args.timeout

    results = []
    has_errors = False
    for url in args.urls:
        clean = url.strip().rstrip(",")
        if not clean:
            continue
        print(f"Fetching {clean} (mobile)...", file=sys.stderr)
        mob_raw = fetch(clean, "mobile")
        print(f"Fetching {clean} (desktop)...", file=sys.stderr)
        desk_raw = fetch(clean, "desktop")
        mob, mob_err = extract(mob_raw) if "error" not in mob_raw else (None, mob_raw["error"])
        desk, desk_err = extract(desk_raw) if "error" not in desk_raw else (None, desk_raw["error"])
        if not mob and not desk:
            has_errors = True
        results.append((clean, mob, desk))

    if args.json_output:
        json_results = []
        for url, mob, desk in results:
            json_results.append({"url": url, "mobile": mob, "desktop": desk})
        print(json.dumps(json_results, indent=2))
        sys.exit(1 if has_errors else 0)

    if len(results) == 1:
        url, mob, desk = results[0]
        print_single(url, mob, desk)
    elif len(results) == 2:
        print_compare(results[0][0], results[0][1], results[0][2],
                      results[1][0], results[1][1], results[1][2])
    else:
        print(f"\n📊 **Batch CWV Results**\n")
        print(f"| Site | M-LCP | M-CLS | M-INP | M-FCP | M-TTFB | CWV |")
        print(f"|------|-------|-------|-------|-------|--------|-----|")
        for url, mob, desk in results:
            if mob:
                row = [url]
                for k in ["lcp", "cls", "inp", "fcp", "ttfb"]:
                    v = mob[k]
                    row.append(f"{fmt(k, v)} {indicator(k, v)}" if v is not None else "N/A")
                row.append(f"{mob['cwv']} {CWV_EMOJI.get(mob['cwv'], '')}")
                print(f"| {' | '.join(row)} |")
            else:
                print(f"| {url} | ERROR | — | — | — | — | — |")

    sys.exit(1 if has_errors else 0)

if __name__ == "__main__":
    main()
