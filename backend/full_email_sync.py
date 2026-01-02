#!/usr/bin/env python3
"""
FULL EMAIL SYNC SCRIPT
======================

This script performs a complete email sync for an IMAP account,
pulling ALL emails (not limited by date) into the email_automation.emails collection.

Usage:
    python full_email_sync.py [email_address] [--batch-size=50] [--limit=0]
    
    --batch-size: Number of emails to fetch per batch (default: 50)
    --limit: Maximum emails to sync (0 = unlimited, default: 0)
    
Example:
    python full_email_sync.py susanta@surveyfieldwork.com --limit=1000
"""

import os
import sys
import imaplib
import email
import argparse
import logging
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')


def decode_email_header(header_value) -> str:
    """Decode email header to string"""
    if header_value is None:
        return ""
    try:
        decoded_parts = decode_header(header_value)
        result = ""
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                result += content.decode(charset or 'utf-8', errors='ignore')
            else:
                result += str(content)
        return result
    except:
        return str(header_value)


def get_email_body(msg) -> Tuple[str, str]:
    """Extract plain text and HTML body from email message"""
    body_plain = ""
    body_html = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    decoded = payload.decode(charset, errors='ignore')
                    if content_type == "text/plain" and not body_plain:
                        body_plain = decoded
                    elif content_type == "text/html" and not body_html:
                        body_html = decoded
            except:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            content = payload.decode(charset, errors='ignore') if payload else ""
            if msg.get_content_type() == "text/html":
                body_html = content
            else:
                body_plain = content
        except:
            body_plain = str(msg.get_payload())
    
    return body_plain.strip(), body_html.strip()


def parse_email_address(addr_str: str) -> Dict[str, str]:
    """Parse email address into name and email dict"""
    name, email_addr = parseaddr(decode_email_header(addr_str))
    return {"name": name, "email": email_addr.lower() if email_addr else ""}


def parse_address_list(addr_str: str) -> List[Dict[str, str]]:
    """Parse comma-separated email addresses"""
    if not addr_str:
        return []
    addresses = []
    for part in addr_str.split(","):
        parsed = parse_email_address(part.strip())
        if parsed["email"]:
            addresses.append(parsed)
    return addresses


def classify_email_category(subject: str, body: str) -> str:
    """Simple rule-based email categorization"""
    content = f"{subject} {body}".lower()
    
    categories = {
        "rfq_pricing": ["rfq", "request for quote", "quotation", "pricing", "quote", "cost", "estimate", "budget", "price"],
        "invoice": ["invoice", "payment", "due", "billing", "receipt", "outstanding", "overdue"],
        "promotional": ["newsletter", "unsubscribe", "marketing", "promotion", "discount", "offer", "sale"],
        "outreach": ["reaching out", "connect", "introduce", "partnership", "collaboration", "opportunity"],
        "discovery": ["demo", "learn more", "exploring", "considering", "evaluate", "discovery call"],
        "banking": ["bank", "account", "transfer", "wire", "transaction", "statement"],
        "negotiation": ["negotiate", "terms", "contract", "agreement", "final offer", "deal"],
    }
    
    for category, keywords in categories.items():
        if any(kw in content for kw in keywords):
            return category
    
    return "uncategorized"


def full_sync_account(
    email_address: str,
    batch_size: int = 50,
    limit: int = 0
) -> Dict[str, Any]:
    """
    Perform full email sync for an account.
    
    Args:
        email_address: Email address to sync
        batch_size: Number of emails per batch
        limit: Max emails (0 = unlimited)
        
    Returns:
        Sync statistics
    """
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    
    # Get IMAP account
    gmail_db = client["torpedo_gmail"]
    account = gmail_db["imap_accounts"].find_one({"email": email_address})
    
    if not account:
        logger.error(f"Account {email_address} not found")
        return {"success": False, "error": "Account not found"}
    
    # Get or create mailbox in email_automation
    email_automation_db = client["email_automation"]
    emails_collection = email_automation_db["emails"]
    mailboxes_collection = email_automation_db["mailboxes"]
    
    mailbox = mailboxes_collection.find_one({"email": email_address})
    if not mailbox:
        mailbox_id = mailboxes_collection.insert_one({
            "email": email_address,
            "display_name": account.get("display_name", ""),
            "provider": "imap",
            "sync_enabled": True,
            "is_active": True,
            "created_at": datetime.utcnow()
        }).inserted_id
    else:
        mailbox_id = mailbox["_id"]
    
    mailbox_id_str = str(mailbox_id)
    
    # Connect to IMAP
    try:
        imap = imaplib.IMAP4_SSL(
            account.get('imap_server', 'imap.gmail.com'),
            account.get('imap_port', 993)
        )
        imap.login(account['email'], account['password'])
        logger.info(f"Connected to IMAP for {email_address}")
    except Exception as e:
        logger.error(f"IMAP connection failed: {e}")
        return {"success": False, "error": str(e)}
    
    stats = {
        "total_fetched": 0,
        "total_inserted": 0,
        "total_updated": 0,
        "total_skipped": 0,
        "errors": 0,
        "folders_processed": []
    }
    
    # Folders to sync
    folders_to_sync = [
        ("INBOX", "inbound"),
        ("[Gmail]/Sent Mail", "outbound"),
        ("Sent", "outbound"),
        ("Sent Items", "outbound"),
    ]
    
    for folder_name, direction in folders_to_sync:
        try:
            status, data = imap.select(folder_name)
            if status != "OK":
                continue
                
            folder_count = int(data[0].decode())
            logger.info(f"Processing {folder_name}: {folder_count} messages")
            stats["folders_processed"].append({"folder": folder_name, "count": folder_count})
            
            # Get all UIDs
            status, data = imap.uid("search", None, "ALL")
            if status != "OK":
                continue
            
            all_uids = data[0].split()
            total_uids = len(all_uids)
            logger.info(f"Found {total_uids} UIDs in {folder_name}")
            
            # Process in batches
            processed_in_folder = 0
            for i in range(0, total_uids, batch_size):
                if limit > 0 and stats["total_fetched"] >= limit:
                    logger.info(f"Reached limit of {limit} emails")
                    break
                
                batch_uids = all_uids[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total_uids + batch_size - 1) // batch_size
                
                logger.info(f"  Batch {batch_num}/{total_batches} ({len(batch_uids)} emails)")
                
                for uid in batch_uids:
                    if limit > 0 and stats["total_fetched"] >= limit:
                        break
                    
                    try:
                        uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                        
                        # Fetch email
                        status, msg_data = imap.uid("fetch", uid_str, "(RFC822)")
                        if status != "OK" or not msg_data or not msg_data[0]:
                            stats["errors"] += 1
                            continue
                        
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        
                        # Parse message
                        message_id = msg.get("Message-ID", f"{email_address}_{folder_name}_{uid_str}")
                        subject = decode_email_header(msg.get("Subject", ""))
                        from_addr = parse_email_address(msg.get("From", ""))
                        to_addrs = parse_address_list(msg.get("To", ""))
                        cc_addrs = parse_address_list(msg.get("Cc", ""))
                        bcc_addrs = parse_address_list(msg.get("Bcc", ""))
                        
                        # Parse date
                        date_str = msg.get("Date", "")
                        try:
                            timestamp = parsedate_to_datetime(date_str)
                        except:
                            timestamp = datetime.utcnow()
                        
                        # Get body
                        body_plain, body_html = get_email_body(msg)
                        
                        # Classify
                        category = classify_email_category(subject, body_plain or body_html)
                        
                        # Check for attachments
                        attachments = []
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_disposition() == "attachment":
                                    filename = part.get_filename()
                                    if filename:
                                        attachments.append({
                                            "filename": decode_email_header(filename),
                                            "content_type": part.get_content_type(),
                                            "size": len(part.get_payload(decode=True) or b"")
                                        })
                        
                        # Create document
                        doc = {
                            "mailbox_id": mailbox_id_str,
                            "provider_message_id": message_id,
                            "provider_thread_id": msg.get("References", "").split()[0] if msg.get("References") else None,
                            "subject": subject,
                            "from_address": from_addr,
                            "to_addresses": to_addrs,
                            "cc_addresses": cc_addrs,
                            "bcc_addresses": bcc_addrs,
                            "body_plain": body_plain[:50000],  # Limit body size
                            "body_html": body_html[:50000],
                            "snippet": (body_plain or body_html)[:300],
                            "timestamp": timestamp,
                            "direction": direction,
                            "category": category,
                            "category_confidence": 0.8,
                            "category_model_version": "rule-based-v1",
                            "categorized_at": datetime.utcnow(),
                            "labels": [folder_name],
                            "has_attachments": len(attachments) > 0,
                            "attachment_count": len(attachments),
                            "attachments": attachments,
                            "delivered_to": email_address,
                            "sync_source": "full_sync",
                            "synced_at": datetime.utcnow(),
                            "processed": True,
                            "raw_headers": {
                                "In-Reply-To": msg.get("In-Reply-To", ""),
                                "References": msg.get("References", ""),
                                "Reply-To": msg.get("Reply-To", "")
                            }
                        }
                        
                        # Upsert to avoid duplicates
                        result = emails_collection.update_one(
                            {
                                "mailbox_id": mailbox_id_str,
                                "provider_message_id": message_id
                            },
                            {"$set": doc},
                            upsert=True
                        )
                        
                        stats["total_fetched"] += 1
                        if result.upserted_id:
                            stats["total_inserted"] += 1
                        elif result.modified_count > 0:
                            stats["total_updated"] += 1
                        else:
                            stats["total_skipped"] += 1
                        
                        processed_in_folder += 1
                        
                    except Exception as e:
                        stats["errors"] += 1
                        if stats["errors"] < 10:
                            logger.warning(f"Error processing email: {e}")
                
                # Progress update
                if batch_num % 10 == 0:
                    logger.info(f"  Progress: {stats['total_fetched']} fetched, {stats['total_inserted']} inserted")
            
            logger.info(f"Completed {folder_name}: {processed_in_folder} emails processed")
            
        except Exception as e:
            logger.warning(f"Could not process folder {folder_name}: {e}")
            continue
    
    # Cleanup
    try:
        imap.logout()
    except:
        pass
    
    # Update account sync time
    gmail_db["imap_accounts"].update_one(
        {"email": email_address},
        {"$set": {"last_sync": datetime.utcnow(), "initial_sync_completed": True}}
    )
    
    stats["success"] = True
    logger.info(f"\n=== SYNC COMPLETE ===")
    logger.info(f"Total fetched: {stats['total_fetched']}")
    logger.info(f"Total inserted: {stats['total_inserted']}")
    logger.info(f"Total updated: {stats['total_updated']}")
    logger.info(f"Total skipped: {stats['total_skipped']}")
    logger.info(f"Errors: {stats['errors']}")
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Full Email Sync")
    parser.add_argument("email", nargs="?", help="Email address to sync")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size (default: 50)")
    parser.add_argument("--limit", type=int, default=0, help="Max emails (0=unlimited)")
    parser.add_argument("--list", action="store_true", help="List available accounts")
    
    args = parser.parse_args()
    
    if args.list:
        client = MongoClient(MONGO_URI)
        accounts = client["torpedo_gmail"]["imap_accounts"].find({"is_active": True})
        print("\nAvailable accounts:")
        for acc in accounts:
            print(f"  - {acc['email']}")
        return
    
    if not args.email:
        parser.print_help()
        return
    
    result = full_sync_account(
        email_address=args.email,
        batch_size=args.batch_size,
        limit=args.limit
    )
    
    if result.get("success"):
        print(f"\nSync successful! {result['total_inserted']} new emails imported.")
    else:
        print(f"\nSync failed: {result.get('error')}")


if __name__ == "__main__":
    main()
