"""
Gmail Automation - Main Application

A comprehensive Gmail automation tool that integrates:
- OAuth 2.0 authentication
- Email fetching and parsing
- Rule-based categorization
- AI-powered sentiment analysis
- Personalized email composition
- Multi-account management

Usage:
    # Command-line interface
    python -m gmail_automation --help
    
    # Python API
    from gmail_automation import GmailAutomation
    
    gmail = GmailAutomation()
    gmail.authenticate()
    emails = gmail.fetch_and_analyze(max_emails=50)
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .auth import GmailAuthenticator
from .email_fetcher import EmailFetcher, Email
from .categorizer import EmailCategorizer, CategorizationResult
from .sentiment_analyzer import SentimentAnalyzer, SentimentResult
from .email_composer import EmailComposer, ComposedEmail
from .account_manager import AccountManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GmailAutomation:
    """
    Main Gmail Automation class that orchestrates all modules.
    
    Provides a unified interface for email management, analysis,
    and automated response generation.
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        credentials_path: str = "credentials.json",
        use_openai: bool = False,
        openai_api_key: Optional[str] = None,
        multi_account: bool = False
    ):
        """
        Initialize Gmail Automation.
        
        Args:
            config_path: Path to configuration directory
            credentials_path: Path to OAuth credentials
            use_openai: Enable OpenAI for advanced analysis
            openai_api_key: OpenAI API key
            multi_account: Enable multi-account mode
        """
        self.config_path = Path(config_path) if config_path else Path.home() / ".gmail_automation"
        self.config_path.mkdir(parents=True, exist_ok=True)
        
        self.credentials_path = credentials_path
        self.use_openai = use_openai
        self.openai_api_key = openai_api_key
        self.multi_account = multi_account
        
        # Initialize components
        self._authenticator: Optional[GmailAuthenticator] = None
        self._fetcher: Optional[EmailFetcher] = None
        self._categorizer: Optional[EmailCategorizer] = None
        self._analyzer: Optional[SentimentAnalyzer] = None
        self._composer: Optional[EmailComposer] = None
        self._account_manager: Optional[AccountManager] = None
        
        self._service = None
        self._user_email: Optional[str] = None
        
        # Results cache
        self._last_fetch: List[Email] = []
        self._last_categorization: Dict[str, CategorizationResult] = {}
        self._last_sentiment: Dict[str, SentimentResult] = {}
    
    def authenticate(self, account_id: Optional[str] = None) -> bool:
        """
        Authenticate with Gmail API.
        
        Args:
            account_id: Account ID for multi-account mode
            
        Returns:
            True if authentication successful
        """
        try:
            if self.multi_account:
                if not self._account_manager:
                    self._account_manager = AccountManager(str(self.config_path))
                
                if account_id:
                    self._service = self._account_manager.get_service(account_id)
                else:
                    self._service = self._account_manager.get_service()
            else:
                self._authenticator = GmailAuthenticator(
                    credentials_path=self.credentials_path,
                    config_dir=str(self.config_path)
                )
                self._service = self._authenticator.authenticate()
                self._user_email = self._authenticator.get_user_email()
            
            # Initialize components with service
            self._fetcher = EmailFetcher(self._service)
            self._categorizer = EmailCategorizer()
            self._analyzer = SentimentAnalyzer(
                use_openai=self.use_openai,
                openai_api_key=self.openai_api_key
            )
            self._composer = EmailComposer(
                service=self._service,
                use_ai=self.use_openai,
                openai_api_key=self.openai_api_key
            )
            
            logger.info(f"Authenticated as: {self._user_email or 'multi-account mode'}")
            return True
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def fetch_emails(
        self,
        query: str = "",
        max_results: int = 50,
        label_ids: Optional[List[str]] = None
    ) -> List[Email]:
        """
        Fetch emails from Gmail.
        
        Args:
            query: Gmail search query
            max_results: Maximum emails to fetch
            label_ids: Filter by label IDs
            
        Returns:
            List of Email objects
        """
        if not self._fetcher:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        emails = self._fetcher.fetch_emails(
            query=query,
            max_results=max_results,
            label_ids=label_ids
        )
        
        self._last_fetch = emails
        return emails
    
    def categorize_emails(
        self,
        emails: Optional[List[Email]] = None
    ) -> Dict[str, List[CategorizationResult]]:
        """
        Categorize emails.
        
        Args:
            emails: Emails to categorize (uses last fetch if not provided)
            
        Returns:
            Dictionary of category to results
        """
        if not self._categorizer:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        emails = emails or self._last_fetch
        if not emails:
            logger.warning("No emails to categorize")
            return {}
        
        results_by_category = self._categorizer.categorize_batch(emails)
        
        # Cache results
        for category_results in results_by_category.values():
            for result in category_results:
                self._last_categorization[result.email_id] = result
        
        return results_by_category
    
    def analyze_sentiment(
        self,
        emails: Optional[List[Email]] = None
    ) -> List[SentimentResult]:
        """
        Analyze sentiment of emails.
        
        Args:
            emails: Emails to analyze (uses last fetch if not provided)
            
        Returns:
            List of SentimentResult objects
        """
        if not self._analyzer:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        emails = emails or self._last_fetch
        if not emails:
            logger.warning("No emails to analyze")
            return []
        
        results = self._analyzer.analyze_batch(emails)
        
        # Cache results
        for result in results:
            self._last_sentiment[result.email_id] = result
        
        return results
    
    def fetch_and_analyze(
        self,
        query: str = "is:unread",
        max_emails: int = 50
    ) -> Dict[str, Any]:
        """
        Fetch, categorize, and analyze emails in one call.
        
        Args:
            query: Gmail search query
            max_emails: Maximum emails to process
            
        Returns:
            Dictionary with all results
        """
        # Fetch emails
        emails = self.fetch_emails(query=query, max_results=max_emails)
        
        if not emails:
            return {
                'email_count': 0,
                'emails': [],
                'categorization': {},
                'sentiment': {},
                'summary': {}
            }
        
        # Categorize
        categorization = self.categorize_emails(emails)
        
        # Analyze sentiment
        sentiment_results = self.analyze_sentiment(emails)
        
        # Build comprehensive results
        email_data = []
        for email in emails:
            cat_result = self._last_categorization.get(email.id)
            sent_result = self._last_sentiment.get(email.id)
            
            email_data.append({
                'email': email.to_dict(),
                'category': cat_result.to_dict() if cat_result else None,
                'sentiment': sent_result.to_dict() if sent_result else None
            })
        
        # Generate summary
        cat_stats = self._categorizer.get_category_stats(
            list(self._last_categorization.values())
        )
        sent_summary = self._analyzer.get_sentiment_summary(sentiment_results)
        
        return {
            'email_count': len(emails),
            'emails': email_data,
            'categorization_stats': cat_stats,
            'sentiment_summary': sent_summary,
            'requires_attention': [
                e for e in email_data 
                if e.get('sentiment') and 
                   SentimentResult(**{**e['sentiment'], 
                                     'sentiment': __import__('gmail_automation.sentiment_analyzer', 
                                                            fromlist=['Sentiment']).Sentiment(e['sentiment']['sentiment']),
                                     'tone': __import__('gmail_automation.sentiment_analyzer', 
                                                       fromlist=['Tone']).Tone(e['sentiment']['tone']),
                                     'urgency': __import__('gmail_automation.sentiment_analyzer', 
                                                          fromlist=['Urgency']).Urgency(e['sentiment']['urgency']),
                                     'intent': __import__('gmail_automation.sentiment_analyzer', 
                                                         fromlist=['Intent']).Intent(e['sentiment']['intent']),
                                     'analyzed_at': datetime.fromisoformat(e['sentiment']['analyzed_at'])
                                     }).requires_attention()
            ] if False else [
                e for e in email_data 
                if e.get('sentiment', {}).get('urgency') in ['critical', 'high'] or
                   e.get('sentiment', {}).get('sentiment') == 'very_negative'
            ]
        }
    
    def compose_response(
        self,
        email_id: str,
        template: Optional[str] = None,
        custom_content: str = "",
        use_ai: bool = False
    ) -> Optional[ComposedEmail]:
        """
        Compose a response to an email.
        
        Args:
            email_id: ID of email to respond to
            template: Template name to use
            custom_content: Custom content for response
            use_ai: Generate content with AI
            
        Returns:
            ComposedEmail or None
        """
        if not self._composer:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        # Find the email
        email = next((e for e in self._last_fetch if e.id == email_id), None)
        if not email:
            # Try to fetch it
            email = self._fetcher.fetch_email_by_id(email_id)
        
        if not email:
            logger.error(f"Email not found: {email_id}")
            return None
        
        sentiment = self._last_sentiment.get(email_id)
        categorization = self._last_categorization.get(email_id)
        
        return self._composer.compose_response(
            original_email=email,
            sentiment_result=sentiment,
            categorization=categorization,
            template_name=template,
            custom_content=custom_content,
            use_ai_content=use_ai
        )
    
    def send_email(self, composed: ComposedEmail) -> Dict[str, Any]:
        """
        Send a composed email.
        
        Args:
            composed: Email to send
            
        Returns:
            Send result dictionary
        """
        if not self._composer:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        result = self._composer.send_email(composed)
        
        # Update account manager if in multi-account mode
        if self.multi_account and self._account_manager:
            account = self._account_manager.get_default_account()
            if account:
                account.record_send()
        
        return {
            'success': result.success,
            'message_id': result.message_id,
            'thread_id': result.thread_id,
            'error': result.error
        }
    
    def add_categorization_rule(
        self,
        category: str,
        keywords: Optional[List[str]] = None,
        sender_patterns: Optional[List[str]] = None,
        subject_patterns: Optional[List[str]] = None
    ) -> None:
        """Add a custom categorization rule."""
        if not self._categorizer:
            self._categorizer = EmailCategorizer()
        
        self._categorizer.add_simple_rule(
            category=category,
            keywords=keywords,
            sender_patterns=sender_patterns,
            subject_patterns=subject_patterns
        )
    
    def add_vip_sender(self, sender: str) -> None:
        """Add a VIP sender."""
        if not self._categorizer:
            self._categorizer = EmailCategorizer()
        self._categorizer.add_vip_sender(sender)
    
    def get_account_manager(self) -> AccountManager:
        """Get the account manager for multi-account operations."""
        if not self._account_manager:
            self._account_manager = AccountManager(str(self.config_path))
        return self._account_manager
    
    def export_results(self, filepath: str) -> None:
        """
        Export analysis results to JSON file.
        
        Args:
            filepath: Output file path
        """
        data = {
            'exported_at': datetime.now().isoformat(),
            'email_count': len(self._last_fetch),
            'emails': [e.to_dict() for e in self._last_fetch],
            'categorization': {
                k: v.to_dict() for k, v in self._last_categorization.items()
            },
            'sentiment': {
                k: v.to_dict() for k, v in self._last_sentiment.items()
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Results exported to {filepath}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status and statistics."""
        status = {
            'authenticated': self._service is not None,
            'user_email': self._user_email,
            'multi_account_mode': self.multi_account,
            'openai_enabled': self.use_openai,
            'cached_emails': len(self._last_fetch),
            'cached_categorizations': len(self._last_categorization),
            'cached_sentiments': len(self._last_sentiment)
        }
        
        if self._categorizer:
            status['categorization_rules'] = len(self._categorizer.rules)
            status['categories'] = list(self._categorizer.categories.keys())
        
        if self._account_manager:
            status['accounts'] = self._account_manager.get_usage_stats()
        
        return status


def main():
    """Command-line interface for Gmail Automation."""
    parser = argparse.ArgumentParser(
        description='Gmail Automation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s fetch --query "is:unread" --max 20
  %(prog)s analyze --query "from:important@example.com"
  %(prog)s status
        """
    )
    
    parser.add_argument(
        '--credentials', '-c',
        default='credentials.json',
        help='Path to OAuth credentials file'
    )
    parser.add_argument(
        '--config-dir',
        default=None,
        help='Configuration directory'
    )
    parser.add_argument(
        '--use-openai',
        action='store_true',
        help='Enable OpenAI for advanced analysis'
    )
    parser.add_argument(
        '--openai-key',
        default=None,
        help='OpenAI API key'
    )
    parser.add_argument(
        '--multi-account',
        action='store_true',
        help='Enable multi-account mode'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Fetch command
    fetch_parser = subparsers.add_parser('fetch', help='Fetch emails')
    fetch_parser.add_argument('--query', '-q', default='is:unread', help='Gmail search query')
    fetch_parser.add_argument('--max', '-m', type=int, default=50, help='Maximum emails')
    fetch_parser.add_argument('--output', '-o', help='Output file (JSON)')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Fetch and analyze emails')
    analyze_parser.add_argument('--query', '-q', default='is:unread', help='Gmail search query')
    analyze_parser.add_argument('--max', '-m', type=int, default=50, help='Maximum emails')
    analyze_parser.add_argument('--output', '-o', help='Output file (JSON)')
    
    # Status command
    subparsers.add_parser('status', help='Show status')
    
    # Compose command
    compose_parser = subparsers.add_parser('compose', help='Compose email')
    compose_parser.add_argument('--to', required=True, help='Recipient email')
    compose_parser.add_argument('--subject', required=True, help='Subject line')
    compose_parser.add_argument('--body', required=True, help='Email body')
    compose_parser.add_argument('--template', help='Template to use')
    compose_parser.add_argument('--send', action='store_true', help='Send immediately')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize automation
    gmail = GmailAutomation(
        config_path=args.config_dir,
        credentials_path=args.credentials,
        use_openai=args.use_openai,
        openai_api_key=args.openai_key,
        multi_account=args.multi_account
    )
    
    if args.command == 'status':
        # Status doesn't require authentication
        print(json.dumps(gmail.get_status(), indent=2))
        return
    
    if not args.command:
        parser.print_help()
        return
    
    # Authenticate
    if not gmail.authenticate():
        print("Authentication failed. Please check your credentials.")
        sys.exit(1)
    
    if args.command == 'fetch':
        emails = gmail.fetch_emails(query=args.query, max_results=args.max)
        
        print(f"Fetched {len(emails)} emails")
        for email in emails[:10]:
            print(f"  - {email.date}: {email.subject[:50]}... (from: {email.sender})")
        
        if len(emails) > 10:
            print(f"  ... and {len(emails) - 10} more")
        
        if args.output:
            gmail.export_results(args.output)
    
    elif args.command == 'analyze':
        results = gmail.fetch_and_analyze(query=args.query, max_emails=args.max)
        
        print(f"\nAnalyzed {results['email_count']} emails")
        print(f"\nCategorization Summary:")
        for cat, count in results.get('categorization_stats', {}).get('by_category', {}).items():
            print(f"  - {cat}: {count}")
        
        print(f"\nSentiment Summary:")
        sent_summary = results.get('sentiment_summary', {})
        print(f"  Average score: {sent_summary.get('average_sentiment_score', 0):.2f}")
        for sent, count in sent_summary.get('sentiment_distribution', {}).items():
            print(f"  - {sent}: {count}")
        
        attention = results.get('requires_attention', [])
        if attention:
            print(f"\n⚠️ {len(attention)} email(s) require attention")
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"\nResults saved to {args.output}")
    
    elif args.command == 'compose':
        composed = gmail._composer.compose_new(
            to=args.to,
            subject=args.subject,
            body=args.body,
            template_name=args.template
        )
        
        if args.send:
            result = gmail.send_email(composed)
            if result['success']:
                print(f"Email sent! Message ID: {result['message_id']}")
            else:
                print(f"Failed to send: {result['error']}")
        else:
            print("Composed email (use --send to send):")
            print(json.dumps(composed.to_dict(), indent=2))


if __name__ == "__main__":
    main()
