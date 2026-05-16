db = db.getSiblingDB("traffic_flow_db");

// Most recent records
print("=== 3 most recent url_parameters records ===");
db.url_parameters.find({}).sort({_id: -1}).limit(3).forEach(d => printjson(d));

// Records with respondentId matching panel pattern (12 digits)
print("\n=== Records with respondentId 744552183870 ===");
db.url_parameters.find({respondentId: "744552183870"}).forEach(d => printjson(d));

// Any record created in last hour
var oneHourAgo = new Date(Date.now() - 3600000);
print("\n=== Records with vendorId 2656 ===");
db.url_parameters.find({vendorId: "2656"}).sort({_id:-1}).limit(3).forEach(d => printjson(d));
