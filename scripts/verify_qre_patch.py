import re
js = open("qre_frontend/assets/index-B3tU2e59.js", encoding="utf-8").read()

checks = [
    ("op=11",               'const op=11,' in js),
    ("Q3=age",              "What is your age?" in js),
    ("Q4=gender",           "What is your gender?" in js),
    ("Q6=MA durables",      '{id:"Q6",type:"MA"' in js),
    ("Q7=SA education",     '{id:"Q7",type:"SA"' in js),
    ("Q8 NOT in screener",  '{id:"Q8",type:"SA",section:"screener"' not in js),
    ("ap starts at Q8",     ',ap=[{id:"Q8"' in js),
    ("Q41 in ap",           '{id:"Q41"' in js),
    ("Q42 in ap",           '{id:"Q42"' in js),
    ("Q43 in ap",           '{id:"Q43"' in js),
    ("Q44 in ap",           '{id:"Q44"' in js),
    ("Ui catKey=pain_fever",',Ui=[{catKey:"pain_fever"' in js),
    ("6 Ui categories",     js.count(',Ui=') == 0 or                   # already in const
                                js.count('catKey:"pain_fever"') == 1 and
                                js.count('catKey:"cold_cough"') == 1 and
                                js.count('catKey:"digestive"') == 1 and
                                js.count('catKey:"vitamins"') == 1 and
                                js.count('catKey:"skin_antifungal"') == 1 and
                                js.count('catKey:"ayurvedic"') == 1),
    ("up uses catKey",      ',up=Ui.flatMap(e=>lp(e.catKey' in js),
    ("vc uses catKey",      "vc[e.catKey]=" in js),
    ("pp uses catKey",      "pp[e.catKey]=" in js),
    ("lp new signature",    "function lp(catKey,catName,brands)" in js),
    ("dp Q36 literal id",   '{id:"Q36"' in js),
    ("dp Q40 literal id",   '{id:"Q40"' in js),
    ("rt=36",               ",rt=36,dp=" in js),
    ("es start:36 end:40",  ",es={start:36,end:40}" in js),
    ("progress loop 1-7",   "C<=7;C++)w.push" in js),
    ("progress loop 8-24",  "C<=24;C++)w.push" in js),
    ("Q41 Q43 Q44 Q42 push",'push("Q41","Q43","Q44","Q42")' in js),
    ("Q25 catKey IDs",      "Q25_${catKey}" in js),
]

all_ok = True
for label, result in checks:
    icon = "OK  " if result else "FAIL"
    if not result:
        all_ok = False
    print(f"  [{icon}] {label}")

print()
print("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED — see FAIL items above")
