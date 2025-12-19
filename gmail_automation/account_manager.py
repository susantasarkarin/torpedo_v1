"""
Account Manager Module

Manages multiple email accounts, aliases, and sending configurations.
Handles account selection, alias management, and routing rules.

Usage:
    from gmail_automation.account_manager import AccountManager
    
    manager = AccountManager()
    manager.add_account("primary", "credentials.json")
    manager.add_alias("primary", "sales@company.com", "Sales Team")
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .auth import GmailAuthenticator, MultiAccountAuthenticator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmailAlias:
    """
    Represents an email alias/send-as address.
    
    Attributes:
        email: Alias email address
        display_name: Display name for this alias
        is_default: Whether this is the default sending address
        is_primary: Whether this is the primary account address
        reply_to: Reply-to address for this alias
        signature: Email signature for this alias
        treat_as_alias: Gmail send-as setting
        verification_status: Verification status
    """
    email: str
    display_name: str = ""
    is_default: bool = False
    is_primary: bool = False
    reply_to: Optional[str] = None
    signature: str = ""
    treat_as_alias: bool = True
    verification_status: str = "verified"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'email': self.email,
            'display_name': self.display_name,
            'is_default': self.is_default,
            'is_primary': self.is_primary,
            'reply_to': self.reply_to,
            'signature': self.signature[:100] + '...' if len(self.signature) > 100 else self.signature,
            'verification_status': self.verification_status
        }


@dataclass
class EmailAccount:
    """
    Represents a Gmail account with its configuration.
    
    Attributes:
        id: Unique account identifier
        email: Primary email address
        display_name: Account display name
        aliases: List of send-as aliases
        is_active: Whether account is active
        daily_limit: Daily sending limit
        sent_today: Emails sent today
        authenticator: Associated GmailAuthenticator
        metadata: Additional account metadata
    """
    id: str
    email: str
    display_name: str = ""
    aliases: List[EmailAlias] = field(default_factory=list)
    is_active: bool = True
    daily_limit: int = 500
    sent_today: int = 0
    last_reset: datetime = field(default_factory=datetime.now)
    authenticator: Optional[GmailAuthenticator] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize primary alias if not present."""
        if self.email and not any(a.is_primary for a in self.aliases):
            self.aliases.insert(0, EmailAlias(
                email=self.email,
                display_name=self.display_name,
                is_default=True,
                is_primary=True
            ))
    
    def get_default_alias(self) -> Optional[EmailAlias]:
        """Get the default sending alias."""
        for alias in self.aliases:
            if alias.is_default:
                return alias
        return self.aliases[0] if self.aliases else None
    
    def get_alias(self, email: str) -> Optional[EmailAlias]:
        """Get alias by email address."""
        for alias in self.aliases:
            if alias.email.lower() == email.lower():
                return alias
        return None
    
    def can_send(self) -> bool:
        """Check if account can send (under daily limit)."""
        self._check_limit_reset()
        return self.is_active and self.sent_today < self.daily_limit
    
    def record_send(self, count: int = 1) -> None:
        """Record that emails were sent."""
        self._check_limit_reset()
        self.sent_today += count
    
    def _check_limit_reset(self) -> None:
        """Reset daily counter if needed."""
        now = datetime.now()
        if now.date() > self.last_reset.date():
            self.sent_today = 0
            self.last_reset = now
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'email': self.email,
            'display_name': self.display_name,
            'aliases': [a.to_dict() for a in self.aliases],
            'is_active': self.is_active,
            'daily_limit': self.daily_limit,
            'sent_today': self.sent_today,
            'can_send': self.can_send()
        }


@dataclass
class RoutingRule:
    """
    Rule for routing emails to specific accounts/aliases.
    
    Attributes:
        name: Rule name
        account_id: Target account
        alias_email: Target alias (optional)
        sender_patterns: Match incoming sender patterns
        recipient_patterns: Match recipients for outgoing
        category_match: Match email categories
        priority: Rule priority (lower = higher priority)
    """
    name: str
    account_id: str
    alias_email: Optional[str] = None
    sender_patterns: List[str] = field(default_factory=list)
    recipient_patterns: List[str] = field(default_factory=list)
    category_match: List[str] = field(default_factory=list)
    priority: int = 100


class AccountManager:
    """
    Manages multiple Gmail accounts and aliases.
    
    Handles account switching, alias management, and
    intelligent routing for multi-account setups.
    """
    
    def __init__(
        self,
        config_dir: Optional[str] = None,
        auto_load: bool = True
    ):
        """
        Initialize Account Manager.
        
        Args:
            config_dir: Directory for configuration files
            auto_load: Automatically load saved configuration
        """
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".gmail_automation"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.accounts: Dict[str, EmailAccount] = {}
        self.routing_rules: List[RoutingRule] = []
        self.default_account_id: Optional[str] = None
        
        self._multi_auth = MultiAccountAuthenticator(str(self.config_dir))
        
        if auto_load:
            self._load_config()
    
    def add_account(
        self,
        account_id: str,
        credentials_path: str = "credentials.json",
        display_name: str = "",
        authenticate_now: bool = True
    ) -> EmailAccount:
        """
        Add a new Gmail account.
        
        Args:
            account_id: Unique identifier for the account
            credentials_path: Path to OAuth credentials
            display_name: Display name for the account
            authenticate_now: Immediately authenticate
            
        Returns:
            EmailAccount instance
        """
        if account_id in self.accounts:
            logger.warning(f"Account {account_id} already exists")
            return self.accounts[account_id]
        
        # Set up authenticator
        auth = self._multi_auth.add_account(account_id, credentials_path)
        
        # Get email address if authenticating now
        email = ""
        if authenticate_now:
            try:
                auth.authenticate()
                email = auth.get_user_email()
            except Exception as e:
                logger.error(f"Failed to authenticate {account_id}: {e}")
        
        # Create account
        account = EmailAccount(
            id=account_id,
            email=email,
            display_name=display_name or account_id,
            authenticator=auth
        )
        
        self.accounts[account_id] = account
        
        # Set as default if first account
        if not self.default_account_id:
            self.default_account_id = account_id
        
        self._save_config()
        logger.info(f"Added account: {account_id} ({email})")
        
        return account
    
    def remove_account(self, account_id: str) -> bool:
        """
        Remove an account.
        
        Args:
            account_id: Account to remove
            
        Returns:
            True if removed
        """
        if account_id not in self.accounts:
            return False
        
        # Revoke credentials
        self._multi_auth.remove_account(account_id)
        
        # Remove account
        del self.accounts[account_id]
        
        # Update default if needed
        if self.default_account_id == account_id:
            self.default_account_id = next(iter(self.accounts.keys()), None)
        
        self._save_config()
        logger.info(f"Removed account: {account_id}")
        return True
    
    def get_account(self, account_id: str) -> Optional[EmailAccount]:
        """Get account by ID."""
        return self.accounts.get(account_id)
    
    def get_default_account(self) -> Optional[EmailAccount]:
        """Get the default account."""
        if self.default_account_id:
            return self.accounts.get(self.default_account_id)
        return None
    
    def set_default_account(self, account_id: str) -> bool:
        """Set the default account."""
        if account_id not in self.accounts:
            return False
        self.default_account_id = account_id
        self._save_config()
        return True
    
    def list_accounts(self) -> List[Dict[str, Any]]:
        """List all accounts."""
        return [
            {**a.to_dict(), 'is_default': a.id == self.default_account_id}
            for a in self.accounts.values()
        ]
    
    def add_alias(
        self,
        account_id: str,
        email: str,
        display_name: str = "",
        signature: str = "",
        is_default: bool = False,
        sync_from_gmail: bool = True
    ) -> Optional[EmailAlias]:
        """
        Add an alias to an account.
        
        Args:
            account_id: Account to add alias to
            email: Alias email address
            display_name: Display name
            signature: Email signature
            is_default: Set as default sending address
            sync_from_gmail: Sync settings from Gmail
            
        Returns:
            EmailAlias if successful
        """
        account = self.accounts.get(account_id)
        if not account:
            logger.error(f"Account not found: {account_id}")
            return None
        
        # Check if alias already exists
        existing = account.get_alias(email)
        if existing:
            logger.warning(f"Alias already exists: {email}")
            return existing
        
        alias = EmailAlias(
            email=email,
            display_name=display_name,
            signature=signature,
            is_default=is_default
        )
        
        # If setting as default, unset other defaults
        if is_default:
            for a in account.aliases:
                a.is_default = False
        
        account.aliases.append(alias)
        
        # Sync with Gmail if requested
        if sync_from_gmail:
            self._sync_alias_from_gmail(account, alias)
        
        self._save_config()
        logger.info(f"Added alias: {email} to {account_id}")
        
        return alias
    
    def remove_alias(self, account_id: str, email: str) -> bool:
        """Remove an alias."""
        account = self.accounts.get(account_id)
        if not account:
            return False
        
        # Can't remove primary
        alias = account.get_alias(email)
        if alias and alias.is_primary:
            logger.error("Cannot remove primary address")
            return False
        
        account.aliases = [a for a in account.aliases if a.email.lower() != email.lower()]
        self._save_config()
        return True
    
    def _sync_alias_from_gmail(
        self,
        account: EmailAccount,
        alias: EmailAlias
    ) -> None:
        """Sync alias settings from Gmail."""
        if not account.authenticator:
            return
        
        try:
            service = account.authenticator.get_service()
            send_as = service.users().settings().sendAs().get(
                userId='me',
                sendAsEmail=alias.email
            ).execute()
            
            alias.display_name = send_as.get('displayName', alias.display_name)
            alias.signature = send_as.get('signature', alias.signature)
            alias.reply_to = send_as.get('replyToAddress')
            alias.treat_as_alias = send_as.get('treatAsAlias', True)
            alias.is_default = send_as.get('isDefault', False)
            alias.is_primary = send_as.get('isPrimary', False)
            alias.verification_status = send_as.get('verificationStatus', 'accepted')
            
        except Exception as e:
            logger.debug(f"Could not sync alias from Gmail: {e}")
    
    def sync_all_aliases(self, account_id: str) -> List[EmailAlias]:
        """
        Sync all send-as addresses from Gmail.
        
        Args:
            account_id: Account to sync
            
        Returns:
            List of synced aliases
        """
        account = self.accounts.get(account_id)
        if not account or not account.authenticator:
            return []
        
        try:
            service = account.authenticator.get_service()
            response = service.users().settings().sendAs().list(
                userId='me'
            ).execute()
            
            # Update existing and add new
            for send_as in response.get('sendAs', []):
                email = send_as.get('sendAsEmail')
                existing = account.get_alias(email)
                
                if existing:
                    existing.display_name = send_as.get('displayName', '')
                    existing.signature = send_as.get('signature', '')
                    existing.reply_to = send_as.get('replyToAddress')
                    existing.is_default = send_as.get('isDefault', False)
                    existing.is_primary = send_as.get('isPrimary', False)
                    existing.verification_status = send_as.get('verificationStatus', '')
                else:
                    alias = EmailAlias(
                        email=email,
                        display_name=send_as.get('displayName', ''),
                        signature=send_as.get('signature', ''),
                        reply_to=send_as.get('replyToAddress'),
                        is_default=send_as.get('isDefault', False),
                        is_primary=send_as.get('isPrimary', False),
                        verification_status=send_as.get('verificationStatus', '')
                    )
                    account.aliases.append(alias)
            
            self._save_config()
            return account.aliases
            
        except Exception as e:
            logger.error(f"Failed to sync aliases: {e}")
            return []
    
    def add_routing_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule."""
        self.routing_rules.append(rule)
        self.routing_rules.sort(key=lambda r: r.priority)
        self._save_config()
    
    def get_sending_address(
        self,
        recipient: Optional[str] = None,
        category: Optional[str] = None,
        account_id: Optional[str] = None
    ) -> Optional[tuple[EmailAccount, EmailAlias]]:
        """
        Get the appropriate sending address based on context.
        
        Args:
            recipient: Email recipient
            category: Email category
            account_id: Specific account to use
            
        Returns:
            Tuple of (account, alias) or None
        """
        import re
        
        # If specific account requested
        if account_id:
            account = self.accounts.get(account_id)
            if account and account.can_send():
                return account, account.get_default_alias()
            return None
        
        # Check routing rules
        for rule in self.routing_rules:
            account = self.accounts.get(rule.account_id)
            if not account or not account.can_send():
                continue
            
            matched = False
            
            # Check recipient patterns
            if recipient and rule.recipient_patterns:
                for pattern in rule.recipient_patterns:
                    if re.search(pattern, recipient, re.IGNORECASE):
                        matched = True
                        break
            
            # Check category
            if category and rule.category_match:
                if category in rule.category_match:
                    matched = True
            
            if matched:
                alias = account.get_alias(rule.alias_email) if rule.alias_email else account.get_default_alias()
                return account, alias
        
        # Fall back to default account
        default = self.get_default_account()
        if default and default.can_send():
            return default, default.get_default_alias()
        
        # Find any account that can send
        for account in self.accounts.values():
            if account.can_send():
                return account, account.get_default_alias()
        
        return None
    
    def get_service(self, account_id: Optional[str] = None):
        """
        Get Gmail service for an account.
        
        Args:
            account_id: Account ID (uses default if not specified)
            
        Returns:
            Gmail API service
        """
        account_id = account_id or self.default_account_id
        if not account_id:
            raise ValueError("No account specified and no default set")
        
        account = self.accounts.get(account_id)
        if not account or not account.authenticator:
            raise ValueError(f"Account not found or not authenticated: {account_id}")
        
        return account.authenticator.get_service()
    
    def authenticate_all(self) -> Dict[str, bool]:
        """
        Authenticate all accounts.
        
        Returns:
            Dictionary of account ID to success status
        """
        results = {}
        
        for account_id, account in self.accounts.items():
            try:
                if account.authenticator:
                    account.authenticator.authenticate()
                    account.email = account.authenticator.get_user_email()
                    results[account_id] = True
                else:
                    results[account_id] = False
            except Exception as e:
                logger.error(f"Failed to authenticate {account_id}: {e}")
                results[account_id] = False
        
        return results
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for all accounts."""
        stats = {
            'total_accounts': len(self.accounts),
            'active_accounts': sum(1 for a in self.accounts.values() if a.is_active),
            'total_aliases': sum(len(a.aliases) for a in self.accounts.values()),
            'total_sent_today': sum(a.sent_today for a in self.accounts.values()),
            'total_daily_limit': sum(a.daily_limit for a in self.accounts.values()),
            'accounts': {}
        }
        
        for account_id, account in self.accounts.items():
            stats['accounts'][account_id] = {
                'email': account.email,
                'sent_today': account.sent_today,
                'daily_limit': account.daily_limit,
                'remaining': account.daily_limit - account.sent_today,
                'can_send': account.can_send(),
                'alias_count': len(account.aliases)
            }
        
        return stats
    
    def _save_config(self) -> None:
        """Save configuration to file."""
        config_path = self.config_dir / "accounts.json"
        
        config = {
            'default_account_id': self.default_account_id,
            'accounts': {},
            'routing_rules': []
        }
        
        for account_id, account in self.accounts.items():
            config['accounts'][account_id] = {
                'email': account.email,
                'display_name': account.display_name,
                'is_active': account.is_active,
                'daily_limit': account.daily_limit,
                'aliases': [
                    {
                        'email': a.email,
                        'display_name': a.display_name,
                        'is_default': a.is_default,
                        'is_primary': a.is_primary,
                        'signature': a.signature,
                        'reply_to': a.reply_to
                    }
                    for a in account.aliases
                ],
                'metadata': account.metadata
            }
        
        for rule in self.routing_rules:
            config['routing_rules'].append({
                'name': rule.name,
                'account_id': rule.account_id,
                'alias_email': rule.alias_email,
                'sender_patterns': rule.sender_patterns,
                'recipient_patterns': rule.recipient_patterns,
                'category_match': rule.category_match,
                'priority': rule.priority
            })
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    def _load_config(self) -> None:
        """Load configuration from file."""
        config_path = self.config_dir / "accounts.json"
        
        if not config_path.exists():
            return
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            self.default_account_id = config.get('default_account_id')
            
            # Load accounts
            for account_id, account_data in config.get('accounts', {}).items():
                # Set up authenticator
                auth = self._multi_auth.add_account(account_id)
                
                # Create aliases
                aliases = []
                for alias_data in account_data.get('aliases', []):
                    aliases.append(EmailAlias(
                        email=alias_data['email'],
                        display_name=alias_data.get('display_name', ''),
                        is_default=alias_data.get('is_default', False),
                        is_primary=alias_data.get('is_primary', False),
                        signature=alias_data.get('signature', ''),
                        reply_to=alias_data.get('reply_to')
                    ))
                
                # Create account
                account = EmailAccount(
                    id=account_id,
                    email=account_data.get('email', ''),
                    display_name=account_data.get('display_name', ''),
                    aliases=aliases,
                    is_active=account_data.get('is_active', True),
                    daily_limit=account_data.get('daily_limit', 500),
                    authenticator=auth,
                    metadata=account_data.get('metadata', {})
                )
                
                self.accounts[account_id] = account
            
            # Load routing rules
            for rule_data in config.get('routing_rules', []):
                self.routing_rules.append(RoutingRule(
                    name=rule_data['name'],
                    account_id=rule_data['account_id'],
                    alias_email=rule_data.get('alias_email'),
                    sender_patterns=rule_data.get('sender_patterns', []),
                    recipient_patterns=rule_data.get('recipient_patterns', []),
                    category_match=rule_data.get('category_match', []),
                    priority=rule_data.get('priority', 100)
                ))
            
            self.routing_rules.sort(key=lambda r: r.priority)
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}")


if __name__ == "__main__":
    # Example usage
    manager = AccountManager()
    
    print("Current accounts:", manager.list_accounts())
    print("Usage stats:", manager.get_usage_stats())
