# QQ 外部 OneBot 接入

QQ 是消息渠道，不是 MediX 网站的登录方式。账号、会话和记忆仍按 MediX `user.id` 隔离。

## 推荐：自动准备并启动 NapCat（Windows x64）

在已安装项目依赖的 Python 环境下，运行：

```powershell
.\start_qq.ps1
```

首次自动从 NapCat 官方 Releases 下载固定版本 4.18.41 的 Windows.Node 包（约118 MB），校验官方 SHA256，解压内置 Node 与 QQ 核心，创建独立 QQ 数据目录和随机令牌。浏览器会打开本机扫码页面；用机器人 QQ 扫码并在手机确认。无需另装 Node 或手填 SnowLuma 路径、HTTP/WS 令牌。

随后按团队原来的方式启动 MediX，网页登录后选择「聊天渠道与提醒 → QQ → 连接本机QQ」，填写接收消息的好友 QQ 号，并由好友回复绑定码。**同一个机器人 QQ 的电脑版客户端先退出**，否则独立核心可能提示重复登录。

运行 `start_qq.ps1` 后就可以启动 MediX，扫码完成后再点击连接。`run_web.py` / `run_kb_demo.py` 自动读取 `data/napcat/medix.env`，配置优先级为：进程环境变量 → 自动生成的 QQ 配置 → `.env.local` → `.env.sms`；自动文件只含 QQ 连接项，不改变模型或短信密钥。

首次需要联网。下载慢可指定自己的代理端口，或使用已下载的官方包，仍会校验哈希：

```powershell
.\start_qq.ps1 -Proxy http://127.0.0.1:7890
.\start_qq.ps1 -Archive 'D:\Downloads\NapCat.Shell.Windows.Node.zip'
```

安装位置是 `data/tools/NapCat-4.18.41-win-node/`，本机配置、QQ会话和扫码页在 `data/napcat/`。安装器只对下载副本的数据目录选择加一处环境变量覆盖，避免读取或写入电脑版QQ的 `Documents/Tencent Files`；原始脚本保留为 `napcat.mjs.official`。不修改电脑上已安装的QQ。程序、令牌、账号和聊天数据全部排除提交；仓库交付自动获取代码，不分发QQ或NapCat二进制及账号登录状态。

本机日志为 `data/napcat/runtime.log`、`bootstrap.log`。端口占用或校验失败会停止，不会关闭其他服务。换电脑必须重新扫码，不能共享别人的QQ登录状态。重启电脑后重新运行 `start_qq.ps1`，会尝试恢复本机已登录账号，必要时重新扫码。

## 已有 OneBot 服务：手工接入

也可使用本机已有的 NapCat 等 OneBot v11 服务。在被 Git 忽略的 `.env.local` 配置（未启用上述自动配置时使用）：

```dotenv
MEDIX_QQ_BACKEND=onebot
MEDIX_QQ_HTTP=http://127.0.0.1:3000
MEDIX_QQ_WS=ws://127.0.0.1:3001
MEDIX_QQ_TOKEN=填写本机HTTP令牌
MEDIX_QQ_WS_TOKEN=填写本机WebSocket令牌
```

先在所选 OneBot 程序完成机器人 QQ 登录，再启动 MediX。未验证的好友不能使用该账号的数据。

HTTP 和 WebSocket 必须指向同一个机器人账号；令牌分别配置。`onebot` 模式连接或重连失败时不会启动 SnowLuma。服务只允许本机回环地址，令牌和账号数据不要提交。

NapCat 官方安装说明：https://napneko.github.io/guide/boot/Shell 。程序下载后存放在仓库外或被忽略的本机目录。独立 Node 运行方式需要登录机器人 QQ，不能直接复用 SnowLuma 的登录状态；本机测试时同账号在电脑版 QQ 在线会返回「当前账号已登录，无法重复登录」，退出电脑版 QQ 后扫码成功。

验证顺序：`get_login_info` 成功 → `get_status` 返回在线 → WebSocket 收到心跳 → 网页连接 → 好友绑定 → 实际私聊及提醒。仅前三项成功不能宣称消息或提醒已验收。

本次本机验证：NapCat 4.18.41 的 QQ 核心初始化、扫码登录、HTTP 在线查询、MediX WebSocket 心跳、网页登录连接、好友绑定码验证及真实私聊问答均已通过；实际回复由用户在接收端确认。定时提醒仅通过回归检查，未在本次执行真实定时投递。安装包及机器专属配置不包含在本文件中；不能只拉取仓库就自动具备 QQ 服务。
