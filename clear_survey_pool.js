// Remove all CPX and CINT surveys from survey_allocation pool

db = db.getSiblingDB('survey_allocation');

// Delete CPX surveys
const cpxResult = db.surveys.deleteMany({ provider: "CPX" });
print("Deleted " + cpxResult.deletedCount + " CPX surveys from survey_allocation.surveys");

// Delete CINT surveys  
const cintResult = db.surveys.deleteMany({ provider: "CINT" });
print("Deleted " + cintResult.deletedCount + " CINT surveys from survey_allocation.surveys");

// Also clear from cpx_research collection if needed
db = db.getSiblingDB('cpx_research');
const cpxPoolResult = db.cpx_surveys.deleteMany({});
print("Deleted " + cpxPoolResult.deletedCount + " surveys from cpx_research.cpx_surveys");

// Clear from cint_research collection
db = db.getSiblingDB('cint_research');
const cintPoolResult = db.cint_surveys.deleteMany({});
print("Deleted " + cintPoolResult.deletedCount + " surveys from cint_research.cint_surveys");

print("\nAll historic CPX and CINT surveys removed.");
