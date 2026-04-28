from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser


COMMON_SEPARATORS = re.compile(r"[。！？!?；;.\n]+")
MULTISPACE_RE = re.compile(r"\s+")
NON_WORD_TITLE_RE = re.compile(r"[\W_]+", re.UNICODE)
DATETIME_PREFIX_RE = re.compile(
    r"(?i)\b(?:published(?:\s+on)?|updated(?:\s+on)?|date|posted)\b\s*[:：-]?\s*"
)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value)
    if "<" not in raw and ">" not in raw:
        return MULTISPACE_RE.sub(" ", raw).strip()
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return MULTISPACE_RE.sub(" ", text).strip()


def normalize_title(value: str) -> str:
    return NON_WORD_TITLE_RE.sub("", value.casefold())


def normalize_datetime_text(value: Any) -> str:
    text = clean_text(str(value))
    if not text:
        return ""

    text = text.replace("发布于", "").replace("发布时间", "").replace("更新时间", "")
    text = DATETIME_PREFIX_RE.sub("", text)
    text = text.replace("号", "日")
    text = re.sub(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日?", r"\1-\2-\3", text)
    text = re.sub(r"(\d{1,2})月\s*(\d{1,2})日", r"\1-\2", text)
    text = text.replace("年", "-").replace("月", "-").replace("日", " ")
    text = text.replace("/", "-").replace(".", "-")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n|,:;")
    return text


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    normalized = normalize_datetime_text(value)
    if not normalized:
        return None
    try:
        parsed = date_parser.parse(normalized)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = date_parser.parse(normalized, fuzzy=True)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_recent(value: datetime | None, max_hours: int) -> bool:
    if value is None:
        return True
    now = datetime.now(timezone.utc)
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return now - dt <= timedelta(hours=max_hours)


def absolute_url(base_url: str, maybe_relative: str) -> str:
    candidate = str(maybe_relative).strip()
    candidate = re.sub(r"^(https?):/(?!/)", r"\1://", candidate)
    return urljoin(base_url, candidate)


def same_domain(url_a: str, url_b: str) -> bool:
    return urlparse(url_a).netloc == urlparse(url_b).netloc


def first_non_empty(*values: str) -> str:
    for value in values:
        cleaned = clean_text(value)
        if cleaned:
            return cleaned
    return ""


def text_contains_keywords(text: str, keywords: list[str]) -> int:
    haystack = text.casefold()
    hits = 0
    for keyword in keywords:
        normalized = keyword.casefold().strip()
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9 .+\-]+", normalized):
            pattern = r"(?<![a-z0-9])" + re.escape(normalized).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                hits += 1
        elif normalized in haystack:
            hits += 1
    return hits


def split_sentences(text: str, limit: int = 4) -> list[str]:
    sentences = [segment.strip(" -") for segment in COMMON_SEPARATORS.split(text) if segment.strip()]
    return sentences[:limit]


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def flatten_json_ld(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for child in payload:
            items.extend(flatten_json_ld(child))
        return items
    if isinstance(payload, dict):
        if "@graph" in payload:
            items.extend(flatten_json_ld(payload["@graph"]))
        else:
            items.append(payload)
    return items


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    json_blobs: list[dict[str, Any]] = []
    if not text:
        return json_blobs

    candidates = []
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)

    brace_match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(1))

    for candidate in candidates:
        try:
            json_blobs.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return json_blobs
