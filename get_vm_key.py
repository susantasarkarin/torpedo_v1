from pymongo import MongoClient
c = MongoClient()
cfg = c.torpedo_settings.app_settings.find_one()
if cfg:
    key = cfg.get("openai_api_key", "")
    if key:
        print(key)
    else:
        print("EMPTY_KEY")
else:
    print("NO_CONFIG")
