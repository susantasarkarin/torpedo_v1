// Check what fields url_parameters actually uses for vendor
print("=== Sample record keys ===");
db.url_parameters.findOne({}, {vid:1, vendorId:1, vendor:1, _id:0, params:1, panelId:1, respondentId:1});

print("\n=== Records with any vid/vendor field ===");
db.url_parameters.find({}).sort({_id:-1}).limit(1).forEach(d=>{
  print("ALL KEYS: " + JSON.stringify(Object.keys(d)));
  print("FULL: " + JSON.stringify(d));
});

// Search for panel-related records
print("\n=== Records with panel in params ===");
db.url_parameters.find({"params.panel": {$exists:true}}).sort({_id:-1}).limit(2).forEach(d=>{
  print(JSON.stringify({keys: Object.keys(d), panelId: d.panelId, params: d.params, vendorId: d.vendorId, vid: d.vid}));
});
