from typing import Optional

def split_telegram_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append("".join(current).rstrip())
                current = []
                current_len = 0
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit].rstrip())
            continue

        if current_len + len(line) > limit:
            chunks.append("".join(current).rstrip())
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current).rstrip())

    return [chunk for chunk in chunks if chunk]

def parse_private_chat_ids(raw_value: str) -> set[int] | None:
    if not raw_value or not raw_value.strip():
        return None
    chat_ids: set[int] = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            chat_ids.add(int(value))
        except ValueError:
            continue
    return chat_ids


def parse_chat_ids(raw_value: str) -> set[int] | None:
    return parse_private_chat_ids(raw_value)
