// Check most recent respondent allocations
// Run with: mongosh survey_allocation --file check_respondent.js

// Summary counts
var cintSurveys = db.surveys.find({provider: "CINT"}).toArray();
var cpxSurveys = db.surveys.find({provider: "CPX"}).toArray();
print("=== SURVEY COUNTS ===");
print("CINT surveys in pool: " + cintSurveys.length);
print("CPX surveys in pool: " + cpxSurveys.length);

var cintIds = cintSurveys.map(s => s._id.toString());
var cpxIds = cpxSurveys.map(s => s._id.toString());

var cintAllocCount = 0;
var cpxAllocCount = 0;

var allLogs = db.allocation_log.find().toArray();
allLogs.forEach(function(l) {
  if (cintIds.indexOf(l.survey_id) >= 0) cintAllocCount++;
  if (cpxIds.indexOf(l.survey_id) >= 0) cpxAllocCount++;
});

print("Total allocation logs: " + allLogs.length);
print("CPX allocations: " + cpxAllocCount);
print("CINT allocations: " + cintAllocCount);

print("\n=== MOST RECENT 10 ALLOCATIONS ===");
var logs = db.allocation_log.find().sort({timestamp:-1}).limit(10).toArray();
var respondentSurveys = {};

logs.forEach(function(l) {
  var s = db.surveys.findOne({_id: ObjectId(l.survey_id)});
  var provider = s ? s.provider : "UNKNOWN";
  var surveyId = s ? s.external_id : l.survey_id;
  var rid = l.rid || l.respondent_id;
  
  if (!respondentSurveys[rid]) {
    respondentSurveys[rid] = {cpx: [], cint: []};
  }
  
  if (provider === "CPX") {
    respondentSurveys[rid].cpx.push(surveyId);
  } else if (provider === "CINT") {
    respondentSurveys[rid].cint.push(surveyId);
  }
  
  print(rid + " -> " + provider + " survey " + surveyId + " @ " + l.timestamp);
});

print("\n=== MOST RECENT RESPONDENT SUMMARY ===");
var firstRid = logs[0] ? logs[0].rid || logs[0].respondent_id : null;
if (firstRid && respondentSurveys[firstRid]) {
  print("Respondent: " + firstRid);
  print("CPX surveys: " + JSON.stringify(respondentSurveys[firstRid].cpx));
  print("CINT surveys: " + JSON.stringify(respondentSurveys[firstRid].cint));
}
