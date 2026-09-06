import os
import re
import logging
import requests
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 🔥 HubCloud Bypass লজিক (HTML থেকে নেওয়া)
# ============================================================

def extract_links_from_html(html: str, base_url: str) -> list:
    """HTML থেকে সব <a> ট্যাগের href এবং text বের করে"""
    links = []
    pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
    for href, text in matches:
        text = re.sub(r'<[^>]+>', '', text).strip()
        links.append({"href": href, "text": text})
    return links

def bypass_hubcloud(url: str) -> dict:
    """
    HubCloud লিংক বাইপাস করে সব ডাউনলোড লিংক বের করে।
    HTML-এর extract() ফাংশনের মতো কাজ করে।
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        session = requests.Session()
        session.headers.update(headers)

        # ১. vifix.site কে hubcloud.one-এ রূপান্তর
        target_url = url
        if re.match(r'^https://vifix\.site/hubcloud/([a-z0-9]+)$', url, re.IGNORECASE):
            file_id = url.split("/")[-1]
            target_url = f"https://hubcloud.one/drive/{file_id}"
            logger.info(f"Converted vifix.site URL to: {target_url}")

        # ২. প্রথম পেজ ফেচ
        resp1 = session.get(target_url, timeout=30, allow_redirects=True)
        resp1.raise_for_status()
        html1 = resp1.text

        # ৩. #download আইডি থাকা <a> ট্যাগ খোঁজ
        all_links = extract_links_from_html(html1, target_url)
        download_node = None
        for link in all_links:
            if 'download' in link['href'].lower() or 'download' in link['text'].lower():
                download_node = link
                break

        if not download_node:
            return {"success": False, "data": "❌ ডাউনলোড লিংক খুঁজে পাওয়া যায়নি (download link missing)"}

        hubcloud_php_url = download_node['href']
        # relative URL ঠিক করা
        if hubcloud_php_url.startswith('/'):
            parsed = requests.utils.urlparse(target_url)
            hubcloud_php_url = f"{parsed.scheme}://{parsed.netloc}{hubcloud_php_url}"
        elif not hubcloud_php_url.startswith('http'):
            hubcloud_php_url = requests.utils.urljoin(target_url, hubcloud_php_url)

        logger.info(f"Found hubcloud.php URL: {hubcloud_php_url}")

        # ৪. hubcloud.php পেজ ফেচ
        resp2 = session.get(hubcloud_php_url, timeout=30, allow_redirects=True)
        resp2.raise_for_status()
        html2 = resp2.text

        # ৫. সব ডাউনলোড লিংক বের করা
        all_links2 = extract_links_from_html(html2, hubcloud_php_url)
        direct_links = []

        for link in all_links2:
            href = link['href']
            if not href:
                continue

            # বিভিন্ন টাইপ শনাক্ত করা
            if 'r2.dev' in href or 'cloudflare' in href:
                direct_links.append({
                    "url": href,
                    "text": link['text'] or "Cloudflare R2 Download",
                    "type": "Cloudflare R2"
                })
            elif 'pixeldrain' in href:
                if '/u/' in href:
                    file_id = href.split('/u/')[-1].split('?')[0]
                    direct_url = f"https://pixeldrain.com/api/file/{file_id}"
                    direct_links.append({
                        "url": direct_url,
                        "text": link['text'] or "PixelDrain Download",
                        "type": "PixelDrain"
                    })
                else:
                    direct_links.append({
                        "url": href,
                        "text": link['text'] or "PixelDrain Download",
                        "type": "PixelDrain"
                    })
            elif 'workers.dev' in href:
                direct_links.append({
                    "url": href,
                    "text": link['text'] or "Cloudflare Worker Download",
                    "type": "Cloudflare Workers"
                })
            elif 'googleusercontent.com' in href or 'drive.google.com' in href:
                direct_links.append({
                    "url": href,
                    "text": link['text'] or "Google Drive Download",
                    "type": "Google Drive"
                })
            elif re.search(r'\.(zip|rar|7z|mkv|mp4|avi|mov|pdf|doc|docx)$', href, re.IGNORECASE):
                direct_links.append({
                    "url": href,
                    "text": link['text'] or "Direct File",
                    "type": "Direct File"
                })
            elif 'mediafire.com' in href or 'mega.nz' in href or 'dropbox.com' in href:
                direct_links.append({
                    "url": href,
                    "text": link['text'] or "External Service",
                    "type": "External Service"
                })

        if not direct_links:
            return {"success": False, "data": "❌ কোনো ডাউনলোড লিংক পাওয়া যায়নি।"}

        return {"success": True, "data": direct_links}

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "data": f"🌐 নেটওয়ার্ক এরর: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"success": False, "data": f"⚠️ অজানা ত্রুটি: {str(e)}"}

# ============================================================
# 🤖 সিঙ্ক্রোনাস টেলিগ্রাম হ্যান্ডলার (async ছাড়া)
# ============================================================

def start(bot: Bot, update: Update):
    bot.send_message(
        chat_id=update.effective_chat.id,
        text="👋 **HubCloud Bypasser Bot**\n\nআমাকে একটি HubCloud লিংক পাঠান।\nআমি সব ডাউনলোড লিংক বের করে দেব।\n\nযেমন: `https://hubcloud.one/drive/xxxxx`"
    )

def help_command(bot: Bot, update: Update):
    bot.send_message(
        chat_id=update.effective_chat.id,
        text="📖 **কীভাবে ব্যবহার করবেন:**\n1️⃣ HubCloud লিংক পাঠান (টেক্সট মেসেজ হিসেবে)\n2️⃣ আমি সব ডাউনলোড লিংক বের করব\n\n🔰 **সাপোর্টেড লিংক:**\n- hubcloud.one\n- vifix.site/hubcloud/xxxxx"
    )

def handle_link(bot: Bot, update: Update):
    user_input = update.message.text.strip()
    if not re.match(r'^https?://', user_input):
        bot.send_message(chat_id=update.effective_chat.id, text="❌ দয়া করে একটি বৈধ URL দিন (http:// বা https:// দিয়ে শুরু)।")
        return

    bot.send_message(chat_id=update.effective_chat.id, text="⏳ বাইপাস করা হচ্ছে, একটু অপেক্ষা করুন...")

    result = bypass_hubcloud(user_input)

    if not result["success"]:
        bot.send_message(chat_id=update.effective_chat.id, text=f"❌ **ব্যর্থ!**\n\n{result['data']}")
        return

    links = result["data"]
    if not links:
        bot.send_message(chat_id=update.effective_chat.id, text="❌ কোনো ডাউনলোড লিংক পাওয়া যায়নি।")
        return

    # রেসপন্স তৈরি
    reply = "✅ **ডাউনলোড লিংক সমূহ:**\n\n"
    for i, link in enumerate(links, 1):
        reply += f"{i}. **{link['type']}** – `{link['url']}`\n"

    # মেসেজ খুব বড় হলে split করে পাঠানো
    if len(reply) > 4000:
        for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
            bot.send_message(chat_id=update.effective_chat.id, text=chunk, disable_web_page_preview=True)
    else:
        bot.send_message(chat_id=update.effective_chat.id, text=reply, disable_web_page_preview=True)

def unknown(bot: Bot, update: Update):
    bot.send_message(chat_id=update.effective_chat.id, text="❓ /help দিন সাহায্যের জন্য।")

# ============================================================
# 🚀 Flask অ্যাপ + ডিসপ্যাচার (Vercel-এর জন্য)
# ============================================================

application = Flask(__name__)
bot = Bot(token=BOT_TOKEN)

# ডিসপ্যাচার তৈরি (সিঙ্ক্রোনাস)
dispatcher = Dispatcher(bot, None, use_context=False)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
dispatcher.add_handler(MessageHandler(filters.COMMAND, unknown))

@application.route('/', methods=['GET'])
def index():
    return "🤖 HubCloud Bypasser Bot is running on Vercel!"

@application.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json(force=True)
        if not body:
            return "Invalid request", 400

        update = Update.de_json(body, bot)
        # সিঙ্ক্রোনাসভাবে ডিসপ্যাচার দিয়ে প্রসেস
        dispatcher.process_update(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
