db = db.getSiblingDB("traffic_flow_db");

// Get a complete traffic record with ALL fields
var rec = db.url_parameters.findOne({});
print("=== Full sample traffic record ===");
printjson(rec);

// Count total records
print("=== Total records: " + db.url_parameters.countDocuments({}));

// Check what vendorId values exist
db.url_parameters.aggregate([
  { $group: { _id: "$vendorId", count: { $sum: 1 } } },
  { $limit: 10 }
]).forEach(d => print(JSON.stringify(d)));
