from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)

# ========== CONFIG ==========
LOCAL = True  # change to False when deployed

if LOCAL:
    BACKEND_HOST = "http://127.0.0.1:5000"
    FRONTEND_URL = "http://127.0.0.1:5173"
else:
    BACKEND_HOST = "https://api.surveyfieldwork.com"  # GCP backend domain
    FRONTEND_URL = "https://surveyfieldwork.com"      # your real website

ZOHO_COMPLETE_URL = f"{FRONTEND_URL}/thankyou"
ZOHO_TERMINATE_URL = f"{FRONTEND_URL}/nosurvey"
ZOHO_QUOTA_URL = f"{FRONTEND_URL}/nosurvey"

# ========== MONGO ==========
try:
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client['traffic_flow_db']
    collection = db['url_parameters']
    print("✅ MongoDB connected successfully!")
except:
    collection = None
    print("❌ MongoDB NOT connected")

# ========== API ==========
@app.route('/api/store', methods=['POST'])
def store_url_params():
    if collection is None:
        return jsonify({"error": "DB not connected"}), 500
    
    data = request.get_json()
    data['timestamp'] = datetime.utcnow().isoformat()
    data['status'] = 'incomplete'
    data['redirectUrl'] = None

    result = collection.insert_one(data)
    return jsonify({"id": str(result.inserted_id)})

# ========== UPDATE ROUTES ==========
@app.route('/surveycomplete')
def survey_complete():
    rid = request.args.get('rid')
    if rid:
        collection.update_one(
            {"_id": ObjectId(rid)},
            {"$set": {"status": "complete", "redirectUrl": request.url}}
        )
    return redirect(ZOHO_COMPLETE_URL)

@app.route('/surveyterminate')
def survey_terminate():
    rid = request.args.get('rid')
    if rid:
        collection.update_one(
            {"_id": ObjectId(rid)},
            {"$set": {"status": "terminated", "redirectUrl": request.url}}
        )
    return redirect(ZOHO_TERMINATE_URL)

@app.route('/surveyquotafull')
def survey_quotafull():
    rid = request.args.get('rid')
    if rid:
        collection.update_one(
            {"_id": ObjectId(rid)},
            {"$set": {"status": "quotafull", "redirectUrl": request.url}}
        )
    return redirect(ZOHO_QUOTA_URL)

# ========== HEALTH ==========
@app.route('/api/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
