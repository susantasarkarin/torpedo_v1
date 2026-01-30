# CPX Integration - Quick Reference

## 🎯 Correct Redirect URL Format
```
https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}
```

## 🔧 How to Apply the Fix

### Option 1: Automated (Recommended)
```bash
python fix_cpx_redirect_url.py
```
Then type `YES` when prompted to confirm.

### Option 2: Manual MongoDB Update
```javascript
use campaign_platform;
db.vendors.updateOne(
  {vendorName: {$regex: "CPX", $options: "i"}},
  {$set: {
    "completeRD": ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"],
    "terminateRD": ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"],
    "updated_at": new Date()
  }}
)
```

## 📋 Verify the Update
```javascript
use campaign_platform;
db.vendors.findOne({vendorName: {$regex: "CPX", $options: "i"}}, {completeRD: 1, terminateRD: 1})
```

Expected output:
```json
{
  "completeRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "terminateRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ]
}
```

## 🔄 Parameter Flow

1. **Survey Entry**: Respondent sent to CPX with `subid_1={traffic_record_id}`
2. **Survey Exit**: CPX calls back `/cpx-response?message_id=complete&subid_1={traffic_record_id}`
3. **Redirect**: User redirected to vendor URL with actual ID values

## 📊 What Changed

| Aspect | Old | New |
|--------|-----|-----|
| **Message Parameter** | `msg` | `message_id` |
| **Subid Parameter** | `sfwid` or `rid` | `subid_1` |
| **Redirect Base URL** | Varies | `https://torpedo.cogentixresearch.com/cpx-research` |
| **Query Format** | Mixed | `?message_id={message_id}&subid={subid_1}` |

## 🧪 Testing

1. Create test survey in CPX
2. Send traffic with proper `subid_1` parameter
3. Complete survey - CPX callback will trigger
4. Verify redirect includes correct parameters

## 📁 Related Files

- `fix_cpx_redirect_url.py` - Automated fix script
- `CPX_REDIRECT_URL_FIX.md` - Detailed documentation
- `backend/routers/traffic.py` - CPX callback handler
- `backend/main.py` - Vendor CRUD operations

## ⚠️ Important Notes

- Both `completeRD` and `terminateRD` must be updated
- The URL is stored as an **array** (first element is used)
- Parameter placeholders `{message_id}` and `{subid_1}` are actual placeholder text
- These get replaced by actual values during callback processing

## ✅ Verification Checklist

- [ ] Script executed successfully
- [ ] MongoDB update confirmed
- [ ] CPX vendor found in database
- [ ] Both completeRD and terminateRD updated
- [ ] No syntax errors in URLs
- [ ] Test traffic record created
- [ ] Survey URL has correct subid_1 parameter
- [ ] Callback handled properly
- [ ] Redirect includes message_id and subid parameters

---

**Last Updated**: 2025-01-03  
**Status**: Ready for Deployment
