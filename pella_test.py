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
# 1. TG 通知功能
# ==========================================
def send_tg_notification(status, message, photo_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id): return
    tz_bj = timezone(timedelta(hours=8))
    bj_time = datetime.now(tz_bj).strftime('%Y-%m-%d %H:%M:%S')
    emoji = "✅" if "成功" in status else "❌"
    formatted_msg = f"{emoji} **Pella 自动化续期报告**\n━━━━━━━━━━━━━━━━━━\n👤 **账户**: `{os.environ.get('PELLA_EMAIL')}`\n📡 **状态**: {status}\n📝 **详情**: {message}\n🕒 **北京时间**: `{bj_time}`\n━━━━━━━━━━━━━━━━━━"
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
# 2. Gmail 验证码提取
# ==========================================
def get_pella_code(mail_address, app_password):
    logger.info("📡 连接 Gmail 抓取验证码...")
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
# 3. Pella 自动化主程序
# ==========================================
def run_test():
    email_addr = os.environ.get("PELLA_EMAIL")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    target_server_url = "https://www.pella.app/server/c216766d5bbb47fc982167ec08c144b1"
    renew_url = "https://cuttlinks.com/Q9wFiVeMT6vw"
    
    with SB(uc=True, xvfb=True) as sb:
        try:
            # --- 第一阶段: 登录与状态识别 ---
            sb.uc_open_with_reconnect("https://www.pella.app/login", 10)
            sb.sleep(5)
            sb.uc_gui_click_captcha()
            sb.wait_for_element_visible("#identifier-field", timeout=25)
            for char in email_addr:
                sb.add_text("#identifier-field", char)
                time.sleep(0.1)
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码抓取失败")
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(10)

            # --- 第二阶段: 检查冷却状态 ---
            sb.uc_open_with_reconnect(target_server_url, 10)
            sb.sleep(8) 
            expiry_info = "未知"
            try:
                full_text = sb.get_text('div.max-h-full.overflow-auto')
                d = re.search(r'(\d+)\s*天', full_text)
                h = re.search(r'(\d+)\s*小时', full_text)
                m = re.search(r'(\d+)\s*分钟', full_text)
                parts = [f"{d.group(1)}天" if d else "", f"{h.group(1)}小时" if h else "", f"{m.group(1)}分钟" if m else ""]
                expiry_info = "".join(parts).strip()
            except: pass

            target_btn_in_pella = 'a[href*="tpi.li/FSfV"]'
            if sb.is_element_visible(target_btn_in_pella):
                btn_class = sb.get_attribute(target_btn_in_pella, "class")
                if "opacity-50" in btn_class or "pointer-events-none" in btn_class:
                    send_tg_notification("保活报告 (冷却中) 🕒", f"按钮尚在冷却。剩余时间: {expiry_info}", None)
                    return 

            # --- 第三阶段: 穿透 Cloudflare (Kata 模式) ---
            logger.info(f"跳转至续期网站: {renew_url}")
            sb.uc_open_with_reconnect(renew_url, 10)
            sb.sleep(6)
            
            logger.info("尝试穿透 Cloudflare...")
            try:
                cf_iframe = 'iframe[src*="cloudflare"]'
                if sb.is_element_visible(cf_iframe):
                    sb.switch_to_frame(cf_iframe)
                    sb.click('span.mark') 
                    sb.switch_to_parent_frame()
                    logger.success("已点击 CF 验证框")
                    sb.sleep(6)
                else:
                    sb.uc_gui_click_captcha()
            except: pass

            # --- 第四阶段: 强力点击 "I am not a robot" ---
            # 该按钮特征: id="submit-button" data-ref="captcha"
            logger.info("开始执行 'I am not a robot' 强力点击...")
            click_done = False
            target_btn = 'button#submit-button[data-ref="captcha"]'
            
            for i in range(8): # 增加到 8 次尝试，应对多层广告
                try:
                    if sb.is_element_visible(target_btn):
                        logger.info(f"第 {i+1} 次点击按钮...")
                        sb.js_click(target_btn)
                        sb.sleep(3)
                        
                        # 核心：自动关闭弹出的广告窗口并切回主页面
                        if len(sb.driver.window_handles) > 1:
                            curr_handle = sb.driver.current_window_handle
                            for handle in sb.driver.window_handles:
                                if handle != curr_handle:
                                    sb.driver.switch_to.window(handle)
                                    sb.driver.close()
                            sb.driver.switch_to.window(sb.driver.window_handles[0])
                        
                        # 检查按钮是否成功消失（代表跳转成功）
                        if not sb.is_element_visible(target_btn):
                            click_done = True
                            break
                except: pass
            
            sb.sleep(5)
            sb.save_screenshot("final_check.png")
            
            if click_done:
                send_tg_notification("续期成功 ✅", f"已穿透人机并完成多次点击。前状态: {expiry_info}", "final_check.png")
            else:
                send_tg_notification("流程结束 ⚠️", f"已尝试多次点击，请通过截图确认是否跳转成功。剩余: {expiry_info}", "final_check.png")

        except Exception as e:
            sb.save_screenshot("error.png")
            send_tg_notification("保活失败 ❌", f"错误详情: `{str(e)}`", "error.png")
            raise e

if __name__ == "__main__":
    run_test()
