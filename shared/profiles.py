"""Player display identity shared by the game server and client."""
import re
import unicodedata

PALETTE = ("#F4B66A", "#B692F6", "#67C9EA", "#EF87A7",
           "#F2DE82", "#9DAEF5", "#E9936C", "#8CD6C0")


def default_color(player_id):
    return PALETTE[(player_id - 1) % len(PALETTE)]


def validate_profile(name, color):
    if not isinstance(name, str):
        raise ValueError("昵称必须是文字")
    name = name.strip()
    if not 1 <= len(name) <= 24 or any(unicodedata.category(c) in ("Cc", "Cs") for c in name):
        raise ValueError("昵称需为 1–24 个字符，且不能包含换行或控制字符")
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("颜色需要是 #RRGGBB 格式")
    return name, color.upper()
