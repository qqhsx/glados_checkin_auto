import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from wxmsg import send_wx


DEFAULT_CHECKIN_TOKEN = "glados.cloud"

DEFAULT_BASE_URL = "https://glados.cloud"
FALLBACK_BASE_URLS = (
    "https://www.glados.vip",
    "https://glados.one",
    "https://glados.network",
    "https://glados.rocks",
)

TIMEOUT = (10, 30)
MAX_ATTEMPTS = 3

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_RETRYABLE = 2

SUCCESS_MARKERS = (
    "checkin!",
    "checkin repeats",
    "observation logged",
)
TOKEN_ERROR_MARKERS = (
    "please checkin via",
    "checkin via http",
)
AUTH_ERROR_MARKERS = (
    "not login",
    "not logged",
    "please login",
    "unauthorized",
    "invalid cookie",
    "cookie expired",
    "session expired",
    "没有权限",
    "未登录",
    "请先登录",
    "登录已过期",
)

SENSITIVE_KEYS = frozenset(
    {
        "email",
        "password",
        "hashed",
        "code",
        "domain",
        "port",
        "phone",
        "usdt_address",
        "telegram_id",
        "configureid",
        "configure_id",
        "user_id",
        "userid",
    }
)


class FatalError(RuntimeError):
    """重试也不会成功的错误。"""


class RetryableError(RuntimeError):
    """网络或服务端临时故障。"""


def now_text():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S UTC+08:00")


def log(message):
    print(f"[{now_text()}] {message}", flush=True)


def get_env(name, default=None):
    """读取环境变量。空字符串按未设置处理。"""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def require_cookies():
    """解析多个 Cookie，支持换行符、'#'、'&' 或 '---' 分隔。"""
    raw_cookies = get_env("GLADOS_COOKIE")
    if not raw_cookies:
        raise FatalError(
            "GLADOS_COOKIE is empty. Update the GitHub Actions repository secret."
        )

    raw_cookies = (
        raw_cookies.replace("---", "\n")
        .replace("#", "\n")
        .replace("&", "\n")
    )

    cookies = [c.strip() for c in raw_cookies.splitlines() if c.strip()]

    final_cookies = []
    for c in cookies:
        if c.count("koa:sess=") > 1:
            parts = ["koa:sess=" + p for p in c.split("koa:sess=") if p.strip()]
            final_cookies.extend([p.strip(" #&;") for p in parts])
        elif c.count("gld:sess=") > 1 and "koa:sess=" not in c:
            parts = ["gld:sess=" + p for p in c.split("gld:sess=") if p.strip()]
            final_cookies.extend([p.strip(" #&;") for p in parts])
        else:
            final_cookies.append(c)

    if not final_cookies:
        raise FatalError("解析出的 Cookie 列表为空，请检查环境变量设置。")

    return final_cookies


def resolve_token():
    token = get_env("GLADOS_CHECKIN_TOKEN", DEFAULT_CHECKIN_TOKEN)
    if token == "glados.one":
        log(
            "WARNING: GLADOS_CHECKIN_TOKEN 仍是已失效的旧值 'glados.one'，"
            f"已自动改用 '{DEFAULT_CHECKIN_TOKEN}'。"
        )
        return DEFAULT_CHECKIN_TOKEN
    return token


def candidate_base_urls():
    primary = get_env("GLADOS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    urls = [primary]
    if get_env("GLADOS_DOMAIN_FALLBACK", "1") != "0":
        for url in FALLBACK_BASE_URLS:
            url = url.rstrip("/")
            if url not in urls:
                urls.append(url)
    return urls


def build_session(cookie):
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Sec-Ch-Ua": '"Not;A=Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Cookie": cookie,
        }
    )
    return session


def parse_json_response(response):
    try:
        return response.json()
    except ValueError:
        return {
            "code": None,
            "message": "Non-JSON response",
            "text": response.text[:500],
        }


def redact(payload):
    if isinstance(payload, dict):
        return {
            key: ("<redacted>" if key.lower() in SENSITIVE_KEYS else redact(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def request_json(session, method, url, origin, payload=None):
    headers = {
        "Origin": origin,
        "Referer": f"{origin}/console/checkin",
    }
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            log(f"{method.upper()} {url} (attempt {attempt}/{MAX_ATTEMPTS})")
            if payload is None:
                response = session.request(
                    method, url, timeout=TIMEOUT, headers=headers
                )
            else:
                response = session.request(
                    method,
                    url,
                    timeout=TIMEOUT,
                    headers=headers,
                    data=json.dumps(payload),
                )

            body = parse_json_response(response)

            redacted_body = redact(body)
            msg = redacted_body.get("message") if isinstance(redacted_body, dict) else None
            if not msg:
                dump_str = json.dumps(redacted_body, ensure_ascii=False)
                msg = dump_str if len(dump_str) <= 120 else dump_str[:120] + "..."

            log(f"HTTP {response.status_code}: {msg}")

            if response.status_code in (401, 403):
                raise FatalError(
                    f"认证失败 (HTTP {response.status_code})，"
                    "请更新 GLADOS_COOKIE。"
                )

            if response.status_code == 429 or response.status_code >= 500:
                raise RetryableError(f"可重试的 HTTP 状态: {response.status_code}")

            response.raise_for_status()
            return body

        except FatalError:
            raise
        except RetryableError as exc:
            last_error = exc
            log(str(exc))
        except requests.RequestException as exc:
            last_error = exc
            log(f"请求失败: {exc}")

        if attempt < MAX_ATTEMPTS:
            sleep_seconds = min(60, 2 ** attempt * 5)
            log(f"{sleep_seconds}s 后重试。")
            time.sleep(sleep_seconds)

    raise RetryableError(f"{MAX_ATTEMPTS} 次尝试后仍失败: {last_error}")


def response_text(payload):
    if isinstance(payload, dict):
        parts = [str(payload.get(key, "")) for key in ("message", "msg", "error")]
        parts.append(json.dumps(payload, ensure_ascii=False))
        return " ".join(parts).lower()
    return str(payload).lower()


def response_message(payload):
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("msg") or "")
    return str(payload)


def classify_checkin(payload):
    text = response_text(payload)
    code = payload.get("code") if isinstance(payload, dict) else None

    if any(marker in text for marker in TOKEN_ERROR_MARKERS):
        return "token_error"
    if any(marker in text for marker in AUTH_ERROR_MARKERS):
        return "auth_error"
    if any(marker in text for marker in SUCCESS_MARKERS):
        return "success"
    if code == 0:
        return "success"
    return "unknown"


def explain_failure(status, payload, token, base_url):
    message = response_message(payload)

    if status == "token_error":
        return (
            "签到 token 已失效，本次签到未生效。\n"
            f"  当前 GLADOS_CHECKIN_TOKEN = {token!r}\n"
            f"  {base_url}/api/user/checkin 返回: {message!r}"
        )
    if status == "auth_error":
        return (
            "Cookie 已失效。请重新登录，更新 GLADOS_COOKIE。\n"
            f"  接口返回: {message!r}"
        )
    return (
        "签到响应无法识别，不能确认签到是否生效。\n"
        f"  {base_url}/api/user/checkin 返回: {message!r}"
    )


def format_number(value):
    """去掉数字字符串末尾无意义的 0 和小数点。"""
    if value is None:
        return None
    text = str(value).strip()
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def mask_email(email):
    """脱敏邮箱显示，如 abc***@gmail.com。"""
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name + "***"
    else:
        masked_name = name[:2] + "***"
    return f"{masked_name}@{domain}"


def do_checkin(session, base_urls, token):
    last_error = None

    for base_url in base_urls:
        try:
            payload = request_json(
                session,
                "post",
                f"{base_url}/api/user/checkin",
                base_url,
                payload={"token": token},
            )
        except RetryableError as exc:
            last_error = exc
            log(f"{base_url} 不可用: {exc}")
            continue

        status = classify_checkin(payload)
        if status in ("token_error", "auth_error"):
            raise FatalError(explain_failure(status, payload, token, base_url))
        return base_url, payload

    raise RetryableError(f"所有候选域名均失败: {last_error}")


def report_account(session, base_url):
    """读取账号状态，并返回通知需要的数据。"""
    result = {
        "email": None,
        "left_days": None,
        "points": None,
        "points_change": None,
    }

    try:
        status_payload = request_json(
            session, "get", f"{base_url}/api/user/status", base_url
        )
    except (FatalError, RetryableError) as exc:
        log(f"WARNING: 读取 status 失败: {exc}")
    else:
        if isinstance(status_payload, dict) and isinstance(status_payload.get("data"), dict):
            data = status_payload["data"]
            email = data.get("email")
            if email:
                result["email"] = mask_email(email)
                log(f"Account Email: {result['email']}")

            left_days = data.get("leftDays")
            if left_days is not None:
                result["left_days"] = format_number(left_days)
                log(f"Current leftDays: {result['left_days']}")

    try:
        points_payload = request_json(
            session, "get", f"{base_url}/api/user/points", base_url
        )
    except (FatalError, RetryableError) as exc:
        log(f"WARNING: 读取 points 失败: {exc}")
        return result

    if not isinstance(points_payload, dict) or points_payload.get("points") is None:
        log("WARNING: 无法从 points 响应读取 points 字段。")
        return result

    result["points"] = format_number(points_payload.get("points"))

    history = points_payload.get("history")
    if isinstance(history, list) and history and isinstance(history[0], dict):
        delta = history[0].get("change")
        if delta is not None:
            result["points_change"] = format_number(delta)
            log(f"Current points: {result['points']}（最近一次变化 {result['points_change']}）")
            return result

    log(f"Current points: {result['points']}")
    return result


def process_single_account(index, total, cookie, token, base_urls):
    """处理单个账号签到，返回通知所需结果。"""
    hash_tag = hashlib.sha256(cookie.encode()).hexdigest()[:12]
    log(f"=================== 正在处理账号 [{index}/{total}] ===================")
    log(f"Cookie 长度 {len(cookie)}，sha256 指纹 {hash_tag}")

    session = build_session(cookie)
    base_url, checkin_payload = do_checkin(session, base_urls, token)
    status = classify_checkin(checkin_payload)
    message = response_message(checkin_payload)

    log(f"签到结果: {message or status}")

    account_info = report_account(session, base_url)

    if status != "success":
        error_text = explain_failure(status, checkin_payload, token, base_url)
        log(f"ERROR: {error_text}")
        return {
            "success": False,
            "status": status,
            "message": message or error_text,
            **account_info,
        }

    return {
        "success": True,
        "status": status,
        "message": message or "签到成功",
        **account_info,
    }


def build_wechat_message(results, start_time):
    """生成企业微信汇总消息。"""
    total = len(results)
    success_count = sum(1 for item in results if item.get("success"))
    failed_count = total - success_count

    lines = [
        "🤖 GLADOS 自动签到",
        "",
        f"时间：{start_time}",
        f"总账号：{total}",
        f"签到成功：{success_count}",
        f"签到失败：{failed_count}",
        "",
    ]

    for index, item in enumerate(results, 1):
        email = item.get("email") or f"账号 {index}"
        if item.get("success"):
            lines.append(f"{index}. {email}")
            lines.append("   ✅ 签到成功")

            points = item.get("points")
            if points is not None:
                point_text = f"   积分：{points}"
                delta = item.get("points_change")
                if delta is not None:
                    point_text += f"（变化 {delta}）"
                lines.append(point_text)

            left_days = item.get("left_days")
            if left_days is not None:
                lines.append(f"   剩余：{left_days} 天")
        else:
            lines.append(f"{index}. {email}")
            lines.append("   ❌ 签到失败")
            message = item.get("message") or item.get("status") or "未知错误"
            lines.append(f"   原因：{message}")

        if index < total:
            lines.append("")

    lines.extend(
        [
            "",
            f"结果：{success_count}/{total} 成功",
        ]
    )

    return "\n".join(lines)


def send_wechat_notification(results, start_time):
    """发送企业微信通知。未配置企业微信时不影响签到结果。"""
    corpid = get_env("WX_CORPID")
    corpsecret = get_env("WX_CORPSECRET")
    agentid = get_env("WX_AGENTID")

    if not corpid or not corpsecret or not agentid:
        log("WARNING: WX_CORPID / WX_CORPSECRET / WX_AGENTID 未完整设置，跳过微信通知。")
        return False

    message = build_wechat_message(results, start_time)

    try:
        ok = send_wx(
            message,
            corpid,
            corpsecret,
            agentid,
        )
    except Exception as exc:
        log(f"[微信通知失败] {exc}")
        return False

    if ok:
        log("[微信通知] 发送成功")
    else:
        log("[微信通知] 发送失败")

    return ok


def main():
    start_time = now_text()

    cookies = require_cookies()
    token = resolve_token()
    base_urls = candidate_base_urls()

    total = len(cookies)
    log(f"共检测到 {total} 个账号，候选域名: {', '.join(base_urls)}")

    success_count = 0
    has_fatal_error = False
    results = []

    for idx, cookie in enumerate(cookies, 1):
        try:
            result = process_single_account(
                idx, total, cookie, token, base_urls
            )
            results.append(result)

            if result.get("success"):
                success_count += 1
            else:
                has_fatal_error = True

        except FatalError as exc:
            log(f"ERROR 账号 [{idx}/{total}] 发生致命错误: {exc}")
            has_fatal_error = True
            results.append(
                {
                    "success": False,
                    "status": "fatal_error",
                    "message": str(exc),
                    "email": None,
                    "left_days": None,
                    "points": None,
                    "points_change": None,
                }
            )

        except Exception as exc:
            log(f"ERROR 账号 [{idx}/{total}] 执行异常: {exc}")
            has_fatal_error = True
            results.append(
                {
                    "success": False,
                    "status": "exception",
                    "message": str(exc),
                    "email": None,
                    "left_days": None,
                    "points": None,
                    "points_change": None,
                }
            )

        if idx < total:
            time.sleep(3)

    log(
        f"=================== 所有任务完成 "
        f"[{success_count}/{total} 成功] ==================="
    )

    # 所有账号处理完后，只发送一条企业微信汇总消息。
    send_wechat_notification(results, start_time)

    if has_fatal_error or success_count < total:
        return EXIT_FATAL

    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FatalError as exc:
        log(f"ERROR: {exc}")
        sys.exit(EXIT_FATAL)
    except RetryableError as exc:
        log(f"ERROR: {exc}")
        sys.exit(EXIT_RETRYABLE)
    except Exception as exc:
        log(f"ERROR: {exc}")
        sys.exit(EXIT_FATAL)
