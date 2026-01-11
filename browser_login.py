"""
Script to open browser and login to torpedo.cogentixresearch.com
"""
import asyncio
from playwright.async_api import async_playwright


async def login():
    async with async_playwright() as p:
        # Launch browser in headed mode (visible)
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Navigate to the site
        print("Navigating to torpedo.cogentixresearch.com...")
        await page.goto("https://torpedo.cogentixresearch.com")
        
        # Wait for page to load
        await page.wait_for_load_state("networkidle")
        
        # Fill in login form
        print("Attempting to login...")
        
        # Try to find and fill username field (common selectors)
        username_selectors = [
            'input[name="username"]',
            'input[name="userid"]',
            'input[name="email"]',
            'input[id="username"]',
            'input[id="userid"]',
            'input[type="text"]',
            'input[placeholder*="user" i]',
            'input[placeholder*="email" i]'
        ]
        
        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            'input[id="password"]'
        ]
        
        # Try to find username field
        username_filled = False
        for selector in username_selectors:
            try:
                username_field = await page.wait_for_selector(selector, timeout=2000)
                if username_field:
                    await username_field.fill("admin")
                    print(f"Found username field using selector: {selector}")
                    username_filled = True
                    break
            except:
                continue
        
        if not username_filled:
            print("Warning: Could not find username field automatically. Please check the page structure.")
        
        # Try to find password field
        password_filled = False
        for selector in password_selectors:
            try:
                password_field = await page.wait_for_selector(selector, timeout=2000)
                if password_field:
                    await password_field.fill("password123")
                    print(f"Found password field using selector: {selector}")
                    password_filled = True
                    break
            except:
                continue
        
        if not password_filled:
            print("Warning: Could not find password field automatically. Please check the page structure.")
        
        # Try to find and click login button
        login_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
            '[id*="login" i]',
            '[class*="login" i]',
            'form button',
            'form input[type="submit"]'
        ]
        
        login_clicked = False
        for selector in login_selectors:
            try:
                login_button = await page.wait_for_selector(selector, timeout=2000)
                if login_button:
                    await login_button.click()
                    print(f"Clicked login button using selector: {selector}")
                    login_clicked = True
                    break
            except:
                continue
        
        if not login_clicked:
            print("Warning: Could not find login button automatically. You may need to click it manually.")
        
        # Wait a bit to see if login was successful
        await asyncio.sleep(3)
        
        print("\nBrowser is open. Please verify if login was successful.")
        print("Press Ctrl+C to close the browser when done.")
        
        # Keep browser open
        try:
            await asyncio.sleep(3600)  # Keep open for 1 hour (or until interrupted)
        except KeyboardInterrupt:
            print("\nClosing browser...")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(login())
