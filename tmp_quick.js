print("Sends: " + db.outreach_sends_v2.countDocuments({}));
print("Sends bounced: " + db.outreach_sends_v2.countDocuments({status:"bounced"}));
print("Leads in_sequence: " + db.outreach_leads_v2.countDocuments({workflow_status:"in_sequence"}));
print("Leads bounced: " + db.outreach_leads_v2.countDocuments({workflow_status:"bounced"}));
print("Suppression: " + db.outreach_bounce_suppression.countDocuments({}));

// Check if there are any OOO / auto-reply type inbound in gmail
var gdb = db.getSiblingDB("torpedo_gmail");
// Just count recent inbound by from_email pattern (non-regex, use indexed field) 
var twoH = new Date(Date.now() - 2*60*60*1000);
var recentIds = gdb.email_metadata.find({mailbox_id:"696b01805cad63fe3d9c4316", synced_at:{$gte:twoH}, direction:"inbound"},{from_email:1,subject:1}).limit(200).toArray();
var bounceCount = 0;
var oooCount = 0;
var replyCount = 0;
recentIds.forEach(m => {
  var from = (m.from_email||"").toLowerCase();
  var subj = (m.subject||"").toLowerCase();
  if (from.includes("mailer-daemon") || from.includes("postmaster") || subj.includes("undeliverable") || subj.includes("delivery") && subj.includes("fail")) {
    bounceCount++;
  } else if (subj.includes("out of office") || subj.includes("automatic reply") || subj.includes("auto-reply") || subj.includes("away from")) {
    oooCount++;
  } else {
    replyCount++;
  }
});
print("\nInbound breakdown (last 2h, first 200):");
print("  Bounces: " + bounceCount);
print("  OOO/Auto-replies: " + oooCount);
print("  Potential real replies: " + replyCount);

// Show potential real replies
recentIds.forEach(m => {
  var from = (m.from_email||"").toLowerCase();
  var subj = (m.subject||"").toLowerCase();
  var isBounce = from.includes("mailer-daemon") || from.includes("postmaster") || subj.includes("undeliverable") || (subj.includes("delivery") && subj.includes("fail"));
  var isOOO = subj.includes("out of office") || subj.includes("automatic reply") || subj.includes("auto-reply") || subj.includes("away from");
  if (!isBounce && !isOOO) {
    print("  REPLY: from=" + m.from_email + " | subj=" + (m.subject||"").substring(0,60));
  }
});
