/**
 * Mobile view validation for Фаза 3 (closed-beta plan).
 *
 * Opens every page in an iPhone 13 viewport (390×844, DPR 3), waits for
 * hydration, then collects:
 *   - Any console errors or warnings fired during initial render.
 *   - Any uncaught page errors.
 *   - Any failed network requests (status >= 400) for local traffic.
 *   - The text of the first <h1> for a sanity check.
 *   - Whether a mobile nav (<nav> or element with "MobileNav"-ish markup)
 *     is visible, since AppShell renders a mobile nav only below lg.
 *   - Whether the page horizontally overflows the viewport width, which
 *     is the classic "forgot mobile styles" signal.
 *
 * Auth-required screens are pre-seeded with a stable UUID in localStorage
 * under the `ai-stylist:user-id` key (see frontend/src/lib/user-id.ts).
 */

const { chromium, devices } = require("playwright");

const BASE = "http://localhost:3000";
const USER_ID = "00000000-0000-0000-0000-000000000001";

// `/` (landing) and `/sign-in` don't use AppShell — so MobileNav is
// intentionally absent. The check still verifies the hard requirements
// (no console/page errors, no failed requests, no horizontal overflow,
// a visible <h1>), just without the nav visibility gate.
const PAGES = [
  { path: "/", hasAppShell: false },
  { path: "/sign-in", hasAppShell: false },
  { path: "/analyze", hasAppShell: true },
  { path: "/wardrobe", hasAppShell: true },
  { path: "/outfits", hasAppShell: true },
  { path: "/today", hasAppShell: true },
  { path: "/tryon", hasAppShell: true },
  { path: "/insights", hasAppShell: true },
  { path: "/recommendations", hasAppShell: true },
];

function summarize(page, result) {
  const marks = [];
  if (result.consoleErrors.length > 0) marks.push(`console:${result.consoleErrors.length}`);
  if (result.pageErrors.length > 0) marks.push(`pageErr:${result.pageErrors.length}`);
  if (result.failedRequests.length > 0) marks.push(`netErr:${result.failedRequests.length}`);
  if (result.horizontalOverflow) marks.push("overflow");
  if (!result.h1) marks.push("no-h1");
  if (page.hasAppShell && !result.mobileNavVisible) marks.push("no-mobile-nav");
  const status = marks.length === 0 ? "OK" : `FAIL: ${marks.join(", ")}`;
  return `${status.padEnd(40)}  ${page.path}   h1="${result.h1 ?? ""}"`;
}

async function checkOne(browser, path) {
  const iPhone = devices["iPhone 13"];
  const context = await browser.newContext({
    ...iPhone,
    // Seed the local "session" identity before any page script runs so
    // every client-side fetch carries the X-User-Id header that the
    // backend (app/api/deps.py) uses for auth.
    storageState: {
      cookies: [],
      origins: [
        {
          origin: BASE,
          localStorage: [{ name: "ai-stylist:user-id", value: USER_ID }],
        },
      ],
    },
  });

  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];

  const page = await context.newPage();
  page.on("console", (msg) => {
    const type = msg.type();
    if (type === "error" || type === "warning") {
      consoleErrors.push(`${type}: ${msg.text()}`);
    }
  });
  page.on("pageerror", (err) => {
    pageErrors.push(String(err.message || err));
  });
  page.on("response", (res) => {
    const url = res.url();
    if (res.status() >= 400 && (url.startsWith(BASE) || url.includes("localhost:8000"))) {
      failedRequests.push(`${res.status()} ${url}`);
    }
  });

  try {
    await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 15000 });
  } catch (e) {
    pageErrors.push(`navigation: ${e.message}`);
  }

  // Let any post-load React Query work settle.
  await page.waitForTimeout(500);

  const h1 = await page.locator("h1").first().textContent().catch(() => null);

  // AppShell renders both a desktop nav (hidden on small screens via
  // Tailwind `hidden lg:flex`) and a MobileNav (hidden on lg+). On iPhone 13
  // we expect the mobile one to be visible. We look for any nav that's
  // visible and sits at the bottom of the viewport, which matches the
  // MobileNav layout convention.
  const mobileNavVisible = await page.evaluate(() => {
    const navs = Array.from(document.querySelectorAll("nav"));
    for (const n of navs) {
      const r = n.getBoundingClientRect();
      const style = window.getComputedStyle(n);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (r.width === 0 || r.height === 0) continue;
      // Bottom-anchored nav → the MobileNav.
      if (r.bottom > window.innerHeight * 0.75) return true;
    }
    // Some pages (sign-in, landing "/") don't render AppShell at all, so
    // the absence of a mobile nav there is expected — signal that back.
    return false;
  });

  const horizontalOverflow = await page.evaluate(() => {
    // Any horizontal scroll past the viewport is the classic signal that
    // mobile styles are missing or a rogue element has a fixed width.
    return document.documentElement.scrollWidth > window.innerWidth + 1;
  });

  await context.close();

  return {
    consoleErrors,
    pageErrors,
    failedRequests,
    h1: h1 ? h1.trim() : null,
    mobileNavVisible,
    horizontalOverflow,
  };
}

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const page of PAGES) {
    const r = await checkOne(browser, page.path);
    rows.push({ ...page, ...r });
    console.log(summarize(page, r));
  }
  await browser.close();

  // Detail report for any failures.
  for (const row of rows) {
    const hasIssues =
      row.consoleErrors.length > 0 ||
      row.pageErrors.length > 0 ||
      row.failedRequests.length > 0 ||
      row.horizontalOverflow;
    if (!hasIssues) continue;
    console.log(`\n--- ${row.path} ---`);
    for (const l of row.consoleErrors) console.log(`  console: ${l}`);
    for (const l of row.pageErrors) console.log(`  pageError: ${l}`);
    for (const l of row.failedRequests) console.log(`  network: ${l}`);
    if (row.horizontalOverflow) console.log(`  overflow: horizontal scroll present`);
  }

  const anyFail = rows.some((r) => {
    const hardIssues =
      r.consoleErrors.length > 0 ||
      r.pageErrors.length > 0 ||
      r.failedRequests.length > 0 ||
      r.horizontalOverflow ||
      !r.h1;
    const navIssue = r.hasAppShell && !r.mobileNavVisible;
    return hardIssues || navIssue;
  });
  process.exit(anyFail ? 1 : 0);
})();
