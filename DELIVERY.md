# MediX 交付包说明

本包为可运行源码交付，不含依赖环境、模型权重或 API Key。解压后进入 medix-agent-swarm 目录。

## 新电脑启动（Windows / Python 3.12）

```powershell
py -3.12 -m venv ..\.medix-venv
..\.medix-venv\Scripts\python.exe -m pip install -r requirements.web.txt
.\start_web.ps1
```

按隐藏输入提示提供模型 Key，再打开 http://127.0.0.1:8765/ 。Mem0 可选，使用 `start_web.ps1 -EnableMem0` 并手动开启页面开关。

- [项目说明与后续功能优先级](README.md)
- [语音输入与播报调研及配置](docs/VOICE.md)
- [运行架构与排障](docs/RUNTIME.md)
- [测试方法与范围](docs/TESTING.md)
- [医疗助手代码解读 Word 文档](docs/医疗助手代码解读.docx)

README 中“当前 Windows 环境”的绝对路径是原开发机路径；在其他电脑应改为实际解压目录。默认外部配置文件不存在时，可以直接使用启动脚本隐藏输入；自定义配置路径用 MEDIX_CONFIG_PATH 指定。

保留 10 份项目原始医学 TXT 和仅含附带知识资料的旧向量源库，启动时迁移已有 180 条索引。文档来源和医学内容尚未审核。本包无模型训练/微调模块，无历史会话保存功能；后续建议不代表已经实现。

Word 文件按用户提供的原件打包，未更新其内部内容；若与代码或新版 README 有出入，以当前源码与 README 为准。

未包含：任何 API Key、外部 config 文件、虚拟环境、模型缓存、运行日志、用户会话摘要、浏览器聊天记录、开发机测试输出。网页截图仅为界面预览，demo-report.png 为虚构测试记录。

PACKAGE-MANIFEST.json 列出本包各文件的 SHA-256。ZIP 同目录的 .sha256 用于校验整个压缩包。
