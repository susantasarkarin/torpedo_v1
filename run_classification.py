from leads.email_classifier import classify_all_pending_emails

def main():
    # batch_size=50, no max_batches = process ALL emails
    result = classify_all_pending_emails(batch_size=50)
    print(result)

if __name__ == "__main__":
    main()
