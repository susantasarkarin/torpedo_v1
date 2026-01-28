"""
LinkedIn Automation Service using Playwright.
Handles connection requests and messaging with anti-detection measures.

REQUIREMENTS:
    pip install playwright
    playwright install chromium

DAILY LIMITS:
    - Connection requests: 100/day
    - Messages: 50/day
    
FEATURES:
    - Persistent browser sessions (cookie-based)
    - Manual 2FA handling (headed browser)
    - Anti-detection: random delays, human-like scrolling
    - Rate limiting with DB tracking
"""

import os
import json
import asyncio
import random
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class LinkedInAutomationService:
    """
    LinkedIn automation service for connection requests and messaging.
    Uses Playwright for browser automation with anti-detection measures.
    """
    
    # Daily limits
    MAX_CONNECTIONS_PER_DAY = 100
    MAX_MESSAGES_PER_DAY = 50
    
    # Collections
    SESSION_COLLECTION = "linkedin_sessions"
    CONNECTIONS_COLLECTION = "linkedin_connections"
    MESSAGES_COLLECTION = "linkedin_messages"
    ACTIVITY_COLLECTION = "linkedin_activity"
    
    def __init__(self, db, storage_dir: str = "./linkedin_sessions"):
        """
        Initialize LinkedIn automation service.
        
        Args:
            db: MongoDB database connection
            storage_dir: Directory to store browser session data
        """
        self.db = db
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        self.session_id = None
        self.email = None
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        await self.close()
    
    async def initialize_session(self, email: str, headless: bool = False) -> bool:
        """
        Initialize browser session for LinkedIn automation.
        Loads existing cookies if available.
        
        Args:
            email: LinkedIn account email
            headless: Run browser in headless mode (default: False for 2FA)
            
        Returns:
            True if session initialized successfully
        """
        try:
            self.email = email
            self.session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
            
            # Start Playwright
            self.playwright = await async_playwright().start()
            
            # Launch browser
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )
            
            # Create context with persistent storage
            storage_file = self.storage_dir / f"{self.session_id}_state.json"
            
            if storage_file.exists():
                logger.info(f"Loading existing session for {email}")
                self.context = await self.browser.new_context(storage_state=str(storage_file))
            else:
                logger.info(f"Creating new session for {email}")
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
            
            # Create page
            self.page = await self.context.new_page()
            
            # Set extra headers to avoid detection
            await self.page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
            })
            
            logger.info(f"LinkedIn session initialized for {email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            return False
    
    async def login(self, email: str, password: str, headless: bool = False) -> bool:
        """
        Login to LinkedIn. Handles 2FA if needed (waits for manual input).
        
        Args:
            email: LinkedIn email
            password: LinkedIn password
            headless: Run in headless mode (not recommended for first login due to 2FA)
            
        Returns:
            True if login successful
        """
        try:
            if not self.page:
                await self.initialize_session(email, headless)
            
            logger.info(f"Logging in to LinkedIn as {email}")
            
            # Navigate to LinkedIn login page
            await self.page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded')
            await self._random_delay(2, 4)
            
            # Fill email
            await self.page.fill('input#username', email)
            await self._random_delay(0.5, 1.5)
            
            # Fill password
            await self.page.fill('input#password', password)
            await self._random_delay(0.5, 1.5)
            
            # Click login button
            await self.page.click('button[type="submit"]')
            
            # Wait for navigation
            await self._random_delay(3, 5)
            
            # Check if 2FA is required
            current_url = self.page.url
            if 'checkpoint' in current_url or 'challenge' in current_url:
                logger.warning("2FA detected. Please complete verification manually.")
                logger.warning("Waiting up to 120 seconds for manual 2FA completion...")
                
                # Wait for user to complete 2FA (max 2 minutes)
                try:
                    await self.page.wait_for_url('https://www.linkedin.com/feed/', timeout=120000)
                    logger.info("2FA completed successfully")
                except PlaywrightTimeout:
                    logger.error("2FA timeout - login may have failed")
                    return False
            
            # Verify we're logged in (check for feed or profile)
            await self._random_delay(2, 3)
            
            if 'feed' in self.page.url or 'in/' in self.page.url:
                logger.info("Login successful")
                
                # Save session state
                await self._save_session_state()
                
                # Update database
                await self._update_session_record()
                
                return True
            else:
                logger.error("Login verification failed - unexpected URL")
                return False
                
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    async def send_connection_request(
        self,
        profile_url: str,
        note: str = "",
        lead_id: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Send a connection request to a LinkedIn profile.
        
        Args:
            profile_url: Full LinkedIn profile URL
            note: Personalized connection note (max 150 chars)
            lead_id: Optional lead ID for tracking
            
        Returns:
            Dict with status and details
        """
        try:
            # Check daily limit
            if not await self._check_connection_limit():
                return {
                    "success": False,
                    "error": "Daily connection limit reached (100/day)",
                    "profile_url": profile_url
                }
            
            logger.info(f"Sending connection request to {profile_url}")
            
            # Navigate to profile
            await self.page.goto(profile_url, wait_until='domcontentloaded')
            await self._random_delay(2, 4)
            
            # Scroll to simulate human behavior
            await self._human_scroll()
            
            # Find and click Connect button
            connect_button = None
            connect_selectors = [
                'button:has-text("Connect")',
                'button[aria-label*="Connect"]',
                'button.pvs-profile-actions__action:has-text("Connect")'
            ]
            
            for selector in connect_selectors:
                try:
                    connect_button = await self.page.wait_for_selector(selector, timeout=5000)
                    if connect_button:
                        break
                except:
                    continue
            
            if not connect_button:
                return {
                    "success": False,
                    "error": "Connect button not found - may already be connected",
                    "profile_url": profile_url
                }
            
            await connect_button.click()
            await self._random_delay(1, 2)
            
            # Check if note dialog appears
            try:
                add_note_button = await self.page.wait_for_selector(
                    'button:has-text("Add a note")',
                    timeout=3000
                )
                
                if add_note_button and note:
                    # Truncate note to 150 chars
                    note = note[:150]
                    
                    await add_note_button.click()
                    await self._random_delay(0.5, 1)
                    
                    # Fill note
                    note_textarea = await self.page.wait_for_selector('textarea[name="message"]')
                    await note_textarea.fill(note)
                    await self._random_delay(0.5, 1)
                    
                    # Click Send
                    send_button = await self.page.wait_for_selector('button:has-text("Send")')
                    await send_button.click()
                else:
                    # No note option or no note provided, just send
                    send_button = await self.page.wait_for_selector('button:has-text("Send")')
                    await send_button.click()
                    
            except PlaywrightTimeout:
                # Sometimes connect happens without dialog
                logger.warning("No note dialog appeared, connection may have been sent directly")
            
            await self._random_delay(2, 3)
            
            # Record in database
            connection_record = {
                "lead_id": lead_id,
                "linkedin_url": profile_url,
                "status": "pending",
                "connection_note": note if note else None,
                "sent_at": datetime.utcnow(),
                "session_id": self.session_id,
                "accepted_at": None,
                "rejected_at": None
            }
            
            self.db[self.CONNECTIONS_COLLECTION].insert_one(connection_record)
            
            # Update activity counter
            await self._increment_activity_counter("connections_sent")
            
            logger.info(f"Connection request sent successfully to {profile_url}")
            
            return {
                "success": True,
                "profile_url": profile_url,
                "note": note,
                "sent_at": connection_record["sent_at"]
            }
            
        except Exception as e:
            logger.error(f"Failed to send connection request: {e}")
            return {
                "success": False,
                "error": str(e),
                "profile_url": profile_url
            }
    
    async def send_message(
        self,
        connection_name: str,
        message: str,
        lead_id: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Send a message to a 1st-degree connection.
        
        Args:
            connection_name: Name of the connection to message
            message: Message content
            lead_id: Optional lead ID for tracking
            
        Returns:
            Dict with status and details
        """
        try:
            # Check daily limit
            if not await self._check_message_limit():
                return {
                    "success": False,
                    "error": "Daily message limit reached (50/day)",
                    "connection_name": connection_name
                }
            
            logger.info(f"Sending message to {connection_name}")
            
            # Navigate to messages
            await self.page.goto('https://www.linkedin.com/messaging/', wait_until='domcontentloaded')
            await self._random_delay(2, 4)
            
            # Search for connection
            search_input = await self.page.wait_for_selector('input[placeholder*="Search"]')
            await search_input.fill(connection_name)
            await self._random_delay(1, 2)
            
            # Click on first result
            first_result = await self.page.wait_for_selector('.msg-conversation-listitem')
            await first_result.click()
            await self._random_delay(1, 2)
            
            # Find message input
            message_input = await self.page.wait_for_selector('.msg-form__contenteditable')
            await message_input.click()
            await self._random_delay(0.5, 1)
            
            # Type message with human-like typing
            await message_input.type(message, delay=random.randint(50, 150))
            await self._random_delay(0.5, 1)
            
            # Send message
            send_button = await self.page.wait_for_selector('button[type="submit"]')
            await send_button.click()
            await self._random_delay(2, 3)
            
            # Record in database
            message_record = {
                "lead_id": lead_id,
                "connection_name": connection_name,
                "message_content": message,
                "sent_at": datetime.utcnow(),
                "session_id": self.session_id,
                "read_at": None,
                "replied_at": None
            }
            
            self.db[self.MESSAGES_COLLECTION].insert_one(message_record)
            
            # Update activity counter
            await self._increment_activity_counter("messages_sent")
            
            logger.info(f"Message sent successfully to {connection_name}")
            
            return {
                "success": True,
                "connection_name": connection_name,
                "sent_at": message_record["sent_at"]
            }
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {
                "success": False,
                "error": str(e),
                "connection_name": connection_name
            }
    
    async def get_activity_stats(self, date: Optional[str] = None) -> Dict[str, any]:
        """
        Get activity statistics for a specific date.
        
        Args:
            date: Date string in YYYY-MM-DD format (default: today)
            
        Returns:
            Dict with activity stats
        """
        if not date:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            activity = self.db[self.ACTIVITY_COLLECTION].find_one({
                "session_id": self.session_id,
                "date": date
            })
            
            if not activity:
                return {
                    "date": date,
                    "connections_sent": 0,
                    "messages_sent": 0,
                    "connections_remaining": self.MAX_CONNECTIONS_PER_DAY,
                    "messages_remaining": self.MAX_MESSAGES_PER_DAY
                }
            
            return {
                "date": date,
                "connections_sent": activity.get("connections_sent", 0),
                "messages_sent": activity.get("messages_sent", 0),
                "connections_remaining": self.MAX_CONNECTIONS_PER_DAY - activity.get("connections_sent", 0),
                "messages_remaining": self.MAX_MESSAGES_PER_DAY - activity.get("messages_sent", 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to get activity stats: {e}")
            return {
                "date": date,
                "connections_sent": 0,
                "messages_sent": 0,
                "error": str(e)
            }
    
    # ==================== PRIVATE HELPER METHODS ====================
    
    async def _save_session_state(self):
        """Save browser session state (cookies, localStorage) to file."""
        try:
            storage_file = self.storage_dir / f"{self.session_id}_state.json"
            await self.context.storage_state(path=str(storage_file))
            logger.info(f"Session state saved to {storage_file}")
        except Exception as e:
            logger.error(f"Failed to save session state: {e}")
    
    async def _update_session_record(self):
        """Update session record in database."""
        try:
            self.db[self.SESSION_COLLECTION].update_one(
                {"session_id": self.session_id},
                {
                    "$set": {
                        "email": self.email,
                        "status": "active",
                        "last_active": datetime.utcnow(),
                        "login_date": datetime.utcnow()
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to update session record: {e}")
    
    async def _check_connection_limit(self) -> bool:
        """Check if connection request limit reached for today."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            activity = self.db[self.ACTIVITY_COLLECTION].find_one({
                "session_id": self.session_id,
                "date": today
            })
            
            if not activity:
                return True
            
            connections_sent = activity.get("connections_sent", 0)
            return connections_sent < self.MAX_CONNECTIONS_PER_DAY
            
        except Exception as e:
            logger.error(f"Failed to check connection limit: {e}")
            return False
    
    async def _check_message_limit(self) -> bool:
        """Check if message limit reached for today."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            activity = self.db[self.ACTIVITY_COLLECTION].find_one({
                "session_id": self.session_id,
                "date": today
            })
            
            if not activity:
                return True
            
            messages_sent = activity.get("messages_sent", 0)
            return messages_sent < self.MAX_MESSAGES_PER_DAY
            
        except Exception as e:
            logger.error(f"Failed to check message limit: {e}")
            return False
    
    async def _increment_activity_counter(self, counter_name: str):
        """Increment activity counter for today."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            self.db[self.ACTIVITY_COLLECTION].update_one(
                {
                    "session_id": self.session_id,
                    "date": today
                },
                {
                    "$inc": {counter_name: 1},
                    "$set": {"last_activity": datetime.utcnow()},
                    "$setOnInsert": {
                        "session_id": self.session_id,
                        "date": today,
                        "daily_connection_limit": self.MAX_CONNECTIONS_PER_DAY,
                        "daily_message_limit": self.MAX_MESSAGES_PER_DAY
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to increment activity counter: {e}")
    
    def _random_delay(self, min_seconds: float = 2.0, max_seconds: float = 5.0):
        """Add random delay to simulate human behavior."""
        delay = random.uniform(min_seconds, max_seconds)
        logger.debug(f"Waiting {delay:.2f} seconds")
        return asyncio.sleep(delay)
    
    async def _human_scroll(self):
        """Simulate human-like scrolling behavior."""
        try:
            # Random scroll down
            scroll_amount = random.randint(300, 800)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await self._random_delay(0.5, 1.5)
            
            # Sometimes scroll back up a bit
            if random.random() > 0.5:
                scroll_back = random.randint(100, 300)
                await self.page.evaluate(f"window.scrollBy(0, -{scroll_back})")
                await self._random_delay(0.3, 0.8)
        except Exception as e:
            logger.debug(f"Scroll simulation failed: {e}")
    
    async def close(self):
        """Close browser and cleanup resources."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            logger.info("LinkedIn automation service closed")
            
        except Exception as e:
            logger.error(f"Error closing service: {e}")


# ==================== CONVENIENCE FUNCTIONS ====================

async def create_linkedin_service(db, email: str, headless: bool = False) -> LinkedInAutomationService:
    """
    Factory function to create and initialize LinkedIn service.
    
    Args:
        db: MongoDB database connection
        email: LinkedIn account email
        headless: Run browser in headless mode
        
    Returns:
        Initialized LinkedInAutomationService instance
    """
    service = LinkedInAutomationService(db)
    await service.initialize_session(email, headless)
    return service


async def batch_send_connections(
    db,
    email: str,
    profiles: List[Dict[str, str]],
    delay_between: tuple = (30, 60)
) -> List[Dict[str, any]]:
    """
    Send connection requests in batch with delays.
    
    Args:
        db: MongoDB database connection
        email: LinkedIn account email
        profiles: List of dicts with keys: profile_url, note, lead_id
        delay_between: (min, max) seconds delay between requests
        
    Returns:
        List of results for each connection request
    """
    results = []
    
    async with LinkedInAutomationService(db) as service:
        await service.initialize_session(email)
        
        for i, profile in enumerate(profiles):
            logger.info(f"Processing connection {i+1}/{len(profiles)}")
            
            result = await service.send_connection_request(
                profile_url=profile.get("profile_url"),
                note=profile.get("note", ""),
                lead_id=profile.get("lead_id")
            )
            
            results.append(result)
            
            # Stop if limit reached
            if not result.get("success") and "limit reached" in result.get("error", "").lower():
                logger.warning("Daily limit reached, stopping batch")
                break
            
            # Delay between requests (except for last one)
            if i < len(profiles) - 1:
                delay = random.uniform(*delay_between)
                logger.info(f"Waiting {delay:.1f} seconds before next request...")
                await asyncio.sleep(delay)
    
    return results
