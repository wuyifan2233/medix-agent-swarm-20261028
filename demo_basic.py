"""Run real CLI examples, then hand the same console to the user."""
import builtins
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log
    def write(self, text):
        self.console.write(text)
        self.log.write(text)
        self.flush()
    def flush(self):
        self.console.flush()
        self.log.flush()
    def __getattr__(self, name):
        return getattr(self.console, name)

log = (ROOT / "demo-live.log").open("w", encoding="utf-8", buffering=1)
sys.stdout = Tee(sys.stdout, log)
sys.stderr = Tee(sys.stderr, log)

import config
mem0_key = config.MEM0_CONFIG.get("api_key", "")
# Run fictional medical examples without retaining them in cloud memory.
config.MEM0_CONFIG["api_key"] = ""
import main as application
from loguru import logger

def demo_logger(verbose=False):
    logger.remove()
    logger.add(sys.stderr, format="  [运行] {message}", level="INFO",
               filter=lambda r: r["level"].no >= 40 or r["name"].startswith("skill_") or "LLM requested" in r["message"])

application.setup_logger = demo_logger
original_input = builtins.input
steps = iter([
    ("1/5 普通问答：观察自动选择单 Agent", "多喝水对健康有什么好处？请用三点简短说明。"),
    ("2/5 知识库：虚构案例，观察实际工具检索", "演示案例：我最近感冒了，有点咳嗽。请查询知识库，简要给出一般性建议。"),
    ("3/5 多轮记忆：追问时不重复病情", "我刚才提到的是什么症状？请只用一句话回答。"),
    ("4/5 多 Agent 协作：虚构复杂案例", "虚构演示案例：35岁男性，持续头痛、头晕、恶心一周，有高血压史。请分别分析症状风险和日常管理建议，简要作答。"),
])

def next_input(prompt):
    try:
        label, question = next(steps)
    except StopIteration:
        builtins.input = original_input
        if mem0_key:
            print("\n========== 5/5 Mem0 跨会话长期记忆 ==========", flush=True)
            print("使用独立虚构用户保存‘喜欢蓝色’，用新客户端检索，随后删除测试记忆。", flush=True)
            import verify_mem0
            result_code = verify_mem0.main()
            print("长期记忆演示：" + ("写入、跨会话检索、清理全部成功。" if result_code == 0 else "请查看上方错误。"), flush=True)
            config.MEM0_CONFIG["api_key"] = mem0_key
        print("\n演示已完成。窗口已切换为自由输入模式，你可以输入问题，输入 exit 退出。", flush=True)
        return original_input(prompt)
    print("\n========== " + label + " ==========", flush=True)
    time.sleep(3)
    print(prompt + question, flush=True)
    return question

builtins.input = next_input
print("MediX 项目实时演示：所有回答来自真实接口和项目代码。", flush=True)
print("接下来自动运行 5 项基本功能，结束后可直接输入自己的问题。", flush=True)
application.main()
