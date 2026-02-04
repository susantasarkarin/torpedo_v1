# API Call Documentation - Leads Import Parsing Page

## Overview
This document shows the API call that is made before the respondent clicks the button on the parsing page.

## Page Location
**File:** `/Campaign_platform/src/pages/sales/LeadsImport.jsx`  
**Route:** `/admin/sales/leads/import`  
**Component:** `LeadsImport` (4-step CSV import wizard)

## The Flow

### Step 1: Upload CSV File
- User uploads a CSV file via drag & drop or file selection
- **Client-side parsing** occurs using Papa.parse() library
- No API call at this stage

### Step 2: Map Columns
- User maps CSV columns to database fields
- Auto-mapping occurs client-side
- Optional API calls:
  - `GET /leads/import/csv/mapping?columns=...` (retrieve saved mappings)
  - `POST /leads/import/csv/mapping` (save mappings for reuse)

### Step 3: Preview Import ⭐ **This is the parsing page**
- User sees preview of first 5 rows
- **NEW: API Call Information Box is displayed**
- User clicks **"✅ Import Leads"** button
- **BEFORE the API call executes**, console logging displays all details

### Step 4: Import Complete
- Shows import results

## The API Call

### Endpoint Details
```
Method: POST
URL: /leads/import/csv
Content-Type: multipart/form-data
Authorization: Session ID from localStorage
```

### Request Payload
```javascript
FormData {
  file: Blob (CSV file with mapped columns)
  // File contains:
  // - Remapped CSV with database field names as headers
  // - All rows from original CSV
  // - Only mapped columns included
}
```

### What Data is Sent
- **File name:** `import.csv`
- **Number of rows:** Count of data rows (e.g., 247 rows)
- **Mapped fields:** Array of database field keys (e.g., ["email", "firstName", "lastName", "companyName"])

### Response Structure
```json
{
  "imported": 247,
  "skipped": 3,
  "errors": [
    "Row 5: Email is required",
    "Row 12: Invalid email format"
  ]
}
```

## New Features Added

### 1. Console Logging (Developer Tools)

When the user clicks "Import Leads", the console displays:

```
🚀 API Call - Leads Import
  📍 Endpoint: http://localhost:8000/leads/import/csv
  📝 Method: POST
  📦 Payload: {
    file: "import.csv",
    rows: 247,
    mappedFields: ["email", "firstName", "lastName", "companyName", "title"]
  }
  🔑 Authorization: Present
  ⏰ Timestamp: 2026-02-04T15:33:18.403Z
```

### 2. UI Information Box (User Interface)

On Step 3 (Preview), a blue information box now shows:

```
┌──────────────────────────────────────────────────┐
│ 🚀 API Call Details                              │
│                                                  │
│ Endpoint: POST /leads/import/csv                 │
│ Payload: 247 rows, 5 fields mapped              │
└──────────────────────────────────────────────────┘
```

**Visual Appearance:**
- Light blue background (#eff6ff)
- Blue border (#bfdbfe)
- Monospace font for technical details
- Positioned above the preview table
- Shows dynamic row count and mapped field count

## Code Implementation

### Console Logging Code (Lines 394-405)
```javascript
// Log API call details before making the request
console.group("🚀 API Call - Leads Import")
console.log("📍 Endpoint:", apiUrl)
console.log("📝 Method:", "POST")
console.log("📦 Payload:", {
  file: "import.csv",
  rows: mappedData.length,
  mappedFields: Object.keys(columnMapping).filter(k => columnMapping[k])
})
console.log("🔑 Authorization:", sessionId ? "Present" : "Missing")
console.log("⏰ Timestamp:", new Date().toISOString())
console.groupEnd()
```

### UI Information Box Code (Lines 566-583)
```jsx
{/* API Call Information Box */}
<div style={{
  padding: "1rem",
  backgroundColor: "#eff6ff",
  border: "1px solid #bfdbfe",
  borderRadius: "8px",
  marginBottom: "1rem",
  fontSize: "0.875rem"
}}>
  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
    <span style={{ fontSize: "1rem" }}>🚀</span>
    <strong style={{ color: "#1e40af" }}>API Call Details</strong>
  </div>
  <div style={{ color: "#1e3a8a", fontFamily: "monospace", fontSize: "0.813rem" }}>
    <div><strong>Endpoint:</strong> POST /leads/import/csv</div>
    <div><strong>Payload:</strong> {csvData.length} rows, {Object.keys(columnMapping).filter(k => columnMapping[k]).length} fields mapped</div>
  </div>
</div>
```

## Backend Endpoint

The backend endpoint that processes this API call is located at:
- **Router:** `/backend/routers/leads.py` (or similar)
- **Function:** `import_leads_csv()` or `parse_csv_leads()`

### What the Backend Does:
1. Receives the multipart/form-data file
2. Parses the CSV using a CSV parser
3. Validates required fields (email is mandatory)
4. Checks for duplicates based on email
5. Imports valid leads to the database
6. Returns import statistics

## Benefits

### For Users:
- **Transparency:** Users can see exactly what API call will be made
- **Confidence:** Clear information about what data is being sent
- **Debugging:** If something goes wrong, users know what was attempted

### For Developers:
- **Debugging:** Console logs provide detailed information for troubleshooting
- **Monitoring:** Can see exact payload and timing of API calls
- **Auditing:** Timestamp and authorization status logged

## Testing the Feature

### How to See the API Call Information:

1. **UI Method (Non-technical users):**
   - Navigate to `/admin/sales/leads/import`
   - Upload a CSV file
   - Map the columns
   - Click "Preview ▶"
   - **Look for the blue "API Call Details" box** above the preview table

2. **Console Method (Developers):**
   - Open browser DevTools (F12)
   - Go to Console tab
   - Follow steps above
   - Click "✅ Import Leads" button
   - **Check the grouped console log** showing all API details

## Summary

The parsing page (`LeadsImport.jsx`) now shows the API call information **BEFORE** the respondent clicks the import button:

- ✅ **Visible in UI:** Blue information box on Step 3 (Preview)
- ✅ **Logged to Console:** Detailed logs when button is clicked (before API call)
- ✅ **Shows:** Endpoint, method, payload details, authorization, timestamp
- ✅ **User-friendly:** Clear, simple language for non-technical users
- ✅ **Developer-friendly:** Detailed technical information in console

The API call is: **`POST /leads/import/csv`** with a CSV file containing the mapped lead data.
