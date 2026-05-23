// Fast targeted queries - check auto_classifier_stats and lead_enrichment_logs
print("=== auto_classifier_stats ===");
printjson(db.auto_classifier_stats.findOne({}));

print("\n=== lead_enrichment_logs sample (last 5) ===");
db.lead_enrichment_logs.find({},{status:1,source:1,created_at:1,_id:0}).sort({_id:-1}).limit(5).forEach(function(d) {
  printjson(d);
});

print("\n=== lead_enrichment_logs by status ===");
db.lead_enrichment_logs.aggregate([
  {$group: {_id: "$status", count: {$sum: 1}}}
]).forEach(function(r) {
  print("  " + r._id + ": " + r.count);
});

print("\n=== leads with seniority breakdown ===");
db.leads.aggregate([
  {$match: {seniority_level: {$exists: true}}},
  {$group: {_id: "$seniority_level", count: {$sum: 1}}},
  {$sort: {count: -1}}
]).forEach(function(r) {
  print("  " + r._id + ": " + r.count);
});
