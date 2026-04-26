"""One-time bulk segregation of all pending emails using rule-based engine."""
import sys, time
sys.path.insert(0, "/var/www/campaign_platform/backend")

from agents.mail_segregation_agent import get_mail_segregation_agent, SegmentationStrategy

agent = get_mail_segregation_agent()

BATCH = 2000
offset = 0
total_processed = 0
total_failed = 0
start = time.time()

while True:
    result = agent.segregate_all_emails(
        strategy=SegmentationStrategy.CATEGORY,
        batch_size=BATCH,
        force_rescan=False
    )
    processed = result.get("processed", 0)
    failed = result.get("failed", 0)
    total_processed += processed
    total_failed += failed
    elapsed = time.time() - start
    rate = total_processed / elapsed if elapsed > 0 else 0
    print(f"[{elapsed:.0f}s] Batch done: +{processed} processed, +{failed} failed | Total: {total_processed} processed, {total_failed} failed | Rate: {rate:.0f}/s")

    if processed == 0:
        print("No more pending emails. Done!")
        break

print(f"\nFinal: {total_processed} processed, {total_failed} failed in {time.time()-start:.0f}s")
