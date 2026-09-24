"""Interpret the players' Discord convention: **action** and plain speech."""

import re


def split_roleplay(content: str) -> tuple[str, str]:
    actions = re.findall(r"\*\*(.+?)\*\*", content, flags=re.DOTALL)
    spoken = re.sub(r"\*\*.+?\*\*", " ", content, flags=re.DOTALL)
    return " ".join(" ".join(actions).split()), " ".join(spoken.split())
