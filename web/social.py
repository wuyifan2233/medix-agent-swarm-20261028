"""Exact social intents; mixed medical questions must keep the medical route."""
import re


def social_reply(message):
    text = re.sub(r"[\s，,。.!！?？、～~]+", "", message).lower()
    if re.fullmatch(r"(你好[呀啊哇]?|您好|嗨|哈[喽啰]|hi|hello|早上好|早安|晚上好|下午好|中午好|在吗)", text):
        return "你好，我是 MediX，你的 AI 健康伙伴。可以和我聊聊健康问题，或上传检查报告一起看看。"
    if re.fullmatch(r"(谢谢[你您]?|感谢[你您]?|多谢|thanks|thankyou)", text):
        return "不客气，有健康方面的问题，随时来聊。"
    if re.fullmatch(r"(你是谁|你叫什么|你能做什么|你能帮我什么|你能提供哪些帮助|请介绍一下你自己|你好请用一句话介绍你能提供的帮助)", text):
        return "我是 MediX，可以帮助你了解健康知识、解读检查报告，以及管理健康档案、记忆和提醒；回答供参考，不能替代医生诊断。"
    return None
