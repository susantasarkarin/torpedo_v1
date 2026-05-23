// MongoDB classification count query
var result = {
  email_classification_guard: db.email_classification_guard.countDocuments({}),
  ai_classification_logs_total: db.ai_classification_logs.countDocuments({}),
  ai_classification_logs_success: db.ai_classification_logs.countDocuments({success: true}),
  ai_classification_logs_failed: db.ai_classification_logs.countDocuments({success: false}),
  campaign_recipients_with_sentiment: db.campaign_recipients.countDocuments({reply_sentiment: {$exists: true}}),
  leads_with_seniority: db.leads.countDocuments({seniority_level: {$exists: true}}),
  leads_with_reply_sentiment: db.leads.countDocuments({reply_sentiment: {$exists: true}})
};
print("=== AI Classification Counts ===");
printjson(result);

print("\n--- AI daily usage (last 10 days) ---");
db.ai_daily_usage.find({}, {date:1, count:1, _id:0}).sort({date:-1}).limit(10).forEach(function(d) {
  print("  " + d.date + ": " + d.count + " AI calls");
});

print("\n--- Reply sentiment distribution ---");
db.campaign_recipients.aggregate([
  {$match: {reply_sentiment: {$exists: true}}},
  {$group: {_id: "$reply_sentiment", count: {$sum: 1}}},
  {$sort: {count: -1}}
]).forEach(function(r) {
  print("  " + r._id + ": " + r.count);
});
