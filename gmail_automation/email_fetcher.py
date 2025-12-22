"""
Email Fetcher Module

Fetches and parses emails from Gmail inbox.
Extracts sender, subject, date, content, and attachments.

Usage:
    from gmail_automation.email_fetcher import EmailFetcher
    
    fetcher = EmailFetcher(gmail_service)
    emails = fetcher.fetch_emails(max_results=50)
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict, Any, Generator
from html import unescape
from html.parser import HTMLParser

from googleapiclient.discovery import Resource

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML content."""
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.ignore_tags = {'script', 'style', 'head', 'meta', 'link'}
        self._ignore_content = False
        
    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.ignore_tags:
            self._ignore_content = True
            
    def handle_endtag(self, tag):
        if tag.lower() in self.ignore_tags:
            self._ignore_content = False
        if tag.lower() in ('p', 'br', 'div', 'li', 'tr'):
            self.result.append('\n')
            
    def handle_data(self, data):
        if not self._ignore_content:
            self.result.append(data)
            
    def get_text(self) -> str:
        return ''.join(self.result).strip()


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    mime_type: str
    size: int
    attachment_id: str
    data: Optional[bytes] = None


@dataclass
class Email:
    """
    Represents a parsed email message.
    
    Attributes:
        id: Gmail message ID
        thread_id: Gmail thread ID
        sender: Sender email address
        sender_name: Sender display name
        recipients: List of recipient email addresses
        cc: List of CC recipients
        bcc: List of BCC recipients
        subject: Email subject line
        date: Email date/time
        snippet: Short preview of email content
        body_text: Plain text body
        body_html: HTML body (if available)
        labels: Gmail labels applied to this email
        is_unread: Whether the email is unread
        is_starred: Whether the email is starred
        is_important: Whether marked as important
        attachments: List of attachments
        headers: Raw email headers
        raw_data: Raw Gmail API response
    """
    id: str
    thread_id: str
    sender: str
    sender_name: str = ""
    recipients: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    subject: str = ""
    date: Optional[datetime] = None
    snippet: str = ""
    body_text: str = ""
    body_html: str = ""
    labels: List[str] = field(default_factory=list)
    is_unread: bool = False
    is_starred: bool = False
    is_important: bool = False
    attachments: List[EmailAttachment] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Extract sender name from email address if not provided."""
        if not self.sender_name and self.sender:
            match = re.match(r'"?([^"<]+)"?\s*<', self.sender)
            if match:
                self.sender_name = match.group(1).strip()
            else:
                self.sender_name = self.sender.split('@')[0]
    
    def get_plain_body(self) -> str:
        """Get plain text body, converting from HTML if necessary."""
        if self.body_text:
            return self.body_text
        if self.body_html:
            return self._html_to_text(self.body_html)
        return self.snippet
    
    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text."""
        try:
            parser = HTMLTextExtractor()
            parser.feed(unescape(html))
            text = parser.get_text()
            # Clean up excessive whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r' +', ' ', text)
            return text.strip()
        except Exception:
            # Fallback: remove all HTML tags
            return re.sub(r'<[^>]+>', '', html)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert email to dictionary."""
        return {
            'id': self.id,
            'thread_id': self.thread_id,
            'sender': self.sender,
            'sender_name': self.sender_name,
            'recipients': self.recipients,
            'cc': self.cc,
            'subject': self.subject,
            'date': self.date.isoformat() if self.date else None,
            'snippet': self.snippet,
            'body_text': self.body_text,
            'labels': self.labels,
            'is_unread': self.is_unread,
            'is_starred': self.is_starred,
            'is_important': self.is_important,
            'attachment_count': len(self.attachments)
        }


class EmailFetcher:
    """
    Fetches and parses emails from Gmail API.
    
    Attributes:
        service: Gmail API service resource
        user_id: Gmail user ID (default: 'me')
    """
    
    def __init__(self, service: Resource, user_id: str = 'me'):
        """
        Initialize the Email Fetcher.
        
        Args:
            service: Gmail API service resource
            user_id: Gmail user ID (default: 'me' for authenticated user)
        """
        self.service = service
        self.user_id = user_id
        
    def fetch_emails(
        self,
        query: str = "",
        max_results: int = 50,
        label_ids: Optional[List[str]] = None,
        include_spam_trash: bool = False,
        fetch_body: bool = True
    ) -> List[Email]:
        """
        Fetch emails from Gmail inbox.
        
        Args:
            query: Gmail search query (e.g., "is:unread", "from:example@gmail.com")
            max_results: Maximum number of emails to fetch
            label_ids: Filter by specific label IDs
            include_spam_trash: Include spam and trash folders
            fetch_body: Whether to fetch full email body
            
        Returns:
            List of Email objects
        """
        logger.info(f"Fetching emails with query: '{query}', max: {max_results}")
        
        message_ids = self._list_message_ids(
            query=query,
            max_results=max_results,
            label_ids=label_ids,
            include_spam_trash=include_spam_trash
        )
        
        emails = []
        for msg_data in message_ids:
            try:
                email = self.fetch_email_by_id(
                    msg_data['id'],
                    fetch_body=fetch_body
                )
                if email:
                    emails.append(email)
            except Exception as e:
                logger.error(f"Failed to fetch email {msg_data['id']}: {e}")
                
        logger.info(f"Fetched {len(emails)} emails")
        return emails
    
    def fetch_emails_generator(
        self,
        query: str = "",
        max_results: int = 100,
        label_ids: Optional[List[str]] = None,
        fetch_body: bool = True
    ) -> Generator[Email, None, None]:
        """
        Fetch emails as a generator for memory-efficient processing.
        
        Yields:
            Email objects one at a time
        """
        message_ids = self._list_message_ids(
            query=query,
            max_results=max_results,
            label_ids=label_ids
        )
        
        for msg_data in message_ids:
            try:
                email = self.fetch_email_by_id(
                    msg_data['id'],
                    fetch_body=fetch_body
                )
                if email:
                    yield email
            except Exception as e:
                logger.error(f"Failed to fetch email {msg_data['id']}: {e}")
    
    def _list_message_ids(
        self,
        query: str = "",
        max_results: int = 50,
        label_ids: Optional[List[str]] = None,
        include_spam_trash: bool = False
    ) -> List[Dict[str, str]]:
        """
        List message IDs matching the query.
        
        Returns:
            List of message ID dictionaries
        """
        messages = []
        request_params = {
            'userId': self.user_id,
            'maxResults': min(max_results, 500),
            'includeSpamTrash': include_spam_trash
        }
        
        if query:
            request_params['q'] = query
        if label_ids:
            request_params['labelIds'] = label_ids
            
        request = self.service.users().messages().list(**request_params)
        
        while request and len(messages) < max_results:
            response = request.execute()
            
            if 'messages' in response:
                messages.extend(response['messages'])
                
            # Get next page
            if 'nextPageToken' in response and len(messages) < max_results:
                request_params['pageToken'] = response['nextPageToken']
                request = self.service.users().messages().list(**request_params)
            else:
                break
                
        return messages[:max_results]
    
    def fetch_email_by_id(
        self,
        message_id: str,
        fetch_body: bool = True,
        fetch_attachments: bool = False
    ) -> Optional[Email]:
        """
        Fetch a single email by its ID.
        
        Args:
            message_id: Gmail message ID
            fetch_body: Whether to fetch the full body
            fetch_attachments: Whether to download attachment data
            
        Returns:
            Email object or None if not found
        """
        format_type = 'full' if fetch_body else 'metadata'
        
        try:
            message = self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format=format_type
            ).execute()
            
            return self._parse_message(message, fetch_attachments)
            
        except Exception as e:
            logger.error(f"Error fetching message {message_id}: {e}")
            return None
    
    def _parse_message(
        self,
        message: Dict[str, Any],
        fetch_attachments: bool = False
    ) -> Email:
        """
        Parse a Gmail API message into an Email object.
        
        Args:
            message: Raw Gmail API message
            fetch_attachments: Whether to download attachment data
            
        Returns:
            Parsed Email object
        """
        headers = self._extract_headers(message.get('payload', {}).get('headers', []))
        
        # Extract body content
        body_text, body_html = self._extract_body(message.get('payload', {}))
        
        # Extract attachments
        attachments = self._extract_attachments(
            message.get('payload', {}),
            message['id'],
            fetch_attachments
        )
        
        # Parse labels
        labels = message.get('labelIds', [])
        
        # Parse date
        date = None
        if 'Date' in headers:
            try:
                date = parsedate_to_datetime(headers['Date'])
            except Exception:
                pass
        
        if not date and 'internalDate' in message:
            try:
                date = datetime.fromtimestamp(int(message['internalDate']) / 1000)
            except Exception:
                pass
        
        return Email(
            id=message['id'],
            thread_id=message.get('threadId', ''),
            sender=headers.get('From', ''),
            recipients=self._parse_recipients(headers.get('To', '')),
            cc=self._parse_recipients(headers.get('Cc', '')),
            bcc=self._parse_recipients(headers.get('Bcc', '')),
            subject=headers.get('Subject', '(No Subject)'),
            date=date,
            snippet=message.get('snippet', ''),
            body_text=body_text,
            body_html=body_html,
            labels=labels,
            is_unread='UNREAD' in labels,
            is_starred='STARRED' in labels,
            is_important='IMPORTANT' in labels,
            attachments=attachments,
            headers=headers,
            raw_data=message
        )
    
    def _extract_headers(self, headers: List[Dict[str, str]]) -> Dict[str, str]:
        """Extract headers into a dictionary."""
        return {h['name']: h['value'] for h in headers}
    
    def _parse_recipients(self, recipients_str: str) -> List[str]:
        """Parse comma-separated recipients into a list."""
        if not recipients_str:
            return []
        # Handle multiple recipients
        recipients = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', recipients_str)
        return [r.strip() for r in recipients if r.strip()]
    
    def _extract_body(self, payload: Dict[str, Any]) -> tuple[str, str]:
        """
        Extract text and HTML body from email payload.
        
        Returns:
            Tuple of (plain_text, html)
        """
        body_text = ""
        body_html = ""
        
        def extract_from_part(part: Dict[str, Any]) -> None:
            nonlocal body_text, body_html
            
            mime_type = part.get('mimeType', '')
            body = part.get('body', {})
            
            if 'data' in body:
                try:
                    decoded = base64.urlsafe_b64decode(body['data']).decode('utf-8')
                    if mime_type == 'text/plain':
                        body_text = decoded
                    elif mime_type == 'text/html':
                        body_html = decoded
                except Exception as e:
                    logger.warning(f"Failed to decode body: {e}")
            
            # Recursively process parts
            for sub_part in part.get('parts', []):
                extract_from_part(sub_part)
        
        extract_from_part(payload)
        return body_text, body_html
    
    def _extract_attachments(
        self,
        payload: Dict[str, Any],
        message_id: str,
        fetch_data: bool = False
    ) -> List[EmailAttachment]:
        """
        Extract attachments from email payload.
        
        Args:
            payload: Email payload
            message_id: Message ID for fetching attachment data
            fetch_data: Whether to download the attachment data
            
        Returns:
            List of EmailAttachment objects
        """
        attachments = []
        
        def extract_from_part(part: Dict[str, Any]) -> None:
            filename = part.get('filename', '')
            body = part.get('body', {})
            
            if filename and 'attachmentId' in body:
                attachment = EmailAttachment(
                    filename=filename,
                    mime_type=part.get('mimeType', 'application/octet-stream'),
                    size=body.get('size', 0),
                    attachment_id=body['attachmentId']
                )
                
                if fetch_data:
                    attachment.data = self._fetch_attachment_data(
                        message_id,
                        body['attachmentId']
                    )
                
                attachments.append(attachment)
            
            # Recursively process parts
            for sub_part in part.get('parts', []):
                extract_from_part(sub_part)
        
        extract_from_part(payload)
        return attachments
    
    def _fetch_attachment_data(
        self,
        message_id: str,
        attachment_id: str
    ) -> Optional[bytes]:
        """
        Fetch attachment data from Gmail API.
        
        Returns:
            Attachment binary data or None
        """
        try:
            attachment = self.service.users().messages().attachments().get(
                userId=self.user_id,
                messageId=message_id,
                id=attachment_id
            ).execute()
            
            if 'data' in attachment:
                return base64.urlsafe_b64decode(attachment['data'])
        except Exception as e:
            logger.error(f"Failed to fetch attachment: {e}")
        
        return None
    
    def fetch_unread(self, max_results: int = 50) -> List[Email]:
        """Fetch unread emails."""
        return self.fetch_emails(query="is:unread", max_results=max_results)
    
    def fetch_starred(self, max_results: int = 50) -> List[Email]:
        """Fetch starred emails."""
        return self.fetch_emails(query="is:starred", max_results=max_results)
    
    def fetch_from_sender(
        self,
        sender: str,
        max_results: int = 50
    ) -> List[Email]:
        """Fetch emails from a specific sender."""
        return self.fetch_emails(query=f"from:{sender}", max_results=max_results)
    
    def fetch_by_subject(
        self,
        subject: str,
        max_results: int = 50
    ) -> List[Email]:
        """Fetch emails with a specific subject."""
        return self.fetch_emails(query=f"subject:{subject}", max_results=max_results)
    
    def fetch_by_date_range(
        self,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        max_results: int = 50
    ) -> List[Email]:
        """
        Fetch emails within a date range.
        
        Args:
            after: Start date (inclusive)
            before: End date (inclusive)
            max_results: Maximum results
        """
        query_parts = []
        if after:
            query_parts.append(f"after:{after.strftime('%Y/%m/%d')}")
        if before:
            query_parts.append(f"before:{before.strftime('%Y/%m/%d')}")
        
        query = " ".join(query_parts)
        return self.fetch_emails(query=query, max_results=max_results)
    
    def get_thread(self, thread_id: str) -> List[Email]:
        """
        Fetch all emails in a thread.
        
        Args:
            thread_id: Gmail thread ID
            
        Returns:
            List of Email objects in the thread
        """
        try:
            thread = self.service.users().threads().get(
                userId=self.user_id,
                id=thread_id,
                format='full'
            ).execute()
            
            emails = []
            for message in thread.get('messages', []):
                emails.append(self._parse_message(message))
            
            return emails
            
        except Exception as e:
            logger.error(f"Error fetching thread {thread_id}: {e}")
            return []
    
    def get_labels(self) -> List[Dict[str, Any]]:
        """
        Get all Gmail labels.
        
        Returns:
            List of label dictionaries
        """
        try:
            response = self.service.users().labels().list(
                userId=self.user_id
            ).execute()
            return response.get('labels', [])
        except Exception as e:
            logger.error(f"Error fetching labels: {e}")
            return []
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark an email as read."""
        return self._modify_labels(message_id, remove_labels=['UNREAD'])
    
    def mark_as_unread(self, message_id: str) -> bool:
        """Mark an email as unread."""
        return self._modify_labels(message_id, add_labels=['UNREAD'])
    
    def add_star(self, message_id: str) -> bool:
        """Add star to an email."""
        return self._modify_labels(message_id, add_labels=['STARRED'])
    
    def remove_star(self, message_id: str) -> bool:
        """Remove star from an email."""
        return self._modify_labels(message_id, remove_labels=['STARRED'])
    
    def _modify_labels(
        self,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None
    ) -> bool:
        """
        Modify labels on a message.
        
        Returns:
            True if successful
        """
        try:
            body = {}
            if add_labels:
                body['addLabelIds'] = add_labels
            if remove_labels:
                body['removeLabelIds'] = remove_labels
            
            self.service.users().messages().modify(
                userId=self.user_id,
                id=message_id,
                body=body
            ).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error modifying labels: {e}")
            return False


if __name__ == "__main__":
    # Example usage
    from gmail_automation.auth import GmailAuthenticator
    
    auth = GmailAuthenticator()
    service = auth.authenticate()
    
    fetcher = EmailFetcher(service)
    
    # Fetch recent unread emails
    emails = fetcher.fetch_unread(max_results=10)
    
    for email in emails:
        print(f"From: {email.sender}")
        print(f"Subject: {email.subject}")
        print(f"Date: {email.date}")
        print(f"Preview: {email.snippet[:100]}...")
        print("-" * 50)
