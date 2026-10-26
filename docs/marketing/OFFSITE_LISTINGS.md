# Off-site SEO: listings and links (MARKETING_PLAN 3.3.7)

For the team to work through. Each listing links back to the BU's site with a tagged URL (Content calendar → *Tagged link*, channel = `referral`, campaign = the directory's name) so visits and leads from it show up in attribution.

Status column: fill in as you go (`todo` → `applied` → `live` + the listing URL).

## Survey Fieldwork (SFW) — fieldwork, panel, data collection

| Listing | Why | Notes | Status |
|---|---|---|---|
| ESOMAR Directory (directory.esomar.org) | where agencies look for fieldwork partners | needs ESOMAR corporate membership | |
| MRSI member list (mrsi.in) | Indian research society, local credibility | membership | |
| Greenbook Directory | global buyer directory, strong for sample / fieldwork | free basic listing | |
| Quirk's Researcher SourceBook | US/EU buyers; Data collection + Panels categories | free basic | |
| Insights Association (if US clients) | US buyers | membership | |
| BVM / ADM (if DE work) | German buyers | optional | |
| Clutch — Market Research | reviews-driven B2B listings | ask 3 clients for reviews | |
| GoodFirms — Market Research | as above | | |
| LinkedIn company page "Services" section | page SEO + LinkedIn search | add CATI / CAWI / B2B sample | |

## Cogentix Research — insights consultancy

| Listing | Why | Notes | Status |
|---|---|---|---|
| ESOMAR Directory | as above, full-service category | | |
| MRSI | | | |
| Greenbook Directory | full-service + qualitative | | |
| Clutch — Market Research | reviews | | |
| Research Live / MRS Research Buyers Guide (UK) | if UK clients | paid | |
| Industry associations of key verticals (e.g. FICCI / CII committees) | thought leadership, events | | |

## BIM Wave Solutions — BIM services

| Listing | Why | Notes | Status |
|---|---|---|---|
| Clutch — BIM / Architecture services | AEC buyers search here | reviews | |
| GoodFirms — BIM | | | |
| BIMobject (if families / content are published) | manufacturers + designers | | |
| Autodesk Partner / Services marketplace (if eligible) | Revit buyers | partner programme | |
| IndiaMART / TradeIndia (India contractors) | local leads | screen for low-quality enquiries | |
| RICS / IGBC (India Green Building Council) member lists | credibility with developers | membership | |

## Backlinks

Search Console's **Links** report has no API. Once a month: Search Console → Links → *Export* (Top linking sites + Top linked pages) → save as CSV next to the Quora exports in `/var/lib/crm/seo_links/<BU>/` (to be imported when the first export arrives). Watch for: lost links from listings above, spammy linking domains (disavow only if a manual action appears).

## Google Business Profile

If a BU has a profile: keep NAP (name, address, phone) identical to the site footer and listings; add services, posts monthly, reply to reviews. Monitoring through the Business Profile API needs Google's API access approval (apply in the Google Cloud project from MARKETING_AUDIT §4.3) — until then, check the profile monthly by hand.
