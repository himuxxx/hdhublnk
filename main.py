import os
import re
import json
import logging
import asyncio
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== কনফিগারেশন ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

# লগিং সেটআপ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== HubCloud Bypass ফাংশন (স্মার্ট ভার্সন) ==========
def bypass_hubcloud(url: str) -> dict:
    """
    HubCloud লিংক বাইপাস করে। 
    প্রথমে পেজ থেকে লিংক খোঁজে, না পেলে রিডাইরেক্ট ফলো করে।
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # রিডাইরেক্ট ফলো সহ GET request
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()

        html = response.text

        # প্যাটার্ন লিস্ট (আরও কম্প্রিহেন্সিভ)
        patterns = [
            # <a> ট্যাগে download, direct link ইত্যাদি
            r'<a[^>]+href=["\'](https?://[^"\']+download[^"\']+)["\'][^>]*>',
            r'<a[^>]+href=["\'](https?://[^"\']+\.(?:mkv|mp4|avi|zip|rar|7z|exe|apk)[^"\']*)["\'][^>]*>',
            # window.location বা window.open জাভাস্ক্রিপ্ট রিডাইরেক্ট
            r'window\.location\s*=\s*["\'](https?://[^"\']+)["\']',
            r'window\.open\s*\(\s*["\'](https?://[^"\']+)["\']',
            # Meta refresh রিডাইরেক্ট
            r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"]*url=(https?://[^"\']+)["\']',
            # iframe-এর মধ্যে থাকতে পারে
            r'<iframe[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>',
            # শুধু "href" যেখানে text এ "Download" বা "Link" আছে
            r'href=["\'](https?://[^"\']+)["\'][^>]*>(?:[^<]*Download[^<]*)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            if matches:
                # প্রথম ম্যাচকেই প্রাধান্য দিচ্ছি
                direct_link = matches[0]
                if isinstance(direct_link, tuple):
                    direct_link = direct_link[0]
                # যদি লিংকে "http" না থাকে তাহলে স্কিপ
                if direct_link.startswith(("http://", "https://")):
                    return {"success": True, "data": direct_link}

        # ২. যদি কোনো প্যাটার্ন না মেলে, তাহলে চূড়ান্ত রিডাইরেক্টেড URL রিটার্ন করি (যদি পরিবর্তন হয়)
        if response.url != url:
            return {"success": True, "data": response.url}

        # ৩. কিছুই না পেলে
        return {"success": False, "data": "❌ কোনো ডাউনলোড লিংক খুঁজে পাওয়া যায়নি। পেজটি চেক করুন।"}

    except requests.exceptions.Timeout:
        return {"success": False, "data": "⏰ টাইমআউট! সার্ভার স্লো অথবা লিংকটি মৃত।"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "data": "🌐 সংযোগ সমস্যা! লিংকটি সঠিক কিনা যাচাই করুন।"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "data": f"⚠️ নেটওয়ার্ক এরর: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"success": False, "data": f"⚠️ অজানা ত্রুটি: {str(e)}"}

# ========== টেলিগ্রাম হ্যান্ডলার ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 **হ্যালো! আমি HubCloud Bypasser Bot**\n\n"
        "আমাকে যেকোনো HubCloud বা শর্টনিং লিংক পাঠান।\n"
        "আমি বাইপাস করে সরাসরি ডাউনলোড লিংক বের করে দেব।\n\n"
        "যেমন: `https://hubcloud.one/xxxxx`"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 **কীভাবে ব্যবহার করবেন:**\n"
        "1️⃣ আমাকে একটি লিংক পাঠান (টেক্সট মেসেজ হিসেবে)।\n"
        "2️⃣ আমি স্বয়ংক্রিয়ভাবে বাইপাস করব।\n"
        "3️⃣ ডাউনলোড লিংক পেয়ে গেলে আমি তা পাঠিয়ে দেব।\n\n"
        "🔰 **উদাহরণ:**\n"
        "`https://hubcloud.one/abc123`"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    
    # URL ভ্যালিডেশন
    if not re.match(r'^https?://', user_input):
        await update.message.reply_text("❌ দয়া করে একটি বৈধ URL দিন (http:// বা https:// দিয়ে শুরু)।")
        return

    # প্রসেসিং মেসেজ
    processing_msg = await update.message.reply_text("⏳ লিংকটি বাইপাস করা হচ্ছে, একটু অপেক্ষা করুন...")

    # বাইপাস কল
    result = bypass_hubcloud(user_input)

    if result["success"]:
        reply = (
            f"✅ **বাইপাস সফল!**\n\n"
            f"📥 **ডাউনলোড লিংক:**\n`{result['data']}`"
        )
        await processing_msg.edit_text(reply, disable_web_page_preview=False)
    else:
        reply = (
            f"❌ **বাইপাস ব্যর্থ!**\n\n"
            f"⚠️ **কারণ:** {result['data']}\n\n"
            f"💡 অন্য কোনো লিংক চেষ্টা করুন অথবা ম্যানুয়ালি চেক করুন।"
        )
        await processing_msg.edit_text(reply)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("❓ দুঃখিত, আমি এই কমান্ড বুঝতে পারিনি। /help দিন।")

# ========== টেলিগ্রাম অ্যাপ্লিকেশন সেটআপ ==========
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
application.add_handler(MessageHandler(filters.COMMAND, unknown))

# ========== VERCEL / FLASK ওয়েবহুক হ্যান্ডলার ==========
app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return "🤖 HubCloud Bypasser Bot is running on Vercel!"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram থেকে আসা POST ডেটা প্রসেস করে"""
    try:
        # টেলিগ্রামের JSON বডি পড়ি
        body = request.get_json(force=True)
        if not body:
            return "Invalid request", 400

        # Update অবজেক্ট তৈরি করি
        update = Update.de_json(body, application.bot)
        
        # নোট: process_update হল async, তাই asyncio.run() দিয়ে চালাতে হবে
        asyncio.run(application.process_update(update))
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return f"Error: {str(e)}", 500

# লোকাল টেস্টের জন্য (শুধু দরকার হলে)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
