# 📧 How to Send Real Emails

## Current Status: ❌ Emails Not Being Sent

Your workflow showed "success" because the system is in **SIMULATION MODE**. Emails are logged to the backend console but NOT actually sent.

## Why You Didn't Receive Emails

The backend `.env` file is missing SMTP configuration, so emails are simulated:
```
📧 SIMULATED EMAIL TO: sristimazumder2835@gmail.com
   SUBJECT: Quick question about Tech Solutions Inc
   (SMTP not configured - emails not actually sent)
```

## 📬 Sender Email Address

**Current sender**: `sristimazumder2835@gmail.com`  
(This is set as SMTP_USER in the .env file)

## ✅ Setup Real Email Sending

### Step 1: Get Gmail App Password

1. **Go to your Google Account**: https://myaccount.google.com/
2. **Enable 2-Factor Authentication** (if not already enabled)
   - Go to Security → 2-Step Verification → Turn On
3. **Generate App Password**:
   - Go to: https://myaccount.google.com/apppasswords
   - Select "Mail" and "Windows Computer" (or Other)
   - Click "Generate"
   - **Copy the 16-character password** (example: `abcd efgh ijkl mnop`)

### Step 2: Update Backend .env File

I've already added these lines to `backend/.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=sristimazumder2835@gmail.com
SMTP_PASSWORD=your-gmail-app-password-here
```

**Replace `your-gmail-app-password-here` with your actual App Password!**

Example:
```env
SMTP_PASSWORD=abcdefghijklmnop
```

### Step 3: Restart Backend

After updating the password:
```bash
# Stop backend (Ctrl+C in terminal)
# Start again:
cd "d:\OneDrive\Desktop\MyProjects\New folder (6)\campaign_platform\backend"
python main.py
```

### Step 4: Test Email Sending

1. Go to: http://localhost:5174/admin/sales/campaign/ai-leads
2. Select your leads
3. Click "🔄 Create Workflow"
4. Choose a template
5. Click "Launch Workflow"
6. **Check your inbox!** 📬

## 📨 Email Details

### Sender Information
- **From**: sristimazumder2835@gmail.com
- **Name**: Admin User (from user profile)
- **Signature**: HTML signature from database

### Recipient Emails
- sristimazumder2835@gmail.com
- aec.cse.sristimazumder@gmail.com
- (and one duplicate sristimazumder2835@gmail.com)

## ⚠️ Important Notes

### Gmail Limits
- **Daily limit**: 500 emails per day
- **Rate limit**: ~20 emails per minute
- **Recommendation**: Use for testing only

### For Production
Consider using:
- **SendGrid** (100 emails/day free)
- **Mailgun** (5,000 emails/month free)
- **Amazon SES** (62,000 emails/month free)

### Troubleshooting

**"Invalid credentials" error?**
- Make sure 2FA is enabled
- Use App Password, not regular password
- Copy password without spaces

**Emails going to spam?**
- Add SPF/DKIM records (advanced)
- Start with small batches
- Warm up the email account

**Still not working?**
- Check backend terminal for errors
- Verify SMTP_PASSWORD has no spaces
- Try with a different Gmail account

## 🎯 Quick Fix Checklist

- [ ] Enable 2-Factor Authentication on Gmail
- [ ] Generate App Password
- [ ] Copy App Password to backend/.env
- [ ] Remove any spaces from password
- [ ] Restart backend server
- [ ] Test by sending to yourself
- [ ] Check spam folder if not in inbox

## 🔍 Verify Configuration

Run this to check your setup:
```bash
cd "d:\OneDrive\Desktop\MyProjects\New folder (6)\campaign_platform"
python verify_email_setup.py
```

Should show:
```
✅ Email templates configured
✅ User signature configured  
✅ Leads available
✅ SMTP configured (if password is set)
```
