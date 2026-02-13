#!/usr/bin/env node

/**
 * Local Core Web Vitals Measurement using Puppeteer + web-vitals
 * 
 * Measures CWV locally without calling Google API.
 * Follows the pattern from Hux's production-performance-capture.js.
 * 
 * **IMPORTANT: INP Not Supported in Local Mode**
 * INP requires PerformanceEventTiming entries from real user interactions.
 * Puppeteer's synthetic events (even PointerEvents via CDP) do not generate these
 * entries in headless Chrome. This is a fundamental browser limitation.
 * Even Google Lighthouse doesn't measure INP — it uses TBT as a proxy instead.
 * 
 * INP is only available via CrUX field data (API mode).
 * Local mode provides TBT, SI, and TTI as lab-specific alternatives.
 * 
 * Usage:
 *   node pagespeed-local.js example.com
 *   node pagespeed-local.js --mobile example.com
 *   node pagespeed-local.js --json example.com
 *   node pagespeed-local.js site-a.com site-b.com  # compare mode
 */

const puppeteer = require('puppeteer');
const fs = require('fs').promises;
const path = require('path');

// Thresholds for rating (CWV + lab metrics)
const THRESHOLDS = {
  // Core Web Vitals (field-comparable)
  lcp:  { good: 2.5, poor: 4.0 },
  cls:  { good: 0.1, poor: 0.25 },
  fcp:  { good: 1.8, poor: 3.0 },
  ttfb: { good: 0.8, poor: 1.8 },
  // Lab-only metrics
  tbt:  { good: 200, poor: 600 },     // Total Blocking Time (ms)
  si:   { good: 3400, poor: 5800 },   // Speed Index (ms)
  tti:  { good: 3800, poor: 7300 },   // Time to Interactive (ms)
};

class LocalCWVMeasurement {
  constructor(options = {}) {
    this.debug = options.debug || false;
    this.webVitalsLib = null;
    this.mobile = options.mobile || false;
  }

  async init() {
    // Load web-vitals library
    const possiblePaths = [
      path.join(__dirname, '../node_modules/web-vitals/dist/web-vitals.iife.js'),
      path.join(process.cwd(), 'node_modules/web-vitals/dist/web-vitals.iife.js'),
    ];
    
    for (const webVitalsPath of possiblePaths) {
      try {
        this.webVitalsLib = await fs.readFile(webVitalsPath, 'utf-8');
        if (this.debug) console.error(`✅ Web-vitals library loaded from: ${webVitalsPath}`);
        return;
      } catch (error) {
        // Try next path
      }
    }
    
    throw new Error('❌ Web-vitals library not found. Run: npm install web-vitals');
  }

  log(message) {
    if (this.debug) {
      const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
      console.error(`[${timestamp}] ${message}`);
    }
  }

  async measure(url) {
    if (!url.startsWith('http')) {
      url = `https://${url}`;
    }

    this.log(`🌐 Measuring ${url} (${this.mobile ? 'mobile' : 'desktop'})...`);

    const browser = await puppeteer.launch({
      headless: 'new',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
        '--enable-blink-features=LayoutInstabilityAPI,LargestContentfulPaint',
        '--enable-features=ElementTiming',
        '--disable-blink-features=AutomationControlled',
        '--window-size=1920,1080',
      ]
    });

    try {
      const page = await browser.newPage();
      
      // Configure viewport and user agent
      if (this.mobile) {
        await page.setViewport({ 
          width: 412, 
          height: 823, 
          deviceScaleFactor: 2.625,
          isMobile: true,
          hasTouch: true
        });
        await page.setUserAgent('Mozilla/5.0 (Linux; Android 10; Pixel 4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36');
      } else {
        await page.setViewport({ width: 1350, height: 940 });
      }

      // Inject web-vitals before navigation
      if (this.webVitalsLib) {
        await page.evaluateOnNewDocument(this.webVitalsLib);
        this.log('✅ Web-vitals library injected');
      }

      // Set up metric collection
      await page.evaluateOnNewDocument(() => {
        window.__performanceMetrics = {
          webVitals: {},
          longTasks: [],
          lcpCandidates: [],
          paintEntries: []
        };

        // Track long tasks for TBT and TTI
        if (typeof PerformanceObserver !== 'undefined') {
          const taskObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (entry.duration > 50) {
                window.__performanceMetrics.longTasks.push({
                  startTime: entry.startTime,
                  duration: entry.duration,
                  blockingTime: entry.duration - 50
                });
              }
            }
          });
          
          try {
            taskObserver.observe({ entryTypes: ['longtask'] });
          } catch (e) {
            // Long tasks not supported
          }

          // Track paint entries for Speed Index estimation
          const paintObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              window.__performanceMetrics.paintEntries.push({
                name: entry.name,
                startTime: entry.startTime
              });
            }
          });
          
          try {
            paintObserver.observe({ entryTypes: ['paint'] });
          } catch (e) {
            // Paint observer not supported
          }
        }

        // Initialize web-vitals collection (NO INP)
        if (typeof webVitals !== 'undefined') {
          const captureMetric = (metric) => {
            window.__performanceMetrics.webVitals[metric.name] = {
              value: metric.value,
              rating: metric.rating,
              delta: metric.delta
            };
          };

          webVitals.onLCP(captureMetric, { reportAllChanges: true });
          webVitals.onFCP(captureMetric);
          webVitals.onCLS(captureMetric, { reportAllChanges: true });
          webVitals.onTTFB(captureMetric);
          webVitals.onFID(captureMetric);
          // INP intentionally omitted — not measurable in synthetic tests
        }

        // Track LCP candidates
        if (typeof PerformanceObserver !== 'undefined') {
          const lcpObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              window.__performanceMetrics.lcpCandidates.push({
                startTime: entry.startTime,
                renderTime: entry.renderTime || entry.startTime,
                size: entry.size
              });
            }
          });
          
          try {
            lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
          } catch (e) {}
        }
      });

      // Enable throttling for mobile
      if (this.mobile) {
        const client = await page.target().createCDPSession();
        await client.send('Network.enable');
        await client.send('Network.emulateNetworkConditions', {
          offline: false,
          downloadThroughput: 1.5 * 1024 * 1024 / 8, // 1.5 Mbps
          uploadThroughput: 750 * 1024 / 8, // 750 Kbps
          latency: 40 // 40ms
        });
        await client.send('Emulation.setCPUThrottlingRate', { rate: 4 });
        this.log('📱 Mobile throttling enabled (3G network, 4x CPU slowdown)');
      }

      // Navigate to URL
      this.log(`🌐 Navigating to ${url}...`);
      await page.goto(url, { 
        waitUntil: 'domcontentloaded',
        timeout: 30000 
      });
      this.log('✅ Page loaded (DOMContentLoaded)');

      // Wait for initial stabilization
      this.log('⏳ Waiting 5s for initial page stabilization...');
      await new Promise(resolve => setTimeout(resolve, 5000));

      // Progressive checks with scrolling (trigger lazy loading)
      const maxWaitTime = 15000;
      const checkInterval = 3000;
      let lastLCP = null;
      let stableLCPCount = 0;

      this.log('🔄 Starting progressive metric collection...');
      for (let elapsed = 0; elapsed < maxWaitTime; elapsed += checkInterval) {
        // Check current LCP
        const currentLCP = await page.evaluate(() => {
          const perf = window.__performanceMetrics || {};
          return perf.webVitals?.LCP?.value || null;
        });

        if (currentLCP === lastLCP && currentLCP !== null) {
          stableLCPCount++;
          if (stableLCPCount >= 2) {
            this.log(`✅ LCP stabilized at ${currentLCP.toFixed(0)}ms`);
            break;
          }
        } else {
          stableLCPCount = 0;
          lastLCP = currentLCP;
        }

        // Scroll to trigger lazy loading
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
        await new Promise(resolve => setTimeout(resolve, checkInterval));
      }

      // Scroll back to top
      await page.evaluate(() => window.scrollTo(0, 0));
      await new Promise(resolve => setTimeout(resolve, 500));

      // Force LCP finalization by clicking body
      this.log('🖱️ Forcing LCP finalization...');
      try {
        await page.click('body');
      } catch (e) {
        // Click may fail, that's ok
      }
      await new Promise(resolve => setTimeout(resolve, 1000));

      // Collect all metrics
      this.log('📊 Collecting final metrics...');
      const metrics = await page.evaluate(() => {
        const perf = window.__performanceMetrics || {};
        const nav = performance.getEntriesByType('navigation')[0];
        const paint = performance.getEntriesByType('paint');
        const lcpEntries = performance.getEntriesByType('largest-contentful-paint');

        // Get FCP
        const fcp = perf.webVitals?.FCP?.value || 
          paint.find(e => e.name === 'first-contentful-paint')?.startTime || null;

        // Get final LCP
        let finalLCP = perf.webVitals?.LCP?.value || null;
        if (lcpEntries.length > 0) {
          const apiLCP = lcpEntries[lcpEntries.length - 1].startTime;
          if (!finalLCP || apiLCP > finalLCP) {
            finalLCP = apiLCP;
          }
        }

        // Calculate TBT (Total Blocking Time)
        let totalBlockingTime = 0;
        if (perf.longTasks && perf.longTasks.length > 0 && fcp) {
          const tti = nav ? nav.loadEventEnd : finalLCP || 10000;
          
          perf.longTasks.forEach(task => {
            if (task.startTime >= fcp && task.startTime < tti) {
              totalBlockingTime += task.blockingTime;
            }
          });
        }

        // Calculate TTI (Time to Interactive)
        // TTI = first point after FCP where there's a 5-second quiet window (no long tasks >50ms)
        let tti = null;
        if (fcp && perf.longTasks) {
          const quietWindow = 5000; // 5 seconds
          const maxTime = nav ? nav.loadEventEnd : (finalLCP || 0) + 10000;
          
          // Sort long tasks by start time
          const sortedTasks = perf.longTasks
            .filter(t => t.startTime >= fcp)
            .sort((a, b) => a.startTime - b.startTime);
          
          if (sortedTasks.length === 0) {
            // No long tasks after FCP = TTI is FCP
            tti = fcp;
          } else {
            // Find first 5-second gap after the last long task
            let lastTaskEnd = fcp;
            let foundQuietWindow = false;
            
            for (let i = 0; i < sortedTasks.length; i++) {
              const task = sortedTasks[i];
              const gapBeforeTask = task.startTime - lastTaskEnd;
              
              if (gapBeforeTask >= quietWindow) {
                // Found quiet window
                tti = lastTaskEnd;
                foundQuietWindow = true;
                break;
              }
              
              lastTaskEnd = task.startTime + task.duration;
            }
            
            // If no quiet window found during tasks, TTI is after last task + quiet window
            if (!foundQuietWindow) {
              tti = lastTaskEnd;
            }
          }
        }

        // Calculate Speed Index (SI)
        // Using FCP * 1.8 as approximation (Hux pattern)
        // More sophisticated: use visual progress if available
        let speedIndex = null;
        if (fcp) {
          // Simple estimation: SI ≈ FCP * 1.8
          speedIndex = fcp * 1.8;
          
          // If we have FCP and LCP, interpolate
          if (finalLCP && finalLCP > fcp) {
            // Assume linear visual progress from FCP (10%) to LCP (100%)
            // SI = weighted average of visual completeness over time
            // Simplified: SI ≈ FCP + (LCP - FCP) * 0.6
            speedIndex = fcp + (finalLCP - fcp) * 0.6;
          }
        }

        return {
          // Core Web Vitals (field-comparable)
          lcp: finalLCP ? Math.round(finalLCP) / 1000 : null,
          fcp: fcp ? Math.round(fcp) / 1000 : null,
          cls: perf.webVitals?.CLS?.value || 0,
          ttfb: perf.webVitals?.TTFB?.value ? Math.round(perf.webVitals.TTFB.value) / 1000 : null,
          // Lab-only metrics
          tbt: Math.round(totalBlockingTime),
          tti: tti ? Math.round(tti) / 1000 : null,
          si: speedIndex ? Math.round(speedIndex) / 1000 : null,
          source: 'Local (Puppeteer)'
        };
      });

      this.log('✅ Metrics collected');
      await browser.close();

      return metrics;
    } catch (error) {
      await browser.close();
      throw error;
    }
  }
}

// Formatting functions (matching pagespeed-single.py)
function indicator(metric, value) {
  if (value === null || value === undefined) return '—';
  const thresh = THRESHOLDS[metric];
  if (!thresh) return '—';
  
  // Handle millisecond metrics (tbt, si, tti stored as seconds but thresholds in ms)
  const compareValue = (['tbt', 'si', 'tti'].includes(metric)) ? value * 1000 : value;
  
  if (compareValue <= thresh.good) return '🟢';
  if (compareValue <= thresh.poor) return '🟡';
  return '🔴';
}

function fmt(metric, value) {
  if (value === null || value === undefined) return 'N/A';
  if (metric === 'tbt') return `${Math.round(value * 1000)}ms`;  // convert back to ms for display
  if (metric === 'si') return `${(value * 1000).toFixed(0)}ms`;
  if (metric === 'tti') return `${value.toFixed(1)}s`;
  if (metric === 'cls') return value.toFixed(2);
  return `${value.toFixed(1)}s`;
}

function printSingle(url, mobile, desktop) {
  console.log(`\n🌐 **${url}** — CWV: Local Measurement\n`);
  
  for (const [label, data] of [['📱 Mobile', mobile], ['🖥️ Desktop', desktop]]) {
    if (data) {
      // CWV metrics (field-comparable)
      const cwvMetrics = ['lcp', 'cls', 'fcp', 'ttfb'].map(k => {
        const v = data[k];
        return `${k.toUpperCase()}: ${fmt(k, v)} ${indicator(k, v)}`;
      });
      
      // Lab metrics (local-only)
      const labMetrics = ['tbt', 'si', 'tti'].map(k => {
        const v = data[k];
        return `${k.toUpperCase()}: ${fmt(k, v)} ${indicator(k, v)}`;
      });
      
      console.log(`${label} *(${data.source})*:`);
      console.log(`  CWV: ${cwvMetrics.join(' | ')}`);
      console.log(`  Lab: ${labMetrics.join(' | ')}`);
    } else {
      console.log(`${label}: ❌ Measurement failed`);
    }
  }
  console.log(`\n📊 Data Source: ${mobile?.source || desktop?.source || 'N/A'}`);
}

function printCompare(urlA, mobA, deskA, urlB, mobB, deskB) {
  console.log(`\n⚔️ **CWV Comparison: ${urlA} vs ${urlB}** *(Local)*\n`);
  console.log(`| Metric | ${urlA} | ${urlB} | Winner |`);
  console.log(`|--------|${'---'.repeat(5)}|${'---'.repeat(5)}|--------|`);
  
  const wins = { [urlA]: 0, [urlB]: 0 };
  
  for (const [prefix, dataA, dataB] of [['📱', mobA, mobB], ['🖥️', deskA, deskB]]) {
    if (!dataA || !dataB) continue;
    
    for (const k of ['lcp', 'cls', 'fcp', 'ttfb', 'tbt', 'si', 'tti']) {
      const va = dataA[k];
      const vb = dataB[k];
      const fa = va !== null ? `${fmt(k, va)} ${indicator(k, va)}` : 'N/A';
      const fb = vb !== null ? `${fmt(k, vb)} ${indicator(k, vb)}` : 'N/A';
      
      let winner = '—';
      if (va !== null && vb !== null) {
        if (va < vb) {
          winner = `✅ ${urlA}`;
          wins[urlA]++;
        } else if (vb < va) {
          winner = `✅ ${urlB}`;
          wins[urlB]++;
        } else {
          winner = 'Tie';
        }
      }
      
      const label = `${prefix} ${k.toUpperCase()}`;
      console.log(`| ${label} | ${fa} | ${fb} | ${winner} |`);
    }
  }
  
  const total = wins[urlA] + wins[urlB];
  const leader = wins[urlA] >= wins[urlB] ? urlA : urlB;
  console.log(`\n**Overall: ${leader} wins ${wins[leader]}/${total} metrics**`);
}

// Permanent errors that will never succeed on retry — don't waste time
const PERMANENT_ERRORS = [
  'ERR_NAME_NOT_RESOLVED',        // DNS failure — domain doesn't exist
  'ERR_CONNECTION_REFUSED',        // Server not accepting connections
  'ERR_CERT_AUTHORITY_INVALID',    // SSL certificate errors
  'ERR_CERT_COMMON_NAME_INVALID',
  'ERR_SSL_PROTOCOL_ERROR',
  'ERR_ABORTED',                   // Navigation aborted (e.g., redirect loop)
  'net::ERR_NAME_NOT_RESOLVED',
  'net::ERR_CONNECTION_REFUSED',
];

function isPermanentError(error) {
  const msg = error.message || '';
  return PERMANENT_ERRORS.some(pe => msg.includes(pe));
}

async function measureWithRetry(measurer, url, maxAttempts = 3) {
  let lastError = null;
  
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      if (attempt > 1) {
        // Exponential backoff: 1s, 2s, 4s
        const backoff = Math.pow(2, attempt - 1) * 1000;
        console.error(`   Retry attempt ${attempt}/${maxAttempts} (waiting ${backoff / 1000}s)...`);
        await new Promise(resolve => setTimeout(resolve, backoff));
      }
      
      const result = await measurer.measure(url);
      
      if (attempt > 1) {
        console.error(`   ✅ Succeeded on attempt ${attempt}`);
      }
      
      return result;
    } catch (error) {
      lastError = error;
      console.error(`   ❌ Attempt ${attempt}/${maxAttempts} failed: ${error.message}`);
      
      // Don't retry permanent errors — they'll never succeed
      if (isPermanentError(error)) {
        console.error(`   ⛔ Permanent error detected, skipping remaining retries`);
        throw error;
      }
      
      if (attempt === maxAttempts) {
        throw error;
      }
    }
  }
  
  throw lastError;
}

async function main() {
  const args = process.argv.slice(2);
  
  // Parse flags
  let mobile = false;
  let jsonOutput = false;
  let debug = false;
  const urls = [];
  
  for (const arg of args) {
    if (arg === '--mobile') mobile = true;
    else if (arg === '--json') jsonOutput = true;
    else if (arg === '--debug') debug = true;
    else if (!arg.startsWith('--')) urls.push(arg);
  }
  
  if (urls.length === 0) {
    console.error('Usage: node pagespeed-local.js [--mobile] [--json] [--debug] <url> [<url2> ...]');
    process.exit(1);
  }

  const results = [];
  
  for (const url of urls) {
    const measurer = new LocalCWVMeasurement({ mobile: false, debug });
    await measurer.init();
    
    console.error(`Measuring ${url} (desktop)...`);
    let desktop = null;
    try {
      desktop = await measureWithRetry(measurer, url);
    } catch (error) {
      console.error(`❌ Desktop measurement failed after all retries: ${error.message}`);
    }
    
    let mobileData = null;
    if (mobile) {
      console.error(`Measuring ${url} (mobile)...`);
      const mobileMeasurer = new LocalCWVMeasurement({ mobile: true, debug });
      await mobileMeasurer.init();
      try {
        mobileData = await measureWithRetry(mobileMeasurer, url);
      } catch (error) {
        console.error(`❌ Mobile measurement failed after all retries: ${error.message}`);
      }
    }
    
    results.push({ url, mobile: mobileData, desktop });
  }
  
  if (jsonOutput) {
    console.log(JSON.stringify(results, null, 2));
    process.exit(0);
  }
  
  if (results.length === 1) {
    const { url, mobile, desktop } = results[0];
    printSingle(url, mobile, desktop);
  } else if (results.length === 2) {
    printCompare(
      results[0].url, results[0].mobile, results[0].desktop,
      results[1].url, results[1].mobile, results[1].desktop
    );
  } else {
    console.log('\n📊 **Batch CWV Results** *(Local)*\n');
    console.log('| Site | LCP | CLS | FCP | TTFB | TBT | SI | TTI |');
    console.log('|------|-----|-----|-----|------|-----|----|----|');
    for (const { url, desktop } of results) {
      if (desktop) {
        const metrics = ['lcp', 'cls', 'fcp', 'ttfb', 'tbt', 'si', 'tti'].map(k => {
          const v = desktop[k];
          return v !== null ? `${fmt(k, v)} ${indicator(k, v)}` : 'N/A';
        });
        console.log(`| ${url} | ${metrics.join(' | ')} |`);
      } else {
        console.log(`| ${url} | ERROR | — | — | — | — | — | — |`);
      }
    }
  }
}

main().catch(error => {
  console.error(`\n❌ Error: ${error.message}`);
  if (error.stack) console.error(error.stack);
  process.exit(1);
});
