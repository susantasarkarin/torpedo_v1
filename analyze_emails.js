// Get classification distribution
print("=== Classification Distribution ===");
db.email_metadata.aggregate([
  {$group: {_id: "$ai_category", count: {$sum: 1}, avgConfidence: {$avg: "$ai_confidence"}}},
  {$sort: {count: -1}}
]).forEach(doc => printjson(doc));

// Check internal domain emails
print("\n=== Emails from cogentixresearch.com ===");
db.email_metadata.find({from_email: /cogentixresearch/}, {from_email: 1, subject: 1, ai_category: 1}).limit(5).forEach(doc => printjson(doc));

print("\n=== Emails from surveyfieldwork.com ===");
db.email_metadata.find({from_email: /surveyfieldwork/}, {from_email: 1, subject: 1, ai_category: 1}).limit(5).forEach(doc => printjson(doc));

print("\n=== Emails with Zoho in subject ===");
db.email_metadata.find({subject: /zoho/i}, {from_email: 1, subject: 1, ai_category: 1}).limit(5).forEach(doc => printjson(doc));

print("\n=== Bank related emails ===");
db.email_metadata.find({from_email: /axis|bank/i}, {from_email: 1, subject: 1, ai_category: 1}).limit(5).forEach(doc => printjson(doc));
