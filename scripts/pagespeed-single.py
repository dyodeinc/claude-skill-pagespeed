#!/usr/bin/env python3
"""Single/batch PageSpeed audit — outputs formatted results to stdout.

Usage:
  python3 pagespeed-single.py example.com
  python3 pagespeed-single.py site-a.com site-b.com          # compare mode
  python3 pagespeed-single.py site1.com site2.com site3.com   # batch mode
  python3 pagespeed-single.py --api-key YOUR_KEY example.com  # inline key
"""

import json, os, sys, urllib.request, urllib.parse, argparse

API_KEY = os.environ.get("GOOGLE_PAGESPEED_API_TOKEN", "")

THRESHOLDS = {
    "lcp":  (2.5, 4.0),
    "cls":  (0.1, 0.25),
    "inp":  (200, 500),
    "fcp":  (1.8, 3.0),
    "ttfb": (0.8, 1.8),
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
    elif metric == "cls":
        return f"{value:.2f}"
    else:
        return f"{value:.1f}s"

def fetch(url, strategy):
    if not url.startswith("http"):
        url = f"https://{url}"
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={urllib.parse.quote(url, safe='')}&strategy={strategy}"
        f"&category=performance&key={API_KEY}"
    )
    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

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
    m_cwv = mobile["cwv"] if mobile else "ERROR"
    d_cwv = desktop["cwv"] if desktop else "ERROR"
    best_cwv = m_cwv if m_cwv != "N/A" else d_cwv
    print(f"\n🌐 **{url}** — CWV: {best_cwv} {CWV_EMOJI.get(best_cwv, '❓')}\n")
    
    for label, data, emoji in [("📱 Mobile", mobile, "📱"), ("🖥️ Desktop", desktop, "🖥️")]:
        if data:
            src = f" *({data['source']})*" if data["source"] != "CrUX field" else ""
            metrics = []
            for k in ["lcp", "cls", "inp", "fcp", "ttfb"]:
                v = data[k]
                metrics.append(f"{k.upper()}: {fmt(k, v)} {indicator(k, v) if v is not None else ''}")
            print(f"{label}{src}:")
            print(f"  {' | '.join(metrics[:3])}")
            print(f"  {' | '.join(metrics[3:])}")
        else:
            print(f"{label}: ❌ No data available")
    print(f"\n📊 Data: {mobile['source'] if mobile else 'N/A'} (mobile) | {desktop['source'] if desktop else 'N/A'} (desktop)")

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
    args = parser.parse_args()

    global API_KEY
    if args.api_key:
        API_KEY = args.api_key
    if not API_KEY:
        print("Error: Set GOOGLE_PAGESPEED_API_TOKEN or use --api-key", file=sys.stderr)
        sys.exit(1)

    results = []
    for url in args.urls:
        clean = url.strip().rstrip(",")
        if not clean:
            continue
        print(f"Fetching {clean}...", file=sys.stderr)
        mob_raw = fetch(clean, "mobile")
        desk_raw = fetch(clean, "desktop")
        mob, mob_err = extract(mob_raw) if "error" not in mob_raw else (None, mob_raw["error"])
        desk, desk_err = extract(desk_raw) if "error" not in desk_raw else (None, desk_raw["error"])
        results.append((clean, mob, desk))

    if len(results) == 1:
        url, mob, desk = results[0]
        print_single(url, mob, desk)
    elif len(results) == 2:
        print_compare(results[0][0], results[0][1], results[0][2],
                      results[1][0], results[1][1], results[1][2])
    else:
        # Batch
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

if __name__ == "__main__":
    main()
