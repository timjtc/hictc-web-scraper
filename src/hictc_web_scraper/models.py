from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Auth:
    base_url: str
    plugin_token: str
    id_token: str | None
    params: dict[str, str]
    headers: dict[str, str]


@dataclass
class Chapter:
    id: str
    title: str
    breadcrumb: list[str] = field(default_factory=list)
    level: int = 0


def _node_id(node: dict[str, Any]) -> str | None:
    for key in ("_id", "id", "chapterId", "chapter"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _node_title(node: dict[str, Any]) -> str:
    for key in ("title", "name", "chapterName"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def flatten_chapters(tree: Any) -> list[Chapter]:
    chapters: list[Chapter] = []

    def walk(nodes: Any, ancestors: list[str], level: int) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = _node_title(node)
            breadcrumb = [*ancestors, title] if title else list(ancestors)
            node_id = _node_id(node)
            if node_id:
                chapters.append(
                    Chapter(
                        id=node_id,
                        title=title or f"Section {len(chapters) + 1}",
                        breadcrumb=breadcrumb,
                        level=level,
                    )
                )
            walk(node.get("children"), breadcrumb, level + 1)

    walk(tree, [], 0)
    return chapters
