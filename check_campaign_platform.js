// Check campaign_platform database
print("=== CAMPAIGN_PLATFORM DATABASE ===");
print("");

db.getCollectionNames().forEach(function(c) {
  print(c + ": " + db[c].countDocuments({}));
});

print("\n=== LEADS COLLECTION ===");
if (db.leads) {
  print("Total leads:", db.leads.countDocuments({}));
  
  var fourHoursAgo = new Date(Date.now() - 4*60*60*1000);
  print("Leads in past 4h:", db.leads.countDocuments({createdAt: {$gte: fourHoursAgo}}));
  
  print("\nLead status breakdown:");
  db.leads.aggregate([
    {$group: {_id: "$status", count: {$sum: 1}}},
    {$sort: {count: -1}}
  ]).forEach(function(r) {
    print("  " + (r._id || "(null)") + ": " + r.count);
  });
  
  print("\nLast 3 leads:");
  db.leads.find({}).sort({createdAt: -1}).limit(3).forEach(function(l) {
    print("  Name:", l.firstName, l.lastName || "");
    print("  Email:", l.email);
    print("  Status:", l.status);
    print("  Created:", l.createdAt);
    print("");
  });
}
