"""
Email Categorization Module

Categorizes emails based on predefined rules, keywords, and sender patterns.
Supports custom categorization rules and priority scoring.

Usage:
    from gmail_automation.categorizer import EmailCategorizer
    
    categorizer = EmailCategorizer()
    categorizer.add_rule("urgent", keywords=["urgent", "asap", "immediately"])
    category = categorizer.categorize(email)
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Set
from enum import Enum
from datetime import datetime

from .email_fetcher import Email

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CategoryPriority(Enum):
    """Email category priority levels."""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    NONE = 5


@dataclass
class Category:
    """
    Represents an email category.
    
    Attributes:
        name: Category identifier
        display_name: Human-readable name
        description: Category description
        priority: Priority level
        color: Optional color code for UI
        auto_label: Gmail label to apply
        auto_reply: Whether to auto-reply
    """
    name: str
    display_name: str = ""
    description: str = ""
    priority: CategoryPriority = CategoryPriority.MEDIUM
    color: str = "#808080"
    auto_label: Optional[str] = None
    auto_reply: bool = False
    
    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()


@dataclass
class CategorizationRule:
    """
    Defines a rule for categorizing emails.
    
    Attributes:
        name: Rule identifier
        category: Target category
        keywords: Keywords to match in subject/body
        sender_patterns: Sender email patterns to match
        subject_patterns: Subject line patterns
        label_filters: Gmail labels to filter by
        condition: Custom condition function
        score_weight: Weight for priority scoring
        case_sensitive: Whether matching is case-sensitive
    """
    name: str
    category: str
    keywords: List[str] = field(default_factory=list)
    sender_patterns: List[str] = field(default_factory=list)
    subject_patterns: List[str] = field(default_factory=list)
    body_patterns: List[str] = field(default_factory=list)
    label_filters: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    condition: Optional[Callable[[Email], bool]] = None
    score_weight: float = 1.0
    case_sensitive: bool = False
    priority: CategoryPriority = CategoryPriority.MEDIUM
    
    def matches(self, email: Email) -> tuple[bool, float]:
        """
        Check if this rule matches an email.
        
        Args:
            email: Email to check
            
        Returns:
            Tuple of (matches, confidence_score)
        """
        score = 0.0
        matched = False
        
        # Prepare text for matching
        subject = email.subject if self.case_sensitive else email.subject.lower()
        body = email.get_plain_body()
        body = body if self.case_sensitive else body.lower()
        sender = email.sender if self.case_sensitive else email.sender.lower()
        full_text = f"{subject} {body}"
        
        # Check exclusions first
        for exclude_kw in self.exclude_keywords:
            pattern = exclude_kw if self.case_sensitive else exclude_kw.lower()
            if pattern in full_text:
                return False, 0.0
        
        # Check keywords
        for keyword in self.keywords:
            pattern = keyword if self.case_sensitive else keyword.lower()
            if pattern in full_text:
                matched = True
                score += 0.3
        
        # Check sender patterns
        for pattern in self.sender_patterns:
            regex_pattern = pattern if self.case_sensitive else pattern.lower()
            if re.search(regex_pattern, sender):
                matched = True
                score += 0.4
        
        # Check subject patterns
        for pattern in self.subject_patterns:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            if re.search(pattern, email.subject, flags):
                matched = True
                score += 0.35
        
        # Check body patterns
        for pattern in self.body_patterns:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            if re.search(pattern, body, flags):
                matched = True
                score += 0.25
        
        # Check labels
        for label in self.label_filters:
            if label in email.labels:
                matched = True
                score += 0.2
        
        # Check custom condition
        if self.condition:
            try:
                if self.condition(email):
                    matched = True
                    score += 0.5
            except Exception as e:
                logger.warning(f"Rule condition failed for {self.name}: {e}")
        
        # Apply weight
        final_score = min(score * self.score_weight, 1.0)
        
        return matched, final_score


@dataclass
class CategorizationResult:
    """
    Result of email categorization.
    
    Attributes:
        email_id: Email message ID
        primary_category: Main category assigned
        all_categories: All matching categories with scores
        confidence: Confidence score for primary category
        matched_rules: List of rules that matched
        priority: Overall priority level
        suggested_actions: Suggested actions based on category
    """
    email_id: str
    primary_category: str
    all_categories: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    matched_rules: List[str] = field(default_factory=list)
    priority: CategoryPriority = CategoryPriority.MEDIUM
    suggested_actions: List[str] = field(default_factory=list)
    categorized_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'email_id': self.email_id,
            'primary_category': self.primary_category,
            'all_categories': self.all_categories,
            'confidence': self.confidence,
            'matched_rules': self.matched_rules,
            'priority': self.priority.name,
            'suggested_actions': self.suggested_actions,
            'categorized_at': self.categorized_at.isoformat()
        }


class EmailCategorizer:
    """
    Categorizes emails based on configurable rules.
    
    Supports keyword matching, sender patterns, regex patterns,
    and custom condition functions.
    """
    
    # Predefined categories
    DEFAULT_CATEGORIES = {
        'urgent': Category(
            name='urgent',
            display_name='Urgent',
            description='Time-sensitive emails requiring immediate attention',
            priority=CategoryPriority.CRITICAL,
            color='#FF0000'
        ),
        'important': Category(
            name='important',
            display_name='Important',
            description='Important emails from key contacts',
            priority=CategoryPriority.HIGH,
            color='#FF6600'
        ),
        'newsletter': Category(
            name='newsletter',
            display_name='Newsletter',
            description='Subscription newsletters and updates',
            priority=CategoryPriority.LOW,
            color='#00AA00'
        ),
        'promotional': Category(
            name='promotional',
            display_name='Promotional',
            description='Marketing and promotional emails',
            priority=CategoryPriority.LOW,
            color='#9933FF'
        ),
        'social': Category(
            name='social',
            display_name='Social',
            description='Social media notifications',
            priority=CategoryPriority.LOW,
            color='#3399FF'
        ),
        'transactional': Category(
            name='transactional',
            display_name='Transactional',
            description='Receipts, invoices, and order confirmations',
            priority=CategoryPriority.MEDIUM,
            color='#666666'
        ),
        'support': Category(
            name='support',
            display_name='Support',
            description='Customer support and help requests',
            priority=CategoryPriority.HIGH,
            color='#FF9900'
        ),
        'work': Category(
            name='work',
            display_name='Work',
            description='Work-related emails',
            priority=CategoryPriority.HIGH,
            color='#0066CC'
        ),
        'personal': Category(
            name='personal',
            display_name='Personal',
            description='Personal correspondence',
            priority=CategoryPriority.MEDIUM,
            color='#00CC99'
        ),
        'uncategorized': Category(
            name='uncategorized',
            display_name='Uncategorized',
            description='Emails that do not match any rules',
            priority=CategoryPriority.NONE,
            color='#CCCCCC'
        )
    }
    
    def __init__(self, use_default_rules: bool = True):
        """
        Initialize the Email Categorizer.
        
        Args:
            use_default_rules: Whether to load default categorization rules
        """
        self.categories: Dict[str, Category] = dict(self.DEFAULT_CATEGORIES)
        self.rules: List[CategorizationRule] = []
        self.vip_senders: Set[str] = set()
        self.blocked_senders: Set[str] = set()
        
        if use_default_rules:
            self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """Load default categorization rules."""
        
        # Urgent keywords
        self.add_rule(CategorizationRule(
            name='urgent_keywords',
            category='urgent',
            keywords=['urgent', 'asap', 'immediately', 'time-sensitive', 
                     'deadline', 'action required', 'respond now'],
            subject_patterns=[r'^\[?URGENT\]?', r'ASAP'],
            priority=CategoryPriority.CRITICAL,
            score_weight=1.5
        ))
        
        # Newsletter patterns
        self.add_rule(CategorizationRule(
            name='newsletter',
            category='newsletter',
            keywords=['newsletter', 'weekly digest', 'monthly update', 
                     'subscribe', 'unsubscribe'],
            sender_patterns=[r'newsletter@', r'news@', r'digest@', 
                           r'updates@', r'noreply@'],
            subject_patterns=[r'newsletter', r'weekly\s+(digest|update)',
                            r'monthly\s+(digest|update)'],
            priority=CategoryPriority.LOW
        ))
        
        # Promotional emails
        self.add_rule(CategorizationRule(
            name='promotional',
            category='promotional',
            keywords=['sale', 'discount', 'offer', 'promotion', 'deal',
                     'limited time', 'free shipping', 'coupon', 'promo code',
                     '% off', 'save now', 'shop now', 'buy now'],
            sender_patterns=[r'promo@', r'marketing@', r'offers@', r'deals@'],
            priority=CategoryPriority.LOW
        ))
        
        # Social media
        self.add_rule(CategorizationRule(
            name='social',
            category='social',
            sender_patterns=[
                r'@(facebook|facebookmail)\.com$',
                r'@twitter\.com$',
                r'@linkedin\.com$',
                r'@instagram\.com$',
                r'@tiktok\.com$',
                r'@pinterest\.com$'
            ],
            keywords=['followed you', 'mentioned you', 'liked your',
                     'commented on', 'new follower', 'connection request'],
            priority=CategoryPriority.LOW
        ))
        
        # Transactional emails
        self.add_rule(CategorizationRule(
            name='transactional',
            category='transactional',
            keywords=['receipt', 'invoice', 'order confirmation', 
                     'payment received', 'shipping confirmation',
                     'delivery update', 'your order', 'order #'],
            subject_patterns=[r'order\s*#?\d+', r'invoice\s*#?\d+',
                            r'receipt\s+(for|from)', r'payment\s+confirmation'],
            priority=CategoryPriority.MEDIUM
        ))
        
        # Support emails
        self.add_rule(CategorizationRule(
            name='support',
            category='support',
            keywords=['support ticket', 'help request', 'case #',
                     'ticket #', 'issue reported', 'bug report'],
            sender_patterns=[r'support@', r'help@', r'helpdesk@',
                           r'customer.service@', r'customercare@'],
            subject_patterns=[r'(ticket|case)\s*#?\d+', r'\[.*support\]'],
            priority=CategoryPriority.HIGH
        ))
    
    def add_category(self, category: Category) -> None:
        """
        Add a custom category.
        
        Args:
            category: Category to add
        """
        self.categories[category.name] = category
        logger.info(f"Added category: {category.name}")
    
    def add_rule(self, rule: CategorizationRule) -> None:
        """
        Add a categorization rule.
        
        Args:
            rule: Rule to add
        """
        # Validate category exists
        if rule.category not in self.categories:
            logger.warning(f"Creating category '{rule.category}' for rule '{rule.name}'")
            self.categories[rule.category] = Category(name=rule.category)
        
        self.rules.append(rule)
        logger.debug(f"Added rule: {rule.name} -> {rule.category}")
    
    def add_simple_rule(
        self,
        category: str,
        keywords: Optional[List[str]] = None,
        sender_patterns: Optional[List[str]] = None,
        subject_patterns: Optional[List[str]] = None,
        priority: CategoryPriority = CategoryPriority.MEDIUM
    ) -> None:
        """
        Add a simple categorization rule.
        
        Args:
            category: Target category name
            keywords: Keywords to match
            sender_patterns: Sender patterns to match
            subject_patterns: Subject patterns to match
            priority: Rule priority
        """
        rule = CategorizationRule(
            name=f"rule_{category}_{len(self.rules)}",
            category=category,
            keywords=keywords or [],
            sender_patterns=sender_patterns or [],
            subject_patterns=subject_patterns or [],
            priority=priority
        )
        self.add_rule(rule)
    
    def add_vip_sender(self, sender: str) -> None:
        """
        Add a VIP sender (always marked as important).
        
        Args:
            sender: Sender email address or pattern
        """
        self.vip_senders.add(sender.lower())
    
    def add_blocked_sender(self, sender: str) -> None:
        """
        Add a blocked sender.
        
        Args:
            sender: Sender email address or pattern
        """
        self.blocked_senders.add(sender.lower())
    
    def categorize(self, email: Email) -> CategorizationResult:
        """
        Categorize a single email.
        
        Args:
            email: Email to categorize
            
        Returns:
            CategorizationResult with category and confidence
        """
        category_scores: Dict[str, float] = {}
        matched_rules: List[str] = []
        highest_priority = CategoryPriority.NONE
        
        # Check VIP senders first
        sender_lower = email.sender.lower()
        is_vip = any(vip in sender_lower for vip in self.vip_senders)
        
        if is_vip:
            category_scores['important'] = 1.0
            matched_rules.append('vip_sender')
            highest_priority = CategoryPriority.HIGH
        
        # Check blocked senders
        is_blocked = any(blocked in sender_lower for blocked in self.blocked_senders)
        if is_blocked:
            return CategorizationResult(
                email_id=email.id,
                primary_category='blocked',
                all_categories={'blocked': 1.0},
                confidence=1.0,
                matched_rules=['blocked_sender'],
                priority=CategoryPriority.NONE
            )
        
        # Apply all rules
        for rule in self.rules:
            matches, score = rule.matches(email)
            
            if matches:
                if rule.category not in category_scores:
                    category_scores[rule.category] = 0.0
                
                category_scores[rule.category] = max(
                    category_scores[rule.category], 
                    score
                )
                matched_rules.append(rule.name)
                
                if rule.priority.value < highest_priority.value:
                    highest_priority = rule.priority
        
        # Gmail label-based categorization
        if 'IMPORTANT' in email.labels and 'important' not in category_scores:
            category_scores['important'] = 0.6
        if 'CATEGORY_PROMOTIONS' in email.labels:
            category_scores['promotional'] = max(
                category_scores.get('promotional', 0), 0.7
            )
        if 'CATEGORY_SOCIAL' in email.labels:
            category_scores['social'] = max(
                category_scores.get('social', 0), 0.7
            )
        if 'CATEGORY_UPDATES' in email.labels:
            category_scores['newsletter'] = max(
                category_scores.get('newsletter', 0), 0.5
            )
        
        # Determine primary category
        if category_scores:
            primary_category = max(category_scores.keys(), 
                                  key=lambda k: category_scores[k])
            confidence = category_scores[primary_category]
        else:
            primary_category = 'uncategorized'
            confidence = 0.0
        
        # Generate suggested actions
        suggested_actions = self._get_suggested_actions(
            primary_category, 
            email,
            highest_priority
        )
        
        return CategorizationResult(
            email_id=email.id,
            primary_category=primary_category,
            all_categories=category_scores,
            confidence=confidence,
            matched_rules=matched_rules,
            priority=highest_priority if highest_priority != CategoryPriority.NONE 
                     else self.categories.get(primary_category, 
                                             Category(name='uncategorized')).priority,
            suggested_actions=suggested_actions
        )
    
    def categorize_batch(
        self, 
        emails: List[Email]
    ) -> Dict[str, List[CategorizationResult]]:
        """
        Categorize multiple emails and group by category.
        
        Args:
            emails: List of emails to categorize
            
        Returns:
            Dictionary mapping category names to categorization results
        """
        results_by_category: Dict[str, List[CategorizationResult]] = {}
        
        for email in emails:
            result = self.categorize(email)
            
            if result.primary_category not in results_by_category:
                results_by_category[result.primary_category] = []
            
            results_by_category[result.primary_category].append(result)
        
        return results_by_category
    
    def _get_suggested_actions(
        self, 
        category: str, 
        email: Email,
        priority: CategoryPriority
    ) -> List[str]:
        """
        Get suggested actions based on category.
        
        Returns:
            List of suggested action strings
        """
        actions = []
        
        if priority in [CategoryPriority.CRITICAL, CategoryPriority.HIGH]:
            actions.append("respond_immediately")
        
        if category == 'urgent':
            actions.append("flag_for_attention")
            actions.append("send_acknowledgment")
        elif category == 'support':
            actions.append("create_ticket")
            actions.append("send_auto_reply")
        elif category == 'newsletter':
            actions.append("archive")
            if email.is_unread:
                actions.append("mark_read")
        elif category == 'promotional':
            actions.append("archive")
            actions.append("possible_unsubscribe")
        elif category == 'transactional':
            actions.append("archive")
            actions.append("add_to_records")
        
        return actions
    
    def get_category_stats(
        self, 
        results: List[CategorizationResult]
    ) -> Dict[str, Any]:
        """
        Get statistics about categorization results.
        
        Args:
            results: List of categorization results
            
        Returns:
            Statistics dictionary
        """
        stats = {
            'total': len(results),
            'by_category': {},
            'by_priority': {},
            'average_confidence': 0.0,
            'uncategorized_count': 0
        }
        
        total_confidence = 0.0
        
        for result in results:
            # Count by category
            cat = result.primary_category
            stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1
            
            # Count by priority
            pri = result.priority.name
            stats['by_priority'][pri] = stats['by_priority'].get(pri, 0) + 1
            
            # Sum confidence
            total_confidence += result.confidence
            
            # Count uncategorized
            if cat == 'uncategorized':
                stats['uncategorized_count'] += 1
        
        if results:
            stats['average_confidence'] = total_confidence / len(results)
        
        return stats
    
    def export_rules(self) -> List[Dict[str, Any]]:
        """
        Export all rules as dictionaries.
        
        Returns:
            List of rule dictionaries
        """
        exported = []
        for rule in self.rules:
            exported.append({
                'name': rule.name,
                'category': rule.category,
                'keywords': rule.keywords,
                'sender_patterns': rule.sender_patterns,
                'subject_patterns': rule.subject_patterns,
                'body_patterns': rule.body_patterns,
                'label_filters': rule.label_filters,
                'exclude_keywords': rule.exclude_keywords,
                'score_weight': rule.score_weight,
                'case_sensitive': rule.case_sensitive,
                'priority': rule.priority.name
            })
        return exported
    
    def import_rules(self, rules_data: List[Dict[str, Any]]) -> int:
        """
        Import rules from dictionaries.
        
        Args:
            rules_data: List of rule dictionaries
            
        Returns:
            Number of rules imported
        """
        imported = 0
        for rule_dict in rules_data:
            try:
                priority = CategoryPriority[rule_dict.get('priority', 'MEDIUM')]
                
                rule = CategorizationRule(
                    name=rule_dict['name'],
                    category=rule_dict['category'],
                    keywords=rule_dict.get('keywords', []),
                    sender_patterns=rule_dict.get('sender_patterns', []),
                    subject_patterns=rule_dict.get('subject_patterns', []),
                    body_patterns=rule_dict.get('body_patterns', []),
                    label_filters=rule_dict.get('label_filters', []),
                    exclude_keywords=rule_dict.get('exclude_keywords', []),
                    score_weight=rule_dict.get('score_weight', 1.0),
                    case_sensitive=rule_dict.get('case_sensitive', False),
                    priority=priority
                )
                
                self.add_rule(rule)
                imported += 1
                
            except Exception as e:
                logger.error(f"Failed to import rule: {e}")
        
        return imported


if __name__ == "__main__":
    # Example usage
    categorizer = EmailCategorizer()
    
    # Add custom rules
    categorizer.add_simple_rule(
        category='client',
        sender_patterns=[r'@clientcompany\.com$'],
        keywords=['project', 'milestone', 'deliverable'],
        priority=CategoryPriority.HIGH
    )
    
    categorizer.add_vip_sender('ceo@company.com')
    
    # Print loaded rules
    print(f"Loaded {len(categorizer.rules)} rules")
    print(f"Categories: {list(categorizer.categories.keys())}")
