// Update all CPX surveys to set country = "ALL"
// This is needed because CPX doesn't provide country code in their API payload
// The allocation logic will skip country filtering for surveys with country="ALL"

db = db.getSiblingDB('cpx_research');

const result = db.cpx_surveys.updateMany(
  {},  // Match all documents
  { $set: { country: "ALL" } }
);

print("Updated " + result.modifiedCount + " CPX surveys to country=ALL");
print("Matched " + result.matchedCount + " documents");
