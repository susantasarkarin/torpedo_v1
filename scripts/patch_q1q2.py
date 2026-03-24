txt = open('qre_frontend/assets/index-B3tU2e59.js', encoding='utf-8').read()

# Define exact old block (Q1 through end of Q2)
old_q1 = '{id:"Q1",type:"MA",section:"screener",text:"Do you or anyone in your immediate family work in any of the following industries?",instruction:"Select all that apply",options:[{label:"Advertising / Media / Public Relations",code:1},{label:"Marketing or Brand Management",code:2},{label:"Pharmaceuticals or operate a pharmacy",code:3},{label:"Market Research or Consumer Insights",code:4},{label:"Radio, TV station, Newspaper or Magazine",code:5},{label:"Health Insurance company",code:6},{label:"Healthcare \u2014 doctor, nurse, hospital staff",code:7},{label:"Telecom / IT / Technology",code:8},{label:"Manufacturing",code:9},{label:"Education",code:10},{label:"Banking / Financial Services",code:11},{label:"Others",code:12,openCapture:!0}]}'

old_q2 = '{id:"Q2",type:"SA",section:"screener",text:"Please select your age group.",instruction:"Select one",options:[{label:"Below 25 years",code:1},{label:"25\u201329 years",code:2},{label:"30\u201334 years",code:3},{label:"35\u201339 years",code:4},{label:"40\u201344 years",code:5},{label:"45\u201350 years",code:6},{label:"51\u201355 years",code:7},{label:"Above 55 years",code:8}]}'

new_q1 = '{id:"Q1",type:"MA",section:"screener",text:"Do you or anyone in your immediate family work in any of the following industries?",instruction:"Select all that apply. If yes to any, you will not be eligible to continue.",options:[{label:"Advertising or Marketing",code:1},{label:"Market Research or Consumer Insights",code:2},{label:"Pharmaceuticals, Medicine or Pharmacy",code:3},{label:"Health Insurance",code:4},{label:"Healthcare or Medical Services",code:5},{label:"Media, PR or Journalism",code:6},{label:"None of the above",code:7}]}'

new_q2 = '{id:"Q2",type:"SA",section:"screener",text:"Which city do you currently live in?",instruction:"Select one \u2014 study is limited to specific Tier 2 cities only",options:[{label:"Lucknow",code:1},{label:"Jaipur",code:2},{label:"Indore",code:3},{label:"Surat",code:4},{label:"Pune",code:5},{label:"Coimbatore",code:6},{label:"Warangal",code:7},{label:"Bhubaneswar",code:8},{label:"Any other city",code:9}]}'

# Verify both are found
if old_q1 not in txt:
    print("ERROR: old_q1 not found")
elif old_q2 not in txt:
    print("ERROR: old_q2 not found")
else:
    txt = txt.replace(old_q1, new_q1, 1)
    txt = txt.replace(old_q2, new_q2, 1)
    open('qre_frontend/assets/index-B3tU2e59.js', 'w', encoding='utf-8').write(txt)
    print("SUCCESS - Q1 and Q2 patched")
