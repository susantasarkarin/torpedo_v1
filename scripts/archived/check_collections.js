print("=== Collections in email_automation ===");
db.getCollectionNames().forEach(n=>print(n));
print("\n=== url_parameters count ===");
print(db.url_parameters.countDocuments({}));
print("\n=== traffic_data count ===");
try { print(db.traffic_data.countDocuments({})); } catch(e) { print("not found"); }
print("\n=== survey_traffic count ===");
try { print(db.survey_traffic.countDocuments({})); } catch(e) { print("not found"); }
