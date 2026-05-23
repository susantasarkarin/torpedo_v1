// Check all relevant DBs for AI classification data
var dbs = ['ai_governance', 'campaign_platform', 'email_automation', 'torpedo'];
dbs.forEach(function(dbName) {
  var d = db.getSiblingDB(dbName);
  var colls = d.getCollectionNames().filter(function(c) {
    return c.match(/classif|sentiment|ai_log|ai_usage|ai_daily|intent|enrich/i);
  });
  if (colls.length > 0) {
    print("=== DB: " + dbName + " ===");
    colls.forEach(function(c) {
      print("  " + c + ": " + d[c].countDocuments({}) + " docs");
    });
  }
});

// Check leads across all DBs
print("\n=== Leads with AI seniority_level ===");
dbs.forEach(function(dbName) {
  var d = db.getSiblingDB(dbName);
  if (d.getCollectionNames().indexOf('leads') >= 0) {
    var n = d.leads.countDocuments({seniority_level: {$exists: true}});
    print("  " + dbName + ".leads: " + n);
  }
});

// Check ai_governance DB specifically
print("\n=== ai_governance DB collections ===");
var agDb = db.getSiblingDB('ai_governance');
agDb.getCollectionNames().forEach(function(c) {
  print("  " + c + ": " + agDb[c].countDocuments({}) + " docs");
});
