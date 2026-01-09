"""
Slack Translation Bot - Vercel Serverless Function
Automatically translates messages between English and Spanish
"""

import os
import json
import hashlib
import hmac
import time
from http.server import BaseHTTPRequestHandler

# Lazy-load clients to avoid initialization errors
_slack_client = None
_openai_client = None


def get_slack_client():
    global _slack_client
    if _slack_client is None:
        from slack_sdk import WebClient
        _slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
    return _slack_client


def get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _openai_client


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify that the request actually came from Slack"""
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    
    if not timestamp or not signature:
        return False
    
    # Check timestamp to prevent replay attacks
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except (ValueError, TypeError):
        return False
    
    # Create the signature base string
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    
    # Create our signature
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(my_signature, signature)


def detect_and_translate(text: str) -> dict:
    """
    Detect the language and translate to the other language.
    Returns {"original_language": "en"|"es", "translation": "..."}
    """
    client = get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": """You are a translation assistant. Your job is to:
1. Detect if the input text is in English or Spanish
2. Translate it to the OTHER language

Respond in JSON format:
{"original_language": "en" or "es", "translation": "the translated text"}

Rules:
- If the text is in English, translate to Spanish
- If the text is in Spanish, translate to English  
- Keep the tone casual and friendly (this is for household communication)
- Preserve any emojis
- If the text is just emojis, punctuation, or can't be translated, return {"original_language": "unknown", "translation": null}
"""
            },
            {
                "role": "user",
                "content": text
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def post_translation(channel: str, thread_ts: str, translation: str, original_lang: str):
    """Post the translation as a threaded reply"""
    from slack_sdk.errors import SlackApiError
    
    # Add a small indicator of what we did
    if original_lang == "en":
        prefix = "🇪🇸 "  # Spanish flag for English→Spanish
    else:
        prefix = "🇺🇸 "  # US flag for Spanish→English
    
    try:
        get_slack_client().chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"{prefix}{translation}"
        )
    except SlackApiError as e:
        print(f"Error posting message: {e}")


def handle_message_event(event: dict):
    """Handle an incoming message event"""
    print(f"[DEBUG] Received message event: {json.dumps(event)}")
    
    # Ignore messages from bots (including ourselves)
    if event.get("bot_id"):
        print("[DEBUG] Skipping: message from bot")
        return
    if event.get("subtype"):
        print(f"[DEBUG] Skipping: message has subtype '{event.get('subtype')}'")
        return
    
    text = event.get("text", "")
    channel = event.get("channel")
    message_ts = event.get("ts")
    
    print(f"[DEBUG] Processing message: '{text}' in channel {channel}")
    
    # Skip empty messages or very short ones
    if not text or len(text.strip()) < 2:
        print("[DEBUG] Skipping: message too short")
        return
    
    # Skip messages that are just URLs or mentions
    if text.startswith("<") and text.endswith(">"):
        print("[DEBUG] Skipping: message is just URL/mention")
        return
    
    # Translate the message
    try:
        print("[DEBUG] Calling OpenAI for translation...")
        result = detect_and_translate(text)
        print(f"[DEBUG] Translation result: {result}")
        
        # Only post if we got a valid translation
        if result.get("translation") and result.get("original_language") in ["en", "es"]:
            print(f"[DEBUG] Posting translation to Slack...")
            post_translation(
                channel=channel,
                thread_ts=message_ts,
                translation=result["translation"],
                original_lang=result["original_language"]
            )
            print("[DEBUG] Translation posted successfully!")
        else:
            print(f"[DEBUG] Skipping: invalid translation result")
    except Exception as e:
        print(f"[DEBUG] Error translating message: {e}")
        import traceback
        traceback.print_exc()


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler"""
    
    def do_POST(self):
        try:
            # Read the request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # Parse the JSON body first (for url_verification we skip signature check)
            data = json.loads(body.decode('utf-8'))
            
            # Handle Slack's URL verification challenge (no signature check needed)
            if data.get("type") == "url_verification":
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(data["challenge"].encode())
                return
            
            # Verify the request is from Slack for other requests
            timestamp = self.headers.get('X-Slack-Request-Timestamp', '')
            signature = self.headers.get('X-Slack-Signature', '')
            
            print(f"[DEBUG] Request type: {data.get('type')}")
            
            if not verify_slack_signature(body, timestamp, signature):
                print("[DEBUG] Signature verification FAILED")
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'Invalid signature')
                return
            
            print("[DEBUG] Signature verification passed")
            
            # Handle event callbacks
            if data.get("type") == "event_callback":
                event = data.get("event", {})
                print(f"[DEBUG] Event type: {event.get('type')}")
                
                if event.get("type") == "message":
                    handle_message_event(event)
                else:
                    print(f"[DEBUG] Ignoring event type: {event.get('type')}")
            
            # Always respond with 200 OK quickly
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
            
        except Exception as e:
            print(f"Error handling request: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'Error: {str(e)}'.encode())
    
    def do_GET(self):
        """Health check endpoint"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Brendy Translation Bot is running!')
