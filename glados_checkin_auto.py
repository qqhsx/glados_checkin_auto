import os
import requests
import json
import time
from wxmsg import send_wx

# 微信企业号配置（可以写死，也可以用环境变量）
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
    max_retries: 最大重试次数
    delay: 每次重试间隔秒数
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
    url = "https://glados.rocks/api/user/checkin"
    url2 = "https://glados.rocks/api/user/status"
    headers = {
        "cookie": cookie,
        "referer": "https://glados.rocks/console/checkin",
        "origin": "https://glados.rocks",
        "user-agent": "Mozilla/5.0",
        "content-type": "application/json;charset=UTF-8"
    }
    payload = {"token": "glados.one"}

    # 使用自动重试版本的请求
    checkin = safe_request("POST", url, headers=headers, data=json.dumps(payload), timeout=20)
    state = safe_request("GET", url2, headers=headers, timeout=20)

    if not checkin or not state:
        print("[错误] 请求失败，跳过该账号。\n")
        return

    if state.status_code == 200:
        data = state.json().get('data', {})
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

        mess = checkin.json().get('message', '未知')
        log = f"[glados] {masked_email} 签到结果： {mess} 剩余({time_str})天"
        print(log)

        global sendContent
        sendContent += log + "\n"
    else:
        print(f"[错误] 查询失败，状态码：{state.status_code}")
        try:
            print("返回内容：", state.text)
        except Exception:
            pass


def start():
    """启动签到流程"""
    global sendContent
    # 1. 从环境变量读取多账号（&分隔）
    # 2. 若无环境变量，则使用本地默认 Cookie
    cookies = os.environ.get("GLADOS_COOKIES", "").split("&") if os.environ.get("GLADOS_COOKIES") else [
        # 本地测试 Cookie 示例
        "koa:sess=yyyy; koa:sess.sig=yyyy",
        # "koa:sess=xxxx; koa:sess.sig=xxxx"
    ]

    for ck in cookies:
        ck = ck.strip()
        if not ck:
            continue
        checkin(ck)

    # 签到完成后，推送到企业微信
    if sendContent:
        send_wx(sendContent, corpid, corpsecret, agentid, touser)
    else:
        print("无签到结果可推送")


if __name__ == "__main__":
    start()
