"""
Email Processor Pipeline
Processes emails from mail_pool → classified_gmail → leads_raw
Implements intelligent classification and enrichment using Gemini
"""

import os
from typing import Dict, List, Optional
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
from .gemini_rotator import get_rotator
from .gemini_enrichment import (
    classify_lead,
    enrich_lead,
    extract_contact_info,
    summarize_email,
    segment_email
)


class EmailProcessor:
    """Process emails through the classification and enrichment pipeline"""
    
    def __init__(self, mongo_uri: str = None):
        """Initialize processor with MongoDB connection"""
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        
        self.client = MongoClient(mongo_uri)
        self.email_db = self.client["email_automation"]
        self.leads_db = self.client["email_automation"]
        
        # Collections
        self.mail_pool = self.email_db["mail_pool"]
        self.classified_gmail = self.email_db["classified_gmail"]
        self.leads_raw = self.leads_db["leads_raw"]
        self.vendor_leads = self.leads_db["vendor_leads"]
        
        # Get Gemini rotator
        self.rotator = get_rotator()
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create necessary indexes"""
        # classified_gmail indexes
        self.classified_gmail.create_index([("email_id", 1)], unique=True)
        self.classified_gmail.create_index([("segment", 1)])
        self.classified_gmail.create_index([("processed_at", -1)])
        self.classified_gmail.create_index([("moved_to_leads", 1)])
        self.classified_gmail.create_index([("priority", 1)])
        
        # leads_raw indexes
        self.leads_raw.create_index([("email", 1)])
        self.leads_raw.create_index([("source", 1)])
        self.leads_raw.create_index([("category", 1)])
        self.leads_raw.create_index([("created_at", -1)])
    
    def process_email(self, email_doc: dict) -> dict:
        """
        Process a single email through the classification pipeline
        
        Args:
            email_doc: Email document from mail_pool
            
        Returns:
            Classified email document for classified_gmail collection
        """
        email_id = email_doc.get("_id")
        sender_email = email_doc.get("sender", {}).get("email", "")
        subject = email_doc.get("subject", "")
        body = email_doc.get("body", "")
        
        # Step 1: Quick segmentation
        segment_result = segment_email(
            subject=subject,
            body=body,
            sender_email=sender_email,
            rotator=self.rotator
        )
        
        # Step 2: Extract contact info if not spam
        contacts_info = {}
        if segment_result["segment"] != "SPAM":
            contacts_info = extract_contact_info(
                email_body=body,
                rotator=self.rotator
            )
        
        # Step 3: Summarize email
        summary = summarize_email(
            email_body=body,
            subject=subject,
            rotator=self.rotator
        )
        
        # Build classified email document
        classified_doc = {
            "email_id": str(email_id),
            "original_email": email_doc,
            "segment": segment_result["segment"],
            "confidence": segment_result["confidence"],
            "reasoning": segment_result["reasoning"],
            "summary": summary["summary"],
            "key_points": summary["key_points"],
            "action_items": summary["action_items"],
            "sentiment": summary["sentiment"],
            "urgency": summary["urgency"],
            "contains_offer": summary["contains_offer"],
            "next_steps": summary["next_steps"],
            "contacts": contacts_info.get("contacts", []),
            "primary_contact": contacts_info.get("primary_contact"),
            "processed_at": datetime.now(),
            "moved_to_leads": False,
            "moved_to_vendor_leads": False,
            "priority": self._calculate_priority(segment_result, summary),
            "metadata": {
                "sender_email": sender_email,
                "subject": subject,
                "received_date": email_doc.get("date"),
                "has_attachments": len(email_doc.get("attachments", [])) > 0
            }
        }
        
        return classified_doc
    
    def _calculate_priority(self, segment_result: dict, summary: dict) -> str:
        """Calculate priority based on segment and summary"""
        segment = segment_result["segment"]
        urgency = summary["urgency"]
        contains_offer = summary["contains_offer"]
        confidence = segment_result["confidence"]
        
        # High priority: client with high urgency or offer
        if segment == "CLIENT":
            if urgency == "HIGH" or contains_offer:
                return "HIGH"
            if confidence > 0.8:
                return "MEDIUM"
            return "LOW"
        
        # Medium priority: vendors, recruiters
        if segment in ["VENDOR", "RECRUITER"]:
            if urgency == "HIGH":
                return "MEDIUM"
            return "LOW"
        
        # Low priority: internal, spam
        return "LOW"
    
    def process_batch(self, limit: int = 100, skip_processed: bool = True) -> dict:
        """
        Process a batch of emails from mail_pool
        
        Args:
            limit: Maximum number of emails to process
            skip_processed: Skip emails already in classified_gmail
            
        Returns:
            Statistics about processed emails
        """
        # Get unprocessed emails
        query = {}
        if skip_processed:
            # Get IDs already processed
            processed_ids = set(
                self.classified_gmail.distinct("email_id")
            )
            if processed_ids:
                query["_id"] = {"$nin": [ObjectId(eid) for eid in processed_ids if ObjectId.is_valid(eid)]}
        
        emails = list(self.mail_pool.find(query).limit(limit))
        
        stats = {
            "total_processed": 0,
            "by_segment": {},
            "errors": [],
            "started_at": datetime.now()
        }
        
        for email_doc in emails:
            try:
                classified_doc = self.process_email(email_doc)
                
                # Insert into classified_gmail
                self.classified_gmail.insert_one(classified_doc)
                
                # Update stats
                stats["total_processed"] += 1
                segment = classified_doc["segment"]
                stats["by_segment"][segment] = stats["by_segment"].get(segment, 0) + 1
                
            except Exception as e:
                stats["errors"].append({
                    "email_id": str(email_doc.get("_id")),
                    "error": str(e)
                })
        
        stats["completed_at"] = datetime.now()
        stats["duration_seconds"] = (stats["completed_at"] - stats["started_at"]).total_seconds()
        
        return stats
    
    def move_to_leads(self, classified_email_id: str, additional_enrichment: dict = None) -> dict:
        """
        Move a classified email to leads_raw with full enrichment
        
        Args:
            classified_email_id: ID of document in classified_gmail
            additional_enrichment: Optional additional data to include
            
        Returns:
            Created lead document
        """
        # Get classified email
        classified = self.classified_gmail.find_one({"_id": ObjectId(classified_email_id)})
        if not classified:
            raise ValueError(f"Classified email {classified_email_id} not found")
        
        # Extract lead data from classified email
        primary_contact = classified.get("primary_contact", {})
        original_email = classified.get("original_email", {})
        
        # Build lead document
        lead_data = {
            "email": primary_contact.get("email") or classified["metadata"]["sender_email"],
            "full_name": primary_contact.get("name", ""),
            "title": primary_contact.get("title", ""),
            "company": primary_contact.get("company", ""),
            "phone": primary_contact.get("phone", ""),
            "source": "classified_gmail",
            "source_email_id": classified["email_id"],
            "category": classified["segment"],
            "priority": classified["priority"],
            "confidence": classified["confidence"],
            "summary": classified["summary"],
            "key_points": classified["key_points"],
            "action_items": classified["action_items"],
            "sentiment": classified["sentiment"],
            "urgency": classified["urgency"],
            "created_at": datetime.now(),
            "metadata": {
                "original_subject": classified["metadata"]["subject"],
                "original_sender": classified["metadata"]["sender_email"],
                "processed_at": classified["processed_at"],
                "next_steps": classified["next_steps"]
            }
        }
        
        # Add additional enrichment if provided
        if additional_enrichment:
            lead_data.update(additional_enrichment)
        
        # Perform full classification and enrichment
        if lead_data["email"]:
            classification = classify_lead(lead_data, self.rotator)
            lead_data["gemini_classification"] = classification
            
            enrichment = enrich_lead(lead_data, self.rotator)
            lead_data["gemini_enrichment"] = enrichment
        
        # Insert into leads_raw
        result = self.leads_raw.insert_one(lead_data)
        lead_data["_id"] = result.inserted_id
        
        # Mark as moved in classified_gmail
        self.classified_gmail.update_one(
            {"_id": ObjectId(classified_email_id)},
            {
                "$set": {
                    "moved_to_leads": True,
                    "moved_to_leads_at": datetime.now(),
                    "lead_id": str(result.inserted_id)
                }
            }
        )
        
        return lead_data
    
    def move_to_vendor_leads(self, classified_email_id: str) -> dict:
        """
        Move a classified email to vendor_leads collection
        
        Args:
            classified_email_id: ID of document in classified_gmail
            
        Returns:
            Created vendor lead document
        """
        # Get classified email
        classified = self.classified_gmail.find_one({"_id": ObjectId(classified_email_id)})
        if not classified:
            raise ValueError(f"Classified email {classified_email_id} not found")
        
        # Build vendor lead document
        primary_contact = classified.get("primary_contact", {})
        
        vendor_lead = {
            "email": primary_contact.get("email") or classified["metadata"]["sender_email"],
            "full_name": primary_contact.get("name", ""),
            "title": primary_contact.get("title", ""),
            "company": primary_contact.get("company", ""),
            "phone": primary_contact.get("phone", ""),
            "service_offered": classified["summary"],
            "contacts": classified.get("contacts", []),
            "source": "classified_gmail",
            "source_email_id": classified["email_id"],
            "created_at": datetime.now(),
            "metadata": {
                "original_subject": classified["metadata"]["subject"],
                "sentiment": classified["sentiment"],
                "urgency": classified["urgency"]
            }
        }
        
        # Insert into vendor_leads
        result = self.vendor_leads.insert_one(vendor_lead)
        vendor_lead["_id"] = result.inserted_id
        
        # Mark as moved in classified_gmail
        self.classified_gmail.update_one(
            {"_id": ObjectId(classified_email_id)},
            {
                "$set": {
                    "moved_to_vendor_leads": True,
                    "moved_to_vendor_leads_at": datetime.now(),
                    "vendor_lead_id": str(result.inserted_id)
                }
            }
        )
        
        return vendor_lead
    
    def get_classified_summary(self) -> dict:
        """Get summary statistics of classified emails"""
        pipeline = [
            {
                "$group": {
                    "_id": "$segment",
                    "count": {"$sum": 1},
                    "high_priority": {
                        "$sum": {"$cond": [{"$eq": ["$priority", "HIGH"]}, 1, 0]}
                    },
                    "moved_to_leads": {
                        "$sum": {"$cond": ["$moved_to_leads", 1, 0]}
                    }
                }
            }
        ]
        
        results = list(self.classified_gmail.aggregate(pipeline))
        
        summary = {
            "by_segment": {},
            "total_classified": 0,
            "total_moved_to_leads": 0,
            "total_high_priority": 0
        }
        
        for result in results:
            segment = result["_id"]
            summary["by_segment"][segment] = {
                "count": result["count"],
                "high_priority": result["high_priority"],
                "moved_to_leads": result["moved_to_leads"]
            }
            summary["total_classified"] += result["count"]
            summary["total_moved_to_leads"] += result["moved_to_leads"]
            summary["total_high_priority"] += result["high_priority"]
        
        return summary


if __name__ == "__main__":
    # Test the email processor
    print("=== Email Processor Test ===\n")
    
    try:
        processor = EmailProcessor()
        
        # Get summary
        print("1. Current classified_gmail summary:")
        summary = processor.get_classified_summary()
        print(f"   Total classified: {summary['total_classified']}")
        print(f"   High priority: {summary['total_high_priority']}")
        print(f"   Moved to leads: {summary['total_moved_to_leads']}")
        print(f"   By segment: {summary['by_segment']}\n")
        
        # Process a batch
        print("2. Processing batch of emails from mail_pool:")
        stats = processor.process_batch(limit=10)
        print(f"   Processed: {stats['total_processed']} emails")
        print(f"   Duration: {stats['duration_seconds']:.2f} seconds")
        print(f"   By segment: {stats['by_segment']}")
        if stats['errors']:
            print(f"   Errors: {len(stats['errors'])}")
        print()
        
        print("✅ Email processor test completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
