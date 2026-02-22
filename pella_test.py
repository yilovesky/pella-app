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
# 3. Pella 自动化流程
# ==========================================
def run_test():
    email_addr = os.environ.get("PELLA_EMAIL")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    target_server_url = "https://www.pella.app/server/3609ece276a7473bba79f75fd897aa78"
    
    with SB(uc=True, xvfb=True) as sb:
        try:
            # --- 第一阶段: 登录与状态识别 ---
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
            sb.save_screenshot("step2_input_email.png")
            send_tg_notification("进度日志 📸", "已输入邮箱地址", "step2_input_email.png")
            
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)
            
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码抓取失败")
            logger.info(f"🔢 [面板监控] 抓取到验证码: {auth_code}")
            
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(10)
            sb.save_screenshot("step3_after_otp.png")
            send_tg_notification("进度日志 📸", "已提交验证码", "step3_after_otp.png")

            # --- 第二阶段: 检查 Pella 状态 ---
            logger.info("🔍 [面板监控] 正在检查服务器初始状态...")
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

            target_btn_selector = 'a[href*="cuty.io"]'
            
            if sb.is_element_visible(target_btn_selector):
                btn_class = sb.get_attribute(target_btn_selector, "class")
                # 【关键修正】：使用更严格的过滤逻辑，排除掉包含 'disabled:' 的干扰项
                # 只有当按钮 class 包含 'opacity-50' 且不带 'disabled:' 前缀时，才认为是冷却中
                is_cooling = "opacity-50" in btn_class and "disabled:opacity-50" not in btn_class
                
                if is_cooling or "pointer-events-none" in btn_class:
                    logger.warning("🕒 [面板监控] 按钮处于冷却中，任务结束。")
                    send_tg_notification("保活报告 (冷却中) 🕒", f"按钮尚在冷却。剩余时间: {expiry_before}", "step4_server_dashboard.png")
                    return 

            # --- 第三阶段: 获取动态网址并跳转 ---
            logger.info("🖱️ [面板监控] 正在从页面抓取动态续期链接...")
            dynamic_renew_url = sb.get_attribute(target_btn_selector, "href")
            logger.info(f"🔗 [面板监控] 成功识别续期网址: {dynamic_renew_url}")
            
            sb.uc_open_with_reconnect(dynamic_renew_url, 10)
            sb.sleep(5)
            sb.save_screenshot("step5_renew_url_opened.png")
            send_tg_notification("进度日志 📸", "已打开续期跳转链接", "step5_renew_url_opened.png")

            # --- 第四阶段: 处理 Cloudflare 人机挑战 ---
            logger.info("🛡️ [面板监控] 检测人机验证中...")
            sb.sleep(5)
            try:
                cf_iframe = 'iframe[src*="cloudflare"]'
                if sb.is_element_visible(cf_iframe):
                    logger.info("✅ [面板监控] 发现 CF 验证，尝试 Kata 模式穿透...")
                    sb.switch_to_frame(cf_iframe)
                    sb.click('span.mark') 
                    sb.switch_to_parent_frame()
                    sb.sleep(6)
                    sb.save_screenshot("step6_after_cf.png")
                    send_tg_notification("进度日志 📸", "已尝试点击 CF 验证", "step6_after_cf.png")
                else:
                    sb.uc_gui_click_captcha()
            except: pass

            # 【新增逻辑】：清理阻碍点击的广告弹窗
            def clean_ads(sb_obj):
                try:
                    # 移除 ID 以 div_netpub_ins_ 开头的广告容器
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
                        clean_ads(sb) # 点击前清理广告
                        sb.js_click(captcha_btn)
                        logger.info(f"🖱️ [面板监控] 点击 'I am not a robot' 第 {i+1} 次")
                        sb.sleep(3)
                        if len(sb.driver.window_handles) > 1:
                            curr = sb.driver.current_window_handle
                            for handle in sb.driver.window_handles:
                                if handle != curr:
                                    sb.driver.switch_to.window(handle)
                                    sb.driver.close()
                            sb.driver.switch_to.window(sb.driver.window_handles[0])
                        if not sb.is_element_visible(captcha_btn):
                            sb.save_screenshot("step7_robot_clicked.png")
                            send_tg_notification("进度日志 📸", "成功点击 Robot 按钮", "step7_robot_clicked.png")
                            break
                except: pass

            # --- 第六阶段: 等待 18 秒计时并点击最终 Go 按钮 ---
            logger.info("⌛ [面板监控] 等待 18 秒计时结束...")
            sb.sleep(18)
            sb.save_screenshot("step8_wait_timer.png")
            send_tg_notification("进度日志 📸", "18秒倒计时结束，准备点击最终按钮", "step8_wait_timer.png")
            
            final_btn = 'button#submit-button[data-ref="show"]'
            click_final = False
            for i in range(8):
                try:
                    if sb.is_element_visible(final_btn):
                        clean_ads(sb) # 点击前清理广告
                        logger.info(f"🖱️ [面板监控] 第 {i+1} 次点击最终 Go 按钮...")
                        sb.js_click(final_btn)
                        sb.sleep(3)
                        if len(sb.driver.window_handles) > 1:
                            curr = sb.driver.current_window_handle
                            for h in sb.driver.window_handles:
                                if h != curr: sb.driver.switch_to.window(h); sb.driver.close()
                            sb.driver.switch_to.window(sb.driver.window_handles[0])
                        
                        if not sb.is_element_visible(final_btn):
                            click_final = True
                            sb.save_screenshot("step9_final_clicked.png")
                            send_tg_notification("进度日志 📸", "成功点击最终 Go 按钮", "step9_final_clicked.png")
                            break
                except: pass
            
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
