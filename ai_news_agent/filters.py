from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from .models import Article
from .utils import normalize_title, split_sentences, text_contains_keywords, trim_text


SECTION_KEYS = [
    "ai_application",
    "ai_model",
    "ai_safety",
    "ai_investment",
    "research_paper",
]

VENUE_KEYWORDS = ["neurips", "icml", "cvpr", "iclr", "aaai", "acl", "emnlp", "arxiv"]


def should_keep_article(article: Article, filtering: dict[str, Any], assume_relevant: bool) -> bool:
    include_keywords = filtering.get("include_keywords", [])
    exclude_keywords = filtering.get("exclude_keywords", [])

    text = f"{article.title} {article.snippet} {article.body_text}".casefold()
    if any(keyword.casefold() in text for keyword in exclude_keywords):
        return False
    if article.forced_category:
        return True
    if assume_relevant:
        return True
    return text_contains_keywords(text, include_keywords) > 0


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    unique: list[Article] = []
    normalized_titles: list[str] = []
    seen_urls: set[str] = set()

    ordered = sorted(
        articles,
        key=lambda item: (item.source_weight, len(item.body_text), item.importance_score),
        reverse=True,
    )

    for article in ordered:
        normalized = normalize_title(article.title)
        if article.url in seen_urls:
            continue
        if not normalized:
            continue
        if normalized in normalized_titles:
            continue

        if any(SequenceMatcher(None, normalized, prior).ratio() >= 0.93 for prior in normalized_titles):
            continue

        normalized_titles.append(normalized)
        seen_urls.add(article.url)
        unique.append(article)

    return unique


def infer_category(article: Article, filtering: dict[str, Any]) -> str:
    if article.forced_category:
        return article.forced_category

    category_keywords = filtering.get("category_keywords", {})
    text = f"{article.title} {article.summary} {article.body_text} {article.snippet}".casefold()
    headline_text = f"{article.title} {article.snippet}".casefold()
    scores = {
        key: text_contains_keywords(text, keywords)
        for key, keywords in category_keywords.items()
        if key in SECTION_KEYS
    }

    paper_signal = text_contains_keywords(
        text,
        ["论文", "paper", "arxiv", "neurips", "icml", "cvpr", "iclr", "aaai", "acl", "emnlp"],
    )
    headline_paper_signal = text_contains_keywords(
        headline_text,
        ["论文", "paper", "arxiv", "neurips", "icml", "cvpr", "iclr", "aaai", "acl", "emnlp"],
    )
    investment_signal = text_contains_keywords(
        text,
        [
            "融资",
            "投资",
            "并购",
            "收购",
            "上市",
            "funding",
            "acquisition",
            "valuation",
            "series a",
            "series b",
            "seed",
            "raise",
            "raises",
            "raised",
            "investor",
            "investors",
            "backed",
            "backs",
            "deal",
            "m&a",
        ],
    )
    headline_investment_signal = text_contains_keywords(
        headline_text,
        [
            "融资",
            "投资",
            "并购",
            "收购",
            "上市",
            "funding",
            "acquisition",
            "valuation",
            "series a",
            "series b",
            "seed",
            "raise",
            "raises",
            "raised",
            "investor",
            "investors",
            "backed",
            "backs",
            "deal",
            "m&a",
        ],
    )

    if any(keyword in text for keyword in VENUE_KEYWORDS):
        scores["research_paper"] = scores.get("research_paper", 0) + 3

    if (
        "融资" in text
        or "investment" in text
        or "funding" in text
        or "acquisition" in text
        or "raise" in text
        or "raised" in text
        or "investor" in text
        or "backed" in text
        or "m&a" in text
    ):
        scores["ai_investment"] = scores.get("ai_investment", 0) + 2

    if "安全" in text or "safety" in text or "security" in text or "policy" in text:
        scores["ai_safety"] = scores.get("ai_safety", 0) + 2

    if paper_signal == 0 or headline_paper_signal == 0:
        scores["research_paper"] = 0
    if investment_signal < 2 or headline_investment_signal == 0:
        scores["ai_investment"] = 0

    category = max(scores.items(), key=lambda item: item[1])[0] if scores else "ai_model"
    return category if scores.get(category, 0) > 0 else "ai_model"


def score_article(article: Article, filtering: dict[str, Any]) -> float:
    now = datetime.now(timezone.utc)
    score = article.source_weight * 35
    reference_text = f"{article.title} {article.summary} {article.body_text} {article.snippet}"

    for key, keywords in filtering.get("category_keywords", {}).items():
        if key in SECTION_KEYS:
            score += min(text_contains_keywords(reference_text, keywords), 4) * 2

    if article.published_at:
        published_at = article.published_at if article.published_at.tzinfo else article.published_at.replace(tzinfo=timezone.utc)
        age_hours = max((now - published_at).total_seconds() / 3600, 0)
        if age_hours <= 24:
            score += 25
        elif age_hours <= 72:
            score += 15
        elif age_hours <= 168:
            score += 8

    score += min(len(article.body_text) / 400, 10)
    score += min(len(article.key_points), 4) * 2

    if article.category == "ai_investment":
        score += 6
    if article.category == "research_paper":
        score += 4

    return round(score, 2)


def build_fallback_summary(
    article: Article,
    min_chars: int = 100,
    max_chars: int = 300,
) -> tuple[str, list[str]]:
    source_text = article.body_text or article.snippet or article.title
    sentences = split_sentences(source_text, limit=8)
    if not sentences:
        return trim_text(article.title, max_chars), [trim_text(article.title, 60)]

    selected_sentences: list[str] = []
    current_length = 0
    for sentence in sentences:
        selected_sentences.append(sentence)
        current_length = len("；".join(selected_sentences))
        if current_length >= min_chars:
            break
    if not selected_sentences:
        selected_sentences = sentences[:2]

    summary = "；".join(selected_sentences).strip("；")
    if not summary.endswith(("。", "！", "？")):
        summary += "。"

    key_points = [trim_text(sentence, 48) for sentence in sentences[:3]]
    return trim_text(summary, max_chars), key_points


def extract_finance_info(article: Article) -> dict[str, str]:
    text = f"{article.title} {article.body_text} {article.summary}"
    amount_pattern = re.compile(
        r"((?:\d+(?:\.\d+)?)\s*(?:亿美元|万美元|亿元|万元|万美金|million|billion|M|B))",
        flags=re.IGNORECASE,
    )
    round_pattern = re.compile(
        r"(天使轮|种子轮|Pre-A|Pre-B|A\+?轮|B\+?轮|C\+?轮|D\+?轮|战略融资|并购|收购|IPO|Series\s+[A-Z])",
        flags=re.IGNORECASE,
    )
    investor_pattern = re.compile(
        r"(?:由|获|led by)\s*([^，。；;]{2,60})(?:领投|投资|参投|invest)",
        flags=re.IGNORECASE,
    )

    company = article.title.split("：")[0].split(":")[0].strip()
    info = {
        "company": trim_text(company, 30),
        "amount": "",
        "round": "",
        "investors": "",
        "business": trim_text(article.summary or article.snippet, 50),
    }

    amount_match = amount_pattern.search(text)
    round_match = round_pattern.search(text)
    investor_match = investor_pattern.search(text)

    if amount_match:
        info["amount"] = amount_match.group(1)
    if round_match:
        info["round"] = round_match.group(1)
    if investor_match:
        info["investors"] = trim_text(investor_match.group(1), 30)
    return info


def extract_paper_info(article: Article) -> dict[str, str]:
    text = f"{article.title} {article.body_text} {article.summary}".casefold()
    venue = next((keyword.upper() for keyword in VENUE_KEYWORDS if keyword in text), "arXiv" if "arxiv" in text else "")
    takeaways = split_sentences(article.summary or article.body_text or article.snippet, limit=2)
    return {
        "venue": venue,
        "institution": "",
        "takeaway": trim_text("；".join(takeaways), 60),
    }
