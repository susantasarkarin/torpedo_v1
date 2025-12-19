"""
Email Composer Module

Generates and sends personalized outbound emails based on
categorization and sentiment analysis results.

Supports templates, AI-assisted content generation, and
personalization tokens.

Usage:
    from gmail_automation.email_composer import EmailComposer
    
    composer = EmailComposer(gmail_service)
    draft = composer.compose_response(original_email, sentiment_result)
    composer.send_email(draft)
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import os

from googleapiclient.discovery import Resource

from .email_fetcher import Email
from .categorizer import CategorizationResult
from .sentiment_analyzer import SentimentResult, Sentiment, Tone, Intent, Urgency

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmailTemplate:
    """
    Email template for generating responses.
    
    Attributes:
        name: Template identifier
        subject: Subject line template
        body: Body content template
        html_body: Optional HTML body template
        category: Associated category
        sentiment_match: Sentiment conditions for this template
        tone: Tone to use in response
        tokens: Available personalization tokens
    """
    name: str
    subject: str
    body: str
    html_body: Optional[str] = None
    category: Optional[str] = None
    sentiment_match: Optional[List[str]] = None
    tone: Tone = Tone.PROFESSIONAL
    description: str = ""
    tokens: Dict[str, str] = field(default_factory=dict)
    
    def render(self, context: Dict[str, Any]) -> tuple[str, str, Optional[str]]:
        """
        Render template with context.
        
        Args:
            context: Dictionary of token values
            
        Returns:
            Tuple of (subject, body, html_body)
        """
        def replace_tokens(text: str) -> str:
            for key, value in context.items():
                text = text.replace(f"{{{{{key}}}}}", str(value))
                text = text.replace(f"{{{{ {key} }}}}", str(value))
            return text
        
        rendered_subject = replace_tokens(self.subject)
        rendered_body = replace_tokens(self.body)
        rendered_html = replace_tokens(self.html_body) if self.html_body else None
        
        return rendered_subject, rendered_body, rendered_html


@dataclass
class ComposedEmail:
    """
    Represents a composed email ready for sending.
    
    Attributes:
        to: Recipient email addresses
        cc: CC recipients
        bcc: BCC recipients
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body
        from_address: Sender address (or alias)
        reply_to: Reply-to address
        in_reply_to: Message-ID of email being replied to
        references: Thread references
        attachments: List of attachment file paths
        headers: Custom headers
        is_draft: Whether to save as draft
    """
    to: List[str]
    subject: str
    body_text: str
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    body_html: Optional[str] = None
    from_address: Optional[str] = None
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    attachments: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    is_draft: bool = False
    thread_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'to': self.to,
            'cc': self.cc,
            'bcc': self.bcc,
            'subject': self.subject,
            'body_text': self.body_text[:500] + '...' if len(self.body_text) > 500 else self.body_text,
            'has_html': bool(self.body_html),
            'from_address': self.from_address,
            'attachment_count': len(self.attachments),
            'is_draft': self.is_draft
        }


@dataclass 
class SendResult:
    """Result of sending an email."""
    success: bool
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    error: Optional[str] = None
    draft_id: Optional[str] = None


class EmailComposer:
    """
    Composes and sends personalized emails.
    
    Supports template-based composition, AI-assisted content,
    and context-aware response generation.
    """
    
    # Default templates
    DEFAULT_TEMPLATES = {
        'acknowledgment': EmailTemplate(
            name='acknowledgment',
            subject='Re: {{original_subject}}',
            body="""Hi {{sender_name}},

Thank you for your email. I wanted to acknowledge receipt and let you know that I'm looking into this matter.

I'll get back to you with a detailed response shortly.

Best regards,
{{my_name}}""",
            tone=Tone.PROFESSIONAL,
            description="Simple acknowledgment response"
        ),
        
        'urgent_response': EmailTemplate(
            name='urgent_response',
            subject='Re: {{original_subject}} [URGENT]',
            body="""Hi {{sender_name}},

Thank you for bringing this urgent matter to my attention. I understand the time-sensitive nature of your request.

{{custom_content}}

Please don't hesitate to reach out if you need any immediate clarification.

Best regards,
{{my_name}}""",
            tone=Tone.PROFESSIONAL,
            sentiment_match=['urgent'],
            description="Response to urgent emails"
        ),
        
        'support_response': EmailTemplate(
            name='support_response',
            subject='Re: {{original_subject}}',
            body="""Hi {{sender_name}},

Thank you for reaching out to our support team.

{{custom_content}}

If you have any further questions or need additional assistance, please don't hesitate to reply to this email.

Best regards,
{{my_name}}
{{company_name}} Support""",
            tone=Tone.FRIENDLY,
            category='support',
            description="Customer support response"
        ),
        
        'complaint_response': EmailTemplate(
            name='complaint_response',
            subject='Re: {{original_subject}}',
            body="""Dear {{sender_name}},

Thank you for taking the time to share your concerns with us. I sincerely apologize for any inconvenience you've experienced.

{{custom_content}}

We value your feedback and are committed to resolving this matter promptly. Please let me know if there's anything else I can do to help.

Sincerely,
{{my_name}}""",
            tone=Tone.APOLOGETIC,
            sentiment_match=['negative', 'very_negative'],
            description="Response to complaints"
        ),
        
        'follow_up': EmailTemplate(
            name='follow_up',
            subject='Following up: {{original_subject}}',
            body="""Hi {{sender_name}},

I wanted to follow up on my previous message regarding {{topic}}.

{{custom_content}}

Please let me know if you have any questions or need additional information.

Best regards,
{{my_name}}""",
            tone=Tone.PROFESSIONAL,
            description="Follow-up email"
        ),
        
        'thank_you': EmailTemplate(
            name='thank_you',
            subject='Re: {{original_subject}}',
            body="""Hi {{sender_name}},

Thank you so much for {{reason}}! I really appreciate your {{what}}.

{{custom_content}}

Looking forward to {{next_step}}.

Warm regards,
{{my_name}}""",
            tone=Tone.APPRECIATIVE,
            sentiment_match=['positive', 'very_positive'],
            description="Thank you response"
        ),
        
        'introduction': EmailTemplate(
            name='introduction',
            subject='{{intro_subject}}',
            body="""Hi {{recipient_name}},

I hope this email finds you well. My name is {{my_name}}, and I'm reaching out {{reason}}.

{{custom_content}}

I would love the opportunity to {{call_to_action}}.

Looking forward to hearing from you.

Best regards,
{{my_name}}
{{my_title}}
{{company_name}}""",
            tone=Tone.FRIENDLY,
            description="Introduction/outreach email"
        )
    }
    
    def __init__(
        self,
        service: Optional[Resource] = None,
        user_id: str = 'me',
        default_from: Optional[str] = None,
        default_name: str = "",
        company_name: str = "",
        use_ai: bool = False,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize Email Composer.
        
        Args:
            service: Gmail API service resource
            user_id: Gmail user ID
            default_from: Default sender address
            default_name: Default sender name
            company_name: Company name for templates
            use_ai: Use AI for content generation
            openai_api_key: OpenAI API key for AI features
        """
        self.service = service
        self.user_id = user_id
        self.default_from = default_from
        self.default_name = default_name
        self.company_name = company_name
        
        self.templates: Dict[str, EmailTemplate] = dict(self.DEFAULT_TEMPLATES)
        self.signatures: Dict[str, str] = {}
        
        self.use_ai = use_ai
        self._openai_client = None
        
        if use_ai:
            self._init_openai(openai_api_key)
    
    def _init_openai(self, api_key: Optional[str]) -> None:
        """Initialize OpenAI client."""
        api_key = api_key or os.getenv('OPENAI_API_KEY')
        if api_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=api_key)
            except ImportError:
                logger.warning("OpenAI not installed")
    
    def add_template(self, template: EmailTemplate) -> None:
        """Add a custom template."""
        self.templates[template.name] = template
        logger.info(f"Added template: {template.name}")
    
    def add_signature(self, name: str, signature: str) -> None:
        """Add a custom signature."""
        self.signatures[name] = signature
    
    def compose_response(
        self,
        original_email: Email,
        sentiment_result: Optional[SentimentResult] = None,
        categorization: Optional[CategorizationResult] = None,
        template_name: Optional[str] = None,
        custom_content: str = "",
        include_original: bool = True,
        use_ai_content: bool = False
    ) -> ComposedEmail:
        """
        Compose a response to an email.
        
        Args:
            original_email: Original email to respond to
            sentiment_result: Sentiment analysis result
            categorization: Categorization result
            template_name: Specific template to use
            custom_content: Custom content to include
            include_original: Include original message in reply
            use_ai_content: Generate content using AI
            
        Returns:
            ComposedEmail ready for sending
        """
        # Select appropriate template
        template = self._select_template(
            template_name,
            sentiment_result,
            categorization
        )
        
        # Build context for template
        context = self._build_context(
            original_email,
            sentiment_result,
            custom_content
        )
        
        # Generate AI content if requested
        if use_ai_content and self.use_ai:
            context['custom_content'] = self._generate_ai_content(
                original_email,
                sentiment_result,
                template.tone
            )
        elif not context.get('custom_content'):
            context['custom_content'] = custom_content or ""
        
        # Render template
        subject, body, html_body = template.render(context)
        
        # Add original message if replying
        if include_original:
            body = self._add_original_quote(body, original_email)
            if html_body:
                html_body = self._add_original_quote_html(html_body, original_email)
        
        # Extract sender email
        sender_email = self._extract_email(original_email.sender)
        
        return ComposedEmail(
            to=[sender_email],
            subject=subject,
            body_text=body,
            body_html=html_body,
            from_address=self.default_from,
            in_reply_to=original_email.headers.get('Message-ID'),
            references=original_email.headers.get('References', '') + 
                      ' ' + original_email.headers.get('Message-ID', ''),
            thread_id=original_email.thread_id
        )
    
    def compose_new(
        self,
        to: Union[str, List[str]],
        subject: str,
        body: str,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None
    ) -> ComposedEmail:
        """
        Compose a new email.
        
        Args:
            to: Recipient(s)
            subject: Email subject
            body: Email body
            template_name: Template to use
            context: Template context
            html_body: HTML body
            cc: CC recipients
            bcc: BCC recipients
            attachments: File paths for attachments
            
        Returns:
            ComposedEmail
        """
        recipients = [to] if isinstance(to, str) else to
        
        # Use template if specified
        if template_name and template_name in self.templates:
            template = self.templates[template_name]
            ctx = context or {}
            ctx.setdefault('my_name', self.default_name)
            ctx.setdefault('company_name', self.company_name)
            ctx.setdefault('custom_content', body)
            
            subject, body, html_body = template.render(ctx)
        
        return ComposedEmail(
            to=recipients,
            subject=subject,
            body_text=body,
            body_html=html_body,
            cc=cc or [],
            bcc=bcc or [],
            from_address=self.default_from,
            attachments=attachments or []
        )
    
    def _select_template(
        self,
        template_name: Optional[str],
        sentiment: Optional[SentimentResult],
        categorization: Optional[CategorizationResult]
    ) -> EmailTemplate:
        """Select the most appropriate template."""
        
        # Use specified template
        if template_name and template_name in self.templates:
            return self.templates[template_name]
        
        # Match by category
        if categorization:
            for template in self.templates.values():
                if template.category == categorization.primary_category:
                    return template
        
        # Match by sentiment
        if sentiment:
            sentiment_value = sentiment.sentiment.value
            for template in self.templates.values():
                if template.sentiment_match and sentiment_value in template.sentiment_match:
                    return template
            
            # Handle specific intents
            if sentiment.intent == Intent.COMPLAINT:
                return self.templates.get('complaint_response', 
                                         self.templates['acknowledgment'])
            
            if sentiment.urgency in [Urgency.CRITICAL, Urgency.HIGH]:
                return self.templates.get('urgent_response',
                                         self.templates['acknowledgment'])
        
        # Default to acknowledgment
        return self.templates['acknowledgment']
    
    def _build_context(
        self,
        email: Email,
        sentiment: Optional[SentimentResult],
        custom_content: str
    ) -> Dict[str, Any]:
        """Build template context from email and analysis."""
        
        sender_name = email.sender_name or email.sender.split('@')[0]
        
        context = {
            'original_subject': email.subject,
            'sender_name': sender_name,
            'sender_email': self._extract_email(email.sender),
            'my_name': self.default_name,
            'company_name': self.company_name,
            'custom_content': custom_content,
            'date': datetime.now().strftime('%B %d, %Y'),
            'original_date': email.date.strftime('%B %d, %Y') if email.date else '',
        }
        
        # Add sentiment context
        if sentiment:
            context['sentiment'] = sentiment.sentiment.value
            context['tone'] = sentiment.tone.value
            context['urgency'] = sentiment.urgency.value
            context['intent'] = sentiment.intent.value
            context['summary'] = sentiment.summary
        
        return context
    
    def _extract_email(self, email_str: str) -> str:
        """Extract email address from string."""
        match = re.search(r'<([^>]+)>', email_str)
        if match:
            return match.group(1)
        match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', email_str)
        if match:
            return match.group(0)
        return email_str
    
    def _add_original_quote(self, body: str, original: Email) -> str:
        """Add quoted original message."""
        date_str = original.date.strftime('%a, %b %d, %Y at %I:%M %p') if original.date else ''
        
        quoted = f"\n\nOn {date_str}, {original.sender} wrote:\n"
        original_text = original.get_plain_body()
        
        # Add quote markers
        for line in original_text.split('\n'):
            quoted += f"> {line}\n"
        
        return body + quoted
    
    def _add_original_quote_html(self, html_body: str, original: Email) -> str:
        """Add quoted original message in HTML."""
        date_str = original.date.strftime('%a, %b %d, %Y at %I:%M %p') if original.date else ''
        
        quoted = f"""
<br><br>
<div class="gmail_quote">
    <div>On {date_str}, {original.sender} wrote:</div>
    <blockquote style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex;">
        {original.body_html or original.get_plain_body()}
    </blockquote>
</div>
"""
        return html_body + quoted
    
    def _generate_ai_content(
        self,
        email: Email,
        sentiment: Optional[SentimentResult],
        tone: Tone
    ) -> str:
        """Generate response content using AI."""
        if not self._openai_client:
            return ""
        
        sentiment_info = ""
        if sentiment:
            sentiment_info = f"""
The email has a {sentiment.sentiment.value} sentiment with {sentiment.urgency.value} urgency.
The sender's intent appears to be: {sentiment.intent.value}
Key points from the email: {sentiment.summary}
"""
        
        prompt = f"""Generate a professional email response body.

Original email subject: {email.subject}
Original email content: {email.get_plain_body()[:1000]}
{sentiment_info}

Desired tone: {tone.value}

Generate only the body paragraph(s) of the response. Do not include greetings or sign-offs.
Keep it concise, professional, and helpful."""

        try:
            response = self._openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email writer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"AI content generation failed: {e}")
            return ""
    
    def send_email(self, composed: ComposedEmail) -> SendResult:
        """
        Send a composed email.
        
        Args:
            composed: ComposedEmail to send
            
        Returns:
            SendResult with message ID or error
        """
        if not self.service:
            return SendResult(success=False, error="Gmail service not initialized")
        
        try:
            message = self._create_message(composed)
            
            if composed.is_draft:
                draft = self.service.users().drafts().create(
                    userId=self.user_id,
                    body={'message': message}
                ).execute()
                
                return SendResult(
                    success=True,
                    draft_id=draft['id'],
                    message_id=draft['message']['id']
                )
            else:
                send_body = {'raw': message['raw']}
                
                if composed.thread_id:
                    send_body['threadId'] = composed.thread_id
                
                sent = self.service.users().messages().send(
                    userId=self.user_id,
                    body=send_body
                ).execute()
                
                return SendResult(
                    success=True,
                    message_id=sent['id'],
                    thread_id=sent.get('threadId')
                )
                
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return SendResult(success=False, error=str(e))
    
    def save_draft(self, composed: ComposedEmail) -> SendResult:
        """Save email as draft."""
        composed.is_draft = True
        return self.send_email(composed)
    
    def _create_message(self, composed: ComposedEmail) -> Dict[str, str]:
        """Create Gmail API message from ComposedEmail."""
        
        if composed.body_html:
            message = MIMEMultipart('alternative')
            
            # Add plain text part
            text_part = MIMEText(composed.body_text, 'plain')
            message.attach(text_part)
            
            # Add HTML part
            html_part = MIMEText(composed.body_html, 'html')
            message.attach(html_part)
        else:
            message = MIMEText(composed.body_text)
        
        # Set headers
        message['To'] = ', '.join(composed.to)
        message['Subject'] = composed.subject
        
        if composed.from_address:
            message['From'] = composed.from_address
        
        if composed.cc:
            message['Cc'] = ', '.join(composed.cc)
        
        if composed.reply_to:
            message['Reply-To'] = composed.reply_to
        
        if composed.in_reply_to:
            message['In-Reply-To'] = composed.in_reply_to
        
        if composed.references:
            message['References'] = composed.references
        
        # Add custom headers
        for header, value in composed.headers.items():
            message[header] = value
        
        # Add attachments
        for filepath in composed.attachments:
            self._add_attachment(message, filepath)
        
        # Encode message
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        return {'raw': raw}
    
    def _add_attachment(
        self,
        message: MIMEMultipart,
        filepath: str
    ) -> None:
        """Add attachment to message."""
        path = Path(filepath)
        
        if not path.exists():
            logger.warning(f"Attachment not found: {filepath}")
            return
        
        try:
            with open(path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{path.name}"'
            )
            message.attach(part)
            
        except Exception as e:
            logger.error(f"Failed to add attachment {filepath}: {e}")
    
    def create_batch_response(
        self,
        emails: List[Email],
        sentiment_results: List[SentimentResult],
        custom_content_map: Optional[Dict[str, str]] = None
    ) -> List[ComposedEmail]:
        """
        Create responses for multiple emails.
        
        Args:
            emails: List of emails to respond to
            sentiment_results: Sentiment results for each email
            custom_content_map: Map of email ID to custom content
            
        Returns:
            List of composed emails
        """
        composed = []
        content_map = custom_content_map or {}
        
        # Create lookup for sentiment results
        sentiment_map = {r.email_id: r for r in sentiment_results}
        
        for email in emails:
            sentiment = sentiment_map.get(email.id)
            custom = content_map.get(email.id, "")
            
            try:
                response = self.compose_response(
                    email,
                    sentiment_result=sentiment,
                    custom_content=custom
                )
                composed.append(response)
            except Exception as e:
                logger.error(f"Failed to compose response for {email.id}: {e}")
        
        return composed
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List available templates."""
        return [
            {
                'name': t.name,
                'description': t.description,
                'tone': t.tone.value,
                'category': t.category,
                'sentiment_match': t.sentiment_match
            }
            for t in self.templates.values()
        ]


if __name__ == "__main__":
    # Example usage
    composer = EmailComposer(
        default_name="John Smith",
        company_name="Acme Corp"
    )
    
    # List available templates
    print("Available templates:")
    for t in composer.list_templates():
        print(f"  - {t['name']}: {t['description']}")
    
    # Create a new email
    email = composer.compose_new(
        to="recipient@example.com",
        subject="Hello from Gmail Automation",
        body="This is a test email from the Gmail Automation system."
    )
    
    print(f"\nComposed email: {email.to_dict()}")
