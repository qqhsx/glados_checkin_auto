# -*- coding: utf-8 -*-
"""
GLaDOS 自动签到（适配新版 gld:sess + 登录设备 UA 校验）

用途：
1. 支持 GitHub Actions / 本地运行
2. 支持一个或多个 Cookie
3. 使用新版 gld:sess / gld:sess.sig
4. 按新版 GLaDOS 的方式使用浏览器 User-Agent
5. 签到后查询账号状态
6. 使用企业微信机器人/应用 wxmsg 发送结果

环境变量：
    GLADOS_COOKIES
        多账号用 && 分隔，例如：
        gld:sess=xxx; gld:sess.sig=xxx&&gld:sess=yyy; gld:sess.sig=yyy

    GLADOS_USER_AGENT
        可选。建议填写“登录 GLaDOS 时使用的浏览器”的完整 UA。
        不填写时使用默认 Windows + Edge UA。

    WX_CORPID
    WX_CORPSECRET
    WX_AGENTID
    WX_TOUSER
"""

import json
import os
import time

import requests

try:
    from wxmsg import send_wx
except ImportError:
    send_wx = None


# ============================================================
# GLaDOS API
# ============================================================

# 新版有效脚本使用 glados.one
CHECKIN_URL = "https://glados.one/api/user/checkin"
STATUS_URL = "https://glados.one/api/user/status"


# ============================================================
# User-Agent
# ============================================================
#
# 新版 GLaDOS 会把“登录设备”和当前请求设备进行比对。
# 如果 Cookie 是在 Windows + Edge 登录取得的，签到请求也应尽量使用
# 同类浏览器 UA。
#
# 可以通过 GitHub Secret：
# GLADOS_USER_AGENT
# 覆盖这个默认值。
#
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
)

USER_AGENT = os.environ.get("GLADOS_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


# ============================================================
# 企业微信
# ============================================================

corpid = os.environ.get("WX_CORPID", "")
corpsecret = os.environ.get("WX_CORPSECRET", "")
agentid = os.environ.get("WX_AGENTID", "1000003")
touser = os.environ.get("WX_TOUSER", "@all")

sendContent = ""


# ============================================================
# 基础工具
# ============================================================

def mask_email(email):
    """邮箱打码，只用于日志和企业微信消息。"""
    if not email or "@" not in email:
        return email or "未知邮箱"

    name, domain = email.split("@", 1)

    if len(name) <= 3:
        masked = name[0] + "***@" + domain
    else:
        masked = name[:3] + "***@" + domain

    return masked


def safe_request(method, url, max_retries=3, delay=1, **kwargs):
    """
    requests 请求 + 自动重试。

    注意：
    这里不修改 Cookie，也不自动重新登录。
    """
    for attempt in range(1, max_retries + 1):
        try:
            method = method.upper()

            if method == "GET":
                return requests.get(url, **kwargs)

            if method == "POST":
                return requests.post(url, **kwargs)

            raise ValueError(f"不支持的 HTTP 方法：{method}")

        except requests.RequestException as e:
            print(f"[警告] 第 {attempt} 次请求失败：{e}")

            if attempt < max_retries:
                print(f"→ {delay} 秒后重试...")
                time.sleep(delay)

    print("[错误] 网络请求多次失败。")
    return None


def build_headers(cookie, with_json=False):
    """
    按新版有效脚本的方法构造请求头。

    与旧脚本相比，关键变化：
    1. User-Agent 不再使用简单的 Mozilla/5.0
    2. 默认使用 Windows + Edge UA
    3. 使用新版 glados.one 地址
    4. JSON POST 时增加 Origin
    5. Cookie 使用当前 gld:sess
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": cookie,
        "Referer": "https://glados.one/console/checkin",
    }

    if with_json:
        headers["Content-Type"] = "application/json;charset=UTF-8"
        headers["Origin"] = "https://glados.one"

    return headers


def check_cookie_shape(cookie):
    """检查新版 Cookie 是否包含 gld:sess 和 gld:sess.sig。"""
    warnings = []

    if "gld:sess=" not in cookie:
        warnings.append(
            "Cookie 中没有 gld:sess。新版 GLaDOS 使用 gld:sess 判断登录状态。"
        )

    if "gld:sess.sig=" not in cookie:
        warnings.append(
            "Cookie 中没有 gld:sess.sig。新版签名 Cookie 应与 gld:sess 成对出现。"
        )

    return warnings


# ============================================================
# GLaDOS 状态
# ============================================================

def get_status(cookie):
    """
    查询账号状态。

    返回：
        {
            "ok": True/False,
            "email": "...",
            "left_days": ...,
            "message": "..."
        }
    """
    headers = build_headers(cookie)

    response = safe_request(
        "GET",
        STATUS_URL,
        headers=headers,
        timeout=20,
    )

    if not response:
        return {
            "ok": False,
            "email": "未知邮箱",
            "left_days": 0,
            "message": "查询状态网络请求失败",
        }

    if response.status_code != 200:
        return {
            "ok": False,
            "email": "未知邮箱",
            "left_days": 0,
            "message": f"查询状态 HTTP {response.status_code}",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "email": "未知邮箱",
            "left_days": 0,
            "message": "查询状态返回内容不是 JSON",
        }

    code = payload.get("code")

    # 新版 Cookie 无效时通常返回 code=-2 / 没有权限
    if code == -2 or "没有权限" in str(payload.get("message", "")):
        return {
            "ok": False,
            "email": "未知邮箱",
            "left_days": 0,
            "message": "没有权限（Cookie 无效或已过期）",
        }

    data = payload.get("data", {}) or {}

    email = data.get("email", "未知邮箱")
    left_days = data.get("leftDays", 0)

    try:
        left_days = int(float(left_days))
    except (ValueError, TypeError):
        left_days = 0

    return {
        "ok": True,
        "email": email,
        "left_days": left_days,
        "message": "",
    }


# ============================================================
# GLaDOS 签到
# ============================================================

def do_checkin(cookie):
    """
    按新版有效脚本的方法执行签到。

    关键点：
        payload = {}

    不再使用旧脚本中的：
        {"token": "glados.cloud"}

    返回：
        (success, message)
    """
    headers = build_headers(cookie, with_json=True)

    # 新版有效脚本使用空 JSON 对象
    payload = {}

    response = safe_request(
        "POST",
        CHECKIN_URL,
        headers=headers,
        json=payload,
        timeout=20,
    )

    if not response:
        return False, "签到请求失败：网络错误"

    if response.status_code != 200:
        return False, f"签到请求失败：HTTP {response.status_code}"

    try:
        data = response.json()
    except ValueError:
        return False, "签到请求失败：服务器返回的不是 JSON"

    code = data.get("code")
    message = str(data.get("message", "") or "")

    # --------------------------------------------------------
    # Cookie 无效
    # --------------------------------------------------------
    if code == -2 or "没有权限" in message:
        return False, "签到失败：没有权限（Cookie 无效或已过期）"

    # --------------------------------------------------------
    # 新版设备校验
    # --------------------------------------------------------
    if (
        code == 4
        or "automated check-in detected" in message.lower()
        or "device-mismatch" in str(data.get("reason", "")).lower()
    ):
        return False, (
            "签到失败：Automated check-in detected。"
            "当前请求 User-Agent 与登录设备不一致，"
            "请将 GLADOS_USER_AGENT 设置为登录 GLaDOS 时使用的浏览器 UA。"
        )

    # --------------------------------------------------------
    # 根据新版接口返回判断签到结果
    # --------------------------------------------------------
    points = data.get("points", 0)

    try:
        points_value = float(points)
    except (ValueError, TypeError):
        points_value = 0

    if points_value > 0:
        return True, f"签到成功，获得 {int(points_value)} 积分"

    # 常见重复签到提示
    lower_message = message.lower()

    if (
        "logged" in lower_message
        or "repeat" in lower_message
        or "tomorrow" in lower_message
    ):
        return True, "今日已签到，明天再来吧"

    # 某些版本可能 code=0 但 points=0
    if code == 0:
        return True, message or "签到成功"

    return False, f"签到失败：{message or '未知错误'}"


# ============================================================
# 单账号
# ============================================================

def checkin(cookie):
    """执行单账号签到。"""
    global sendContent

    cookie = (cookie or "").strip()

    if not cookie:
        print("[错误] Cookie 为空")
        return

    print("--------------------------------------------------")

    # 先检查 Cookie 结构
    warnings = check_cookie_shape(cookie)

    for warning in warnings:
        print(f"[警告] {warning}")

    if warnings:
        print("[提示] 当前 Cookie 看起来不是新版 gld:sess 格式。")

    # --------------------------------------------------------
    # 先查询 status
    # --------------------------------------------------------
    status = get_status(cookie)

    if status["ok"]:
        email = status["email"]
        masked_email = mask_email(email)
        left_days = status["left_days"]

        print(f"[账号] {masked_email}")
        print(f"[状态] Cookie 有效")
        print(f"[状态] 剩余 {left_days} 天")
    else:
        masked_email = "未知邮箱"
        left_days = 0

        print(f"[账号] {masked_email}")
        print(f"[状态] {status['message']}")

        log = (
            f"[glados] {masked_email} "
            f"签到结果： {status['message']} "
            f"剩余({left_days})天"
        )

        print(log)
        sendContent += log + "\n"
        return

    # --------------------------------------------------------
    # 执行签到
    # --------------------------------------------------------
    success, checkin_message = do_checkin(cookie)

    log = (
        f"[glados] {masked_email} "
        f"签到结果： {checkin_message} "
        f"剩余({left_days})天"
    )

    print(log)

    sendContent += log + "\n"


# ============================================================
# 主流程
# ============================================================

def start():
    """启动多账号签到。"""
    global sendContent

    print("==================================================")
    print("GLaDOS 自动签到")
    print("==================================================")
    print(f"Checkin URL : {CHECKIN_URL}")
    print(f"Status URL  : {STATUS_URL}")
    print(f"User-Agent  : {USER_AGENT}")
    print("==================================================")

    # --------------------------------------------------------
    # Cookie
    #
    # 多账号使用 && 分隔：
    #
    # gld:sess=aaa; gld:sess.sig=bbb&&gld:sess=ccc;gld:sess.sig=ddd
    # --------------------------------------------------------
    cookie_text = os.environ.get("GLADOS_COOKIES", "").strip()

    if cookie_text:
        cookies = [
            ck.strip()
            for ck in cookie_text.split("&&")
            if ck.strip()
        ]
    else:
        # 本地测试时可以直接在这里放 Cookie。
        # 不要把真实 Cookie 提交到 GitHub。
        cookies = [
            "gld:sess=xxxx; gld:sess.sig=xxxx"
        ]

    print(f"共发现 {len(cookies)} 个账号")
    print()

    for index, cookie in enumerate(cookies, 1):
        print(f"开始处理第 {index} 个账号")
        checkin(cookie)

    # --------------------------------------------------------
    # 企业微信
    # --------------------------------------------------------
    if sendContent:
        print("==================================================")
        print("准备发送企业微信通知")
        print("==================================================")

        if send_wx is None:
            print("[微信通知] wxmsg 未安装，跳过通知。")
            return

        try:
            result = send_wx(
                sendContent,
                corpid,
                corpsecret,
                agentid,
                touser,
            )

            print(f"[微信通知] {result}")

        except Exception as e:
            print(f"[微信通知] 发送失败：{e}")
    else:
        print("无签到结果可推送")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    start()
