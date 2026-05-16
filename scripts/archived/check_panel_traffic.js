// Check a recent SFW Panel traffic record (vid: "2656")
db = db.getSiblingDB("email_automation");
var rec = db.url_parameters.findOne(
  { vendorId: "2656" },
  { vendorId:1, respondentId:1, panelId:1, params:1, status:1, createdAt:1 }
);
printjson(rec);

// Also check what field names exist
print("\n--- Field names from 5 panel records ---");
db.url_parameters.find({ vendorId: "2656" }, { _id:0 }).limit(3).forEach(function(r) {
  printjson(Object.keys(r));
});
