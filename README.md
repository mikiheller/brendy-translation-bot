# 🌐 Brendy Translation Bot

A Slack bot that automatically translates messages between English and Spanish. Perfect for multilingual households or teams!

## How It Works

1. Someone posts a message in English → Bot replies in thread with Spanish translation 🇪🇸
2. Someone posts a message in Spanish → Bot replies in thread with English translation 🇺🇸

## Setup Guide

### Step 1: Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. Name it something like "Brendy Translator" and select your workspace

### Step 2: Configure Bot Permissions

1. Go to **"OAuth & Permissions"** in the sidebar
2. Under **"Scopes" → "Bot Token Scopes"**, add:
   - `chat:write` (to post translations)
   - `channels:history` (to read messages in public channels)
   - `groups:history` (to read messages in private channels)
   - `im:history` (to read direct messages)
   - `mpim:history` (to read group DMs)

### Step 3: Enable Event Subscriptions

1. Go to **"Event Subscriptions"** in the sidebar
2. Toggle **"Enable Events"** to ON
3. For **Request URL**, enter: `https://your-vercel-app.vercel.app/api/slack`
   (You'll get this URL after deploying to Vercel)
4. Under **"Subscribe to bot events"**, add:
   - `message.channels` (messages in public channels)
   - `message.groups` (messages in private channels)
   - `message.im` (direct messages)
   - `message.mpim` (group DMs)
5. Save changes

### Step 4: Install the App

1. Go to **"Install App"** in the sidebar
2. Click **"Install to Workspace"**
3. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)

### Step 5: Get Your Signing Secret

1. Go to **"Basic Information"** in the sidebar
2. Under **"App Credentials"**, copy the **"Signing Secret"**

### Step 6: Deploy to Vercel

1. Install Vercel CLI: `npm i -g vercel`
2. Run `vercel` in this project directory
3. Add your environment variables in the Vercel dashboard:
   - `SLACK_BOT_TOKEN` = your bot token from Step 4
   - `SLACK_SIGNING_SECRET` = your signing secret from Step 5
   - `OPENAI_API_KEY` = your OpenAI API key

### Step 7: Update Slack with Your URL

1. Go back to your Slack app settings → **"Event Subscriptions"**
2. Update the **Request URL** with your actual Vercel URL: `https://your-app.vercel.app/api/slack`
3. Slack will verify the URL - it should show a green checkmark ✓

### Step 8: Invite the Bot

In Slack, invite the bot to your channel:
```
/invite @Brendy Translator
```

## That's It! 🎉

Now whenever someone posts in the channel, the bot will automatically translate their message in a thread reply.

## Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file with your credentials
cp .env.example .env
# Edit .env with your actual values

# For local testing, you'll need ngrok to expose your localhost
# ngrok http 3000
```

## Tech Stack

- **Python** - Core language
- **Slack SDK** - Slack API integration
- **OpenAI GPT-5** - Language detection, intent inference & translation
- **Vercel** - Serverless hosting

