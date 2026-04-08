// Run: mongosh traffic_flow_db /tmp/check_traffic.js --quiet
print("=== RECENT 24H TRAFFIC ===");
print("count: " + db.url_parameters.countDocuments({createdAt:{$gte:new Date(Date.now()-86400000)}}));

var recent = db.url_parameters.find(
  {createdAt:{$gte:new Date(Date.now()-86400000)}},
  {_id:1,status:1,surveySource:1,vendorId:1,respondentId:1,assignedSurveyId:1,projectId:1,redirectUrl:1}
).limit(5).toArray();
recent.forEach(function(r){ print(JSON.stringify(r)); });

print("\n=== SOURCE BREAKDOWN ===");
db.url_parameters.aggregate([{$group:{_id:"$surveySource",ct:{$sum:1}}}]).toArray().forEach(function(r){ print(JSON.stringify(r)); });

print("\n=== PROJECT STATUS BREAKDOWN ===");
db.url_parameters.aggregate([{$match:{surveySource:"PROJECT"}},{$group:{_id:"$status",ct:{$sum:1}}}]).toArray().forEach(function(r){ print(JSON.stringify(r)); });

print("\n=== SAMPLE COMPLETED PROJECT RECORD ===");
var comp = db.url_parameters.findOne({surveySource:"PROJECT",status:"COMPLETE"});
if(comp){ print(JSON.stringify(comp)); } else { print("none"); }

print("\n=== SAMPLE INCOMPLETE PROJECT RECORD ===");
var inc = db.url_parameters.findOne({surveySource:"PROJECT"});
if(inc){ print(JSON.stringify(inc)); } else { print("none"); }
