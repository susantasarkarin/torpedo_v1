"""
Gmail Authentication Module

Handles OAuth 2.0 authentication with Gmail API.
Manages token storage, refresh, and credential validation.

Usage:
    from gmail_automation.auth import GmailAuthenticator
    
    auth = GmailAuthenticator(credentials_path="credentials.json")
    service = auth.authenticate()
"""

import os
import pickle
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GmailAuthenticator:
    """
    Handles Gmail API OAuth 2.0 authentication.
    
    Attributes:
        credentials_path (str): Path to the OAuth credentials JSON file
        token_path (str): Path to store the access token
        scopes (List[str]): Gmail API scopes required
    """
    
    # Default scopes for full Gmail access
    DEFAULT_SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.compose',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.labels'
    ]
    
    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.pickle",
        scopes: Optional[List[str]] = None,
        config_dir: Optional[str] = None
    ):
        """
        Initialize the Gmail Authenticator.
        
        Args:
            credentials_path: Path to OAuth 2.0 credentials JSON file
            token_path: Path to store the authentication token
            scopes: List of Gmail API scopes (uses defaults if not provided)
            config_dir: Directory for storing configuration files
        """
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".gmail_automation"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.credentials_path = self._resolve_path(credentials_path)
        self.token_path = self.config_dir / token_path
        self.scopes = scopes or self.DEFAULT_SCOPES
        self._service: Optional[Resource] = None
        self._credentials: Optional[Credentials] = None
        
    def _resolve_path(self, path: str) -> Path:
        """Resolve path, checking config dir and current directory."""
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        
        # Check config directory first
        config_path = self.config_dir / path
        if config_path.exists():
            return config_path
        
        # Fall back to current directory
        return path_obj
    
    def authenticate(self, force_refresh: bool = False) -> Resource:
        """
        Authenticate with Gmail API and return the service object.
        
        Args:
            force_refresh: Force token refresh even if valid token exists
            
        Returns:
            Gmail API service resource
            
        Raises:
            FileNotFoundError: If credentials file is not found
            AuthenticationError: If authentication fails
        """
        logger.info("Starting Gmail authentication...")
        
        self._credentials = self._get_valid_credentials(force_refresh)
        
        if not self._credentials:
            self._credentials = self._perform_oauth_flow()
            self._save_token()
        
        self._service = build('gmail', 'v1', credentials=self._credentials)
        logger.info("Gmail authentication successful")
        
        return self._service
    
    def _get_valid_credentials(self, force_refresh: bool) -> Optional[Credentials]:
        """
        Retrieve valid credentials from stored token.
        
        Args:
            force_refresh: Force token refresh
            
        Returns:
            Valid credentials or None if not available
        """
        if force_refresh:
            return None
            
        if not self.token_path.exists():
            logger.info("No stored token found")
            return None
        
        try:
            with open(self.token_path, 'rb') as token_file:
                credentials = pickle.load(token_file)
                
            if credentials.valid:
                logger.info("Using valid stored credentials")
                return credentials
                
            if credentials.expired and credentials.refresh_token:
                logger.info("Refreshing expired credentials...")
                credentials.refresh(Request())
                self._credentials = credentials
                self._save_token()
                return credentials
                
        except Exception as e:
            logger.warning(f"Failed to load stored credentials: {e}")
            
        return None
    
    def _perform_oauth_flow(self) -> Credentials:
        """
        Perform the OAuth 2.0 authentication flow.
        
        Returns:
            New OAuth credentials
            
        Raises:
            FileNotFoundError: If credentials file is missing
        """
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_path}\n"
                "Please download OAuth 2.0 credentials from Google Cloud Console:\n"
                "1. Go to https://console.cloud.google.com/\n"
                "2. Create a project and enable Gmail API\n"
                "3. Create OAuth 2.0 credentials (Desktop App)\n"
                "4. Download and save as 'credentials.json'"
            )
        
        logger.info("Starting OAuth flow - browser will open for authentication")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_path),
            self.scopes
        )
        
        # Run local server for OAuth callback
        credentials = flow.run_local_server(
            port=0,
            authorization_prompt_message="Opening browser for Gmail authentication...",
            success_message="Authentication successful! You may close this window.",
            open_browser=True
        )
        
        return credentials
    
    def _save_token(self) -> None:
        """Save credentials to token file."""
        try:
            with open(self.token_path, 'wb') as token_file:
                pickle.dump(self._credentials, token_file)
            logger.info(f"Token saved to {self.token_path}")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
    
    def revoke_credentials(self) -> bool:
        """
        Revoke the current credentials and delete stored token.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if self._credentials:
                from google.auth.transport.requests import Request as AuthRequest
                self._credentials.revoke(AuthRequest())
                
            if self.token_path.exists():
                self.token_path.unlink()
                
            self._credentials = None
            self._service = None
            logger.info("Credentials revoked successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke credentials: {e}")
            return False
    
    def get_service(self) -> Resource:
        """
        Get the Gmail API service, authenticating if necessary.
        
        Returns:
            Gmail API service resource
        """
        if self._service is None:
            return self.authenticate()
        return self._service
    
    def get_user_email(self) -> str:
        """
        Get the authenticated user's email address.
        
        Returns:
            User's email address
        """
        service = self.get_service()
        profile = service.users().getProfile(userId='me').execute()
        return profile.get('emailAddress', '')
    
    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated with valid credentials.
        
        Returns:
            True if authenticated, False otherwise
        """
        return self._credentials is not None and self._credentials.valid
    
    def get_token_info(self) -> dict:
        """
        Get information about the current token.
        
        Returns:
            Dictionary with token information
        """
        if not self._credentials:
            return {"authenticated": False}
            
        return {
            "authenticated": True,
            "valid": self._credentials.valid,
            "expired": self._credentials.expired,
            "expiry": str(self._credentials.expiry) if self._credentials.expiry else None,
            "scopes": list(self._credentials.scopes) if self._credentials.scopes else []
        }


class MultiAccountAuthenticator:
    """
    Manage authentication for multiple Gmail accounts.
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize multi-account authenticator.
        
        Args:
            config_dir: Directory for storing configuration files
        """
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".gmail_automation"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._authenticators: dict[str, GmailAuthenticator] = {}
        
    def add_account(
        self,
        account_id: str,
        credentials_path: str = "credentials.json"
    ) -> GmailAuthenticator:
        """
        Add a new Gmail account for authentication.
        
        Args:
            account_id: Unique identifier for this account
            credentials_path: Path to OAuth credentials for this account
            
        Returns:
            GmailAuthenticator instance for the account
        """
        token_path = f"token_{account_id}.pickle"
        
        auth = GmailAuthenticator(
            credentials_path=credentials_path,
            token_path=token_path,
            config_dir=str(self.config_dir)
        )
        
        self._authenticators[account_id] = auth
        logger.info(f"Added account: {account_id}")
        
        return auth
    
    def authenticate_account(self, account_id: str) -> Resource:
        """
        Authenticate a specific account.
        
        Args:
            account_id: Account identifier
            
        Returns:
            Gmail API service for the account
        """
        if account_id not in self._authenticators:
            raise ValueError(f"Account not found: {account_id}")
            
        return self._authenticators[account_id].authenticate()
    
    def authenticate_all(self) -> dict[str, Resource]:
        """
        Authenticate all registered accounts.
        
        Returns:
            Dictionary mapping account IDs to their services
        """
        services = {}
        for account_id, auth in self._authenticators.items():
            try:
                services[account_id] = auth.authenticate()
            except Exception as e:
                logger.error(f"Failed to authenticate {account_id}: {e}")
        return services
    
    def get_account(self, account_id: str) -> Optional[GmailAuthenticator]:
        """Get authenticator for specific account."""
        return self._authenticators.get(account_id)
    
    def list_accounts(self) -> List[str]:
        """List all registered account IDs."""
        return list(self._authenticators.keys())
    
    def remove_account(self, account_id: str) -> bool:
        """
        Remove an account and its stored credentials.
        
        Args:
            account_id: Account to remove
            
        Returns:
            True if successful
        """
        if account_id in self._authenticators:
            self._authenticators[account_id].revoke_credentials()
            del self._authenticators[account_id]
            return True
        return False


if __name__ == "__main__":
    # Example usage
    auth = GmailAuthenticator()
    
    try:
        service = auth.authenticate()
        email = auth.get_user_email()
        print(f"Authenticated as: {email}")
        print(f"Token info: {auth.get_token_info()}")
    except FileNotFoundError as e:
        print(f"Setup required: {e}")
