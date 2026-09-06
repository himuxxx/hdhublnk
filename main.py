import os
import re
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== কনফিগারেশন ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== HubCloud Bypass ফাংশন ==========
def bypass_hubcloud(url: str) -> dict:
    """
    MN-BOTS/hubcloud-bypasser এর লজিক অনুসারে HubCloud লিংক বাইপাস করে।
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # ১. মূল পেজে রিকোয়েস্ট পাঠাই
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()

        html = response.text

        # ২. পেজ থেকে ডাউনলোড লিংক খুঁজি (প্যাটার্ন ম্যাচিং)
        patterns = [
            r'<a[^>]+href=["\'](https?://[^"\']+\.(?:mkv|mp4|avi|zip|rar|7z))["\'][^>]*>',  # সরাসরি ফাইল
            r'window\.location\s*=\s*["\'](https?://[^"\']+)["\']',  # JS রিডাইরেক্ট
            r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"]*url=(https?://[^"\']+)["\']',  # Meta refresh
            r'<a[^>]+href=["\'](https?://[^"\']+download[^"\']+)["\'][^>]*>',  # "download" keyword
            r'href=["\'](https?://[^"\']+\.(?:mp4|mkv|avi))["\'][^>]*>',  # ভিডিও ফাইল
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                direct_link = matches[0]
                if isinstance(direct_link, tuple):
                    direct_link = direct_link[0]
                return {"success": True, "data": direct_link}

        # ৩. রিডাইরেক্ট ফলো করলে যদি URL পরিবর্তন হয়
        if response.url != url:
            return {"success": True, "data": response.url}

        return {"success": False, "data": "❌ কোনো ডাউনলোড লিংক খুঁজে পাওয়া যায়নি।"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "data": f"🌐 নেটওয়ার্ক এরর: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"success": False, "data": f"⚠️ অজানা ত্রুটি: {str(e)}"}

# ========== টেলিগ্রাম হ্যান্ডলার ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 **হ্যালো! আমি HubCloud Bypasser Bot**\n\n"
        "আমাকে যেকোনো HubCloud লিংক পাঠান।\n"
        "আমি বাইপাস করে সরাসরি ডাউনলোড লিংক বের করে দেব।\n\n"
        "যেমন: `https://hubcloud.one/xxxxx`"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 **কীভাবে ব্যবহার করবেন:**\n"
        "1️⃣ আমাকে একটি HubCloud লিংক পাঠান (টেক্সট মেসেজ হিসেবে)।\n"
        "2️⃣ আমি বাইপাস করে ডাউনলোড লিংক বের করব।\n\n"
        "🔰 **উদাহরণ:**\n"
        "`https://hubcloud.one/abc123`"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    
    if not re.match(r'^https?://', user_input):
        await update.message.reply_text("❌ দয়া করে একটি বৈধ URL দিন (http:// বা https:// দিয়ে শুরু)।")
        return

    processing_msg = await update.message.reply_text("⏳ লিংকটি বাইপাস করা হচ্ছে, একটু অপেক্ষা করুন...")

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
            f"⚠️ **কারণ:** {result['data']}"
        )
        await processing_msg.edit_text(reply)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("❓ দুঃখিত, আমি এই কমান্ড বুঝতে পারিনি। /help দিন।")

# ========== মেইন ফাংশন ==========
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    logger.info("🤖 Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
