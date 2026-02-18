#!/usr/bin/env node
/**
 * Get Last N Cint Respondent Payloads (JavaScript version)
 * 
 * This script connects to MongoDB and retrieves the last N respondent payloads
 * that were sent to Cint.
 * 
 * Usage:
 *   node scripts/get_last_cint_payloads.js [limit]
 *   
 * Examples:
 *   node scripts/get_last_cint_payloads.js           # Get last 10
 *   node scripts/get_last_cint_payloads.js 20        # Get last 20
 */

const { MongoClient, ObjectId } = require('mongodb');

const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/';
const CINT_SUPPLIER_CODE = process.env.CINT_SUPPLIER_CODE || '6777';
const CINT_CALLBACK_URL = process.env.CINT_CALLBACK_URL || 'https://torpedo.cogentixresearch.com/api/cint/status';

function formatTimestamp(date) {
    if (!date) return 'N/A';
    return date.toISOString().replace('T', ' ').split('.')[0] + ' UTC';
}

async function getLastCintPayloads(limit = 10) {
    const client = new MongoClient(MONGO_URI);
    
    try {
        await client.connect();
        console.log('✓ Connected to MongoDB');
        
        // Access databases
        const surveyDb = client.db('survey_allocation');
        const allocationLog = surveyDb.collection('allocation_log');
        const surveysCollection = surveyDb.collection('surveys');
        const respondentsCollection = surveyDb.collection('respondents');
        
        const cintDb = client.db('cint_research');
        const cintSurveys = cintDb.collection('cint_surveys');
        
        const payloads = [];
        
        // Get all allocation logs sorted by timestamp (most recent first)
        const allLogs = await allocationLog.find({}).sort({ timestamp: -1 }).toArray();
        
        // Filter for CINT allocations
        for (const log of allLogs) {
            if (payloads.length >= limit) break;
            
            const surveyId = log.survey_id;
            if (!surveyId) continue;
            
            // Get survey to check provider
            const survey = await surveysCollection.findOne({ _id: surveyId });
            if (!survey || survey.provider !== 'CINT') continue;
            
            const respondentId = log.rid || log.respondent_id;
            const externalSurveyId = survey.external_id;
            const surveyName = survey.name;
            
            // Get respondent details
            const respondent = await respondentsCollection.findOne({ rid: respondentId });
            
            // Try to get Cint survey details
            let cintSurvey = null;
            if (externalSurveyId) {
                cintSurvey = await cintSurveys.findOne({ survey_id: parseInt(externalSurveyId) });
            }
            
            // Reconstruct the payload that was sent to Cint
            const payload = {
                survey_id: externalSurveyId ? String(externalSurveyId) : String(surveyId),
                supplier_code: CINT_SUPPLIER_CODE,
                respondent_id: respondentId,
                secure_hash: '[HMAC-SHA256 hash - not stored]',
                return_url: CINT_CALLBACK_URL
            };
            
            // Additional metadata
            const metadata = {
                timestamp: formatTimestamp(log.timestamp),
                allocation_id: log.allocation_id ? String(log.allocation_id) : '',
                vid: log.vid,
                cc: log.cc,
                ip_address: log.ip_address,
                user_agent: log.user_agent,
                survey_name: surveyName,
                survey_status: survey.status
            };
            
            const fullRecord = {
                payload_sent_to_cint: payload,
                metadata: metadata
            };
            
            // Add Cint survey details if available
            if (cintSurvey) {
                fullRecord.cint_survey_details = {
                    survey_name: cintSurvey.survey_name,
                    country_language: cintSurvey.country_language,
                    loi: cintSurvey.bid_length_of_interview,
                    cpi: cintSurvey.revenue_per_interview?.value,
                    conversion: cintSurvey.conversion
                };
            }
            
            payloads.push(fullRecord);
        }
        
        return payloads;
        
    } catch (error) {
        console.error('Error retrieving payloads:', error);
        throw error;
    } finally {
        await client.close();
    }
}

function printPayloads(payloads) {
    if (!payloads || payloads.length === 0) {
        console.log('\nNo Cint payloads found.');
        return;
    }
    
    console.log('\n' + '='.repeat(80));
    console.log(`LAST ${payloads.length} RESPONDENT PAYLOADS SENT TO CINT`);
    console.log('='.repeat(80));
    console.log();
    
    payloads.forEach((record, i) => {
        console.log(`[${i + 1}] Timestamp: ${record.metadata.timestamp}`);
        console.log('-'.repeat(80));
        
        console.log('\nPayload sent to Cint API:');
        console.log('  POST https://api.samplicio.us/supply/v1/entrylinks');
        const payload = record.payload_sent_to_cint;
        for (const [key, value] of Object.entries(payload)) {
            console.log(`    ${key}: ${value}`);
        }
        
        console.log('\nMetadata:');
        const metadata = record.metadata;
        for (const [key, value] of Object.entries(metadata)) {
            if (key !== 'timestamp') {  // Already shown above
                console.log(`    ${key}: ${value || 'N/A'}`);
            }
        }
        
        if (record.cint_survey_details) {
            console.log('\nCint Survey Details:');
            const details = record.cint_survey_details;
            for (const [key, value] of Object.entries(details)) {
                console.log(`    ${key}: ${value || 'N/A'}`);
            }
        }
        
        console.log('\n' + '='.repeat(80));
        console.log();
    });
}

async function main() {
    const limit = parseInt(process.argv[2]) || 10;
    
    console.log('Connecting to MongoDB...');
    console.log(`Retrieving last ${limit} Cint respondent payloads...\n`);
    
    try {
        const payloads = await getLastCintPayloads(limit);
        printPayloads(payloads);
        console.log(`\nTotal payloads retrieved: ${payloads.length}`);
        process.exit(0);
    } catch (error) {
        console.error('\nError:', error.message);
        process.exit(1);
    }
}

// Run if called directly
if (require.main === module) {
    main();
}

module.exports = { getLastCintPayloads };
