import os
import time
import imaplib
import email
import re
import requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB
from loguru import logger

# ==========================================
# 1. TG 通知功能 (增强版：确保每步都有反馈)
# ==========================================
def send_tg_notification(status, message, photo_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id): return
    tz_bj = timezone(timedelta(hours=8))
    bj_time = datetime.now(tz_bj).strftime('%Y-%m-%d %H:%M:%S')
    emoji = "✅" if "成功" in status else "❌"
    formatted_msg = f"{emoji} **Pella 自动化续期报告**\n━━━━━━━━━━━━━━━━━━\n👤 **账户**: `{os.environ.get('PELLA_EMAIL')}`\n📡 **状态**: {status}\n📝 **详情**: {message}\n🕒 **时间**: `{bj_time}`\n━━━━━━━━━━━━━━━━━━"
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", 
                              data={'chat_id': chat_id, 'caption': formatted_msg, 'parse_mode': 'Markdown'}, 
                              files={'photo': f})
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          data={'chat_id': chat_id, 'text': formatted_msg, 'parse_mode': 'Markdown'})
    except Exception as e: logger.error(f"TG通知失败: {e}")

# ==========================================
# 2. Gmail 验证码提取 (保持逻辑)
# ==========================================
def get_pella_code(mail_address, app_password):
    logger.info(f"📡 连接 Gmail 抓取...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(mail_address, app_password)
        mail.select("inbox")
        for i in range(10):
            status, messages = mail.search(None, '(FROM "Pella" UNSEEN)')
            if status == "OK" and messages[0]:
                latest_msg_id = messages[0].split()[-1]
                status, data = mail.fetch(latest_msg_id, "(RFC822)")
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                content = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            content = part.get_payload(decode=True).decode()
                else:
                    content = msg.get_payload(decode=True).decode()
                code = re.search(r'\b\d{6}\b', content)
                if code:
                    mail.store(latest_msg_id, '+FLAGS', '\\Seen')
                    return code.group()
            time.sleep(10)
        return None
    except Exception as e: return None

# ==========================================
# 3. Pella 自动化核心流
# ==========================================
def run_test():
    email_addr = os.environ.get("PELLA_EMAIL")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    
    with SB(uc=True, xvfb=True) as sb:
        try:
            # 1. 登录
            sb.uc_open_with_reconnect("https://www.pella.app/login", 10)
            sb.sleep(5)
            sb.uc_gui_click_captcha()
            sb.wait_for_element_visible("#identifier-field", timeout=25)
            for char in email_addr:
                sb.add_text("#identifier-field", char)
                time.sleep(0.1)
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)

            # 2. 验证
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码提取失败")
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(12) # 给足跳转时间

            # 3. 定位并点击服务器 nztz
            logger.info("正在寻找服务器项目: nztz")
            sb.wait_for_element_visible('div:contains("nztz")', timeout=30)
            sb.js_click('div:contains("nztz")') # 改用 JS 点击，防止遮挡
            sb.sleep(5)
            sb.save_screenshot("server_detail.png") # 确认是否点进去了

            # 4. 提取到期时间 (全单位匹配)
            expiry_info = "提取失败"
            try:
                full_text = sb.get_text('div.max-h-full.overflow-auto')
                d = re.search(r'(\d+)\s*天', full_text)
                h = re.search(r'(\d+)\s*小时', full_text)
                m = re.search(r'(\d+)\s*分钟', full_text)
                res = []
                if d: res.append(f"{d.group(1)}天")
                if h: res.append(f"{h.group(1)}小时")
                if m: res.append(f"{m.group(1)}分钟")
                expiry_info = "".join(res) if res else "未匹配到数值"
            except: pass

            # 5. 执行保活点击
            target_btn = 'a[href*="tpi.li/FSfV"]'
            if sb.is_element_visible(target_btn):
                btn_class = sb.get_attribute(target_btn, "class")
                if "opacity-50" in btn_class or "pointer-events-none" in btn_class:
                    msg = f"按钮冷却中。剩余时长: {expiry_info}"
                    send_tg_notification("保活报告 (冷却中) 🕒", msg, "server_detail.png")
                else:
                    sb.js_click(target_btn)
                    sb.sleep(3)
                    sb.save_screenshot("after_renew.png")
                    send_tg_notification("保活成功 ✅", f"已自动续期。操作前剩余: {expiry_info}", "after_renew.png")
            else:
                send_tg_notification("保活报告 📡", f"已进入项目页。当前剩余: {expiry_info}", "server_detail.png")

        except Exception as e:
            sb.save_screenshot("error.png")
            send_tg_notification("保活失败 ❌", f"错误: `{str(e)}`", "error.png")
            raise e

if __name__ == "__main__":
    run_test()
