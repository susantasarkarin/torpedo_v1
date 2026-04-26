db.outreach_leads_v2.find(
  {campaign_id: "00ff5440-2df2-46fc-843b-f3db3cd81e94"},
  {email:1, workflow_status:1, last_send_error:1}
).forEach(doc => printjson(doc));
