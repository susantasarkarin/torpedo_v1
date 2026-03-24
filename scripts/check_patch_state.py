import re, sys

JS = "qre_frontend/assets/index-B3tU2e59.js"
js = open(JS, encoding="utf-8").read()

print(f"File size: {len(js):,} bytes\n")

checks = [
    ("op value",        r'const op=(\d+),', 1),
    ("rt value",        r',rt=(\d+),dp=\[', 1),
    ("es constant",     r',es=\{[^}]+\}', 0),
    ("progress loop",   r'for\(let C=1;C<=(\d+);C\+\+\)', 1),
    ("Q3 text",         r'\{id:"Q3"[^}]+text:"([^"]{0,60})', 1),
    ("Q4 text",         r'\{id:"Q4"[^}]+text:"([^"]{0,60})', 1),
    ("Q6 type",         r'\{id:"Q6",type:"([^"]+)"', 1),
    ("Q7 type",         r'\{id:"Q7",type:"([^"]+)"', 1),
    ("ap first q",      r',ap=\[\{id:"([^"]+)"', 1),
    ("Ui style",        r',Ui=\[\{([a-z]+):', 1),
    ("Q8 in screener",  r'\{id:"Q8",type:"SA",section:"screener"', 0),
]

for label, pat, grp in checks:
    m = re.search(pat, js)
    if m:
        val = m.group(grp) if grp else m.group(0)[:60]
        print(f"  {label:25s} = {val}")
    else:
        print(f"  {label:25s} = NOT FOUND")
