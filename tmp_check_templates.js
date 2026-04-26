// Check if campaigns have step templates
["2a451219-3ce3-43fe-91d3-e1a3155f5363", "00ff5440-2df2-46fc-843b-f3db3cd81e94", "a981bdcd-fbd5-497a-8522-e886e9c2f57c"].forEach(cid => {
  var c = db.outreach_campaigns_v2.findOne({campaign_id: cid}, {campaign_id: 1, name: 1, business: 1, "steps": 1});
  if (c) {
    print("\n=== " + c.name + " (" + c.business + ") ===");
    print("Campaign: " + c.campaign_id);
    if (c.steps) {
      c.steps.forEach((s, i) => {
        var hasContent = s.subject && s.body_html;
        print("  Step " + i + ": subject=" + (s.subject ? "YES" : "NO") + " body=" + (s.body_html ? "YES (" + s.body_html.length + " chars)" : "NO"));
      });
    } else {
      print("  NO STEPS!");
    }
  } else {
    print("Campaign " + cid + " NOT FOUND");
  }
});
