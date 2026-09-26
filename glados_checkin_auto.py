import os
import json
import hashlib
import requests

# ==================== 配置区 ====================
# 支持从环境变量 GLADOS_COOKIES 中获取，多个 Cookie 用 '&&' 分隔
# 格式示例: gld:sess=xxx; gld:sess.sig=yyy&&gld:sess=zzz; gld:sess.sig=www
RAW_COOKIES = os.environ.get("GLADOS_COOKIES", "")
# 企业微信 Webhook 地址
WECHAT_WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

CHECKIN_URL = "https://glados.one/api/user/checkin"
STATUS_URL = "https://glados.one/api/user/status"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://glados.one",
    "Referer": "https://glados.one/console/checkin"
}

def get_cookie_fingerprint(cookie_str: str) -> str:
    """生成 Cookie 短指纹，用于识别 Cookie 但不泄露敏感数据"""
    return hashlib.sha256(cookie_str.encode('utf-8')).hexdigest()[:8]

def validate_cookie_format(cookie_str: str) -> bool:
    """检查 Cookie 是否包含必要的 session 字段"""
    return "gld:sess" in cookie_str and "gld:sess.sig" in cookie_str

def do_checkin(cookie: str):
    """执行签到请求并解析结果"""
    headers = HEADERS.copy()
    headers["Cookie"] = cookie.strip()
    
    try:
        # GLaDOS 接口要求 POST {}
        res = requests.post(CHECKIN_URL, headers=headers, json={}, timeout=15)
        data = res.json()
        
        code = data.get("code")
        message = data.get("message", "")
        list_data = data.get("list", [])
        
        # 提取签到积分
        points = 0
        if list_data and isinstance(list_data, list) and len(list_data) > 0:
            try:
                points = int(float(list_data[0].get("balance", 0)))
            except (ValueError, TypeError):
                points = 0

        # 判断签到状态
        if code == -2:
            return False, "没有权限（Cookie 无效或已过期）"
        elif code == 4 or "device" in message.lower():
            return False, f"设备不匹配 ({message})"
        elif points > 0:
            return True, f"签到成功，获得 {points} 积分"
        elif "logged" in message.lower() or "repeat" in message.lower() or "tomorrow" in message.lower() or "已经" in message:
            return True, "今日已签到，明天再来吧"
        else:
            return False, f"签到失败: {message if message else '未知状态'}"
            
    except Exception as e:
        return False, f"请求异常: {str(e)}"

def get_status_info(cookie: str):
    """获取用户账号状态及剩余天数"""
    headers = HEADERS.copy()
    headers["Cookie"] = cookie.strip()
    
    try:
        res = requests.post(STATUS_URL, headers=headers, json={}, timeout=15)
        data = res.json()
        
        if data.get("code") == 0 and "data" in data:
            user_data = data["data"]
            email = user_data.get("email", "未知邮箱")
            left_days = int(float(user_data.get("leftDays", 0)))
            return True, email, left_days
        else:
            return False, "未知邮箱", 0
    except Exception as e:
        return False, "未知邮箱", 0

def send_wechat_notice(content: str):
    """发送企业微信 Bot 通知"""
    if not WECHAT_WEBHOOK_URL:
        print("[微信通知] 未配置 WECHAT_WEBHOOK_URL，跳过发送通知")
        return
        
    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    
    try:
        res = requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=10)
        res_json = res.json()
        print(f"[微信通知] {res_json}")
        print(f"[微信通知] {res_json.get('errcode') == 0}")
    except Exception as e:
        print(f"[微信通知失败] {str(e)}")

def main():
    print("=" * 50)
    print("GLaDOS 自动签到")
    print("=" * 50)
    print(f"Checkin URL : {CHECKIN_URL}")
    print(f"Status URL  : {STATUS_URL}")
    print(f"User-Agent  : {HEADERS['User-Agent']}")
    print("=" * 50)

    # 拆分多账号 Cookie
    cookies = [c.strip() for c in RAW_COOKIES.split("&&") if c.strip()]
    if not cookies:
        print("未检测到有效 Cookie，请在环境变量 GLADOS_COOKIES 中配置")
        return

    print(f"共发现 {len(cookies)} 个账号\n")
    
    summary_logs = []

    for idx, cookie in enumerate(cookies, start=1):
        print(f"开始处理第 {idx} 个账号")
        print("-" * 50)
        
        fingerprint = get_cookie_fingerprint(cookie)
        print(f"[Cookie 指纹] {fingerprint}")

        # 校验 Cookie 格式完整性
        if not validate_cookie_format(cookie):
            msg = "[状态] Cookie 格式错误 (缺少 gld:sess 或 gld:sess.sig)"
            print(msg)
            result_str = f"[glados] 指纹:{fingerprint} 签到结果： Cookie 格式不完整 剩余(0)天"
            print(result_str)
            summary_logs.append(result_str)
            print()
            continue

        # 先执行签到操作
        success, checkin_msg = do_checkin(cookie)

        # 获取账号 status 信息
        status_ok, email, left_days = get_status_info(cookie)

        # 格式化邮箱掩码显示 (例如 abc***@qq.com)
        if "@" in email:
            name, domain = email.split("@", 1)
            masked_email = f"{name[:3]}***@{domain}" if len(name) > 3 else f"{name}***@{domain}"
        else:
            masked_email = email

        if not status_ok:
            print("[账号] 未知邮箱")
            print(f"[状态] {checkin_msg}")
        else:
            print(f"[账号] {masked_email}")
            print(f"[状态] Cookie 有效")
            print(f"[状态] 剩余 {left_days} 天")

        log_item = f"[glados] {masked_email} 签到结果： {checkin_msg} 剩余({left_days})天"
        print(log_item)
        summary_logs.append(log_item)
        print()

    print("=" * 50)
    print("准备发送企业微信通知")
    print("=" * 50)
    
    notice_text = "GLaDOS 自动签到结果：\n" + "\n".join(summary_logs)
    send_wechat_notice(notice_text)

if __name__ == "__main__":
    main()
