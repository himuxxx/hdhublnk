import os
import re
import asyncio
import logging
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def bypass_hubcloud(url: str) -> dict:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        html = response.text

        patterns = [
            r'<a[^>]+href=["\'](https?://[^"\']+\.(?:mkv|mp4|avi|zip|rar|7z))["\'][^>]*>',
            r'window\.location\s*=\s*["\'](https?://[^"\']+)["\']',
            r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"]*url=(https?://[^"\']+)["\']',
            r'<a[^>]+href=["\'](https?://[^"\']+download[^"\']+)["\'][^>]*>',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                direct_link = matches[0]
                if isinstance(direct_link, tuple):
                    direct_link = direct_link[0]
                return {"success": True, "data": direct_link}

        if response.url != url:
            return {"success": True, "data": response.url}

        return {"success": False, "data": "❌ কোনো ডাউনলোড লিংক খুঁজে পাওয়া যায়নি।"}
    except Exception as e:
        return {"success": False, "data": f"⚠️ এরর: {str(e)}"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 HubCloud Bypasser Bot! আমাকে একটি লিংক পাঠান।")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("একটি HubCloud লিংক পাঠান, আমি বাইপাস করে দেব।")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if not re.match(r'^https?://', user_input):
        await update.message.reply_text("❌ বৈধ URL দিন।")
        return

    await update.message.reply_text("⏳ বাইপাস করা হচ্ছে...")
    result = bypass_hubcloud(user_input)

    if result["success"]:
        await update.message.reply_text(f"✅ **Direct Link:**\n{result['data']}")
    else:
        await update.message.reply_text(f"❌ ব্যর্থ! {result['data']}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ /help দিন।")

# ========== টেলিগ্রাম অ্যাপ্লিকেশন ==========
telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.initialize()  # ✅ এই লাইনটি যোগ করুন

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
telegram_app.add_handler(MessageHandler(filters.COMMAND, unknown))

# ========== Flask অ্যাপ (Vercel-এর জন্য) ==========
application = Flask(__name__)

@application.route('/', methods=['GET'])
def index():
    return "🤖 HubCloud Bypasser Bot is running on Vercel!"

@application.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json(force=True)
        if not body:
            return "Invalid request", 400

        update = Update.de_json(body, telegram_app.bot)
        asyncio.run(telegram_app.process_update(update))
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
