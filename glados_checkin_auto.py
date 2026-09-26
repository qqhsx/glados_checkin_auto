import os
import requests
import json
import time
from wxmsg import send_wx

# 微信企业号配置（支持环境变量）
corpid = os.environ.get("WX_CORPID", "")
corpsecret = os.environ.get("WX_CORPSECRET", "")
agentid = os.environ.get("WX_AGENTID", "1000003")
touser = os.environ.get("WX_TOUSER", "@all")

sendContent = ""


def mask_email(email):
    """对邮箱进行隐私打码"""
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 3:
        masked = name[0] + "***@" + domain
    else:
        masked = name[:3] + "***@" + domain
    return masked


def safe_request(method, url, max_retries=3, delay=1, **kwargs):
    """
    安全请求方法：支持自动重试机制
    method: "GET" 或 "POST"
    """
    for attempt in range(1, max_retries + 1):
        try:
            if method.upper() == "GET":
                return requests.get(url, **kwargs)
            elif method.upper() == "POST":
                return requests.post(url, **kwargs)
        except requests.RequestException as e:
            print(f"[警告] 第 {attempt} 次请求失败: {e}")
            if attempt < max_retries:
                print(f"→ {delay} 秒后重试...")
                time.sleep(delay)
    print("[错误] 网络请求多次失败，跳过此账号。")
    return None


def checkin(cookie):
    """执行单账号签到"""
    # 使用你最新确认可用的 glados.rocks 节点及请求参数
    url = "https://glados.rocks/api/user/checkin"
    url2 = "https://glados.rocks/api/user/status"
    headers = {
        "cookie": cookie,
        "referer": "https://glados.rocks/console/checkin",
        "origin": "https://glados.rocks",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0",
        "content-type": "application/json;charset=UTF-8"
    }
    payload = {"token": "glados.rocks"}

    # 使用 safe_request 请求 API
    checkin_res = safe_request("POST", url, headers=headers, data=json.dumps(payload), timeout=20)
    state_res = safe_request("GET", url2, headers=headers, timeout=20)

    global sendContent

    if not checkin_res or not state_res:
        print("[错误] 请求失败，跳过该账号。\n")
        return

    # 校验并提取状态信息
    if state_res.status_code == 200:
        try:
            data = state_res.json().get('data', {})
            email = data.get('email', '未知邮箱')
            masked_email = mask_email(email)
            left_days = data.get('leftDays', 0)

            # 兼容 leftDays 类型（int / float / str）
            if isinstance(left_days, (int, float)):
                time_str = str(int(left_days))
            elif isinstance(left_days, str):
                time_str = left_days.split('.')[0]
            else:
                time_str = "未知"

            # 获取签到返回消息
            checkin_json = checkin_res.json()
            mess = checkin_json.get('message', '未知')

            log = f"[glados] {masked_email}----结果--{mess}----剩余({time_str})天"
            print(log)
            sendContent += log + "\n"

        except Exception as e:
            err_log = f"[错误] 解析响应数据失败: {e}"
            print(err_log)
            sendContent += err_log + "\n"
    else:
        err_log = f"[错误] Cookie已失效或查询失败，状态码：{state_res.status_code}"
        print(err_log)
        sendContent += err_log + "\n"


def start():
    """启动签到流程"""
    global sendContent
    # 支持 GLADOS_COOKIE 和 GLADOS_COOKIES 两种环境变量命名
    raw_cookies = os.environ.get("GLADOS_COOKIE") or os.environ.get("GLADOS_COOKIES") or ""
    
    # 拆分 & 连接的多账号 Cookie
    cookies = [c.strip() for c in raw_cookies.split("&") if c.strip()] if raw_cookies else [
        # 本地测试 Cookie 示例
        # "koa:sess=xxxx; koa:sess.sig=xxxx"
    ]

    if not cookies:
        print("未获取到 COOKIE 变量，请先配置环境变量。")
        return

    for ck in cookies:
        checkin(ck)

    # 签到完成后，推送到企业微信
    if sendContent:
        send_wx(sendContent, corpid, corpsecret, agentid, touser)
    else:
        print("无签到结果可推送")


if __name__ == "__main__":
    start()
