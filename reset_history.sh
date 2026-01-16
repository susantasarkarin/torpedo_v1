mongosh torpedo_gmail --quiet --eval 'db.workspace_mailboxes.updateOne({email: "info@surveyfieldwork.com"}, {$unset: {last_history_id: 1}})'
