import os
import re
import json
import logging
import requests
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 🔥 HubCloud Bypass লজিক (HTML থেকে নেওয়া)
# ============================================================

def extract_links_from_html(html: str) -> list:
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
            target_url = f"https://hubcloud.cx/drive/{file_id}"
            logger.info(f"Converted vifix.site URL to: {target_url}")

        # ২. প্রথম পেজ ফেচ
        resp1 = session.get(target_url, timeout=30, allow_redirects=True)
        resp1.raise_for_status()
        html1 = resp1.text

        # ৩. #download আইডি থাকা <a> ট্যাগ খোঁজ
        all_links = extract_links_from_html(html1)
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
        all_links2 = extract_links_from_html(html2)
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
# 📤 টেলিগ্রামে মেসেজ পাঠানোর ফাংশন
# ============================================================

def send_telegram_message(chat_id: int, text: str, parse_mode: str = "Markdown", disable_web_page_preview: bool = False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

# ============================================================
# 🤖 ফ্লাস্ক অ্যাপ (Vercel ওয়েবহুক)
# ============================================================

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

        # মেসেজের ডেটা বের করা
        message = body.get('message')
        if not message:
            return "No message", 200

        chat_id = message.get('chat', {}).get('id')
        if not chat_id:
            return "No chat_id", 200

        # কমান্ড বা টেক্সট প্রসেস
        text = message.get('text', '')
        if not text:
            send_telegram_message(chat_id, "❌ শুধু টেক্সট মেসেজ গ্রহণ করি।")
            return "OK", 200

        # কমান্ড হ্যান্ডলিং
        if text.startswith('/'):
            if text == '/start':
                send_telegram_message(
                    chat_id,
                    "👋 **HubCloud Bypasser Bot**\n\nআমাকে একটি HubCloud লিংক পাঠান।\nআমি সব ডাউনলোড লিংক বের করে দেব।\n\nযেমন: `https://hubcloud.cx/drive/xxxxx`"
                )
            elif text == '/help':
                send_telegram_message(
                    chat_id,
                    "📖 **কীভাবে ব্যবহার করবেন:**\n1️⃣ HubCloud লিংক পাঠান (টেক্সট মেসেজ হিসেবে)\n2️⃣ আমি সব ডাউনলোড লিংক বের করব\n\n🔰 **সাপোর্টেড লিংক:**\n- hubcloud.one\n- vifix.site/hubcloud/xxxxx"
                )
            else:
                send_telegram_message(chat_id, "❓ অজানা কমান্ড। /help দিন সাহায্যের জন্য।")
            return "OK", 200

        # লিংক চেক
        if not re.match(r'^https?://', text):
            send_telegram_message(chat_id, "❌ দয়া করে একটি বৈধ URL দিন (http:// বা https:// দিয়ে শুরু)।")
            return "OK", 200

        # প্রসেসিং শুরু
        send_telegram_message(chat_id, "⏳ বাইপাস করা হচ্ছে, একটু অপেক্ষা করুন...")

        result = bypass_hubcloud(text)

        if not result["success"]:
            send_telegram_message(chat_id, f"❌ **ব্যর্থ!**\n\n{result['data']}")
            return "OK", 200

        links = result["data"]
        if not links:
            send_telegram_message(chat_id, "❌ কোনো ডাউনলোড লিংক পাওয়া যায়নি।")
            return "OK", 200

        # রেসপন্স তৈরি
        reply = "✅ **ডাউনলোড লিংক সমূহ:**\n\n"
        for i, link in enumerate(links, 1):
            reply += f"{i}. **{link['type']}** – `{link['url']}`\n"

        # মেসেজ খুব বড় হলে split করে পাঠানো
        if len(reply) > 4000:
            for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
                send_telegram_message(chat_id, chunk, disable_web_page_preview=True)
        else:
            send_telegram_message(chat_id, reply, disable_web_page_preview=True)

        return "OK", 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
