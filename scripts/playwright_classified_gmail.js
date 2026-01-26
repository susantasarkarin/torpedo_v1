#!/usr/bin/env node
/*
Playwright smoke check for Classified Gmail route on the VM preview server.
- Navigates to /admin/sales/classified-gmail
- Captures console errors and failed requests
- Takes a screenshot for review
- Reports whether the Classified Gmail text is visible (may require auth)

Usage (on VM):
  BASE_URL=http://127.0.0.1:4173 node /var/www/campaign_platform/scripts/playwright_classified_gmail.js

Environment variables:
  BASE_URL     Base URL of the frontend preview (default http://127.0.0.1:4173)
  ROUTE_PATH   Path to test (default /admin/sales/classified-gmail)
  SCREENSHOT   Where to save the screenshot (default /var/www/campaign_platform/logs/playwright_classified_gmail.png)
  TIMEOUT_MS   Page load timeout in ms (default 20000)
*/

import { chromium } from "playwright"
import fs from "fs"
import path from "path"

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:4173"
const ROUTE_PATH = process.env.ROUTE_PATH || "/admin/sales/classified-gmail"
const TIMEOUT_MS = Number(process.env.TIMEOUT_MS || 20000)
const defaultScreenshot = process.env.SCREENSHOT || "/var/www/campaign_platform/logs/playwright_classified_gmail.png"
const screenshotPath = path.resolve(defaultScreenshot)

async function main() {
  const url = `${BASE_URL}${ROUTE_PATH}`
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const page = await context.newPage()

  const consoleErrors = []
  const failedRequests = []

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text())
    }
  })

  page.on("requestfailed", (req) => {
    failedRequests.push({ url: req.url(), failure: req.failure()?.errorText })
  })

  let navigationOk = false
  let classifiedVisible = false
  let loginVisible = false
  let finalURL = url

  try {
    const response = await page.goto(url, { waitUntil: "networkidle", timeout: TIMEOUT_MS })
    finalURL = page.url()
    navigationOk = !!response && response.ok()
  } catch (err) {
    console.error("Navigation error:", err.message)
  }

  try {
    classifiedVisible = await page.getByText(/Classified Gmail/i).first().isVisible({ timeout: 2000 })
  } catch (_) {
    classifiedVisible = false
  }

  try {
    loginVisible = await page.getByText(/login/i).first().isVisible({ timeout: 2000 })
  } catch (_) {
    loginVisible = false
  }

  await fs.promises.mkdir(path.dirname(screenshotPath), { recursive: true })
  await page.screenshot({ path: screenshotPath, fullPage: true })

  await browser.close()

  const result = {
    testedUrl: url,
    finalURL,
    navigationOk,
    classifiedVisible,
    loginVisible,
    consoleErrors,
    failedRequests,
    screenshotPath,
  }

  console.log(JSON.stringify(result, null, 2))

  if (!navigationOk || failedRequests.length > 0) {
    process.exit(1)
  }
  process.exit(0)
}

main().catch((err) => {
  console.error("Fatal error:", err)
  process.exit(1)
})
