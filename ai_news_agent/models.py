from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Article:
    source_name: str
    source_home: str
    url: str
    title: str
    snippet: str = ""
    published_at: datetime | None = None
    body_text: str = ""
    locale: str = "zh"
    source_weight: float = 1.0
    forced_category: str | None = None
    category: str | None = None
    importance_score: float = 0.0
    title_zh: str = ""
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    local_image_paths: list[Path] = field(default_factory=list)
    finance_info: dict[str, str] = field(default_factory=dict)
    paper_info: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title


@dataclass(slots=True)
class SectionBundle:
    key: str
    label: str
    articles: list[Article] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    output_path: Path
    markdown_path: Path | None
    stats_path: Path | None
    sections: list[SectionBundle]
    candidate_count: int
    article_count: int
    llm_used: bool
    started_at: datetime
    finished_at: datetime
    log_path: Path
    source_stats: list[dict[str, Any]] = field(default_factory=list)
