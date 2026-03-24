import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME",   "qre_otc_discovery")

# ---------- Study ----------
STUDY_TITLE   = "India OTC Discovery Intelligence Study"
STUDY_VERSION = "2.0"
TOTAL_SAMPLE  = int(os.getenv("TOTAL_SAMPLE", "1760"))

# ---------- City quotas — 8 Tier 2 cities, unequal allocation (Q2) ----------
# Lucknow n=250 | Jaipur n=200 | Indore n=200 | Surat n=225 | Pune n=250
# Coimbatore n=200 | Warangal n=185 | Bhubaneswar n=200  (total target n=1,760)
QUOTA_CITY = {
    "lucknow":     250,
    "jaipur":      200,
    "indore":      200,
    "surat":       225,
    "pune":        250,
    "coimbatore":  200,
    "warangal":    185,
    "bhubaneswar": 200,
}

# Q2 code → quota key  (code 9 = any other city → terminate)
CITY_CODE_MAP = {
    1: "lucknow",
    2: "jaipur",
    3: "indore",
    4: "surat",
    5: "pune",
    6: "coimbatore",
    7: "warangal",
    8: "bhubaneswar",
}

# ---------- Age quotas (Q3): ~30% 25-34 | ~30% 35-44 | ~20% 45-55 ----------
# (Code 1 = 18-24 terminates; code 5 = above 55 terminates per QRE routing)
QUOTA_AGE = {
    "band1_25_34": int(TOTAL_SAMPLE * 0.30),   # code 2
    "band2_35_44": int(TOTAL_SAMPLE * 0.30),   # code 3
    "band3_45_55": int(TOTAL_SAMPLE * 0.20),   # code 4
}

# ---------- Gender — soft quota 55F / 45M (Q4) ----------
QUOTA_GENDER = {
    "female": int(TOTAL_SAMPLE * 0.55),
    "male":   int(TOTAL_SAMPLE * 0.45),
}

# ---------- NCCS quotas (Q6+Q7): 50% A / 50% B ----------
QUOTA_NCCS = {
    "nccs_a": int(TOTAL_SAMPLE * 0.50),
    "nccs_b": int(TOTAL_SAMPLE * 0.50),
}

# ---------- Module C brand lists (Appendix A) ----------
CATEGORY_BRANDS = {
    "pain_fever": [
        "Dolo 650", "Crocin", "Calpol", "Combiflam",
        "Disprin", "Meftal Spas", "Brufen", "D'Cold Total",
    ],
    "cold_cough": [
        "Strepsils", "Vicks", "Benadryl", "Corex",
        "Cheston Cold", "Dabur Honitus", "Cofsils", "Himalaya Koflet",
    ],
    "digestive": [
        "Eno", "Gelusil", "Digene", "Pudin Hara",
        "Hajmola", "Pepfiz", "Dabur Sat Isabgol", "Himalaya Gasex",
    ],
    "vitamins": [
        "Becosules", "Revital H", "Supradyn", "Limcee Vitamin C",
        "Neurobion Forte", "Centrum", "Oziva", "Wellbeing Nutrition",
    ],
    "skin_antifungal": [
        "Candid", "Ring Guard", "Fourderm", "Betadine",
        "Soframycin", "Dermadew", "Cetaphil", "Terbinafine generics",
    ],
    "ayurvedic": [
        "Patanjali", "Himalaya", "Dabur", "Hamdard",
        "Zandu", "Baidyanath", "Kerala Ayurveda", "Charak Pharma",
    ],
}

CATEGORY_NAMES = {
    "pain_fever":      "Pain & Fever Relief",
    "cold_cough":      "Cold, Cough & Flu",
    "digestive":       "Digestive & Acidity",
    "vitamins":        "Vitamins & Supplements",
    "skin_antifungal": "Skin & Antifungal",
    "ayurvedic":       "Ayurvedic / Herbal OTC",
}

# Priority order for Module C block assignment (max 3 per respondent)
CATEGORY_PRIORITY = [
    "pain_fever", "cold_cough", "digestive",
    "vitamins", "skin_antifungal", "ayurvedic",
]

# ---------- Quality control thresholds ----------
# Speeder: completes in under this many seconds → disqualified
MIN_COMPLETE_SECONDS = int(os.getenv("MIN_COMPLETE_SECONDS", "240"))  # 4 min floor

# Straight-liner detection: grids where identical answers across all rows = 1 flag.
# Once both grid questions are flagged (STRAIGHT_LINE_FLAGS_TO_TERMINATE reached),
# the respondent is quality-terminated.
GRID_STRAIGHT_LINE_QUESTIONS = ("Q12", "Q17")
STRAIGHT_LINE_FLAGS_TO_TERMINATE = 2

# ---------- CORS & Auth ----------
CORS_ORIGINS    = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD",  "admin@QRE2026")
CLIENT_PASSWORD = os.getenv("CLIENT_PASSWORD", "viewer@QRE2026")
