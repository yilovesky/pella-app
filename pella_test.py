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
# 1. TG 通知功能 (保持不变)
# ==========================================
def send_tg_notification(status, message, photo_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id): return
    tz_bj = timezone(timedelta(hours=8))
    bj_time = datetime.now(tz_bj).strftime('%Y-%m-%d %H:%M:%S')
    emoji = "✅" if "成功" in status else "❌"
    formatted_msg = f"{emoji} **Pella 自动化续期报告**\n━━━━━━━━━━━━━━━━━━\n👤 **账户**: `{os.environ.get('PELLA_EMAIL')}`\n📡 **状态**: {status}\n📝 : {message}\n🕒 **北京时间**: `{bj_time}`\n━━━━━━━━━━━━━━━━━━"
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={'chat_id': chat_id, 'caption': formatted_msg, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': formatted_msg, 'parse_mode': 'Markdown'})
    except Exception as e: logger.error(f"TG通知失败: {e}")

# ==========================================
# 2. Gmail 验证码提取 (锁死不改)
# ==========================================
def get_pella_code(mail_address, app_password):
    logger.info("📡 正在连接 Gmail 抓取验证码...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(mail_address, app_password)
        mail.select("inbox")
        for i in range(15):  # 略微增加轮次确保稳定
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
# 3. Pella 自动化流程
# ==========================================
def run_test():
    email_addr = "yilovesky520@gmail.com"
    app_pw = "rmbfwtttsecnxhog"
    
    with SB(uc=True, xvfb=True) as sb:
        main_window = sb.driver.current_window_handle
        
        try:
            # --- 第一阶段: 登录与动态服务器识别 ---
            logger.info("🚀 [面板监控] 正在启动 Pella 登录流程...")
            sb.uc_open_with_reconnect("https://www.pella.app/login", 10)
            sb.sleep(5)
            sb.save_screenshot("step1_login_page.png")
            send_tg_notification("进度日志 📸", "已打开登录页面", "step1_login_page.png")

            sb.uc_gui_click_captcha()
            logger.info("🖱️ [面板监控] 已点击登录页 Captcha")
            sb.wait_for_element_visible("#identifier-field", timeout=25)
            for char in email_addr:
                sb.add_text("#identifier-field", char)
                time.sleep(0.1)
            
            # 【顺序修正】：先点回车提交，才会触发验证码邮件
            sb.press_keys("#identifier-field", "\n")
            logger.info("📩 [面板监控] 已提交邮箱，正在请求发送验证码...")
            sb.sleep(5)
            
            # 提交后才去抓码
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码抓取失败")
            logger.info(f"🔢 [面板监控] 抓取到验证码: {auth_code}")
            
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(10)
            sb.save_screenshot("step3_after_otp.png")
            send_tg_notification("进度日志 📸", "已提交验证码", "step3_after_otp.png")
            
            # 【动态扫描 UUID】
            logger.info("🔍 [面板监控] 正在扫描网页中的服务器 UUID...")
            sb.wait_for_element_visible('a[href^="/server/"]', timeout=20)
            server_link = sb.get_attribute('a[href^="/server/"]', "href")
            uuid_match = re.search(r'/server/([a-z0-9]+)', server_link)
            extracted_uuid = uuid_match.group(1) if uuid_match else ""
            
            if server_link.startswith("/"):
                target_server_url = f"https://www.pella.app{server_link}"
            else:
                target_server_url = server_link
            
            logger.info(f"✅ [面板监控] 自动识别到服务器地址: {target_server_url}")
            sb.save_screenshot("step3_after_login_scan.png")
            send_tg_notification("进度日志 📸", f"登录成功，自动扫到服务器: {target_server_url}", "step3_after_login_scan.png")

            # --- 第二阶段: 检查 Pella 状态 ---
            logger.info("🔍 [面板监控] 正在进入识别到的服务器面板...")
            sb.uc_open_with_reconnect(target_server_url, 10)
            sb.sleep(10) 
            sb.save_screenshot("step4_server_dashboard.png")
            send_tg_notification("进度日志 📸", "已进入服务器控制面板", "step4_server_dashboard.png")
            
            def get_expiry_time_raw(sb_obj):
                try:
                    js_code = """
                    var divs = document.querySelectorAll('div');
                    for (var d of divs) {
                        var txt = d.innerText;
                        if (txt.includes('expiring') && (txt.includes('Day') || txt.includes('Hours') || txt.includes('天'))) {
                            return txt;
                        }
                    }
                    return "未找到时间文本";
                    """
                    raw_text = sb_obj.execute_script(js_code)
                    clean_text = " ".join(raw_text.split())
                    if "expiring in" in clean_text:
                        return clean_text.split("expiring in")[1].split(".")[0].strip()
                    return clean_text[:60]
                except: return "获取失败"

            expiry_before = get_expiry_time_raw(sb)
            logger.info(f"🕒 [面板监控] 续期前剩余时间: {expiry_before}")

            # --- 物理点击进入续期跳转页 ---
            target_btn_selector = 'a[href*="cuty.io"]'
            if sb.is_element_visible(target_btn_selector):
                logger.info("🖱️ [面板监控] 正在执行真实物理点击以触发后端续期握手...")
                sb.click(target_btn_selector)
                sb.sleep(5)
                if len(sb.driver.window_handles) > 1:
                    for handle in sb.driver.window_handles:
                        sb.driver.switch_to.window(handle)
                        if "cuty.io" in sb.driver.current_url: break
                sb.save_screenshot("step5_renew_clicked.png")
                send_tg_notification("进度日志 📸", "已通过物理点击进入续期跳转页面", "step5_renew_clicked.png")

            logger.info("🖱️ [面板监控] 执行第一个 Continue 强力点击...")
            for i in range(5):
                try:
                    if sb.is_element_visible('button#submit-button[data-ref="first"]'):
                        sb.js_click('button#submit-button[data-ref="first"]')
                        sb.sleep(3)
                        if len(sb.driver.window_handles) > 1:
                            sb.driver.switch_to.window(sb.driver.window_handles[0])
                        if not sb.is_element_visible('button#submit-button[data-ref="first"]'): break
                except: pass

            # --- 第四阶段: 处理 Cloudflare 人机挑战 ---
            logger.info("🛡️ [面板监控] 检测人机验证中...")
            sb.sleep(5)
            try:
                cf_iframe = 'iframe[src*="cloudflare"]'
                if sb.is_element_visible(cf_iframe):
                    sb.switch_to_frame(cf_iframe)
                    sb.click('span.mark') 
                    sb.switch_to_parent_frame()
                    sb.sleep(6)
            except: pass

            def clean_ads(sb_obj):
                try:
                    js_cleanup = """
                    var ads = document.querySelectorAll('div[id^="div_netpub_ins_"]');
                    ads.forEach(function(ad) { ad.remove(); });
                    var iframes = document.querySelectorAll('iframe[id^="adg-"]');
                    iframes.forEach(function(f) { f.remove(); });
                    document.body.style.overflow = 'auto';
                    """
                    sb_obj.execute_script(js_cleanup)
                except: pass

            # --- 第五阶段: 强力点击 "I am not a robot" ---
            logger.info("🖱️ [面板监控] 开始点击 'I am not a robot' (data-ref='captcha')...")
            captcha_btn = 'button#submit-button[data-ref="captcha"]'
            for i in range(8): 
                try:
                    if sb.is_element_visible(captcha_btn):
                        clean_ads(sb) 
                        sb.js_click(captcha_btn)
                        sb.sleep(3)
                        if len(sb.driver.window_handles) > 1:
                            sb.driver.switch_to.window(main_window)
                        if not sb.is_element_visible(captcha_btn):
                            sb.save_screenshot("step7_robot_clicked.png")
                            send_tg_notification("进度日志 📸", "成功点击 Robot 按钮", "step7_robot_clicked.png")
                            break
                except: pass

            # --- 第六阶段: 等待 计时并点击最终 Go 按钮 ---
            logger.info("⌛ [面板监控] 等待 18 秒计时结束...")
            sb.sleep(18)
            sb.save_screenshot("step8_wait_timer.png")
            
            final_btn = 'button#submit-button[data-ref="show"]'
            click_final = False
            for i in range(8):
                try:
                    if sb.is_element_visible(final_btn):
                        clean_ads(sb)
                        logger.info(f"🖱️ [面板监控] 第 {i+1} 次点击最终 Go 按钮...")
                        sb.js_click(final_btn)
                        sb.sleep(3)
                        # 核心修正：点完 GO 强制回主窗口
                        if len(sb.driver.window_handles) > 1:
                            sb.driver.switch_to.window(main_window)
                        if not sb.is_element_visible(final_btn):
                            click_final = True
                            sb.save_screenshot("step9_final_clicked.png")
                            send_tg_notification("进度日志 📸", "成功点击最终 Go 按钮", "step9_final_clicked.png")
                            break
                except: pass

            # 【强制在原页面执行 15 秒等待和刷新】
            if click_final:
                sb.driver.switch_to.window(main_window)
                logger.info("⌛ [面板监控] 点击成功，主标签页原地等待 15 秒...")
                sb.sleep(15)
                
                renew_final_url = f"https://www.pella.app/renew/{extracted_uuid}"
                logger.info(f"🚀 [面板监控] 跳转确认页并刷新: {renew_final_url}")
                sb.uc_open_with_reconnect(renew_final_url, 10)
                
                for r in range(3):
                    sb.sleep(5)
                    logger.info(f"🔄 [面板监控] 执行确认页第 {r+1} 次刷新...")
                    sb.refresh_page()
                    sb.save_screenshot(f"refresh_step_{r+1}.png")
                    send_tg_notification("进度日志 📸", f"执行第 {r+1} 次刷新确认", f"refresh_step_{r+1}.png")
            
            # --- 第七阶段: 结果验证 ---
            logger.info("🏁 [面板监控] 操作完成，正在回访 Pella 验证续期结果...")
            sb.sleep(5)
            sb.uc_open_with_reconnect(target_server_url, 10)
            sb.sleep(10)
            
            expiry_after = get_expiry_time_raw(sb)
            logger.info(f"🕒 [面板监控] 续期后剩余时间: {expiry_after}")
            sb.save_screenshot("final_result.png")
            
            if click_final:
                send_tg_notification("续期成功 ✅", f"续期前: {expiry_before}\n续期后: {expiry_after}", "final_result.png")
            else:
                send_tg_notification("操作反馈 ⚠️", f"流程已执行至最后，请检查截图。续期前: {expiry_before}\n当前时间: {expiry_after}", "final_result.png")

        except Exception as e:
            logger.error(f"🔥 [面板监控] 流程崩溃: {str(e)}")
            sb.save_screenshot("error.png")
            send_tg_notification("保活失败 ❌", f"错误详情: `{str(e)}`", "error.png")
            raise e

if __name__ == "__main__":
    run_test()
