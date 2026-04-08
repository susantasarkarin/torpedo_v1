// check vendor and admin export
print("=== CINT VENDOR (vid=4738) ===");
var v = db.vendors.findOne({vid:"4738"});
if(!v) v = db.vendors.findOne({vid:4738});
if(v){ print(JSON.stringify(v)); } else { print("NOT FOUND"); }

print("\n=== ALL VENDORS ===");
db.vendors.find({},{_id:0,vid:1,vendorName:1,vendorVariable:1,completeRD:1,terminateRD:1,quotaFullRD:1}).forEach(function(r){ print(JSON.stringify(r)); });
