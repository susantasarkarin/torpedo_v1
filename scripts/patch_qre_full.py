"""
Full QRE Question Rectification — PDF v3
Patches qre_frontend/assets/index-B3tU2e59.js to match the OTC Discovery Study.

JS structure (single minified file, all in one const declaration):
  const op=21,ip=[Q1..Q8],ap=[Q9..Q29],sp=[Q30],Ui=[25 cats],
        up=Ui.flatMap(...),_t=556,cp=[...],rt=561,dp=[Q561..Q566]

Phases:
  1.  Screener ip: Q3→Age, Q4→Gender, Q6→Durables, Q7+Q8→Education
  2.  Replace ap array (Module A+B, Q8-Q44)
  3.  op=21 → op=11
  4.  Replace lp() function (11 questions, Q25-Q35_{catKey})
  5.  Replace Ui array (6 PDF categories with catKey)
  6.  Fix up= to use catKey
  7.  Fix vc/pp to use catKey
  8.  Replace rt,dp with Q36-Q40 demographics
  9.  Fix es constant end
  10. Fix progress v() function loops
"""
import os, sys, re

JS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "qre_frontend", "assets", "index-B3tU2e59.js",
)

def load():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()

def save(content):
    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def sub(content, old, new, label):
    """Replace old→new exactly once, print result."""
    c = content.count(old)
    if c == 0:
        print(f"  ✗  {label}: NOT FOUND")
        return content
    if c > 1:
        print(f"  !  {label}: {c} occurrences (replacing first)")
    print(f"  ✓  {label}")
    return content.replace(old, new, 1)

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1  Screener ip array
# ═══════════════════════════════════════════════════════════════════════════════
def phase1(js):
    print("\n── Phase 1: Screener ip array ───────────────────────────")

    # Q3  gender → age
    js = sub(js,
        '{id:"Q3",type:"SA",section:"screener",text:"Please select your gender.",'
        'instruction:"Select one",options:[{label:"Male",code:1},{label:"Female",code:2},'
        '{label:"Non-binary / Prefer not to say",code:3}]}',
        '{id:"Q3",type:"SA",section:"screener",text:"What is your age?",'
        'instruction:"Select one",options:['
        '{label:"18\u201324 years",code:1},'
        '{label:"25\u201334 years",code:2},'
        '{label:"35\u201344 years",code:3},'
        '{label:"45\u201355 years",code:4},'
        '{label:"Above 55 years",code:5}'
        ']}',
        "Q3 → Age")

    # Q4  city tier → gender (literal em-dash in source)
    q4_old = (
        '{id:"Q4",type:"SA",section:"screener",text:"Which city tier do you currently reside in?",'
        'instruction:"Select one \u2014 for classification and regional analysis",'
        'options:[{label:"Metro \u2014 Mumbai, Delhi, Bangalore, Chennai, Hyderabad, Kolkata",code:1},'
        '{label:"Tier 1 \u2014 Pune, Ahmedabad, Jaipur, Lucknow, Surat, Chandigarh",code:2},'
        '{label:"Tier 2 \u2014 Indore, Nagpur, Coimbatore, Kochi, Vizag, Bhubaneswar",code:3},'
        '{label:"Tier 3 or smaller city / town",code:4}]}'
    )
    q4_new = (
        '{id:"Q4",type:"SA",section:"screener",text:"What is your gender?",'
        'instruction:"Select one \u2014 soft quota, no termination",'
        'options:['
        '{label:"Female",code:1},'
        '{label:"Male",code:2},'
        '{label:"Non-binary or prefer to self-describe",code:3},'
        '{label:"Prefer not to say",code:4}'
        ']}'
    )
    if q4_old in js:
        js = sub(js, q4_old, q4_new, "Q4 → Gender")
    else:
        # regex fallback
        m = re.search(r'\{id:"Q4",type:"SA",section:"screener",text:"Which city tier[^;]+?\}(?=,\{id:"Q5")', js, re.DOTALL)
        if m:
            js = js[:m.start()] + q4_new + js[m.end():]
            print("  ✓  Q4 → Gender (regex)")
        else:
            print("  ✗  Q4 → Gender: FAILED")

    # Q6  old city list → household durables MA
    js = sub(js,
        '{id:"Q6",type:"SA",section:"screener",text:"Which city do you currently reside in?",'
        'instruction:"Select one",options:[{label:"Mumbai",code:1},{label:"Delhi NCR",code:2},'
        '{label:"Bangalore",code:3},{label:"Kolkata",code:4},{label:"Chennai",code:5},'
        '{label:"Hyderabad",code:6},{label:"Pune",code:7},{label:"Ahmedabad",code:8},'
        '{label:"Jaipur",code:9},{label:"Lucknow",code:10},{label:"Other City",code:11}]}',
        '{id:"Q6",type:"MA",section:"screener",text:"Please select all items present in your home.",'
        'instruction:"Select all that apply",options:['
        '{label:"Electricity connection",code:1},'
        '{label:"Ceiling fan(s)",code:2},'
        '{label:"Refrigerator",code:3},'
        '{label:"Motorcycle or scooter",code:4},'
        '{label:"Colour television",code:5},'
        '{label:"Car or four-wheeler",code:6},'
        '{label:"Air conditioner",code:7},'
        '{label:"Washing machine",code:8}'
        ']}',
        "Q6 → Household Durables (MA)")

    # Q7 (old durables) + Q8 screener education  →  Q7 Education only, remove Q8
    # Source has literal em-dash; ip array closes with the final }]}]
    q7q8_old = (
        '{id:"Q7",type:"MA",section:"screener",text:"Please select all items you have in your home.",'
        'instruction:"Household SEC classification \u2014 select all that apply",'
        'options:[{label:"Electricity connection",code:1},{label:"Ceiling Fan",code:2},'
        '{label:"LPG Stove",code:3},{label:"Two-Wheeler",code:4},{label:"Colour TV",code:5},'
        '{label:"Refrigerator",code:6},{label:"Washing Machine",code:7},'
        '{label:"Personal Computer / Laptop",code:8},{label:"Car / Jeep / Van",code:9},'
        '{label:"Air Conditioner",code:10},{label:"Agricultural land",code:11}]},'
        '{id:"Q8",type:"SA",section:"screener",'
        'text:"Highest education of the primary household income earner?",'
        'instruction:"Select one",'
        'options:[{label:"Graduate / Postgraduate: Professional",code:1},'
        '{label:"Graduate / Postgraduate: General",code:2},'
        '{label:"Some College / Diploma, not Graduate",code:3},'
        '{label:"SSC / HSC",code:4},'
        '{label:"School \u2014 5 to 9 years",code:5},'
        '{label:"Literate / School up to 4 years or less",code:6}]}]'
    )
    q7_new = (
        '{id:"Q7",type:"SA",section:"screener",'
        'text:"What is the highest level of education completed by the main income earner in your household?",'
        'instruction:"Select one",options:['
        '{label:"Graduate / Postgraduate \u2014 Professional (MBBS, CA, LLB)",code:1},'
        '{label:"Graduate / Postgraduate \u2014 General",code:2},'
        '{label:"Diploma or some college (not full graduate)",code:3},'
        '{label:"SSC / HSC (Class 10 or 12 pass)",code:4},'
        '{label:"School below Class 10",code:5},'
        '{label:"No formal education",code:6}'
        ']}]'  # closes ip array
    )
    if q7q8_old in js:
        js = sub(js, q7q8_old, q7_new, "Q7+Q8 → Education + remove Q8 screener")
    else:
        # regex fallback: match from Q7 MA through end of Q8 SA (last option code:6)
        m = re.search(
            r'\{id:"Q7",type:"MA",section:"screener"[\s\S]+?'
            r'\{id:"Q8",type:"SA",section:"screener"[\s\S]+?'
            r'code:6\}\]\}(?=\])',  # ends just before ip closing ]
            js, re.DOTALL)
        if m:
            js = js[:m.start()] + q7_new[:-1] + js[m.end():]  # slice off trailing ] from q7_new
            print("  ✓  Q7+Q8 → Education (regex)")
        else:
            print("  ✗  Q7+Q8: FAILED")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2  Replace ap array  (Q8-Q44, Module A + B)
# Note: ap is part of the same const as ip, so it's ",ap=[" not "const ap=["
# ═══════════════════════════════════════════════════════════════════════════════
NEW_AP = (
    ',ap=['
    # Q8 — category incidence (MA, drives active_categories in backend)
    '{id:"Q8",type:"MA",section:"core_symptom",'
    'text:"Which of the following OTC health issues have you personally experienced in the past 6 months?",'
    'instruction:"Select all that apply",'
    'options:['
    '{label:"Fever or elevated body temperature",code:1},'
    '{label:"Body ache, headache or joint pain",code:2},'
    '{label:"Acidity, indigestion, gas or bloating",code:3},'
    '{label:"Skin rash or fungal infection",code:4},'
    '{label:"Fatigue, low energy or suspected nutrient deficiency",code:5},'
    '{label:"Diarrhoea, loose motions or stomach upset",code:6},'
    '{label:"General wellness or immunity maintenance",code:7},'
    '{label:"Ayurvedic or herbal product used for wellness",code:8},'
    '{label:"None of the above",code:9,exclusive:!0}'
    ']},'
    # Q9 — first discovery channel (SA)
    '{id:"Q9",type:"SA",section:"core_journey",'
    'text:"When you last experienced an OTC health issue \u2014 how did you FIRST discover which product or remedy to use?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Already knew \u2014 habit from previous experience",code:1},'
    '{label:"Pharmacist recommended it at the counter",code:2},'
    '{label:"Doctor prescribed or recommended it",code:3},'
    '{label:"A family member or friend suggested it",code:4},'
    '{label:"Google search or health website",code:5},'
    '{label:"YouTube health video or review",code:6},'
    '{label:"Instagram, Facebook or social media",code:7},'
    '{label:"WhatsApp message from family or community group",code:8},'
    '{label:"TV or digital advertisement",code:9},'
    '{label:"Newspaper, magazine or print advertisement",code:10},'
    '{label:"Prominent display or promotion at the pharmacy",code:11},'
    '{label:"App notification from 1mg or PharmEasy",code:12}'
    ']},'
    # Q10 — pre-purchase behaviour (SA)
    '{id:"Q10",type:"SA",section:"core_journey",'
    'text:"BEFORE making your last OTC purchase \u2014 what did you typically do first?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Bought it immediately without any additional check",code:1},'
    '{label:"Called or visited the pharmacist to confirm",code:2},'
    '{label:"Searched online to verify the product or dosage",code:3},'
    '{label:"Asked a family member or friend to confirm",code:4},'
    '{label:"Consulted a doctor before buying",code:5}'
    ']},'
    # Q11 — chemist role today (SA)
    '{id:"Q11",type:"SA",section:"core_journey",'
    'text:"What role does the local chemist play TODAY in your OTC health purchase decisions?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Primary source \u2014 I trust their recommendation most",code:1},'
    '{label:"Confirmation step \u2014 I visit to verify what I found elsewhere",code:2},'
    '{label:"Convenience only \u2014 location matters, not advice",code:3},'
    '{label:"Declining role \u2014 I mostly buy online now",code:4},'
    '{label:"Not relevant \u2014 I go to doctors or buy online directly",code:5}'
    ']},'
    # Q12 — discovery influence grid (straight-liner guard)
    '{id:"Q12",type:"grid",section:"core_journey",'
    'text:"How frequently does each source influence WHICH SPECIFIC PRODUCT you choose for an OTC health issue?",'
    'instruction:"Rate each 1\u20135: 1\u202fNever \u2192 5\u202fAlways",'
    'gridRows:['
    '{id:"r1",label:"Pharmacist recommendation at the chemist counter"},'
    '{id:"r2",label:"Doctor recommendation or prescription"},'
    '{id:"r3",label:"Recommendation from family or close friends"},'
    '{id:"r4",label:"Google search or health articles online"},'
    '{id:"r5",label:"YouTube health channel or product review"},'
    '{id:"r6",label:"Instagram, Facebook or social media content"},'
    '{id:"r7",label:"WhatsApp messages from family or community"},'
    '{id:"r8",label:"Customer reviews on 1mg, PharmEasy or Amazon"},'
    '{id:"r9",label:"TV or digital advertisement for the product"},'
    '{id:"r10",label:"Previous personal experience with the brand"},'
    '{id:"r11",label:"Product packaging, label or ingredient list"}'
    '],'
    'gridCols:['
    '{code:1,label:"1 \u2013 Never"},'
    '{code:2,label:"2"},'
    '{code:3,label:"3 \u2013 Sometimes"},'
    '{code:4,label:"4"},'
    '{code:5,label:"5 \u2013 Always"}'
    ']},'
    # Q41 — app usage by purpose grid (NEW)
    '{id:"Q41",type:"grid",section:"core_journey",'
    'text:"In the past 3 months \u2014 for which PURPOSES have you used each of these apps or platforms?",'
    'instruction:"Tick all that apply per row",'
    'gridRows:['
    '{id:"r1",label:"Finding health information or symptom guidance"},'
    '{id:"r2",label:"Researching or comparing health products"},'
    '{id:"r3",label:"Purchasing health products or medicines"}'
    '],'
    'gridCols:['
    '{code:1,label:"Instagram"},'
    '{code:2,label:"YouTube"},'
    '{code:3,label:"WhatsApp"},'
    '{code:4,label:"Google / Google Health"},'
    '{code:5,label:"1mg"},'
    '{code:6,label:"PharmEasy"},'
    '{code:7,label:"Blinkit"},'
    '{code:8,label:"Zepto"},'
    '{code:9,label:"Swiggy Instamart"},'
    '{code:10,label:"Amazon / Flipkart"},'
    '{code:11,label:"None of the above"}'
    ']},'
    # Q13 — digital health literacy (SA)
    '{id:"Q13",type:"SA",section:"core_journey",'
    'text:"How comfortable are you finding reliable health information online?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Very comfortable \u2014 I actively research and evaluate sources",code:1},'
    '{label:"Fairly comfortable \u2014 I find what I need but verify with professionals",code:2},'
    '{label:"Uncertain \u2014 conflicting information online confuses me",code:3},'
    '{label:"Uncomfortable \u2014 I prefer professional guidance over online search",code:4},'
    '{label:"Not applicable \u2014 I do not search for health information online",code:5}'
    ']},'
    # Q14 — quick commerce adoption (SA)
    '{id:"Q14",type:"SA",section:"core_channel",'
    'text:"How frequently do you use online apps or quick-commerce platforms to purchase OTC health products?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Very frequently \u2014 this is my primary channel",code:1},'
    '{label:"Frequently \u2014 I use it regularly alongside other channels",code:2},'
    '{label:"Occasionally \u2014 only when urgent or more convenient",code:3},'
    '{label:"Rarely \u2014 prefer physical chemist but have tried online",code:4},'
    '{label:"Never \u2014 I only buy from physical chemist or pharmacy",code:5},'
    '{label:"Never heard of or used quick commerce for health products",code:6}'
    ']},'
    # Q15 — discovery-to-purchase gap (SA)
    '{id:"Q15",type:"SA",section:"core_channel",'
    'text:"When you last discovered a new OTC health product \u2014 where did you ULTIMATELY purchase it?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Immediately online \u2014 1mg, PharmEasy or Blinkit",code:1},'
    '{label:"Online after checking prices or reading reviews",code:2},'
    '{label:"Local neighbourhood chemist or pharmacy",code:3},'
    '{label:"Went to the chemist even though I discovered it online",code:4},'
    '{label:"Organised pharmacy chain \u2014 Apollo, MedPlus or Wellness Forever",code:5},'
    '{label:"Did not purchase immediately \u2014 researched more first",code:6}'
    ']},'
    # Q43 — purchase channel by situation grid (NEW)
    '{id:"Q43",type:"grid",section:"core_channel",'
    'text:"For each SITUATION below \u2014 which ONE channel would you MOST LIKELY use?",'
    'instruction:"Select one channel per row",'
    'gridRows:['
    '{id:"r1",label:"Routine replenishment of a product you use regularly"},'
    '{id:"r2",label:"Urgent or immediate health need"},'
    '{id:"r3",label:"First-time purchase of a new OTC product"}'
    '],'
    'gridCols:['
    '{code:1,label:"Local neighbourhood chemist"},'
    '{code:2,label:"Online pharmacy (1mg / PharmEasy)"},'
    '{code:3,label:"Quick commerce (Blinkit / Zepto)"},'
    '{code:4,label:"Hospital or clinic pharmacy"}'
    ']},'
    # Q16 — why chemist despite online discovery MA (conditional on Q15 codes 3 or 4)
    '{id:"Q16",type:"MA",section:"core_channel",'
    'text:"You discovered the product online but purchased at a physical pharmacy \u2014 why? Select all that apply.",'
    'instruction:"Select all that apply",'
    'options:['
    '{label:"I wanted to see, feel or check the product in person",code:1},'
    '{label:"Concern about authenticity or counterfeit products online",code:2},'
    '{label:"I needed it immediately \u2014 could not wait for delivery",code:3},'
    '{label:"In-person pharmacist advice was important",code:4},'
    '{label:"Similar price online \u2014 no meaningful saving",code:5},'
    '{label:"Uncertain about correct dosage without guidance",code:6},'
    '{label:"Habit \u2014 I always buy medicines from a physical chemist",code:7},'
    '{label:"My pharmacy offers delivery or a loyalty programme",code:8}'
    ']},'
    # Q44 — online purchase motivations MA max 2 (conditional on Q14 codes 1-3)
    '{id:"Q44",type:"MA",section:"core_channel",'
    'text:"What were the TOP 2 reasons you first started buying health products online or via quick commerce?",'
    'instruction:"Select up to 2 only",maxSelect:2,'
    'options:['
    '{label:"Faster and more convenient than going to a chemist",code:1},'
    '{label:"Better prices, cashback or exclusive online offers",code:2},'
    '{label:"Wider range of products not available locally",code:3},'
    '{label:"Easier to compare products and read reviews before buying",code:4},'
    '{label:"Privacy or discretion for sensitive health purchases",code:5},'
    '{label:"Available any time \u2014 including late night",code:6}'
    ']},'
    # Q17 — trust hierarchy grid (straight-liner guard)
    '{id:"Q17",type:"grid",section:"core_influence",'
    'text:"How much do you PERSONALLY TRUST health advice or recommendations from each of these sources?",'
    'instruction:"Rate each 1\u20135: 1\u202fNot trustworthy \u2192 5\u202fCompletely trustworthy",'
    'gridRows:['
    '{id:"r1",label:"Doctor or specialist"},'
    '{id:"r2",label:"Local pharmacist at the chemist counter"},'
    '{id:"r3",label:"Staff at organised pharmacy chain (Apollo / MedPlus)"},'
    '{id:"r4",label:"Family member or close friend"},'
    '{id:"r5",label:"Google search or health articles"},'
    '{id:"r6",label:"YouTube health channels"},'
    '{id:"r7",label:"Instagram or Facebook health influencers"},'
    '{id:"r8",label:"WhatsApp messages from family or community"},'
    '{id:"r9",label:"Customer reviews on 1mg or Amazon"},'
    '{id:"r10",label:"TV or digital advertisements"},'
    '{id:"r11",label:"Brand packaging, label or package insert"},'
    '{id:"r12",label:"AI chatbot or health app"}'
    '],'
    'gridCols:['
    '{code:1,label:"1 \u2013 Not Trustworthy"},'
    '{code:2,label:"2"},'
    '{code:3,label:"3 \u2013 Neutral"},'
    '{code:4,label:"4"},'
    '{code:5,label:"5 \u2013 Very Trustworthy"}'
    ']},'
    # Q42 — language preference SA (NEW)
    '{id:"Q42",type:"SA",section:"core_influence",'
    'text:"When consuming health information online, which language do you prefer?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"English only",code:1},'
    '{label:"English and Hindi mixed (Hinglish)",code:2},'
    '{label:"Hindi only",code:3},'
    '{label:"My regional language",code:4},'
    '{label:"No strong preference",code:5}'
    ']},'
    # Q18 — digital trust proof-points MA max 3
    '{id:"Q18",type:"MA",section:"core_influence",'
    'text:"What makes you CONFIDENT trusting an unfamiliar health brand encountered online? Select your top 3.",'
    'instruction:"Select up to 3 only",maxSelect:3,'
    'options:['
    '{label:"Doctor or healthcare professional endorsement",code:1},'
    '{label:"Recognised quality certifications (FSSAI, GMP, ISO, AYUSH)",code:2},'
    '{label:"Independent lab test results published on the product page",code:3},'
    '{label:"High star rating with many verified reviews",code:4},'
    '{label:"Transparent and complete ingredient list",code:5},'
    '{label:"Professional and credible product page",code:6},'
    '{label:"Positive coverage in news or health media",code:7},'
    '{label:"Influencer or celebrity endorsement",code:8},'
    '{label:"Free sample, trial or money-back guarantee",code:9},'
    '{label:"Available in Apollo, MedPlus or established chains",code:10},'
    '{label:"Recommended by someone in my trusted personal network",code:11}'
    ']},'
    # Q19 — chemist vs online reliability comparison (SA)
    '{id:"Q19",type:"SA",section:"core_influence",'
    'text:"Compared to your local chemist \u2014 how reliable is online health information for choosing OTC products?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Much more reliable than my chemist",code:1},'
    '{label:"Somewhat more reliable",code:2},'
    '{label:"About the same level of reliability",code:3},'
    '{label:"Somewhat less reliable than my chemist",code:4},'
    '{label:"Much less reliable \u2014 I trust my chemist far more",code:5},'
    '{label:"I do not use online sources for health information",code:6}'
    ']},'
    # Q20 — trust erosion triggers (MA)
    '{id:"Q20",type:"MA",section:"core_influence",'
    'text:"Which of the following would make you LESS LIKELY to trust a health brand? Select all that apply.",'
    'instruction:"Select all that apply",'
    'options:['
    '{label:"Negative reviews or complaints from other users",code:1},'
    '{label:"Lack of recognised quality certifications",code:2},'
    '{label:"Vague or confusing product descriptions",code:3},'
    '{label:"Aggressive or unrealistic discounts",code:4},'
    '{label:"Not available at any established pharmacy chain",code:5},'
    '{label:"Influencer promotions that feel paid or inauthentic",code:6},'
    '{label:"No transparent labelling of ingredients",code:7},'
    '{label:"Difficulty verifying product authenticity",code:8},'
    '{label:"New brand with no history or track record",code:9},'
    '{label:"Poor customer service or returns process",code:10}'
    ']},'
    # Q21 — WTP for certified quality (SA)
    '{id:"Q21",type:"SA",section:"core_influence",'
    'text:"Would you pay a PREMIUM for an OTC product carrying a verified quality certification (FSSAI, BIS, ISO, AYUSH)?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Definitely yes \u2014 I would pay up to 20% more",code:1},'
    '{label:"Probably yes \u2014 up to 10% more seems reasonable",code:2},'
    '{label:"Neutral \u2014 reassuring but not a strong price driver",code:3},'
    '{label:"Probably not \u2014 I expect quality regardless of marks",code:4},'
    '{label:"Definitely not \u2014 quality marks have little influence",code:5},'
    '{label:"I know too little about quality certifications to say",code:6}'
    ']},'
    # Q22 — online trust barriers (open, min 15 chars)
    '{id:"Q22",type:"open",section:"core_influence",'
    'text:"What is the BIGGEST barrier stopping you from fully trusting health products purchased online?",'
    'instruction:"Open-ended \u2014 please be as specific as possible (minimum 15 characters)",'
    'placeholder:"Describe your biggest concern about buying health products online...",minLength:15},'
    # Q23 — monthly OTC spend (SA)
    '{id:"Q23",type:"SA",section:"core_influence",'
    'text:"Approximately how much do you personally spend on OTC health products per month?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Less than INR 100 per month",code:1},'
    '{label:"INR 100 \u2013 300 per month",code:2},'
    '{label:"INR 301 \u2013 700 per month",code:3},'
    '{label:"INR 701 \u2013 1,500 per month",code:4},'
    '{label:"INR 1,501 \u2013 3,000 per month",code:5},'
    '{label:"More than INR 3,000 per month",code:6},'
    '{label:"I do not regularly purchase OTC health products",code:7}'
    ']},'
    # Q24 — spend trend (SA)
    '{id:"Q24",type:"SA",section:"core_influence",'
    'text:"Compared to 12 months ago, how has your monthly spending on OTC health products changed?",'
    'instruction:"Select one only",'
    'options:['
    '{label:"Increased significantly",code:1},'
    '{label:"Increased slightly",code:2},'
    '{label:"Stayed about the same",code:3},'
    '{label:"Decreased slightly",code:4},'
    '{label:"Decreased significantly",code:5}'
    ']}'
    ']'   # end of ap array
)

def phase2(js):
    print("\n── Phase 2: Replace ap array (Q8-Q44) ──────────────────────")
    # ap starts as ",ap=[" (comma-separated in const) and ends just before ",sp=["
    pat = re.compile(r',ap=\[[\s\S]*?\](?=,sp=\[)', re.DOTALL)
    m = pat.search(js)
    if m:
        old = m.group(0)
        js = js[:m.start()] + NEW_AP + js[m.end():]
        print(f"  ✓  ap replaced ({len(old):,} → {len(NEW_AP):,} chars)")
    else:
        print("  ✗  ap array: pattern not found")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3  const op=21 → 11
# ═══════════════════════════════════════════════════════════════════════════════
def phase3(js):
    print("\n── Phase 3: op=21 → 11 ─────────────────────────────────────")
    return sub(js, 'const op=21,', 'const op=11,', "op constant")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4  Replace lp() function (11 questions, catKey-based IDs)
# lp function is defined just before "const op=21,"
# new signature: lp(catKey, catName, brands)
# generates Q25_catKey through Q35_catKey
# ═══════════════════════════════════════════════════════════════════════════════

NEW_LP = (
    'function lp(catKey,catName,brands){'
    'const bOpts=brands.map((d,y)=>({label:d,code:y+1}));'
    'bOpts.push({label:"None of the above",code:brands.length+1});'
    'const bSub=[...brands.map((d,y)=>({label:d,code:y+1})),'
    '{label:"I would not substitute \u2014 only my main brand",code:brands.length+1},'
    '{label:"I would search online for an alternative",code:brands.length+2}];'
    'return['
    # Q25 — usage frequency (SA, gating question)
    '{id:`Q25_${catKey}`,type:"SA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`In the past 6 months, how often have you personally used a ${catName.toLowerCase()} product?`,'
    'instruction:"Select one \u2014 if not used recently the category block will be skipped",'
    'options:['
    '{label:"Weekly or more often",code:1},'
    '{label:"Once or twice a month",code:2},'
    '{label:"Once every 2\u20133 months",code:3},'
    '{label:"Once or twice a year",code:4},'
    '{label:"Less than once a year",code:5},'
    '{label:"I have not used this category in the past 6 months",code:6}'
    ']},'
    # Q26 — first discovery in category (SA)
    '{id:`Q26_${catKey}`,type:"SA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`When you FIRST started using ${catName.toLowerCase()} products \u2014 how did you discover which one to use?`,'
    'instruction:"Select one only",'
    'options:['
    '{label:"Doctor or pharmacist recommendation",code:1},'
    '{label:"Recommendation from family or close friends",code:2},'
    '{label:"TV or digital advertisement",code:3},'
    '{label:"Google search or online article",code:4},'
    '{label:"YouTube or social media content",code:5},'
    '{label:"Prominent display or promotion at the pharmacy",code:6},'
    '{label:"WhatsApp or community recommendation",code:7},'
    '{label:"Personal experience \u2014 tried based on my own knowledge",code:8},'
    '{label:"Always knew this category \u2014 used since childhood",code:9}'
    ']},'
    # Q27 — top-of-mind brand (open)
    '{id:`Q27_${catKey}`,type:"open",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`When you think of ${catName.toLowerCase()}, which brand name comes to mind FIRST?`,'
    'instruction:"Open-ended \u2014 type the first brand that comes to mind",'
    'placeholder:"Type the first brand name..."},'
    # Q28 — aided awareness MA
    '{id:`Q28_${catKey}`,type:"MA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`Which of the following ${catName.toLowerCase()} brands have you seen, heard of or are aware of?`,'
    'instruction:"Select all that apply",options:bOpts,rotate:!0},'
    # Q29 — trial/usage MA (piped from Q28)
    '{id:`Q29_${catKey}`,type:"MA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`Which of the following ${catName.toLowerCase()} brands have you personally USED in the past 6 months?`,'
    'instruction:"Select all that apply",options:bOpts,rotate:!0,pipeFrom:`Q28_${catKey}`},'
    # Q30 — most-used brand SA
    '{id:`Q30_${catKey}`,type:"SA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`Which ONE ${catName.toLowerCase()} brand are you using MOST OFTEN right now?`,'
    'instruction:"Select one only",options:bOpts},'
    # Q31 — reasons for choice MA max 3
    '{id:`Q31_${catKey}`,type:"MA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:"Why do you choose this brand? Select your top 3 reasons.",'
    'instruction:"Select up to 3 only",maxSelect:3,'
    'options:['
    '{label:"Doctor or specialist recommendation",code:1},'
    '{label:"Pharmacist recommended it",code:2},'
    '{label:"Trusted and well-established brand",code:3},'
    '{label:"Affordable price",code:4},'
    '{label:"Clinically proven or science-backed formulation",code:5},'
    '{label:"Natural or herbal \u2014 free from harmful chemicals",code:6},'
    '{label:"Easily available at my preferred channel",code:7},'
    '{label:"Positive reviews from other users online",code:8},'
    '{label:"Recommended by family or close friends",code:9},'
    '{label:"Habit \u2014 I have always used this brand",code:10},'
    '{label:"Promotional offer or discount",code:11}'
    ']},'
    # Q32 — purchase channel MA max 2
    '{id:`Q32_${catKey}`,type:"MA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`Where do you most commonly purchase ${catName.toLowerCase()} products? Select up to 2.`,'
    'instruction:"Select up to 2 channels",maxSelect:2,'
    'options:['
    '{label:"Local neighbourhood chemist",code:1},'
    '{label:"Organised pharmacy chain (Apollo / MedPlus / Wellness Forever)",code:2},'
    '{label:"Online pharmacy (1mg / PharmEasy / Netmeds)",code:3},'
    '{label:"Quick commerce (Blinkit / Zepto / Swiggy Instamart)",code:4},'
    '{label:"Amazon or Flipkart",code:5},'
    '{label:"D2C brand website or app",code:6},'
    '{label:"Hospital or clinic pharmacy",code:7},'
    '{label:"Supermarket (DMart / Big Bazaar / Reliance Smart)",code:8}'
    ']},'
    # Q33 — brand image grid (MA per row, piped from Q28)
    '{id:`Q33_${catKey}`,type:"grid",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`For each statement \u2014 which ${catName.toLowerCase()} brands best match? Select all that apply per row.`,'
    'instruction:"MA per row \u2014 showing only brands you are aware of",'
    'gridRows:['
    '{id:"bi1",label:"A brand I completely trust for my health needs"},'
    '{id:"bi2",label:"Recommended or approved by doctors"},'
    '{id:"bi3",label:"Offers good value for money"},'
    '{id:"bi4",label:"Produces noticeably effective results"},'
    '{id:"bi5",label:"Easily available whenever I need it"},'
    '{id:"bi6",label:"A brand I have been loyal to for a long time"},'
    '{id:"bi7",label:"Uses safe, natural or clean ingredients"},'
    '{id:"bi8",label:"A brand that feels modern and up-to-date"},'
    '{id:"bi9",label:"A premium or aspirational brand"},'
    '{id:"bi10",label:"An innovative brand that launches new products"}'
    '],gridCols:bOpts,pipeFrom:`Q28_${catKey}`},'
    # Q34 — OOS substitution SA
    '{id:`Q34_${catKey}`,type:"SA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`If your main ${catName.toLowerCase()} brand was UNAVAILABLE \u2014 what would you do?`,'
    'instruction:"Select one only",options:bSub},'
    # Q35 — brand loyalty SA
    '{id:`Q35_${catKey}`,type:"SA",section:"category_module",sectionLabel:catName,catKey:catKey,'
    'text:`How likely are you to switch from your current ${catName.toLowerCase()} brand in the next 3 months?`,'
    'instruction:"Select one only",'
    'options:['
    '{label:"Very unlikely \u2014 completely loyal to my current brand",code:1},'
    '{label:"Unlikely",code:2},'
    '{label:"Neutral \u2014 might switch if the right option came along",code:3},'
    '{label:"Likely",code:4},'
    '{label:"Very likely \u2014 actively looking for a better option",code:5}'
    ']}'
    ']}'  # closes return [] and function
)

def phase4(js):
    print("\n── Phase 4: Replace lp() function ──────────────────────────")
    # lp function ends just before "const op=21,"
    pat = re.compile(r'function lp\([\s\S]*?\}(?=const op=)', re.DOTALL)
    m = pat.search(js)
    if m:
        old = m.group(0)
        js = js[:m.start()] + NEW_LP + js[m.end():]
        print(f"  ✓  lp() replaced ({len(old):,} → {len(NEW_LP):,} chars)")
    else:
        print("  ✗  lp() function: not found")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5  Replace Ui array (25 cats → 6 PDF cats)
# Ui is in the same const: ...sp=[Q30],Ui=[...],up=...
# ═══════════════════════════════════════════════════════════════════════════════

NEW_UI = (
    ',Ui=['
    '{catKey:"pain_fever",name:"Pain & Fever Relief",'
    'brands:["Dolo 650","Crocin","Calpol","Combiflam","Disprin","Meftal Spas","Brufen","D\'Cold Total"]},'
    '{catKey:"cold_cough",name:"Cold, Cough & Flu",'
    'brands:["Strepsils","Vicks","Benadryl","Corex","Cheston Cold","Dabur Honitus","Cofsils","Himalaya Koflet"]},'
    '{catKey:"digestive",name:"Digestive & Acidity",'
    'brands:["Eno","Gelusil","Digene","Pudin Hara","Hajmola","Pepfiz","Dabur Sat Isabgol","Himalaya Gasex"]},'
    '{catKey:"vitamins",name:"Vitamins & Supplements",'
    'brands:["Becosules","Revital H","Supradyn","Limcee Vitamin C","Neurobion Forte","Centrum","Oziva","Wellbeing Nutrition"]},'
    '{catKey:"skin_antifungal",name:"Skin & Antifungal",'
    'brands:["Candid","Ring Guard","Fourderm","Betadine","Soframycin","Dermadew","Cetaphil","Terbinafine"]},'
    '{catKey:"ayurvedic",name:"Ayurvedic / Herbal OTC",'
    'brands:["Patanjali","Himalaya","Dabur","Hamdard","Zandu","Baidyanath","Kerala Ayurveda","Charak Pharma"]}'
    ']'
)

def phase5(js):
    print("\n── Phase 5: Replace Ui array (25→6 categories) ─────────────")
    # pattern: ",Ui=[{num:1," ... "]" right before ",up="
    pat = re.compile(r',Ui=\[\{num:1,[\s\S]*?\](?=,up=)', re.DOTALL)
    m = pat.search(js)
    if m:
        old = m.group(0)
        js = js[:m.start()] + NEW_UI + js[m.end():]
        print(f"  ✓  Ui replaced ({len(old):,} → {len(NEW_UI):,} chars)")
    else:
        print("  ✗  Ui array: pattern not found")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6  Fix up= computation
# ═══════════════════════════════════════════════════════════════════════════════
def phase6(js):
    print("\n── Phase 6: Fix up= computation ─────────────────────────────")
    return sub(js,
        ',up=Ui.flatMap(e=>lp(e.num,e.startQ,e.name,e.brands,e.focalBrand,e.focalStatement,e.priceLabel))',
        ',up=Ui.flatMap(e=>lp(e.catKey,e.name,e.brands))',
        "up= (catKey-based)")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 7  Fix vc / pp computations
# ═══════════════════════════════════════════════════════════════════════════════
def phase7(js):
    print("\n── Phase 7: Fix vc/pp computations ──────────────────────────")
    js = sub(js,
        'const vc={};Ui.forEach(e=>{vc[e.num]=Array.from({length:op},(t,n)=>`Q${e.startQ+n}`)});',
        'const vc={};Ui.forEach(e=>{vc[e.catKey]=Array.from({length:op},(t,n)=>`Q${25+n}_${e.catKey}`)});',
        "vc (catKey)")
    js = sub(js,
        'const pp={};Ui.forEach(e=>{pp[e.num]=e.name});',
        'const pp={};Ui.forEach(e=>{pp[e.catKey]=e.name});',
        "pp (catKey)")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 8  Replace rt,dp with Q36-Q40 demographics
# Structure: ...,rt=561,dp=[...]  (still inside the big const)
# ═══════════════════════════════════════════════════════════════════════════════

NEW_DP = (
    ',rt=36,dp=['
    # Q36 — employment status
    '{id:"Q36",type:"SA",section:"demographics",'
    'text:"What is your current employment status?",'
    'instruction:"Select one",'
    'options:['
    '{label:"Employed full-time \u2014 private sector (salaried)",code:1},'
    '{label:"Employed full-time \u2014 government or public sector",code:2},'
    '{label:"Self-employed, freelance or own business",code:3},'
    '{label:"Homemaker \u2014 primary household manager",code:4},'
    '{label:"Student",code:5},'
    '{label:"Currently not employed",code:6},'
    '{label:"Retired",code:7}'
    ']},'
    # Q37 — household income
    '{id:"Q37",type:"SA",section:"demographics",'
    'text:"Approximately what is your total monthly household income from all sources?",'
    'instruction:"Select one",'
    'options:['
    '{label:"Below INR 25,000",code:1},'
    '{label:"INR 25,001 \u2013 50,000",code:2},'
    '{label:"INR 50,001 \u2013 75,000",code:3},'
    '{label:"INR 75,001 \u2013 1,00,000",code:4},'
    '{label:"INR 1,00,001 \u2013 1,50,000",code:5},'
    '{label:"Above INR 1,50,000",code:6},'
    '{label:"Prefer not to say",code:7}'
    ']},'
    # Q38 — household size
    '{id:"Q38",type:"SA",section:"demographics",'
    'text:"How many people currently live in your household, including yourself?",'
    'instruction:"Select one",'
    'options:['
    '{label:"1 \u2014 I live alone",code:1},'
    '{label:"2 people",code:2},'
    '{label:"3 to 4 people",code:3},'
    '{label:"5 to 6 people",code:4},'
    '{label:"7 or more people",code:5}'
    ']},'
    # Q39 — children in household
    '{id:"Q39",type:"SA",section:"demographics",'
    'text:"Are there any children below the age of 15 in your household?",'
    'instruction:"Select one",'
    'options:['
    '{label:"Yes \u2014 one or more children under 15",code:1},'
    '{label:"No \u2014 no children under 15",code:2},'
    '{label:"Prefer not to say",code:3}'
    ']},'
    # Q40 — chronic condition
    '{id:"Q40",type:"SA",section:"demographics",'
    'text:"Do you personally have any diagnosed chronic health condition?",'
    'instruction:"Optional \u2014 confidential, used for profiling only",'
    'optional:!0,'
    'options:['
    '{label:"Yes \u2014 diabetes or high blood sugar",code:1},'
    '{label:"Yes \u2014 hypertension or high blood pressure",code:2},'
    '{label:"Yes \u2014 thyroid condition",code:3},'
    '{label:"Yes \u2014 asthma or respiratory condition",code:4},'
    '{label:"Yes \u2014 another chronic condition",code:5},'
    '{label:"No \u2014 no diagnosed chronic condition",code:6},'
    '{label:"Prefer not to say",code:7}'
    ']}'
    ']'  # end dp
)

def phase8(js):
    print("\n── Phase 8: Replace rt,dp (demographics Q36-Q40) ───────────")
    # old pattern: ",rt=561,dp=[" ... "]" before ",fp=["
    pat = re.compile(r',rt=\d+,dp=\[[\s\S]*?\](?=,fp=\[)', re.DOTALL)
    m = pat.search(js)
    if m:
        old = m.group(0)
        js = js[:m.start()] + NEW_DP + js[m.end():]
        print(f"  ✓  rt,dp replaced ({len(old):,} → {len(NEW_DP):,} chars)")
    else:
        print("  ✗  rt,dp: pattern not found")
    return js


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 9  Fix es constant: end:rt+5 → end:40  (5 demographics, not 6)
# Declaration: const Za={start:_t,end:_t+4},es={start:rt,end:rt+5};
# After phase 8, rt=36, so rt+5=41 which conflicts with Q41 in module A.
# We fix es to use literal {start:36,end:40} to be safe.
# ═══════════════════════════════════════════════════════════════════════════════
def phase9(js):
    print("\n── Phase 9: Fix es constant ─────────────────────────────────")
    return sub(js,
        ',es={start:rt,end:rt+5};',
        ',es={start:36,end:40};',
        "es constant (start:36 end:40)")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 10  Fix progress v() function loops
# Old: for C=1..8 (screener), for C=9..30 (module A/B)
# New: for C=1..7 (screener Q1-Q7), for C=8..24 (module A/B Q8-Q24),
#      push Q41,Q43,Q44,Q42 explicitly
# ═══════════════════════════════════════════════════════════════════════════════
def phase10(js):
    print("\n── Phase 10: Fix progress v() function ──────────────────────")
    return sub(js,
        'for(let C=1;C<=8;C++)w.push(`Q${C}`);for(let C=9;C<=30;C++)w.push(`Q${C}`);',
        'for(let C=1;C<=7;C++)w.push(`Q${C}`);for(let C=8;C<=24;C++)w.push(`Q${C}`);'
        'w.push("Q41","Q43","Q44","Q42");',
        "progress loops (Q1-7 screener, Q8-24 moduleA/B + Q41/43/44/42)")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    if not os.path.exists(JS_PATH):
        sys.exit(f"ERROR: JS file not found at {JS_PATH}")

    js = load()
    orig_len = len(js)
    print(f"Loaded {JS_PATH}\nSize: {orig_len:,} bytes\n")

    js = phase1(js)
    js = phase2(js)
    js = phase3(js)
    js = phase4(js)
    js = phase5(js)
    js = phase6(js)
    js = phase7(js)
    js = phase8(js)
    js = phase9(js)
    js = phase10(js)

    save(js)
    print(f"\n{'='*60}")
    print(f"Saved. Size: {len(js):,} bytes  (delta: {len(js)-orig_len:+,})")
    print("Run scripts/verify_qre_patch.py to verify key strings.")

if __name__ == "__main__":
    main()
