import os
import sys
import logging
import requests
from flask import Flask, request, jsonify
from api import call_gemini_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

# Credentials & Configurations
WA_TOKEN = os.environ.get("WA_AGENT_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_secret_token")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "YOUR_PHONE_NUMBER_ID")

def get_graph_api_url():
    phone_id = os.environ.get("WA_PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    return f"https://graph.facebook.com/v18.0/{phone_id}/messages"

def get_headers():
    token = os.environ.get("WA_AGENT_TOKEN", WA_TOKEN)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

# Health Check Endpoints (for Render / Railway / Cloud Liveness Probes)
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "healthy",
        "service": "WhatsApp Gemini Agent",
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    }), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200

# Meta Webhook Verification Endpoint
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verify_token = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if mode == "subscribe" and token == verify_token:
        logging.info("[WEBHOOK VERIFIED] Handshake successful with Meta WhatsApp API.")
        return challenge, 200
    logging.warning(f"[WEBHOOK VERIFICATION FAILED] Received token: {token}")
    return "Verification failed", 403

# Incoming Message Receiver Endpoint
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json(silent=True) or {}
    
    try:
        entries = data.get("entry", [])
        if not entries:
            return jsonify({"status": "ignored", "reason": "no entries"}), 200

        entry = entries[0]
        changes = entry.get("changes", [])
        if not changes:
            return jsonify({"status": "ignored", "reason": "no changes"}), 200

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            from_phone = msg.get("from")
            
            # Text Message Processing
            if msg.get("type") == "text":
                user_text = msg.get("text", {}).get("body", "")
                logging.info(f"[RECEIVED] From {from_phone}: {user_text}")
                
                # Gemini + C++ Backend Response
                try:
                    bot_response = call_gemini_api(prompt=user_text)
                    send_whatsapp_reply(from_phone, bot_response)
                except Exception as api_err:
                    logging.error(f"[ERROR Gemini Processing]: {api_err}")
                    send_whatsapp_reply(from_phone, "I am currently experiencing higher than usual traffic. Please try again shortly.")

    except Exception as e:
        logging.error(f"[ERROR Processing Webhook]: {e}")

    return jsonify({"status": "success"}), 200

def send_whatsapp_reply(recipient_phone, text_reply):
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text_reply}
    }
    try:
        res = requests.post(
            get_graph_api_url(),
            json=payload,
            headers=get_headers(),
            timeout=10
        )
        if res.status_code == 200:
            logging.info(f"[SENT SUCCESS] Reply sent to {recipient_phone}")
        else:
            logging.error(f"[SEND FAILED] Meta Error: {res.status_code} - {res.text}")
    except Exception as e:
        logging.error(f"[ERROR Connection]: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting WhatsApp Webhook Server on Port {port}...")
    app.run(host="0.0.0.0", port=port)