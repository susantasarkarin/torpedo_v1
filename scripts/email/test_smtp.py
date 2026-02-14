"""
Test email sending with current SMTP configuration
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMTP settings from .env
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "sristimazumder2835@gmail.com"
SMTP_PASSWORD = "cygvuzqwxgngaghx"  # Without spaces

# Test sending
print("🔍 Testing SMTP Configuration...")
print(f"   Host: {SMTP_HOST}")
print(f"   Port: {SMTP_PORT}")
print(f"   User: {SMTP_USER}")
print(f"   Password: {'*' * len(SMTP_PASSWORD)}\n")

try:
    # Create message
    msg = MIMEMultipart('alternative')
    msg['From'] = SMTP_USER
    msg['To'] = "sristimazumder2835@gmail.com"
    msg['Subject'] = "🧪 Test Email from Campaign Platform"
    
    html_body = """
    <html>
      <body>
        <h2>✅ Email System Test</h2>
        <p>This is a test email from your Campaign Platform.</p>
        <p>If you received this, your SMTP configuration is working correctly!</p>
        <br>
        <p><strong>Next Steps:</strong></p>
        <ul>
          <li>Go to Workflow Builder</li>
          <li>Select your leads</li>
          <li>Choose a template</li>
          <li>Send your campaign!</li>
        </ul>
      </body>
    </html>
    """
    
    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)
    
    # Connect and send
    print("📡 Connecting to SMTP server...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        print("🔐 Starting TLS...")
        server.starttls()
        
        print("🔑 Logging in...")
        server.login(SMTP_USER, SMTP_PASSWORD)
        
        print("📧 Sending test email...")
        server.send_message(msg)
    
    print("\n✅ SUCCESS! Test email sent to sristimazumder2835@gmail.com")
    print("📬 Check your inbox (and spam folder)!\n")
    
except smtplib.SMTPAuthenticationError as e:
    print(f"\n❌ AUTHENTICATION FAILED!")
    print(f"   Error: {e}")
    print("\n🔧 Possible fixes:")
    print("   1. Check your Gmail App Password is correct")
    print("   2. Make sure 2-Factor Authentication is enabled")
    print("   3. Generate a new App Password at: https://myaccount.google.com/apppasswords")
    print("   4. Copy password without spaces\n")
    
except smtplib.SMTPException as e:
    print(f"\n❌ SMTP ERROR!")
    print(f"   Error: {e}")
    print("\n🔧 Check your network connection and SMTP settings\n")
    
except Exception as e:
    print(f"\n❌ UNEXPECTED ERROR!")
    print(f"   Error: {e}\n")
