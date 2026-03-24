txt = open('qre_frontend/assets/index-B3tU2e59.js', encoding='utf-8').read()
idx = txt.find('{id:"Q1"')
# Print the exact raw bytes around Q1 and Q2
segment = txt[idx:idx+3000]
print(repr(segment[:500]))
print("---")
print(repr(segment[500:1000]))
print("---")
print(repr(segment[1000:1500]))
