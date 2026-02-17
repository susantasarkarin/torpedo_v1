// Top 5 countries by active survey count
var result = db.surveys.aggregate([
  { $match: { status: "active" } },
  { $unwind: "$country_codes" },
  { $group: { _id: "$country_codes", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 5 }
]).toArray();

print("=== TOP 5 COUNTRIES BY ACTIVE SURVEYS ===\n");
result.forEach(function(r) {
  print("Country code " + r._id + ": " + r.count + " active surveys");
});

print("\n=== BREAKDOWN BY PROVIDER ===");
var byProvider = db.surveys.aggregate([
  { $match: { status: "active" } },
  { $unwind: "$country_codes" },
  { $group: { _id: { cc: "$country_codes", provider: "$provider" }, count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 10 }
]).toArray();

byProvider.forEach(function(r) {
  print(r._id.provider + " - Country " + r._id.cc + ": " + r.count);
});
