# Database Migrations

MongoDB migration scripts for the Campaign Platform. Handles schema evolution, new collections, and index creation.

## Migration Files

### 001_add_engagement_fields.py
Adds engagement tracking fields to the `leads` collection:
- `engagement_score` - Numeric score for engagement level (0-100)
- `engagement_status` - Status: active, inactive, cold, etc.
- `sequence_stage` - Current stage in outreach sequence
- `last_outreach_date` - Timestamp of last contact
- `outreach_history` - Array of outreach attempts
- `reengagement_eligible` - Boolean flag
- `reengagement_pool_date` - When moved to reengagement
- `timezone` - Lead's timezone
- `linkedin_connection_status` - Connection status
- `linkedin_connection_date` - Date connected
- `linkedin_last_message_date` - Last message timestamp
- `reply_sentiment` - Sentiment of last reply

### 002_add_campaign_fields.py
Adds multi-channel and A/B testing configuration to `campaigns` collection:
- `campaign_type` - Type: email, linkedin, multi_channel
- `personalization_level` - minimal, medium, advanced
- `ab_test_config` - A/B test configuration object
- `reengagement_timeline` - Days and limits for reengagement
- Enhances `sequence_steps` with channel and condition info

### 003_create_linkedin_collections.py
Creates LinkedIn automation tracking collections:
- `linkedin_sessions` - Session tokens and metadata
- `linkedin_connections` - Track connections made
- `linkedin_messages` - Store outreach messages
- `linkedin_activities` - Log all automation activities

### 004_create_deliverability_collections.py
Creates email deliverability tracking collections:
- `domain_health` - Domain reputation metrics
- `gmail_account_usage` - Gmail account limits and usage
- `reputation_metrics` - Reputation scores and trends

### 005_create_indexes.py
Creates performance indexes on all collections:
- Single field indexes for common queries
- Compound indexes for complex queries
- Sorted indexes for efficient sorting

## Usage

### Run All Migrations
```bash
python run_migrations.py
```

### Check Migration Status
```bash
python run_migrations.py --status
```

### Rollback Last Migration
```bash
python run_migrations.py --rollback
```

### Rollback All Migrations
```bash
python rollback_migrations.py --all
```

### Rollback to Specific Migration
```bash
python rollback_migrations.py --to 001
```

### Show Applied Migrations
```bash
python rollback_migrations.py --show
```

## Environment Variables

Required environment variables in `.env`:
```
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=email_automation
```

## Migration Features

### Idempotent
All migrations are safe to run multiple times. They:
- Check for existing fields/collections before creating
- Only update documents missing the fields
- Skip already-applied migrations

### Logged
All migrations:
- Log progress and operations
- Track completion in `migrations_log` collection
- Record timestamps and error messages

### Reversible
Each migration has a `down()` function that:
- Removes added fields with `$unset`
- Drops created collections
- Removes created indexes (except _id)

### Transactional Support
For production use, wrap migration calls in MongoDB transactions:
```python
with client.start_session() as session:
    with session.start_transaction():
        up(db)
```

## Migration Log

The `migrations_log` collection tracks all migrations:
```javascript
{
    "_id": ObjectId(...),
    "migration": "001_add_engagement_fields",
    "status": "success",
    "completed_at": ISODate(...),
    "error": null
}
```

## Best Practices

1. **Always test migrations on a development database first**
2. **Backup production database before running migrations**
3. **Run migrations during low-traffic periods**
4. **Monitor migration progress with logs**
5. **Keep migration files immutable after deployment**
6. **Create new migration files for new changes, never modify existing ones**

## Troubleshooting

### Migration Failed
Check logs for error details:
```bash
# Look for ERROR in logs
python run_migrations.py 2>&1 | grep ERROR
```

### Rollback Failed
Check if migration has down() function and try manual rollback:
```bash
python rollback_migrations.py --to <migration_name>
```

### Duplicate Runs
Migrations track completed status and skip already-applied ones automatically.

## Dependencies

- pymongo >= 3.12
- python-dotenv >= 0.19

Install with:
```bash
pip install pymongo python-dotenv
```
