// Clean up test email_metadata from torpedo_gmail
db = db.getSiblingDB('torpedo_gmail');
var delMeta = db.email_metadata.deleteMany({ direction: 'sent' });
print('Deleted email_metadata sent records: ' + delMeta.deletedCount);
