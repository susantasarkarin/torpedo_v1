// check vendor and quota from new pdf
print("=== VENDORS ===");
db.vendors.find({},{_id:0,vid:1,vendorName:1,vendorVariable:1,completeRD:1,terminateRD:1,quotaFullRD:1}).forEach(function(r){ print(JSON.stringify(r)); });

print("\n=== VENDOR COUNT ===");
print("count: "+db.vendors.count());
