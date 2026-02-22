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
    email_addr = "yilovesky520@gmail.com"
    app_pw = "rmbfwtttsecnxhog"
    
    with SB(uc=True, xvfb=True) as sb:
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
            sb.save_screenshot("step2_input_email.png")
            send_tg_notification("进度日志 📸", "已输入邮箱地址", "step2_input_email.png")
            
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)
            
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码抓取失败")
            logger.info(f"🔢 [面板监控] 抓取到验证码: {auth_code}")
            
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(10)
            
            # 【动态扫描 UUID】: 登录后在主页寻找服务器链接
            logger.info("🔍 [面板监控] 正在扫描网页中的服务器 UUID...")
            sb.wait_for_element_visible('a[href^="/server/"]', timeout=20)
            server_link = sb.get_attribute('a[href^="/server/"]', "href")
            # 提取 UUID 用于后续跳转
            uuid_match = re.search(r'/server/([a-z0-9]+)', server_link)
            extracted_uuid = uuid_match.group(1) if uuid_match else ""
            
            # 如果是相对路径则补全
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

            target_btn_selector = 'a[href*="cuty.io"]'
            
            if sb.is_element_visible(target_btn_selector):
                btn_class = sb.get_attribute(target_btn_selector, "class")
                is_cooling = "opacity-50" in btn_class and "disabled:opacity-50" not in btn_class
                
                if is_cooling or "pointer-events-none" in btn_class:
                    logger.warning("🕒 [面板监控] 按钮处于冷却中，任务结束。")
                    send_tg_notification("保活报告 (冷却中) 🕒", f"按钮尚在冷却。剩余时间: {expiry_before}", "step4_server_dashboard.png")
                    return 

            # --- 第三阶段: 点击按钮进入续期网站 ---
            logger.info("🖱️ [面板监控] 正在点击续期按钮进入续期网站...")
            
            # 获取当前窗口句柄，以便点击后切换
            original_window = sb.driver.current_window_handle
            
            # 执行点击进入续期网站 (此处按照你的要求改成了点击 a 标签进入)
            if sb.is_element_visible(target_btn_selector):
                sb.js_click(target_btn_selector)
                sb.sleep(5)
                
                # 处理 target="_blank" 打开的新窗口
                if len(sb.driver.window_handles) > 1:
                    for handle in sb.driver.window_handles:
                        if handle != original_window:
                            sb.driver.switch_to.window(handle)
                            logger.info("🌐 [面板监控] 已通过点击切换至续期跳转新页面")
                            break

            sb.save_screenshot("step5_renew_url_opened.png")
            send_tg_notification("进度日志 📸", "已通过点击进入续期页面", "step5_renew_url_opened.png")

            logger.info("🖱️ [面板监控] 执行第一个 Continue 强力点击...")
            for i in range(5):
                try:
                    if sb.is_element_visible('button#submit-button[data-ref="first"]'):
                        sb.js_click('button#submit-button[data-ref="first"]')
                        sb.sleep(3)
                        # 如果点击后产生了干扰弹窗窗口，保持切回操作页
                        if len(sb.driver.window_handles) > 2:
                             sb.driver.switch_to.window(sb.driver.window_handles[-1])
                        if not sb.is_element_visible('button#submit-button[data-ref="first"]'):
                            break
                except: pass

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
            if sb.is_element_visible(final_btn):
                clean_ads(sb)
                
                # 1. 记住当前 Cuty.io 所在的窗口
                main_window = sb.driver.current_window_handle
                logger.info(f"🖱️ [面板监控] 准备点击最终 GO 按钮...")
                
                # 2. 点击 GO
                sb.js_click(final_btn)
                sb.sleep(4) # 等待广告窗口弹出
                
                # 3. 强力清理弹出的广告窗口，并回到主窗口
                if len(sb.driver.window_handles) > 1:
                    for handle in sb.driver.window_handles:
                        if handle != main_window:
                            sb.driver.switch_to.window(handle)
                            sb.driver.close() # 关掉广告页
                    sb.driver.switch_to.window(main_window)
                    logger.info("🚫 [面板监控] 已关闭广告弹窗，切回主窗口等待重定向...")

                # 4. 【关键】不要手动跳转！死等原窗口自动变更为 Pella 链接
                # Cuty.io 会在 5-15 秒内把原窗口重定向回 pella.app/renew/xxx
                success_redirect = False
                for _ in range(30): # 最多等 30 秒
                    curr_url = sb.get_current_url()
                    if "pella.app/renew/" in curr_url:
                        logger.info(f"✅ [面板监控] 检测到自动重定向成功: {curr_url}")
                        success_redirect = True
                        break
                    sb.sleep(1)
                
                if not success_redirect:
                    logger.warning("⚠️ [面板监控] 未检测到自动重定向，尝试手动补救跳转...")
                    renew_final_url = f"https://www.pella.app/renew/{extracted_uuid}"
                    sb.uc_open_with_reconnect(renew_final_url, 10)

                # 5. 重定向到达后，按照你之前的逻辑刷新 3 次确认
                for r in range(3):
                    sb.sleep(5)
                    sb.refresh_page()
                    logger.info(f"🔄 [面板监控] 执行第 {r+1} 次刷新确认...")
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
