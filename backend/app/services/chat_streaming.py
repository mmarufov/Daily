from __future__ import annotations

import json
import re
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_blocks_from_text(
    text: str,
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        tag = section.get("tag") or section["kind"]
        match = re.search(
            rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue

        raw_content = match.group(1).strip()
        if not raw_content:
            continue

        kind = section["kind"]
        heading = section.get("heading")
        if kind in {"bullet_list", "timeline", "watchlist"}:
            items = _extract_list_items(raw_content)
            if not items:
                continue
            blocks.append(
                {
                    "id": f"{kind}-{index}",
                    "kind": kind,
                    "heading": heading,
                    "items": items,
                }
            )
        else:
            blocks.append(
                {
                    "id": f"{kind}-{index}",
                    "kind": kind,
                    "heading": heading,
                    "text": _normalize_text(raw_content),
                }
            )

    if blocks:
        return blocks

    fallback_text = _strip_tags(text).strip()
    return [
        {
            "id": "body-0",
            "kind": "body",
            "heading": "Analysis",
            "text": _normalize_text(fallback_text),
        }
    ]


def blocks_plain_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        heading = block.get("heading")
        if heading:
            parts.append(str(heading))
        if block.get("text"):
            parts.append(str(block["text"]))
        if block.get("items"):
            parts.extend(f"- {item}" for item in block["items"])
    return "\n".join(part for part in parts if part).strip()


class SectionStreamParser:
    def __init__(self, sections: list[dict[str, Any]]):
        self.sections = [
            {
                "kind": section["kind"],
                "heading": section.get("heading"),
                "tag": section.get("tag") or section["kind"],
            }
            for section in sections
        ]
        self.buffer = ""
        self.current: dict[str, Any] | None = None
        self.next_index = 0

    def feed(self, chunk: str) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        self.buffer += chunk

        while True:
            if self.current is None:
                if self.next_index >= len(self.sections):
                    self.buffer = self.buffer[-128:]
                    break

                section = self.sections[self.next_index]
                open_tag = f"<{section['tag']}>"
                open_index = self.buffer.find(open_tag)
                if open_index == -1:
                    self.buffer = self.buffer[-(len(open_tag) + 8) :]
                    break

                self.buffer = self.buffer[open_index + len(open_tag) :]
                self.current = section
                events.append(
                    (
                        "section_open",
                        {
                            "index": self.next_index,
                            "kind": section["kind"],
                            "heading": section.get("heading"),
                        },
                    )
                )

            assert self.current is not None
            close_tag = f"</{self.current['tag']}>"
            close_index = self.buffer.find(close_tag)
            if close_index == -1:
                flush_upto = max(0, len(self.buffer) - len(close_tag) - 8)
                if flush_upto == 0:
                    break

                delta = self.buffer[:flush_upto]
                self.buffer = self.buffer[flush_upto:]
                normalized = _stream_delta(delta)
                if normalized:
                    events.append(
                        (
                            "section_delta",
                            {
                                "index": self.next_index,
                                "kind": self.current["kind"],
                                "delta": normalized,
                            },
                        )
                    )
                break

            delta = self.buffer[:close_index]
            self.buffer = self.buffer[close_index + len(close_tag) :]
            normalized = _stream_delta(delta)
            if normalized:
                events.append(
                    (
                        "section_delta",
                        {
                            "index": self.next_index,
                            "kind": self.current["kind"],
                            "delta": normalized,
                        },
                    )
                )

            self.current = None
            self.next_index += 1

        return events

    def finish(self) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        if self.current:
            normalized = _stream_delta(self.buffer)
            if normalized:
                events.append(
                    (
                        "section_delta",
                        {
                            "index": self.next_index,
                            "kind": self.current["kind"],
                            "delta": normalized,
                        },
                    )
                )
        self.buffer = ""
        self.current = None
        return events


def _extract_list_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if cleaned:
            items.append(cleaned)
    if items:
        return items
    cleaned = _normalize_text(text)
    return [cleaned] if cleaned else []


def _strip_tags(text: str) -> str:
    return re.sub(r"</?[a-z_]+>", "", text)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _stream_delta(text: str) -> str:
    return text.replace("\r", "")
