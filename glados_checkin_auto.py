import os
import requests
import json
from wx_msg import send_wx  

# 微信企业号配置（可以写死，也可以用环境变量）
corpid = os.environ.get("WX_CORPID", "")
corpsecret = os.environ.get("WX_CORPSECRET", "")
agentid = os.environ.get("WX_AGENTID", "1000003")
touser = os.environ.get("WX_TOUSER", "@all")

sendContent = ""

def checkin(cookie):
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

    checkin = requests.post(url, headers=headers, data=json.dumps(payload))
    state = requests.get(url2, headers=headers)

    if state.status_code == 200:
        email = state.json()['data']['email']
        time = state.json()['data']['leftDays'].split('.')[0]
        mess = checkin.json().get('message', '未知')
        log = f"[glados] {email} 签到结果： {mess} 剩余({time})天"
        print(log)
        global sendContent
        sendContent += log + "\n"
    else:
        print("查询失败")


def start():
    global sendContent
    # 1. 如果设置了环境变量 GLADOS_COOKIES，就用环境变量（支持多账号，& 分隔）
    # 2. 如果没设置，就用下面本地写死的 cookies 列表
    cookies = os.environ.get("GLADOS_COOKIES", "").split("&") if os.environ.get("GLADOS_COOKIES") else [
        # 本地测试写这里，直接放浏览器复制的 cookie
        "koa:sess=yyyy; koa:sess.sig=yyyy",
        # "koa:sess=yyyy; koa:sess.sig=yyyy"  # 可以多个
    ]
    for ck in cookies:
        checkin(ck)

    # 签到完成后，推送到企业微信
    if sendContent:
        send_wx(sendContent, corpid, corpsecret, agentid, touser)

if __name__ == "__main__":
    start()
