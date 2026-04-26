var gdb = db.getSiblingDB("torpedo_gmail");

// Check total for indira
var mid = "696b01805cad63fe3d9c4316";
print("Total indira metadata: " + gdb.email_metadata.countDocuments({mailbox_id: mid}));

// Latest 5 regardless of date
print("\nLatest 5 indira emails (by any date field):");
gdb.email_metadata.find({mailbox_id: mid}).sort({_id: -1}).limit(5).forEach(m => {
  printjson({
    from: m.from_email,
    to: m.to_email,
    subject: (m.subject||"").substring(0,50),
    direction: m.direction,
    date: m.date,
    created_at: m.created_at,
    synced_at: m.synced_at,
    received_at: m.received_at,
    gmail_message_id: m.gmail_message_id
  });
});

// Check indexes on email_metadata
print("\n=== Indexes on email_metadata ===");
gdb.email_metadata.getIndexes().forEach(idx => print("  " + idx.name + ": " + JSON.stringify(idx.key)));
