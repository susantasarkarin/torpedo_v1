import re
js = open("qre_frontend/assets/index-B3tU2e59.js", encoding="utf-8").read()
matches = list(re.finditer(r'catKey:["\w]+', js))
print(f"Total catKey: occurrences: {len(matches)}")
for i, m in enumerate(matches):
    ctx = js[m.start()-5:m.end()+25]
    print(f"  [{i+1}] {ctx}")
