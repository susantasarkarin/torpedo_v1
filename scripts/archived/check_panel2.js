db.vendors.find({vid:"2656"}).forEach(d=>print(JSON.stringify(d)));
print("---url_parameters count with vid 2656:");
print(db.url_parameters.countDocuments({vendorId:"2656"}));
print("---recent url_parameters for vid 2656:");
db.url_parameters.find({vendorId:"2656"}).sort({_id:-1}).limit(2).forEach(d=>print(JSON.stringify(d)));
