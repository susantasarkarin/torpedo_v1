db.outreach_campaigns_v2.updateOne(
  {campaign_id: 'a981bdcd-fbd5-497a-8522-e886e9c2f57c', 'steps.step_number': 1},
  {$set: {'steps.$.subject': 'test', 'steps.$.body_html': 'test', 'steps.$.body_text': 'test'}}
);
print('Step 1 saved');
