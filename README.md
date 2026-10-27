GLaDOS 自动签到

基于 Python 和 GitHub Actions 的 GLaDOS 自动签到脚本，支持多账号签到、账号状态查询及企业微信结果通知。

功能特点

多账号签到：支持配置多个账号的 Cookie。

自动重试：网络异常或服务器临时故障时自动重试。

域名备用：主站不可用时，可尝试备用域名。

状态查询：获取账号剩余天数、积分及最近一次积分变化。

企业微信通知：所有账号处理完成后，统一推送签到结果。

定时运行：通过 GitHub Actions 定时执行，无需本地电脑持续运行。

使用方法

1. Fork 仓库

Fork 本项目到自己的 GitHub 账号。

2. 配置 Secrets

进入仓库：

Settings → Secrets and variables → Actions → New repository secret

添加以下配置：

名称

说明

GLADOS_COOKIE

GLaDOS 账号 Cookie，支持多个账号

WX_CORPID

企业微信 CorpID

WX_CORPSECRET

企业微信应用 Secret

WX_AGENTID

企业微信应用 AgentId

多个账号的 Cookie 可使用换行符、#、& 或 --- 分隔。

企业微信配置为可选项。不配置时，脚本仍会执行签到，但不会发送通知。

3. 启用 GitHub Actions

进入仓库的 Actions 页面，启用工作流。

脚本支持：

定时自动签到。

手动触发签到。

默认定时任务为每天 UTC 23:20，即北京时间次日 07:20。

4. 查看运行结果

进入 Actions，选择对应的工作流并查看运行日志。

如果配置了企业微信，还可以接收包含以下信息的汇总通知：

总账号数及签到成功、失败数量。

各账号签到结果。

当前积分及最近一次积分变化。

账号剩余天数。
