// Search all databases for leads
var databases = ["campaign_platform", "email_automation", "cint_research", "cpx_research", "torpedo_gmail"];

databases.forEach(function(dbName) {
  print("\n=== " + dbName + " ===");
  var currentDb = db.getSiblingDB(dbName);
  currentDb.getCollectionNames().forEach(function(c) {
    var count = currentDb[c].countDocuments({});
    if (count > 0) {
      print("  " + c + ": " + count);
    }
  });
});

// Check specifically for leads collections
print("\n\n=== SEARCHING FOR LEADS COLLECTIONS ===");
["campaign_platform", "email_automation"].forEach(function(dbName) {
  var currentDb = db.getSiblingDB(dbName);
  print("\n" + dbName + ":");
  
  // Check leads
  if (currentDb.leads) {
    print("  leads: " + currentDb.leads.countDocuments({}));
  }
  
  // Check leads_enriched
  if (currentDb.leads_enriched) {
    print("  leads_enriched: " + currentDb.leads_enriched.countDocuments({}));
  }
  
  // Check leads_raw
  if (currentDb.leads_raw) {
    print("  leads_raw: " + currentDb.leads_raw.countDocuments({}));
  }
  
  // Check contacts
  if (currentDb.contacts) {
    print("  contacts: " + currentDb.contacts.countDocuments({}));
  }
});
