db = db.getSiblingDB("traffic_flow_db");

// Find a recent panel traffic record
var rec = db.url_parameters.findOne(
  { vendorId: "2656" },
  { vendorId:1, respondentId:1, panelId:1, params:1, status:1, createdAt:1 }
);
print("=== Panel traffic record (vid 2656) ===");
printjson(rec);

// Count how many panel records exist
print("=== Total panel records: " + db.url_parameters.countDocuments({ vendorId: "2656" }));

// Also check a Hansa record to see what fields look like
var hansa = db.url_parameters.findOne(
  { },
  { vendorId:1, respondentId:1, panelId:1, params:1, status:1, createdAt:1 }
);
print("=== Sample traffic record (any vendor) ===");
printjson(hansa);

// Check vendors in this DB too
db2 = db.getSiblingDB("email_automation");
var vendor = db2.vendors.findOne({ vid: "2656" });
print("=== email_automation vendor 2656 ===");
printjson(vendor);
