print("00ff5440 not_started: " + db.outreach_leads_v2.countDocuments({campaign_id:"00ff5440-2df2-46fc-843b-f3db3cd81e94", workflow_status:"not_started"}));
print("00ff5440 error: " + db.outreach_leads_v2.countDocuments({campaign_id:"00ff5440-2df2-46fc-843b-f3db3cd81e94", workflow_status:"error"}));
print("00ff5440 total: " + db.outreach_leads_v2.countDocuments({campaign_id:"00ff5440-2df2-46fc-843b-f3db3cd81e94"}));
print("SFW not_started: " + db.outreach_leads_v2.countDocuments({campaign_id:"2a451219-3ce3-43fe-91d3-e1a3155f5363", workflow_status:"not_started"}));
print("Cogentix not_started: " + db.outreach_leads_v2.countDocuments({campaign_id:"a981bdcd-fbd5-497a-8522-e886e9c2f57c", workflow_status:"not_started"}));
