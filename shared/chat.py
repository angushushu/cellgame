"""Public chat validation shared by the server and local client."""
import unicodedata

CHAT_MAX_LENGTH = 200
CHAT_HISTORY_LIMIT = 100
CHAT_INTERVAL_SECONDS = 1.0


def validate_chat_text(text):
    if not isinstance(text, str):
        raise ValueError("消息必须是文字")
    text = text.strip()
    if not text:
        raise ValueError("消息不能为空")
    if len(text) > CHAT_MAX_LENGTH:
        raise ValueError(f"消息不能超过 {CHAT_MAX_LENGTH} 个字符")
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in text):
        raise ValueError("消息不能包含换行或控制字符")
    return text
