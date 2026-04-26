print("Suppression list: " + db.outreach_bounce_suppression.countDocuments({}));
print("Distinct send statuses: " + JSON.stringify(db.outreach_sends_v2.distinct("status")));
print("Collections: " + db.getCollectionNames().filter(c => /outreach|bounce|track/i.test(c)).join(", "));

// Check if open pixel is injected in sent emails
var sample = db.outreach_sends_v2.findOne({}, {body_html: 1, subject: 1, email: 1});
if (sample) {
  var hasPixel = sample.body_html && sample.body_html.includes("track");
  print("Sample sent email has tracking pixel: " + hasPixel);
  if (sample.body_html) {
    var match = sample.body_html.match(/img[^>]*src="([^"]*track[^"]*)"/i);
    if (match) print("Pixel URL: " + match[1]);
  }
}

// Check outreach log for any bounce/error in last sends
print("\nRecent send errors:");
db.outreach_sends_v2.find({status: {$ne: "sent"}}).limit(5).forEach(d => {
  print("  " + d.email + " | " + d.status + " | " + (d.error || ""));
});
print("(found " + db.outreach_sends_v2.countDocuments({status: {$ne: "sent"}}) + " non-sent records)");
