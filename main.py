import os
import re
import asyncio
import logging
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== কনফিগারেশন ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

API_BASE_URL = os.environ.get("API_BASE_URL", "https://hdhublnk.vercel.app")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== API-ভিত্তিক Bypass ফাংশন ==========
def bypass_hubcloud(url: str) -> dict:
    try:
        api_endpoint = f"{API_BASE_URL}/find"
        response = requests.post(
            api_endpoint,
            json={"url": url},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("links") and len(data["links"]) > 0:
            first_link = data["links"][0]
            return {
                "success": True,
                "data": first_link.get("url", "❌ লিংক পাওয়া যায়নি।")
            }
        else:
            return {
                "success": False,
                "data": "❌ এই পেজ থেকে কোনো ডাউনলোড লিংক বের করা সম্ভব হয়নি।"
            }
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "data": f"🌐 নেটওয়ার্ক এরর: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"success": False, "data": f"⚠️ অজানা ত্রুটি: {str(e)}"}

# ========== টেলিগ্রাম হ্যান্ডলার ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 **হ্যালো! আমি HDHub Bypasser Bot**\n\n"
        "আমাকে যেকোনো HDHub বা শর্টনিং লিংক পাঠান।\n"
        "আমি বাইপাস করে সরাসরি ডাউনলোড লিংক বের করে দেব।\n\n"
        "যেমন: `https://hdhub4u.catering/xyz`"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 **কীভাবে ব্যবহার করবেন:**\n"
        "1️⃣ আমাকে একটি লিংক পাঠান (টেক্সট মেসেজ হিসেবে)।\n"
        "2️⃣ আমি API-এর মাধ্যমে বাইপাস করব।\n"
        "3️⃣ ডাউনলোড লিংক পেয়ে গেলে আমি তা পাঠিয়ে দেব।"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    
    if not re.match(r'^https?://', user_input):
        await update.message.reply_text("❌ দয়া করে একটি বৈধ URL দিন (http:// বা https:// দিয়ে শুরু)।")
        return

    processing_msg = await update.message.reply_text("⏳ লিংকটি বাইপাস করা হচ্ছে, একটু অপেক্ষা করুন...")
    result = bypass_hubcloud(user_input)

    if result["success"]:
        reply = f"✅ **বাইপাস সফল!**\n\n📥 **ডাউনলোড লিংক:**\n`{result['data']}`"
        await processing_msg.edit_text(reply, disable_web_page_preview=False)
    else:
        reply = f"❌ **বাইপাস ব্যর্থ!**\n\n⚠️ **কারণ:** {result['data']}"
        await processing_msg.edit_text(reply)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("❓ দুঃখিত, আমি এই কমান্ড বুঝতে পারিনি। /help দিন।")

# ========== টেলিগ্রাম অ্যাপ্লিকেশন সেটআপ ==========
telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
telegram_app.add_handler(MessageHandler(filters.COMMAND, unknown))

# ========== FLASK অ্যাপ (Vercel-এর জন্য) ==========
application = Flask(__name__)  # ✅ এটা Vercel খুঁজে পাবে

@application.route('/', methods=['GET'])
def index():
    return "🤖 HDHub Bypasser Bot is running on Vercel!"

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
        logger.error(f"Webhook processing error: {e}")
        return f"Error: {str(e)}", 500

# লোকাল টেস্টের জন্য
if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
