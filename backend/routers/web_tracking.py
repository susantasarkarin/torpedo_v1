"""First-party landing-page tracking and website forms (CRM plan 3.12).
Public (/track is on the AuthGuard public list), rate limited.

Each company site loads the tracker from its own first-party subdomain:

  <script>/* consent default: denied */</script>
  <script src="https://t.<site-domain>/api/track/t.js" data-bu="SFW" async></script>

The script shows the consent banner. Analytics and ad tags written as
<script type="text/plain" data-cgx-consent> (the sites' GA4, Meta pixel) run
only after consent; Google Consent Mode v2 defaults to denied. Events go to
/collect with sendBeacon (text/plain: no CORS preflight). A mail link's
?r=<token> ties the visitor cookie to that contact on any of the sites.

Forms marked data-torpedo-form post to /lead (text/plain; the response is
readable only from the configured site origins). If Torpedo cannot be reached
the visitor still sees the site's own thank-you, and the enquiry is kept in
the browser and re-sent on the next page view. If the tracker itself does
not load, the site's original form handler runs unchanged.
"""
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from middleware.rate_limit import client_key, rate_limit
from web_tracking import rules

router = APIRouter(prefix="/api/track", tags=["web-tracking"])
_collect_limit = rate_limit(120, 60, "web_track")
_lead_limit = rate_limit(5, 600, "web_form_lead")          # 5 enquiries per 10 minutes per IP


def _cfg():
    try:
        from platform_core import config_store
        return config_store.get("web")
    except Exception:
        return rules.DEFAULTS


@router.post("/collect", dependencies=[Depends(_collect_limit)])
async def collect(request: Request):
    raw = (await request.body())[:20000]
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return Response(status_code=204)
    cfg, now = _cfg(), datetime.utcnow()
    visitor = str(body.get("v") or "")
    contact = rules.read_token(str(body.get("r") or ""), os.getenv("SESSION_SECRET", "")) if body.get("r") else None
    ip = client_key(request) or ""
    docs = [d for d in (rules.clean_event(e, visitor=visitor, ip=ip, ua=request.headers.get("user-agent", ""), now=now, cfg=cfg)
                        for e in (body.get("events") or [])[:50] if isinstance(e, dict)) if d]
    if not docs:
        return Response(status_code=204)
    from database import get_database
    db = get_database("email_automation")
    db["web_events"].insert_many(docs)
    upd = {"$set": {"last_seen": now, "consent": docs[-1]["consent"]}, "$setOnInsert": {"first_seen": now},
           "$addToSet": {"bus": {"$each": sorted({d["bu"] for d in docs if d["bu"]})},
                         "hosts": {"$each": sorted({d["host"] for d in docs if d["host"]})}},
           "$inc": {"events": len(docs)}}
    if contact:
        upd["$set"]["contact_id"] = contact
    emails = sorted({d["form_email"] for d in docs if d.get("form_email")})
    if emails:
        upd["$set"]["form_email"] = emails[-1]
    db["web_visitors"].update_one({"visitor_id": visitor[:64]}, upd, upsert=True)
    return Response(status_code=204)


# ---------------------------------------------------------------- website forms


def _origin_site(request: Request, cfg) -> Optional[Dict[str, Any]]:
    """The configured site this request comes from (Origin, else Referer)."""
    src = request.headers.get("origin") or request.headers.get("referer") or ""
    host = (urlparse(src).hostname or "").lower()
    return rules.site_for_host(host, cfg)


def _cors(resp: Response, request: Request, site) -> Response:
    if site:
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("origin") or f"https://{site['domain']}"
        resp.headers["Vary"] = "Origin"
    return resp


@router.post("/lead", dependencies=[Depends(_lead_limit)])
async def form_lead(request: Request):
    cfg = _cfg()
    site = _origin_site(request, cfg)
    if not site:
        return JSONResponse({"ok": False, "error": "origin not allowed"}, status_code=403)
    raw = (await request.body())[:20000]
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _cors(JSONResponse({"ok": False, "error": "bad request"}, status_code=400), request, site)
    if not isinstance(body, dict):
        return _cors(JSONResponse({"ok": False, "error": "bad request"}, status_code=400), request, site)
    contact = rules.read_token(str(body.get("r") or ""), os.getenv("SESSION_SECRET", "")) if body.get("r") else None
    from database import get_database
    from web_tracking import leads
    out = leads.capture(get_database, body, site=site, ip=client_key(request) or "",
                        ua=request.headers.get("user-agent", ""), contact_from_token=contact, cfg=cfg)
    status = 200 if out.get("ok") else 422
    return _cors(JSONResponse(out, status_code=status), request, site)


_JS = r"""(function(){
var S=document.currentScript||document.querySelector('script[src*="/api/track/t.js"]');
var C=%CFG%,K='_cgx_v',CK='_cgx_consent',RK='_cgx_r',QK='_cgx_pending',api=(S&&S.src?new URL(S.src).origin:C.origin)+'/api/track';
var BU=(S&&S.getAttribute('data-bu'))||'';
function ck(n){var m=document.cookie.match('(^|;)\\s*'+n+'=([^;]*)');return m?decodeURIComponent(m[2]):null}
function sc(n,v,d){document.cookie=n+'='+encodeURIComponent(v)+';path=/;max-age='+(d*86400)+';SameSite=Lax;Secure'}
var v=ck(K);if(!v){v=(window.crypto&&crypto.randomUUID?crypto.randomUUID():String(Math.random()).slice(2)+Date.now());}sc(K,v,390);
var r=new URLSearchParams(location.search).get('r');if(r){sc(RK,r,30)}else{r=ck(RK)}
var consent=ck(CK)==='granted',q=[],utm={};
new URLSearchParams(location.search).forEach(function(val,key){if(key.indexOf('utm_')===0)utm[key]=val.slice(0,100)});
if(Object.keys(utm).length){try{sessionStorage.setItem('_cgx_utm',JSON.stringify(utm))}catch(e){}}else{try{utm=JSON.parse(sessionStorage.getItem('_cgx_utm')||'{}')}catch(e){}}
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}window.gtag=window.gtag||gtag;
if(!window._cgxConsentDefault){gtag('consent','default',{ad_storage:'denied',analytics_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',wait_for_update:500});}
function post(path,b){var s=JSON.stringify(b);if(navigator.sendBeacon&&path==='/collect'){return navigator.sendBeacon(api+path,new Blob([s],{type:'text/plain'}))}
 return fetch(api+path,{method:'POST',body:s,headers:{'Content-Type':'text/plain'},keepalive:true,credentials:'omit'})}
function send(){if(!q.length)return;post('/collect',{v:v,r:r,bu:BU,events:q.splice(0,50)})}
function ev(t,x){x=x||{};x.type=t;x.url=location.href;x.referrer=document.referrer;x.consent=consent;q.push(x);if(q.length>=10)send()}
function runConsented(){document.querySelectorAll('script[type="text/plain"][data-cgx-consent]').forEach(function(o){
 var n=document.createElement('script');for(var i=0;i<o.attributes.length;i++){var a=o.attributes[i];if(a.name!=='type'&&a.name!=='data-cgx-consent')n.setAttribute(a.name,a.value)}
 if(!o.src)n.text=o.text;o.parentNode.replaceChild(n,o)})}
function tags(){var t=C.tags||{};
 if(t.google_ads_id){var s=document.createElement('script');s.async=1;s.src='https://www.googletagmanager.com/gtag/js?id='+t.google_ads_id;document.head.appendChild(s);gtag('js',new Date());gtag('config',t.google_ads_id)}
 if(t.linkedin_partner_id){window._linkedin_data_partner_ids=[t.linkedin_partner_id];var l=document.createElement('script');l.async=1;l.src='https://snap.licdn.com/li.lms-analytics/insight.min.js';document.head.appendChild(l)}
 if(t.meta_pixel_id&&!window.fbq){!function(f,b,e,v,n,t2,s2){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t2=b.createElement(e);t2.async=!0;t2.src=v;s2=b.getElementsByTagName(e)[0];s2.parentNode.insertBefore(t2,s2)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init',t.meta_pixel_id);fbq('track','PageView')}
 runConsented()}
function grant(){consent=true;sc(CK,'granted',180);gtag('consent','update',{ad_storage:'granted',analytics_storage:'granted',ad_user_data:'granted',ad_personalization:'granted'});tags();ev('consent',{value:1})}
function banner(){if(ck(CK))return;var d=document.createElement('div');d.id='cgx-consent';d.setAttribute('role','dialog');d.setAttribute('aria-label','Cookie consent');
 d.style.cssText='position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;background:#fff;color:#111;border:1px solid #ccc;border-radius:8px;padding:12px 16px;font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.15);display:flex;gap:12px;flex-wrap:wrap;align-items:center;max-width:720px;margin:0 auto';
 d.innerHTML='<span style="flex:1 1 240px">We use cookies to understand visits and, with your consent, for analytics and advertising. <a href="'+(C.privacy||'/privacy.html')+'" style="color:inherit">Privacy</a></span>';
 var a=document.createElement('button');a.type='button';a.id='cgx-accept';a.textContent='Accept';a.style.cssText='padding:8px 14px;border:0;border-radius:6px;background:#111;color:#fff;cursor:pointer';
 var n=document.createElement('button');n.type='button';n.id='cgx-reject';n.textContent='Reject';n.style.cssText='padding:8px 14px;border:1px solid #999;border-radius:6px;background:#fff;color:#111;cursor:pointer';
 a.onclick=function(){grant();d.remove()};n.onclick=function(){sc(CK,'denied',180);ev('consent',{value:0});d.remove()};d.appendChild(n);d.appendChild(a);document.body.appendChild(d)}
if(consent)tags();
var t0=Date.now(),maxs=0;ev('page_view');
addEventListener('scroll',function(){var s=Math.round(100*(scrollY+innerHeight)/Math.max(1,document.documentElement.scrollHeight));if(s>maxs)maxs=s},{passive:true});
document.addEventListener('click',function(e){var el=e.target.closest&&e.target.closest('a,button,[data-cta]');if(el&&(el.hasAttribute('data-cta')||/quote|contact|demo|book|rfq|join|sign|enquir|inquir/i.test(el.textContent||'')))ev('cta_click',{value:null})},true);
var started={};document.addEventListener('input',function(e){var f=e.target.form;if(!f)return;var id=f.id||f.getAttribute('action')||'form';var em=f.querySelector('input[type=email]');
 if(!started[id]){started[id]=Date.now();ev('form_start',{})}if(em&&/@/.test(em.value)&&!started[id+'e']){started[id+'e']=1;ev('form_start',{email:em.value})}},true);
function fields(f){var o={};new FormData(f).forEach(function(val,key){o[key]=String(val).slice(0,4000)});return o}
function thanks(f,ok){var m=f.getAttribute('data-cgx-success')||'Thank you! We will contact you shortly.';var mode=f.getAttribute('data-cgx-thanks')||'alert';
 if(mode==='button'){var b=f.querySelector('button[type="submit"],button:not([type])');if(b){var o=b.textContent;b.textContent=m;b.disabled=true;setTimeout(function(){b.textContent=o;b.disabled=false},3500)}}else{alert(m)}f.reset()}
function queue(p){try{var a=JSON.parse(localStorage.getItem(QK)||'[]');a.push(p);localStorage.setItem(QK,JSON.stringify(a.slice(-5)))}catch(e){}}
function flush(){var a;try{a=JSON.parse(localStorage.getItem(QK)||'[]')}catch(e){a=[]}if(!a.length)return;try{localStorage.removeItem(QK)}catch(e){}
 a.forEach(function(p){p.retried=1;post('/lead',p).then(function(x){if(!x.ok&&x.status>=500)queue(p)}).catch(function(){queue(p)})})}
document.addEventListener('submit',function(e){var f=e.target;if(!f.matches||!f.matches('form[data-torpedo-form]'))return;
 var observe=f.getAttribute('data-cgx-mode')==='observe';
 if(!observe){e.preventDefault();e.stopImmediatePropagation()}
 var o=fields(f),need=(f.getAttribute('data-cgx-required')||'name,email,message').split(',');
 for(var i=0;i<need.length;i++){if(!(o[need[i]]||'').trim()){if(!observe)alert('Please fill in all required fields.');return}}
 var fk=f.id||f.getAttribute('action')||'form';
 var p={fields:o,v:v,r:r,bu:BU,page:location.href,referrer:document.referrer,utm:utm,form:fk,
  elapsed_ms:started[fk]?Date.now()-started[fk]:null};
 ev('form_submit',{email:o.email||null});send();
 if(observe){post('/lead',p).then(function(x){if(!x.ok&&x.status>=500)queue(p)}).catch(function(){queue(p)});return}
 var done=false,timer=setTimeout(function(){if(!done){done=true;queue(p);thanks(f,false)}},6000);
 post('/lead',p).then(function(x){if(done)return;done=true;clearTimeout(timer);if(!x.ok&&x.status>=500)queue(p);thanks(f,x.ok)})
  .catch(function(){if(done)return;done=true;clearTimeout(timer);queue(p);thanks(f,false)})},true);
addEventListener('pagehide',function(){ev('time_on_page',{value:Math.round((Date.now()-t0)/1000)});ev('scroll',{value:maxs});send()});
if(document.readyState!=='loading'){banner();flush()}else document.addEventListener('DOMContentLoaded',function(){banner();flush()});
window.cgxTracker={visitor:v,api:api,bu:BU,grant:grant};
})();"""


@router.get("/t.js")
def tracker_js(request: Request):
    cfg = _cfg()
    host = (request.headers.get("host") or "").split(":")[0].lower()
    site = rules.site_for_host(host[2:] if host.startswith("t.") else host, cfg) or {}
    conf = {"origin": os.getenv("PUBLIC_API_BASE", "https://torpedo.cogentixresearch.com"),
            "tags": {**(cfg.get("tags") or {}), **(site.get("tags") or {})},
            "privacy": site.get("privacy_url") or cfg.get("privacy_url") or "/privacy.html"}
    return PlainTextResponse(_JS.replace("%CFG%", json.dumps(conf)), media_type="application/javascript",
                             headers={"Cache-Control": "public, max-age=600"})
