import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "qre_health_survey")

# ---------- Quota configuration ----------
TOTAL_SAMPLE = int(os.getenv("TOTAL_SAMPLE", "2100"))

# Age quotas (Q2): ~33% each across 3 bands
QUOTA_AGE = {
    "band1_25_34": int(TOTAL_SAMPLE * 0.33),  # codes 2,3
    "band2_35_44": int(TOTAL_SAMPLE * 0.34),  # codes 4,5
    "band3_45_55": int(TOTAL_SAMPLE * 0.33),  # codes 6,7
}

# Gender quotas (Q3): 55% Female / 45% Male — soft quota
QUOTA_GENDER = {
    "male": int(TOTAL_SAMPLE * 0.45),
    "female": int(TOTAL_SAMPLE * 0.55),
}

# NCCS quotas (Q8): 60% A / 40% B
QUOTA_NCCS = {
    "nccs_a": int(TOTAL_SAMPLE * 0.60),  # codes 1,2
    "nccs_b": int(TOTAL_SAMPLE * 0.40),  # codes 3,4
}

# City quotas — equal distribution across 10 cities (210 each)
QUOTA_CITY = {
    "mumbai": int(TOTAL_SAMPLE * 0.10),
    "delhi_ncr": int(TOTAL_SAMPLE * 0.10),
    "bangalore": int(TOTAL_SAMPLE * 0.10),
    "kolkata": int(TOTAL_SAMPLE * 0.10),
    "chennai": int(TOTAL_SAMPLE * 0.10),
    "hyderabad": int(TOTAL_SAMPLE * 0.10),
    "pune": int(TOTAL_SAMPLE * 0.10),
    "ahmedabad": int(TOTAL_SAMPLE * 0.10),
    "jaipur": int(TOTAL_SAMPLE * 0.10),
    "lucknow": int(TOTAL_SAMPLE * 0.10),
}

# Rotation group quotas — 300 per group, 7 groups
QUOTA_ROTATION_GROUP = {
    "group_a": 300,
    "group_b": 300,
    "group_c": 300,
    "group_d": 300,
    "group_e": 300,
    "group_f": 300,
    "group_g": 300,
}

# Rotation group → category module mapping (25 categories, 7 groups, 4 per group)
ROTATION_GROUPS = {
    "group_a": [1, 2, 3, 4],      # Pain & Fever / Vitamins / Cold, Cough / Anti-Diarrheal
    "group_b": [5, 6, 7, 8],      # Antacids / Allergy / Antiseptics / Herbal
    "group_c": [9, 10, 11, 12],   # Antifungal / Eye & Ear / Oral Care / Maternal
    "group_d": [13, 14, 15, 16],  # Diagnostics / Digital Health / Wearables / Hospital
    "group_e": [17, 18, 19, 20],  # Health Insurance / Fitness / Mental Health / D2C
    "group_f": [21, 22, 23, 24],  # Dental & Vision / Weight Mgmt / Hair Loss / Sexual Wellness
    "group_g": [25, 1, 2, 19],    # Women's Health / Pain & Fever / Vitamins / Mental Health (overlap)
}

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# ---------- Dashboard credentials ----------
# Change these via environment variables before deploying
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD",  "admin@QRE2026")
CLIENT_PASSWORD = os.getenv("CLIENT_PASSWORD", "viewer@QRE2026")
