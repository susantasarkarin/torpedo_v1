"""Connect a static company website to Torpedo (owner, 2026-10-24) -- on a COPY.

  python scripts/site_connect.py SRC_DIR OUT_DIR --domain cogentixresearch.com --bu COGENTIX
         [--tracker-origin https://t.cogentixresearch.com]   # default: https://t.<domain>

SRC_DIR is never modified. OUT_DIR/site/ gets the full converted copy (for
staging), OUT_DIR/changed/ only the files that changed (what to upload to
Hostinger), OUT_DIR/report.json what was done per page.

Per HTML page:
  1. <head> starts with the Consent Mode default (denied) and the tracker
     loaded from the first-party host, with data-bu.
  2. Existing analytics / ad tags (GA4 gtag, Meta pixel, LinkedIn insight)
     become <script type="text/plain" data-cgx-consent>, run only after the
     visitor accepts; <noscript> pixel images are removed (no consent possible).
  3. Contact / enquiry forms (any form with an email field, except panel
     sign-up and newsletter forms) get data-torpedo-form, the site's own
     thank-you text, and a hidden honeypot field. The site's JS stays as the
     fallback if the tracker cannot load.
Idempotent: a page that already has the tracker is left alone.
"""
import argparse
import html as html_lib
import json
import os
import re
import shutil
import zipfile

CONSENT_DEFAULT = ("<script data-cfasync=\"false\">window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}"
                   "gtag('consent','default',{ad_storage:'denied',analytics_storage:'denied',ad_user_data:'denied',"
                   "ad_personalization:'denied',wait_for_update:500});window._cgxConsentDefault=1;</script>")
TRACKER = '<script src="{origin}/api/track/t.js" data-bu="{bu}" data-cfasync="false" async></script>'
HONEYPOT = ('<div aria-hidden="true" style="position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden">'
            '<label>Leave this empty<input type="text" name="website_url" tabindex="-1" autocomplete="off"></label></div>')
TAG_SRC = re.compile(r"googletagmanager\.com/gtag/js|connect\.facebook\.net|snap\.licdn\.com|static\.hotjar|clarity\.ms", re.I)
TAG_INLINE = re.compile(r"gtag\(\s*['\"]config|fbq\(\s*['\"]init|_linkedin_partner_id|hotjar|clarity", re.I)
SKIP_FORM = re.compile(r"newsletter|subscribe|join[-_ ]?panel|panel[-_ ]?signup|register|login|search", re.I)
THANKS_JS = re.compile(r"alert\(\s*['\"](Thank you[^'\"]{5,200})['\"]\s*\)")
BUTTON_THANKS_JS = re.compile(r"textContent\s*=\s*['\"](Thank you[^'\"]{5,200})['\"]")


def site_thanks(src_dir: str):
    """The thank-you text the site's own JS shows (alert or button text)."""
    for root, _, files in os.walk(src_dir):
        for fn in files:
            if fn.endswith(".js"):
                txt = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
                m = THANKS_JS.search(txt)
                if m:
                    return m.group(1), "alert"
                m = BUTTON_THANKS_JS.search(txt)
                if m:
                    return m.group(1), "button"
    return "Thank you! We will contact you shortly.", "button"


def gate_tags(html: str, rep: dict) -> str:
    def script(m):
        tag, body = m.group(1), m.group(2)
        if "data-cgx-consent" in tag or "type=\"text/plain\"" in tag:
            return m.group(0)
        src = re.search(r"src=[\"']([^\"']+)", tag)
        if (src and TAG_SRC.search(src.group(1))) or (not src and TAG_INLINE.search(body)):
            rep["tags_gated"].append((src.group(1) if src else body.strip()[:60]).split("?")[0][:80])
            t = re.sub(r"\stype=[\"'][^\"']*[\"']", "", tag)
            return t.replace("<script", '<script type="text/plain" data-cgx-consent', 1) + body + "</script>"
        return m.group(0)
    html = re.sub(r"(<script\b[^>]*>)(.*?)</script>", script, html, flags=re.S | re.I)

    def noscript(m):
        if re.search(r"facebook\.com/tr|px\.ads\.linkedin|googletagmanager", m.group(0), re.I):
            rep["noscript_pixels_removed"] += 1
            return ""
        return m.group(0)
    return re.sub(r"<noscript>.*?</noscript>", noscript, html, flags=re.S | re.I)


def handled_ids(src_dir: str) -> set:
    """Form ids the site's own JS handles (getElementById / querySelector('#id'))."""
    ids = set()
    for root, _, files in os.walk(src_dir):
        for fn in files:
            if fn.lower().endswith((".js", ".html", ".htm")):
                txt = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
                ids |= set(re.findall(r"getElementById\(\s*['\"]([\w-]+)['\"]", txt))
                ids |= set(re.findall(r"querySelector(?:All)?\(\s*['\"]#([\w-]+)['\"]", txt))
    return ids


def wire_forms(html: str, rep: dict, thanks: str, mode: str, handled: set = frozenset()) -> str:
    def form(m):
        open_tag, inner = m.group(1), m.group(2)
        ident = " ".join(re.findall(r"(?:id|name|class|action)=[\"']([^\"']*)", open_tag))
        if "data-torpedo-form" in open_tag:
            return m.group(0)
        if not re.search(r"type=[\"']email[\"']|name=[\"']email[\"']", inner, re.I):
            return m.group(0)
        if SKIP_FORM.search(ident) or SKIP_FORM.search(inner[:400]):
            rep["forms_skipped"].append(ident or "form")
            return m.group(0)
        req = [n for n in ("name", "email", "message") if re.search(rf"name=[\"']{n}[\"']", inner)]
        fid = (re.search(r"\bid=[\"']([^\"']+)", open_tag) or [None, None])[1]
        observe = bool(fid and fid in handled)
        attrs = (f' data-torpedo-form data-cgx-mode="{"observe" if observe else "intercept"}"'
                 f' data-cgx-success="{html_lib.escape(thanks, quote=True)}" data-cgx-thanks="{mode}"'
                 f' data-cgx-required="{",".join(req) or "email"}"')
        rep["forms_wired"].append((ident or "form") + (" [observe]" if observe else " [intercept]"))
        return open_tag[:-1] + attrs + ">" + HONEYPOT + inner + "</form>"
    return re.sub(r"(<form\b[^>]*>)(.*?)</form>", form, html, flags=re.S | re.I)


def convert_page(html: str, *, origin: str, bu: str, thanks: str, mode: str, handled: set = frozenset()):
    rep = {"tracker_added": False, "tags_gated": [], "noscript_pixels_removed": 0, "forms_wired": [], "forms_skipped": []}
    if "/api/track/t.js" in html:
        return html, rep
    html = gate_tags(html, rep)
    html = wire_forms(html, rep, thanks, mode, handled)
    head = re.search(r"<head\b[^>]*>", html, re.I)
    snippet = CONSENT_DEFAULT + TRACKER.format(origin=origin.rstrip("/"), bu=bu)
    if head:
        i = head.end()
        # keep <meta charset> first so the browser does not re-parse the page
        cs = re.match(r"\s*<meta\s+charset=[^>]*>", html[i:], re.I)
        if cs:
            i += cs.end()
        html = html[:i] + "\n  " + snippet + html[i:]
        rep["tracker_added"] = True
    return html, rep


def run(src: str, out: str, domain: str, bu: str, origin: str = None):
    origin = origin or f"https://t.{domain}"
    site_dir, changed_dir = os.path.join(out, "site"), os.path.join(out, "changed")
    for d in (site_dir, changed_dir):
        if os.path.exists(d):
            shutil.rmtree(d)
    shutil.copytree(src, site_dir)                     # work on a copy; SRC is never touched
    thanks, mode = site_thanks(site_dir)
    handled = handled_ids(site_dir)
    report = {"domain": domain, "bu": bu, "tracker_origin": origin, "thank_you": thanks, "thank_you_mode": mode, "pages": {}}
    for root, _, files in os.walk(site_dir):
        for fn in files:
            if not fn.lower().endswith((".html", ".htm")):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, site_dir).replace("\\", "/")
            html = open(p, encoding="utf-8", errors="replace").read()
            new, rep = convert_page(html, origin=origin, bu=bu, thanks=thanks, mode=mode, handled=handled)
            report["pages"][rel] = rep
            if new != html:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
                dst = os.path.join(changed_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(p, dst)
    zpath = os.path.join(out, f"{domain}-changed-files.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(changed_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, changed_dir))
    pages = report["pages"].values()
    report["summary"] = {"pages": len(report["pages"]), "changed": sum(1 for r in pages if r["tracker_added"]),
                         "forms_wired": sum(len(r["forms_wired"]) for r in pages),
                         "forms_skipped": sorted({f for r in pages for f in r["forms_skipped"]}),
                         "tags_gated": sorted({t for r in pages for t in r["tags_gated"]}), "zip": zpath}
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--bu", required=True, choices=["SFW", "COGENTIX", "BIM"])
    ap.add_argument("--tracker-origin")
    a = ap.parse_args()
    print(json.dumps(run(a.src, a.out, a.domain, a.bu, a.tracker_origin)["summary"], indent=1))
