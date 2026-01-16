db.email_metadata.find({}, {from_email: 1, subject: 1, ai_category: 1, ai_confidence: 1}).limit(20).forEach(doc => printjson(doc))
