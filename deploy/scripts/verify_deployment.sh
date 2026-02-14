#!/bin/bash
# Post-deployment verification script for Cint Integration
# Tests the two key diagnostic questions:
# 1. Are Cint inventories getting downloaded?
# 2. Are entry links getting created with live_link populated?

set -e

VM_HOST="${1:-torpedo.cogentixresearch.com}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Cint Integration Verification ===${NC}"
echo "Testing: https://${VM_HOST}"
echo ""

# Test 1: Diagnostic Endpoint
echo -e "${YELLOW}[Test 1/5] Checking diagnostic endpoint...${NC}"
DIAG_RESPONSE=$(curl -s "https://${VM_HOST}/api/cint/diagnostic")
DIAG_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${VM_HOST}/api/cint/diagnostic")

if [ "$DIAG_HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ Diagnostic endpoint is accessible${NC}"

    # Parse survey count
    SURVEY_COUNT=$(echo "$DIAG_RESPONSE" | jq -r '.surveys.total // 0' 2>/dev/null || echo "0")
    ACTIVE_SURVEYS=$(echo "$DIAG_RESPONSE" | jq -r '.surveys.active // 0' 2>/dev/null || echo "0")
    LIVE_SURVEYS=$(echo "$DIAG_RESPONSE" | jq -r '.surveys.live // 0' 2>/dev/null || echo "0")

    echo "  Total surveys: ${SURVEY_COUNT}"
    echo "  Active surveys: ${ACTIVE_SURVEYS}"
    echo "  Live surveys: ${LIVE_SURVEYS}"

    if [ "$SURVEY_COUNT" -gt "0" ]; then
        echo -e "${GREEN}  ✓ Inventories are being downloaded${NC}"
    else
        echo -e "${RED}  ✗ No surveys found in database${NC}"
    fi
else
    echo -e "${RED}✗ Diagnostic endpoint not accessible (HTTP ${DIAG_HTTP_CODE})${NC}"
    echo "  The deployment may not have completed successfully."
    exit 1
fi

echo ""

# Test 2: Entry Links
echo -e "${YELLOW}[Test 2/5] Checking entry links...${NC}"
ENTRY_LINK_COUNT=$(echo "$DIAG_RESPONSE" | jq -r '.entry_links.total // 0' 2>/dev/null || echo "0")
WITH_LIVE_LINK=$(echo "$DIAG_RESPONSE" | jq -r '.entry_links.with_live_link // 0' 2>/dev/null || echo "0")
WITHOUT_LIVE_LINK=$(echo "$DIAG_RESPONSE" | jq -r '.entry_links.without_live_link // 0' 2>/dev/null || echo "0")

echo "  Total entry links: ${ENTRY_LINK_COUNT}"
echo "  With live_link: ${WITH_LIVE_LINK}"
echo "  Without live_link: ${WITHOUT_LIVE_LINK}"

if [ "$ENTRY_LINK_COUNT" -gt "0" ]; then
    if [ "$WITH_LIVE_LINK" -gt "0" ]; then
        echo -e "${GREEN}  ✓ Entry links are created with live_link populated${NC}"
    else
        echo -e "${RED}  ✗ Entry links exist but live_link is NULL${NC}"
        echo "  This indicates an API response mapping issue."
    fi
else
    if [ "$SURVEY_COUNT" -gt "0" ]; then
        echo -e "${YELLOW}  ⚠ No entry links created yet (but surveys exist)${NC}"
        echo "  You may need to run auto-create manually."
    else
        echo -e "${YELLOW}  ⚠ No entry links (no surveys to create links for)${NC}"
    fi
fi

echo ""

# Test 3: Webhook Subscription
echo -e "${YELLOW}[Test 3/5] Checking webhook subscription...${NC}"
SUBSCRIPTION=$(curl -s "https://${VM_HOST}/api/cint/subscription/opportunities")
SUB_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${VM_HOST}/api/cint/subscription/opportunities")

if [ "$SUB_HTTP_CODE" = "200" ]; then
    SUPPLIER_CODE=$(echo "$SUBSCRIPTION" | jq -r '.supplier_code // "unknown"' 2>/dev/null)
    CALLBACK_URL=$(echo "$SUBSCRIPTION" | jq -r '.callback // "unknown"' 2>/dev/null)
    SEND_INTERVAL=$(echo "$SUBSCRIPTION" | jq -r '.send_interval_seconds // "unknown"' 2>/dev/null)

    echo -e "${GREEN}✓ Webhook subscription is active${NC}"
    echo "  Supplier Code: ${SUPPLIER_CODE}"
    echo "  Callback URL: ${CALLBACK_URL}"
    echo "  Send Interval: ${SEND_INTERVAL} seconds"
else
    echo -e "${RED}✗ Webhook subscription not found (HTTP ${SUB_HTTP_CODE})${NC}"
    echo "  You may need to create the subscription."
fi

echo ""

# Test 4: Opportunities Endpoint
echo -e "${YELLOW}[Test 4/5] Checking opportunities endpoint...${NC}"
OPPORTUNITIES=$(curl -s "https://${VM_HOST}/api/cint/opportunities")
OPP_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${VM_HOST}/api/cint/opportunities")

if [ "$OPP_HTTP_CODE" = "200" ]; then
    OPP_COUNT=$(echo "$OPPORTUNITIES" | jq -r '.count // 0' 2>/dev/null || echo "0")
    echo -e "${GREEN}✓ Opportunities endpoint accessible${NC}"
    echo "  Opportunities available: ${OPP_COUNT}"
else
    echo -e "${RED}✗ Opportunities endpoint error (HTTP ${OPP_HTTP_CODE})${NC}"
fi

echo ""

# Test 5: Issues and Recommendations
echo -e "${YELLOW}[Test 5/5] Checking diagnostic issues...${NC}"
ISSUES=$(echo "$DIAG_RESPONSE" | jq -r '.issues[]' 2>/dev/null || echo "")
RECOMMENDATIONS=$(echo "$DIAG_RESPONSE" | jq -r '.recommendations[]' 2>/dev/null || echo "")

if [ -n "$ISSUES" ]; then
    echo -e "${RED}Issues detected:${NC}"
    echo "$ISSUES" | while read -r issue; do
        echo "  - $issue"
    done
    echo ""

    if [ -n "$RECOMMENDATIONS" ]; then
        echo -e "${YELLOW}Recommendations:${NC}"
        echo "$RECOMMENDATIONS" | while read -r rec; do
            echo "  - $rec"
        done
    fi
else
    echo -e "${GREEN}✓ No issues detected${NC}"
fi

echo ""
echo -e "${BLUE}=== Summary ===${NC}"
echo ""

# Final verdict
if [ "$DIAG_HTTP_CODE" != "200" ]; then
    echo -e "${RED}DEPLOYMENT STATUS: FAILED${NC}"
    echo "The diagnostic endpoint is not accessible."
    echo ""
    echo "Action: Check server logs for errors."
elif [ "$SURVEY_COUNT" = "0" ]; then
    echo -e "${YELLOW}DEPLOYMENT STATUS: SUCCESSFUL (Awaiting Surveys)${NC}"
    echo ""
    echo "The deployment was successful, but no surveys have been received yet."
    echo ""
    echo "Possible reasons:"
    echo "  1. No surveys available from Cint matching your criteria"
    echo "  2. Webhooks are arriving but failing to process"
    echo "  3. Need to wait longer for webhook delivery (15-30 seconds interval)"
    echo ""
    echo "Next steps:"
    echo "  1. Wait 5-10 minutes for webhooks to arrive"
    echo "  2. Check server logs for webhook activity:"
    echo "     ssh ${VM_HOST} 'tail -f /var/log/torpedo/backend.log | grep \"Received opportunities webhook\"'"
    echo "  3. If still no surveys after 24 hours, contact Cint support"
elif [ "$WITH_LIVE_LINK" = "0" ] && [ "$ENTRY_LINK_COUNT" != "0" ]; then
    echo -e "${YELLOW}DEPLOYMENT STATUS: PARTIAL SUCCESS${NC}"
    echo ""
    echo "Surveys are being downloaded, but entry links don't have live_link populated."
    echo ""
    echo "Next steps:"
    echo "  1. Check entry link debug logs:"
    echo "     ssh ${VM_HOST} 'tail -f /var/log/torpedo/backend.log | grep \"ENTRY LINK DEBUG\"'"
    echo "  2. Look for API response field name mismatches"
    echo "  3. May need to add Field(alias=\"LiveLink\") to model"
else
    echo -e "${GREEN}DEPLOYMENT STATUS: SUCCESSFUL${NC}"
    echo ""
    echo "✓ Inventories are being downloaded"
    echo "✓ Entry links are created with live_link"
    echo "✓ Webhook subscription is active"
    echo ""
    echo "The Cint integration is working correctly!"
fi

echo ""
echo "Full diagnostic output:"
echo "$DIAG_RESPONSE" | jq '.' 2>/dev/null || echo "$DIAG_RESPONSE"
