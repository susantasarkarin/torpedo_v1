// Fix SFW Panel vendor redirect URLs in MongoDB
// Run: mongosh /tmp/fix_panel_vendor.js

db = db.getSiblingDB("email_automation");

var result = db.vendors.updateOne(
  { vendorName: "SFW Panel" },
  {
    $set: {
      vendorVariable: "rid",
      completeRD: ["https://panel.surveyfieldwork.com/api/surveys/redirect/complete?rid="],
      terminateRD: ["https://panel.surveyfieldwork.com/api/surveys/redirect/terminate?rid="],
      quotaFullRD: ["https://panel.surveyfieldwork.com/api/surveys/redirect/quotafull?rid="]
    }
  }
);

print("Matched: " + result.matchedCount);
print("Modified: " + result.modifiedCount);

// Verify
var doc = db.vendors.findOne({ vendorName: "SFW Panel" });
print("vendorVariable: " + doc.vendorVariable);
print("completeRD:  " + doc.completeRD[0]);
print("terminateRD: " + doc.terminateRD[0]);
print("quotaFullRD: " + doc.quotaFullRD[0]);
