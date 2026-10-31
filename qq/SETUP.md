# 在另一台电脑上复现 QQ 登录

仓库里的代码会启动本机的 SnowLuma，并连接已经登录的电脑版 QQ。SnowLuma 程序、QQ 号、登录口令和 OneBot 令牌都不在仓库里，换机器后需要在那台电脑上重新准备。

1. 安装 Node.js 24 或更新版本，并安装电脑版 QQ。
2. 从 [SnowLuma Releases](https://github.com/SnowLuma/SnowLuma/releases) 下载 Windows lite 包（例如 `SnowLuma-v2.2.1-win-x64-lite`），解压到任意目录。目录里要有 `index.mjs`。
3. 把 `config/local.env.example` 复制为 `config/local.env`，把 `MEDIX_SNOWLUMA_HOME` 写成解压后的目录。QQ 不在默认安装位置时，再填写 `MEDIX_QQ_EXE`。
4. 在项目根目录运行 `py -3.12 run_web.py` 或 `.\start_web.ps1`，打开 http://127.0.0.1:8765 。
5. 侧栏选择 QQ，在电脑 QQ 已登录的情况下添加好友。第一次连接会在 `data/snowluma/` 里生成本机口令和 OneBot 配置，这些文件不要提交。

`data/` 里的账号、好友和令牌只属于当前电脑。另一台电脑需要自己登录 QQ 并重新添加好友。
