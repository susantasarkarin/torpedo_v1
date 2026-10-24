"""First-party landing-page tracking (CRM plan 3.12). Public (/track is on the
AuthGuard public list), rate limited, no PII beyond what a visitor types.

<script src="https://torpedo.cogentixresearch.com/api/track/t.js" async></script>

The script shows a consent banner and loads analytics / ad tags only after
consent (Google Consent Mode v2 defaults to denied). Events are sent with
sendBeacon as text/plain, so no CORS preflight. A mail link's ?r=<token>
ties the visitor cookie to that contact.
"""
import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response

from middleware.rate_limit import rate_limit, client_key
from web_tracking import rules

router = APIRouter(prefix="/api/track", tags=["web-tracking"])
_collect_limit = rate_limit(120, 60, "web_track")


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
           "$addToSet": {"bus": {"$each": sorted({d["bu"] for d in docs if d["bu"]})}}, "$inc": {"events": len(docs)}}
    if contact:
        upd["$set"]["contact_id"] = contact
    emails = sorted({d["form_email"] for d in docs if d.get("form_email")})
    if emails:
        upd["$set"]["form_email"] = emails[-1]
    db["web_visitors"].update_one({"visitor_id": visitor[:64]}, upd, upsert=True)
    return Response(status_code=204)


_JS = r"""(function(){
var C=%CFG%,K='_cgx_v',CK='_cgx_consent',api=C.api;
function ck(n){var m=document.cookie.match('(^|;)\\s*'+n+'=([^;]*)');return m?decodeURIComponent(m[2]):null}
function sc(n,v,d){document.cookie=n+'='+encodeURIComponent(v)+';path=/;max-age='+(d*86400)+';SameSite=Lax;Secure'}
var v=ck(K);if(!v){v=(crypto.randomUUID?crypto.randomUUID():String(Math.random()).slice(2)+Date.now());}sc(K,v,390);
var r=new URLSearchParams(location.search).get('r');if(r){try{sessionStorage.setItem('_cgx_r',r)}catch(e){}}else{try{r=sessionStorage.getItem('_cgx_r')}catch(e){}}
var consent=ck(CK)==='granted',q=[];
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}window.gtag=window.gtag||gtag;
gtag('consent','default',{ad_storage:'denied',analytics_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});
function send(){if(!q.length)return;var b=JSON.stringify({v:v,r:r,events:q.splice(0,50)});
 if(navigator.sendBeacon){navigator.sendBeacon(api+'/collect',new Blob([b],{type:'text/plain'}))}else{fetch(api+'/collect',{method:'POST',body:b,keepalive:true})}}
function ev(t,x){x=x||{};x.type=t;x.url=location.href;x.referrer=document.referrer;x.consent=consent;q.push(x);if(q.length>=10)send()}
function tags(){var t=C.tags||{};
 if(t.google_ads_id){var s=document.createElement('script');s.async=1;s.src='https://www.googletagmanager.com/gtag/js?id='+t.google_ads_id;document.head.appendChild(s);gtag('js',new Date());gtag('config',t.google_ads_id)}
 if(t.linkedin_partner_id){window._linkedin_data_partner_ids=[t.linkedin_partner_id];var l=document.createElement('script');l.async=1;l.src='https://snap.licdn.com/li.lms-analytics/insight.min.js';document.head.appendChild(l)}
 if(t.meta_pixel_id&&!window.fbq){!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init',t.meta_pixel_id);fbq('track','PageView')}}
function grant(){consent=true;sc(CK,'granted',180);gtag('consent','update',{ad_storage:'granted',analytics_storage:'granted',ad_user_data:'granted',ad_personalization:'granted'});tags()}
function banner(){if(ck(CK))return;var d=document.createElement('div');d.setAttribute('role','dialog');d.setAttribute('aria-label','Cookie consent');
 d.style.cssText='position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;background:#fff;color:#111;border:1px solid #ccc;border-radius:8px;padding:12px 16px;font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.15);display:flex;gap:12px;flex-wrap:wrap;align-items:center';
 d.innerHTML='<span style="flex:1 1 240px">We use cookies to understand visits and, with your consent, for advertising. <a href="'+C.privacy+'" style="color:inherit">Privacy</a></span>';
 var a=document.createElement('button');a.textContent='Accept';a.style.cssText='padding:8px 14px;border:0;border-radius:6px;background:#111;color:#fff;cursor:pointer';
 var n=document.createElement('button');n.textContent='Reject';n.style.cssText='padding:8px 14px;border:1px solid #999;border-radius:6px;background:#fff;color:#111;cursor:pointer';
 a.onclick=function(){grant();d.remove()};n.onclick=function(){sc(CK,'denied',180);d.remove()};d.appendChild(n);d.appendChild(a);document.body.appendChild(d)}
if(consent)tags();
var t0=Date.now(),maxs=0;ev('page_view');
addEventListener('scroll',function(){var s=Math.round(100*(scrollY+innerHeight)/Math.max(1,document.documentElement.scrollHeight));if(s>maxs)maxs=s},{passive:true});
document.addEventListener('click',function(e){var el=e.target.closest&&e.target.closest('a,button,[data-cta]');if(el&&(el.hasAttribute('data-cta')||/quote|contact|demo|book|rfq|join|sign/i.test(el.textContent||'')))ev('cta_click',{value:null})},true);
var started={};document.addEventListener('input',function(e){var f=e.target.form;if(!f)return;var id=f.id||f.action||'form';var em=f.querySelector('input[type=email]');
 if(!started[id]||(em&&em.value&&!started[id+'e'])){started[id]=1;if(em&&em.value&&/@/.test(em.value)){started[id+'e']=1}ev('form_start',{email:em&&/@/.test(em.value)?em.value:null})}},true);
document.addEventListener('submit',function(e){var em=e.target.querySelector&&e.target.querySelector('input[type=email]');ev('form_submit',{email:em&&em.value||null});send()},true);
addEventListener('pagehide',function(){ev('time_on_page',{value:Math.round((Date.now()-t0)/1000)});ev('scroll',{value:maxs});send()});
if(document.readyState!=='loading')banner();else document.addEventListener('DOMContentLoaded',banner);
})();"""


@router.get("/t.js")
def tracker_js():
    cfg = _cfg()
    conf = {"api": os.getenv("PUBLIC_API_BASE", "https://torpedo.cogentixresearch.com") + "/api/track",
            "tags": cfg.get("tags") or {}, "privacy": cfg.get("privacy_url") or "/privacy"}
    return PlainTextResponse(_JS.replace("%CFG%", json.dumps(conf)), media_type="application/javascript",
                             headers={"Cache-Control": "public, max-age=3600"})
