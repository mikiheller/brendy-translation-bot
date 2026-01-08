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
from openai import OpenAI
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


# Initialize clients
slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Get the bot's own user ID (we'll cache this)
BOT_USER_ID = None


def get_bot_user_id():
    """Get the bot's user ID to avoid translating our own messages"""
    global BOT_USER_ID
    if BOT_USER_ID is None:
        try:
            response = slack_client.auth_test()
            BOT_USER_ID = response["user_id"]
        except SlackApiError:
            BOT_USER_ID = "unknown"
    return BOT_USER_ID


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify that the request actually came from Slack"""
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    
    # Check timestamp to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 60 * 5:
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
    response = openai_client.chat.completions.create(
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
    # Add a small indicator of what we did
    if original_lang == "en":
        prefix = "🇪🇸 "  # Spanish flag for English→Spanish
    else:
        prefix = "🇺🇸 "  # US flag for Spanish→English
    
    try:
        slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"{prefix}{translation}"
        )
    except SlackApiError as e:
        print(f"Error posting message: {e}")


def handle_message_event(event: dict):
    """Handle an incoming message event"""
    # Ignore messages from bots (including ourselves)
    if event.get("bot_id") or event.get("subtype"):
        return
    
    # Ignore messages from this bot
    if event.get("user") == get_bot_user_id():
        return
    
    text = event.get("text", "")
    channel = event.get("channel")
    message_ts = event.get("ts")  # Use the message timestamp as the thread parent
    
    # Skip empty messages or very short ones
    if not text or len(text.strip()) < 2:
        return
    
    # Skip messages that are just URLs or mentions
    if text.startswith("<") and text.endswith(">"):
        return
    
    # Translate the message
    result = detect_and_translate(text)
    
    # Only post if we got a valid translation
    if result.get("translation") and result.get("original_language") in ["en", "es"]:
        post_translation(
            channel=channel,
            thread_ts=message_ts,
            translation=result["translation"],
            original_lang=result["original_language"]
        )


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler"""
    
    def do_POST(self):
        # Read the request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        # Verify the request is from Slack
        timestamp = self.headers.get('X-Slack-Request-Timestamp', '')
        signature = self.headers.get('X-Slack-Signature', '')
        
        if not verify_slack_signature(body, timestamp, signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'Invalid signature')
            return
        
        # Parse the JSON body
        data = json.loads(body.decode('utf-8'))
        
        # Handle Slack's URL verification challenge
        if data.get("type") == "url_verification":
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(data["challenge"].encode())
            return
        
        # Handle event callbacks
        if data.get("type") == "event_callback":
            event = data.get("event", {})
            
            if event.get("type") == "message":
                handle_message_event(event)
        
        # Always respond with 200 OK quickly (Slack expects this within 3 seconds)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')
    
    def do_GET(self):
        """Health check endpoint"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Brendy Translation Bot is running!')

