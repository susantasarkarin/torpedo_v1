"""
Live site audit for torpedo.cogentixresearch.com
Checks:
  1. Login
  2. AL Database — lead gen, email generation, field completeness
  3. Email Patterns — detection for mailpool + CSV
  4. Lead generation flow: enrichment → ICP → outreach
  5. Mail Pool → CLIENT/VENDOR leads pulled into Leads section
"""

import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://torpedo.cogentixresearch.com"
CREDS = {"username": "admin", "password": "password123"}
SCREENSHOTS = r"d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\tmp_audit_shots"

import os
os.makedirs(SCREENSHOTS, exist_ok=True)

def ss(page, name):
    path = os.path.join(SCREENSHOTS, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  📸 {name}.png")

def wait_idle(page, timeout=15000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PWTimeout:
        pass  # still usable

def login(page):
    print("\n[1] LOGIN")
    page.goto(f"{BASE}/admin/login", wait_until="domcontentloaded")
    wait_idle(page, 10000)
    ss(page, "01_login_page")

    # Fill credentials
    try:
        page.fill("input[type='text'], input[name='username'], input[placeholder*='user' i], input[placeholder*='email' i]", CREDS["username"])
        page.fill("input[type='password']", CREDS["password"])
        ss(page, "02_login_filled")
        page.click("button[type='submit'], button:has-text('Login'), button:has-text('Sign in')")
        wait_idle(page, 12000)
        ss(page, "03_post_login")
        print(f"  URL after login: {page.url}")
        print("  ✅ Login attempted")
    except Exception as e:
        print(f"  ❌ Login error: {e}")
        ss(page, "02_login_error")

def audit_al_database(page):
    print("\n[2] AL DATABASE (AI Leads)")
    # Navigate to Sales → Campaign → AI Leads
    try:
        page.goto(f"{BASE}/admin/sales/campaign/ai-leads", wait_until="domcontentloaded")
        wait_idle(page, 12000)
        ss(page, "04_al_database")
        
        # Count leads and check field completeness
        leads_data = page.evaluate("""() => {
            const rows = document.querySelectorAll('tr, [data-row], .lead-row, tbody tr');
            const leads = [];
            rows.forEach(r => {
                const cells = r.querySelectorAll('td');
                if (cells.length > 2) {
                    leads.push(Array.from(cells).map(c => c.innerText.trim()).filter(Boolean));
                }
            });
            return { count: leads.length, sample: leads.slice(0, 5) };
        }""")
        print(f"  Rows visible: {leads_data.get('count', 0)}")
        for i, row in enumerate(leads_data.get('sample', [])):
            print(f"    Row {i+1}: {row[:6]}")
        
        # Check enrichment status distribution
        enrichment_stats = page.evaluate("""() => {
            const badges = document.querySelectorAll('[class*="badge"], [class*="status"], [class*="tag"], span, td');
            const counts = {};
            badges.forEach(b => {
                const t = b.innerText.trim().toLowerCase();
                if (['enriched','needed','pending','skipped','failed'].some(s => t === s)) {
                    counts[t] = (counts[t] || 0) + 1;
                }
            });
            return counts;
        }""")
        print(f"  Enrichment status counts: {enrichment_stats}")
        
        # Check email field presence
        email_check = page.evaluate("""() => {
            const emailPattern = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/;
            const allText = document.body.innerText;
            const emails = allText.match(new RegExp(emailPattern.source, 'g')) || [];
            const uniqueDomains = [...new Set(emails.map(e => e.split('@')[1]))];
            return { email_count: emails.length, sample_emails: emails.slice(0, 10), domains: uniqueDomains.slice(0, 8) };
        }""")
        print(f"  Emails visible: {email_check.get('email_count', 0)}")
        print(f"  Sample emails: {email_check.get('sample_emails', [])[:5]}")
        
    except Exception as e:
        print(f"  ❌ AL Database error: {e}")
        ss(page, "04_al_database_error")

def audit_email_patterns(page):
    print("\n[3] EMAIL PATTERNS")
    try:
        page.goto(f"{BASE}/admin/sales/campaign/email-patterns", wait_until="domcontentloaded")
        wait_idle(page, 12000)
        ss(page, "05_email_patterns")
        
        # Get stats
        stats_text = page.evaluate("""() => {
            const cards = document.querySelectorAll('[class*="stat"], [class*="card"], [class*="metric"]');
            return Array.from(cards).map(c => c.innerText.trim()).filter(Boolean);
        }""")
        print(f"  Stats cards: {stats_text[:8]}")
        
        # Check pattern list
        patterns = page.evaluate("""() => {
            const rows = document.querySelectorAll('tr, [class*="pattern-row"]');
            const data = [];
            rows.forEach(r => {
                const t = r.innerText.trim();
                if (t && t.length > 5) data.push(t.substring(0, 80));
            });
            return data.slice(0, 10);
        }""")
        print(f"  Pattern rows: {len(patterns)}")
        for p in patterns[:5]:
            print(f"    {p}")
        
        # Check if new buttons are present
        buttons = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean);
        }""")
        print(f"  Buttons: {buttons}")
        
    except Exception as e:
        print(f"  ❌ Email Patterns error: {e}")
        ss(page, "05_email_patterns_error")

def audit_lead_flow(page):
    print("\n[4] LEAD GENERATION FLOW")
    try:
        # Check leads list with enrichment/ICP/outreach status
        page.goto(f"{BASE}/admin/sales/leads", wait_until="domcontentloaded")
        wait_idle(page, 12000)
        ss(page, "06_leads_list")
        
        lead_stats = page.evaluate("""() => {
            const allText = document.body.innerText;
            const lines = allText.split('\\n').map(l => l.trim()).filter(Boolean);
            
            // Look for ICP tiers
            const icp = {};
            ['A','B','C','D','E','F'].forEach(tier => {
                const count = (allText.match(new RegExp('ICP[\\\\s:]+' + tier + '|Tier[\\\\s:]+' + tier, 'gi')) || []).length;
                if (count) icp[tier] = count;
            });
            
            // Look for outreach status
            const outreach = {};
            ['sent','queued','pending','enrolled','not started'].forEach(s => {
                const c = (allText.toLowerCase().match(new RegExp(s, 'g')) || []).length;
                if (c) outreach[s] = c;
            });
            
            return { icp_counts: icp, outreach_counts: outreach, total_lines: lines.length };
        }""")
        print(f"  ICP tiers found: {lead_stats.get('icp_counts', {})}")
        print(f"  Outreach status mentions: {lead_stats.get('outreach_counts', {})}")
        
        # Check a single lead detail for completeness
        first_lead = page.query_selector("tr:nth-child(2) td a, tbody tr:first-child a, [class*='lead-name'] a")
        if first_lead:
            first_lead.click()
            wait_idle(page, 8000)
            ss(page, "07_lead_detail")
            
            detail = page.evaluate("""() => {
                const fields = {};
                document.querySelectorAll('label, [class*="field-label"], [class*="label"]').forEach(el => {
                    const key = el.innerText.trim();
                    const val = el.nextElementSibling?.innerText?.trim() || '';
                    if (key && val) fields[key] = val;
                });
                return fields;
            }""")
            print(f"  Lead detail fields: {list(detail.keys())[:15]}")
            
    except Exception as e:
        print(f"  ❌ Lead flow error: {e}")
        ss(page, "06_leads_error")

def audit_mailpool_to_leads(page):
    print("\n[5] MAIL POOL → LEADS")
    try:
        # Check mail pool for CLIENT/VENDOR classified
        page.goto(f"{BASE}/admin/mail-pool", wait_until="domcontentloaded")
        wait_idle(page, 12000)
        ss(page, "08_mailpool")
        
        pool_stats = page.evaluate("""() => {
            const allText = document.body.innerText;
            const segments = {};
            ['CLIENT','VENDOR','PROSPECT','PARTNER','SPAM','INTERNAL'].forEach(s => {
                const c = (allText.match(new RegExp(s, 'g')) || []).length;
                if (c) segments[s] = c;
            });
            return { segments };
        }""")
        print(f"  Mail pool segments: {pool_stats.get('segments', {})}")
        
        # Check if "Process & Import" button is visible
        buttons = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean);
        }""")
        has_import = any('import' in b.lower() or 'process' in b.lower() for b in buttons)
        print(f"  'Process & Import' button present: {has_import}")
        print(f"  All buttons: {[b for b in buttons if len(b) > 2][:12]}")
        
        # Now check leads filtered by source=classified_gmail
        page.goto(f"{BASE}/admin/sales/leads?source=classified_gmail", wait_until="domcontentloaded")
        wait_idle(page, 10000)
        ss(page, "09_leads_from_gmail")
        
        gmail_leads = page.evaluate("""() => {
            const rows = document.querySelectorAll('tbody tr');
            const data = [];
            rows.forEach(r => data.push(r.innerText.trim().substring(0, 100)));
            return { count: rows.length, sample: data.slice(0, 5) };
        }""")
        print(f"  Leads from classified_gmail: {gmail_leads.get('count', 0)}")
        for s in gmail_leads.get('sample', []):
            print(f"    {s}")
        
    except Exception as e:
        print(f"  ❌ Mail pool → Leads error: {e}")
        ss(page, "08_mailpool_error")

def audit_api_direct(page):
    """Hit backend API endpoints to get raw data for the audit."""
    print("\n[API CHECKS]")
    checks = [
        ("/api/email-patterns/stats", "Email pattern stats"),
        ("/api/classified-gmail/stats", "Classified Gmail stats"),
        ("/api/sales/leads/stats", "Leads stats"),
    ]
    for path, label in checks:
        try:
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
            wait_idle(page, 8000)
            text = page.evaluate("() => document.body.innerText")
            try:
                data = json.loads(text)
                print(f"  {label}: {json.dumps(data, indent=2)[:500]}")
            except:
                print(f"  {label}: {text[:300]}")
        except Exception as e:
            print(f"  {label} error: {e}")


print("=" * 60)
print("TORPEDO LIVE SITE AUDIT")
print("=" * 60)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        ignore_https_errors=True,
    )
    page = ctx.new_page()
    page.set_default_timeout(20000)

    login(page)
    audit_al_database(page)
    audit_email_patterns(page)
    audit_lead_flow(page)
    audit_mailpool_to_leads(page)
    audit_api_direct(page)

    browser.close()

print("\n" + "=" * 60)
print("AUDIT COMPLETE — screenshots saved to tmp_audit_shots/")
print("=" * 60)
