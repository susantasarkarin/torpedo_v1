// Run with: mongosh qre_otc_discovery scripts/check_qre_db.js
print("=== RESPONDENT STATUS ===");
db.respondents.aggregate([{$group:{_id:"$status",count:{$sum:1}}}]).forEach(r=>print("  "+r._id+": "+r.count));
print("  TOTAL: " + db.respondents.countDocuments({}));

print("\n=== TERMINATION REASONS ===");
db.respondents.aggregate([
  {$match:{status:"terminated"}},
  {$group:{_id:"$termination_reason",count:{$sum:1}}},
  {$sort:{count:-1}}
]).forEach(r=>print("  "+r._id+": "+r.count));

print("\n=== DB QUOTAS (global) ===");
var q = db.quotas.findOne({_id:"global"});
if(q){ delete q._id; print(JSON.stringify(q,null,2)); } else { print("  (none)"); }

print("\n=== QUOTA LIMITS ===");
var ql = db.quota_limits.findOne({_id:"limits"});
if(ql){ delete ql._id; print(JSON.stringify(ql,null,2)); } else { print("  (none)"); }

print("\n=== STUDIES ===");
db.studies.find({},{_id:1,name:1,redirects:1}).forEach(r=>print("  "+JSON.stringify(r)));

print("\n=== SAMPLE RESPONDENT ===");
var s = db.respondents.findOne({},{started_at:1,status:1,study_id:1,vendor_rid:1,ip_address:1});
print(s ? JSON.stringify(s) : "  (none)");
