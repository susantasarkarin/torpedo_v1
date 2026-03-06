"""
LinkedIn Bot - Selenium-based automation
Handles LinkedIn account interactions: login, connections, messages, likes, reposts, comments.
Refactored from user's script into a class-based structure.
"""

import logging
import time
import random
from typing import Optional, List, Tuple
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException
)

from backend.linkedin_automation.models import LinkedInJobResult, LinkedInBotConfig

logger = logging.getLogger(__name__)


class LinkedInBot:
    """Selenium-based LinkedIn bot for automation"""
    
    def __init__(self, email: str, password: str, config: LinkedInBotConfig):
        """Initialize the LinkedIn bot"""
        self.email = email
        self.password = password
        self.config = config
        self.driver = None
        self.wait = None
        self.results = LinkedInJobResult()
        self.start_time = None
    
    def setup_driver(self) -> webdriver.Chrome:
        """Setup Selenium WebDriver with Chrome"""
        try:
            options = Options()
            
            if self.config.browser_headless:
                options.add_argument("--headless")
            
            options.add_argument("--start-maximized")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_experimental_option("excludeSwitches", ["enable-logging"])
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            if self.config.chromedriver_path:
                service = Service(executable_path=self.config.chromedriver_path)
            else:
                service = Service()
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.config.browser_timeout_seconds)
            
            logger.info("WebDriver setup successful")
            return self.driver
        
        except Exception as e:
            logger.error(f"Failed to setup WebDriver: {str(e)}")
            raise
    
    def login(self) -> bool:
        """Login to LinkedIn with email and password"""
        try:
            logger.info(f"Attempting to login with email: {self.email}")
            self.driver.get("https://www.linkedin.com/login")
            
            # Enter email
            self.wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(self.email)
            time.sleep(random.uniform(0.5, 1.5))
            
            # Enter password
            self.wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(self.password)
            time.sleep(random.uniform(0.5, 1.5))
            
            # Click Sign In button
            sign_in_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Sign in')]"))
            )
            sign_in_button.click()
            
            # Wait for home page to load
            self.wait.until(EC.presence_of_element_located((By.ID, "global-nav-typeahead")))
            logger.info("✓ Successfully logged in")
            return True
        
        except TimeoutException:
            logger.error("Login timeout - credentials may be incorrect or LinkedIn is slow")
            self.results.errors.append("Login timeout")
            return False
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            self.results.errors.append(f"Login error: {str(e)}")
            return False
    
    def interact_with_posts(self, max_posts: int = 100) -> int:
        """
        Interact with posts: like, repost, and comment
        Returns the number of posts interacted with
        """
        try:
            logger.info(f"Starting to interact with up to {max_posts} posts")
            self.driver.get("https://www.linkedin.com/feed/")
            
            posts_interacted = 0
            previous_scroll_height = -1
            
            while posts_interacted < max_posts:
                try:
                    # Scroll down to load more posts
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(random.uniform(self.config.scroll_pause_min, self.config.scroll_pause_max))
                    
                    current_scroll_height = self.driver.execute_script("return document.body.scrollHeight")
                    
                    # Check if we've reached the end
                    if current_scroll_height == previous_scroll_height:
                        try:
                            show_more_button = self.wait.until(
                                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Show more feed updates')]"))
                            )
                            logger.info("Found 'Show more feed updates' button")
                            self.driver.execute_script("arguments[0].click();", show_more_button)
                            time.sleep(random.uniform(5, 7))
                            continue
                        except TimeoutException:
                            logger.info("No more feed updates available")
                            break
                    
                    previous_scroll_height = current_scroll_height
                    
                    # Find all feed items
                    feed_items = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'feed-shared-update-v2')]")
                    
                    for item in feed_items:
                        if posts_interacted >= max_posts:
                            break
                        
                        try:
                            # Like the post
                            self._try_like_post(item)
                            time.sleep(random.uniform(self.config.action_pause_min, self.config.action_pause_max))
                            
                            # Repost the post
                            self._try_repost_post(item)
                            time.sleep(random.uniform(3, 5))
                            
                            # Comment on the post
                            self._try_comment_post(item)
                            time.sleep(random.uniform(3, 5))
                            
                            posts_interacted += 1
                            logger.info(f"Interacted with post {posts_interacted}")
                        
                        except StaleElementReferenceException:
                            logger.warning("Stale element, skipping post")
                            continue
                        except Exception as e:
                            logger.warning(f"Error interacting with post: {str(e)}")
                            continue
                
                except Exception as e:
                    logger.error(f"Unexpected error in interaction loop: {str(e)}")
                    break
            
            self.results.posts_liked = posts_interacted
            logger.info(f"Finished interacting with {posts_interacted} posts")
            return posts_interacted
        
        except Exception as e:
            logger.error(f"Failed to interact with posts: {str(e)}")
            self.results.errors.append(f"Post interaction error: {str(e)}")
            return 0
    
    def _try_like_post(self, item) -> bool:
        """Try to like a post"""
        try:
            # Find the like button that hasn't been pressed
            like_button = item.find_element(
                By.XPATH,
                ".//button[@aria-label='React Like' and @aria-pressed='false']"
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", like_button)
            like_button.click()
            self.results.posts_liked += 1
            logger.debug("Liked post")
            return True
        except (NoSuchElementException, TimeoutException, WebDriverException):
            return False
    
    def _try_repost_post(self, item) -> bool:
        """Try to repost a post"""
        try:
            repost_button = item.find_element(By.XPATH, ".//button[@aria-label='Repost']")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", repost_button)
            repost_button.click()
            
            # Wait for confirmation button
            confirm_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@id, 'artdeco-modal')]//button[span[text()='Repost']]"))
            )
            confirm_button.click()
            self.results.posts_reposted += 1
            logger.debug("Reposted post")
            return True
        except (NoSuchElementException, TimeoutException, WebDriverException, StaleElementReferenceException):
            return False
    
    def _try_comment_post(self, item) -> bool:
        """Try to comment on a post"""
        try:
            comment_button = item.find_element(By.XPATH, ".//button[contains(@aria-label, 'Add a comment')]")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", comment_button)
            comment_button.click()
            
            # Wait for comment box
            comment_box = self.wait.until(
                EC.presence_of_element_located((By.XPATH, ".//div[@aria-label='Add a comment, press enter to post']"))
            )
            comment_box.send_keys("Great post!")
            time.sleep(random.uniform(1, 2))
            
            # Find and click the Comment button
            post_comment_button = item.find_element(By.XPATH, ".//button[span[text()='Comment']]")
            self.driver.execute_script("arguments[0].click();", post_comment_button)
            self.results.posts_commented += 1
            logger.debug("Commented on post")
            return True
        except (NoSuchElementException, TimeoutException, WebDriverException, StaleElementReferenceException):
            return False
    
    def send_connection_requests(self, max_requests: int = 10) -> int:
        """
        Send connection requests
        Note: Simplified placeholder - full implementation would need target profile logic
        """
        logger.info(f"Connection requests feature is a placeholder. Max: {max_requests}")
        self.results.connections_sent = 0
        return 0
    
    def send_messages(self, target_profiles: Optional[List[str]] = None, max_messages: int = 5) -> int:
        """
        Send messages to conversations
        Note: Simplified placeholder - full implementation would need target conversation logic
        """
        logger.info(f"Message sending feature is a placeholder. Max: {max_messages}")
        self.results.messages_sent = 0
        return 0
    
    def run_all(self, max_posts: int = 100) -> LinkedInJobResult:
        """
        Run all automation tasks: like, repost, comment
        """
        try:
            self.start_time = datetime.utcnow()
            
            if not self.login():
                return self.results
            
            # Run tasks
            self.interact_with_posts(max_posts)
            
            # Calculate duration
            duration = (datetime.utcnow() - self.start_time).total_seconds()
            self.results.duration_seconds = duration
            
            logger.info(f"Automation complete. Results: {self.results.model_dump()}")
            return self.results
        
        except Exception as e:
            logger.error(f"Critical error in run_all: {str(e)}")
            self.results.errors.append(f"Critical error: {str(e)}")
            self.results.duration_seconds = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0.0
            return self.results
    
    def close(self):
        """Close the WebDriver"""
        try:
            if self.driver:
                self.driver.quit()
                logger.info("WebDriver closed")
        except Exception as e:
            logger.error(f"Error closing WebDriver: {str(e)}")


class LinkedInBotFactory:
    """Factory for creating and executing LinkedIn bots"""
    
    @staticmethod
    def execute_automation(
        email: str,
        password: str,
        config: LinkedInBotConfig = None
    ) -> LinkedInJobResult:
        """
        Execute LinkedIn automation for a single account
        Returns job results
        """
        if config is None:
            config = LinkedInBotConfig()
        
        bot = None
        try:
            bot = LinkedInBot(email, password, config)
            bot.setup_driver()
            results = bot.run_all()
            return results
        
        except Exception as e:
            logger.error(f"Failed to execute automation: {str(e)}")
            results = LinkedInJobResult(
                errors=[f"Execution failed: {str(e)}"],
                duration_seconds=0.0
            )
            return results
        
        finally:
            if bot:
                bot.close()
