txt = open('qre_frontend/assets/index-B3tU2e59.js', encoding='utf-8').read()
idx = txt.find('{id:"Q1"')
print(txt[idx:idx+1000])
