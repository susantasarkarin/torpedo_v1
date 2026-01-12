from pymongo import MongoClient
c = MongoClient("mongodb://susanta:StrongPassDogfish!@127.0.0.1:27017/admin")
db = c["cpx_research"]

surveys = db.cpx_surveys.find({}).limit(5)
for s in surveys:
    sid = s.get("survey_id")
    cr = s.get("conversion_rate")
    conv = s.get("conversion")
    raw = s.get("raw_data", {})
    ctr = raw.get("click_to_okay_rate") if raw else None
    cr_raw = raw.get("conversion_rate") if raw else None
    print(f"ID: {sid}, conversion_rate: {cr}, conversion: {conv}, click_to_okay_rate: {ctr}, raw_conversion_rate: {cr_raw}")
