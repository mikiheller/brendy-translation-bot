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


SYSTEM_PROMPT = """You are a translation assistant for a household Slack workspace where Miki (English speaker, the homeowner) communicates with his house cleaner (native Spanish speaker). Messages from the cleaner are often casual, may contain typos, missing words, missing punctuation, or phonetic misspellings (e.g. "boy" for "soy", "Vasura" for "Basura"). Your job is NOT to translate words literally — it is to translate the INTENT of what the person most likely meant.

Your job:
1. Detect if the input is primarily English or Spanish.
2. Figure out what the sender most likely MEANT to say, using:
   - The thread context provided above (if any). This is the single most important signal for disambiguation.
   - Common sense about typical household cleaner / homeowner conversations (lost items, trash, packages, cleaning schedules, instructions about where things go, etc.).
   - Spanish phonetic typos: "boy"→"soy", "Vasura"→"Basura", "ablar"→"hablar", missing accents, etc.
3. Translate the intended meaning into the OTHER language.

Respond in JSON:
{"original_language": "en" or "es", "translation": "the translated text"}

Rules for meaning and punctuation:
- If a message looks like it could be a question given the thread context (e.g. the cleaner holding up an item and saying "this is trash" as a reply to no prior question), translate it as a question with a "?". Example: "Hola miki esto es Vasura" after Miki posted a photo of items → "Hi Miki, is this trash?" (not "Hi Miki, this is trash").
- Correct obvious typos silently in the translation. Do not mention the correction.
- If the sender omits a word that is obvious from context, include it in the translation.
- When genuinely ambiguous between statement vs. question and no context resolves it, prefer the interpretation that makes the message more useful to reply to (usually a question).

Rules for formatting (CRITICAL):
- Preserve the original formatting EXACTLY: line breaks (\\n), blank lines between paragraphs, bullet characters (•, -, *, ●), numbered lists, indentation, and emojis.
- If the input has bullet points on separate lines, the translation MUST have bullet points on separate lines.
- Do not merge multiple lines into one paragraph.
- Do not add or remove blank lines.

Rules for tone:
- Keep it casual and friendly (household communication).
- Preserve emojis.

Skip rule:
- If the text is just emojis, punctuation, URLs, or otherwise can't be translated, return {"original_language": "unknown", "translation": null}."""


def get_thread_context(channel: str, thread_ts: str, current_ts: str, limit: int = 10) -> list:
    """
    Fetch recent messages in the same thread (excluding the current one) to give
    the translator conversational context. Returns a list of {"user_label", "text"}
    dicts ordered oldest -> newest, capped to `limit`.
    """
    if not channel or not thread_ts:
        return []

    from slack_sdk.errors import SlackApiError
    try:
        resp = get_slack_client().conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=50,
            inclusive=True,
        )
    except SlackApiError as e:
        print(f"Error fetching thread context: {e}")
        return []

    messages = resp.get("messages", []) or []
    context = []
    for msg in messages:
        if msg.get("ts") == current_ts:
            continue
        text = msg.get("text") or ""
        if not text.strip():
            continue
        # Skip the translator bot's own replies — they're just translations of other messages
        # already in the thread, and including them would duplicate context and confuse the model.
        if msg.get("bot_id") or msg.get("subtype") == "bot_message":
            continue
        label = f"user_{msg.get('user', 'unknown')}"
        context.append({"user_label": label, "text": text})

    return context[-limit:]


def detect_and_translate(text: str, thread_context: list | None = None) -> dict:
    """
    Detect the language and translate to the other language, using optional
    thread context to infer the sender's intent.
    Returns {"original_language": "en"|"es", "translation": "..."}
    """
    client = get_openai_client()

    context_block = ""
    if thread_context:
        lines = []
        for m in thread_context:
            lines.append(f"[{m['user_label']}]: {m['text']}")
        context_block = (
            "Prior messages in this Slack thread (oldest first). Use this to infer "
            "what the latest message most likely means:\n\n"
            + "\n\n".join(lines)
            + "\n\n---\n\n"
        )

    user_content = (
        context_block
        + "Latest message to translate (translate ONLY this, not the context above):\n"
        + text
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    result = json.loads(response.choices[0].message.content)
    return result


def post_translation(channel: str, thread_ts: str, translation: str, original_lang: str):
    """Post the translation as a threaded reply"""
    from slack_sdk.errors import SlackApiError
    
    try:
        get_slack_client().chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"✨ {translation}"
        )
    except SlackApiError as e:
        print(f"Error posting message: {e}")


def handle_message_event(event: dict):
    """Handle an incoming message event"""
    # Ignore messages from bots (including ourselves)
    if event.get("bot_id") or event.get("subtype"):
        return
    
    text = event.get("text", "")
    channel = event.get("channel")
    message_ts = event.get("ts")
    thread_ts = event.get("thread_ts") or message_ts
    
    # Skip empty messages or very short ones
    if not text or len(text.strip()) < 2:
        return
    
    # Skip messages that are just URLs or mentions
    if text.startswith("<") and text.endswith(">"):
        return
    
    # Pull thread context so the translator can infer the sender's intent
    try:
        thread_context = get_thread_context(channel, thread_ts, message_ts)
    except Exception as e:
        print(f"Error getting thread context: {e}")
        thread_context = []
    
    # Translate the message
    try:
        result = detect_and_translate(text, thread_context=thread_context)
        
        # Only post if we got a valid translation
        if result.get("translation") and result.get("original_language") in ["en", "es"]:
            post_translation(
                channel=channel,
                thread_ts=message_ts,
                translation=result["translation"],
                original_lang=result["original_language"]
            )
    except Exception as e:
        print(f"Error translating message: {e}")


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
            
            # Ignore Slack retries to prevent duplicate translations
            if self.headers.get('X-Slack-Retry-Num'):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
                return
            
            if not verify_slack_signature(body, timestamp, signature):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'Invalid signature')
                return
            
            # Handle event callbacks
            if data.get("type") == "event_callback":
                event = data.get("event", {})
                if event.get("type") == "message":
                    handle_message_event(event)
            
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
