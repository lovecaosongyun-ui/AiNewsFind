from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import Article
from .utils import (
    absolute_url,
    clean_text,
    first_non_empty,
    flatten_json_ld,
    parse_datetime,
    same_domain,
    text_contains_keywords,
)


GENERIC_ARTICLE_SELECTORS = [
    "article",
    "main article",
    "main",
    ".article-content",
    ".entry-content",
    ".post-content",
    ".post__content",
    ".rich-text",
    ".content",
]

PUBLISHED_PATTERNS = [
    re.compile(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})"),
    re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日)"),
]


ENGLISH_MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)

PUBLISHED_PATTERNS = [
    re.compile(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(r"(20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}[日号]?\s*\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(rf"({ENGLISH_MONTH_PATTERN}\s+\d{{1,2}},\s+20\d{{2}}(?:\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?)", re.I),
    re.compile(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})"),
    re.compile(r"(20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}[日号]?)"),
    re.compile(rf"({ENGLISH_MONTH_PATTERN}\s+\d{{1,2}},\s+20\d{{2}})", re.I),
]


class NewsFetcher:
    def __init__(self, config: dict[str, Any], session: requests.Session, logger, progress_callback=None) -> None:
        self.config = config
        self.session = session
        self.logger = logger
        self.timeout = config["runtime"].get("request_timeout_seconds", 20)
        self.max_workers = config["runtime"].get("max_workers", 8)
        self.last_source_statuses: dict[str, dict[str, Any]] = {}
        self.progress_callback = progress_callback

    def collect_articles(self) -> list[Article]:
        candidates: list[tuple[Article, dict[str, Any]]] = []
        sources = self.config.get("sources", [])
        total_sources = max(len(sources), 1)
        for index, source in enumerate(sources, start=1):
            source_name = source["name"]
            requested_limit = self._resolve_source_limit(source)
            self.last_source_statuses[source_name] = {
                "enabled": bool(source.get("enabled", True)),
                "fetched_count": 0,
                "requested_limit": requested_limit,
                "status": "pending",
                "message": "",
            }
            if not source.get("enabled", True):
                self.last_source_statuses[source_name]["status"] = "disabled"
                continue
            self._report_source_progress(
                index=index,
                total=total_sources,
                source_name=source_name,
                message=f"正在抓取 {source_name}（{index}/{total_sources}）...",
            )
            try:
                source_candidates = self._fetch_source_candidates(source)
                candidates.extend((candidate, source) for candidate in source_candidates)
                self.last_source_statuses[source_name]["fetched_count"] = len(source_candidates)
                self.last_source_statuses[source_name]["status"] = "ok" if source_candidates else "empty"
                self.logger.info("数据源 %s 获取候选资讯 %s 条", source_name, len(source_candidates))
            except Exception as exc:  # noqa: BLE001
                self.last_source_statuses[source_name]["status"] = "error"
                self.last_source_statuses[source_name]["message"] = str(exc)
                self.logger.warning("数据源 %s 获取失败：%s", source_name, exc)
        self._report_source_progress(
            index=total_sources,
            total=total_sources,
            source_name="全部数据源",
            message="候选文章抓取完成，正在补齐正文与图片信息...",
        )

        hydrated: list[Article] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(self._hydrate_candidate, article, source): (article, source)
                for article, source in candidates
            }
            for future in as_completed(future_map):
                base_article, _ = future_map[future]
                try:
                    article = future.result()
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("正文抓取失败 %s：%s", base_article.url, exc)
                    article = base_article
                hydrated.append(article)
        return hydrated

    def _fetch_source_candidates(self, source: dict[str, Any]) -> list[Article]:
        kind = source.get("kind", "html")
        if kind == "rss":
            return self._fetch_rss_candidates(source)
        return self._fetch_html_candidates(source)

    def _fetch_rss_candidates(self, source: dict[str, Any]) -> list[Article]:
        response = self.session.get(source["url"], timeout=self.timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        max_items = self._resolve_source_limit(source)
        required_tags = {str(tag).casefold() for tag in source.get("required_entry_tags", [])}
        required_keywords = [str(keyword) for keyword in source.get("required_entry_keywords", [])]
        articles: list[Article] = []
        for entry in feed.entries:
            title = clean_text(entry.get("title"))
            link = entry.get("link")
            if not title or not link:
                continue
            snippet = first_non_empty(entry.get("summary"), entry.get("description"))
            if not snippet and entry.get("content"):
                snippet = clean_text(entry["content"][0].get("value"))
            entry_tags = {str(tag.get("term", "")).casefold() for tag in entry.get("tags", [])}
            reference_text = f"{title} {snippet}"
            if required_tags and not (required_tags & entry_tags):
                continue
            if required_keywords and not any(keyword.casefold() in reference_text.casefold() for keyword in required_keywords):
                continue
            articles.append(
                Article(
                    source_name=source["name"],
                    source_home=source.get("homepage_url", source["url"]),
                    url=link,
                    title=title,
                    snippet=snippet,
                    published_at=parse_datetime(entry.get("published") or entry.get("updated")),
                    locale=source.get("locale", "zh"),
                    source_weight=float(source.get("source_weight", 1.0)),
                    forced_category=source.get("forced_category"),
                    metadata={"assume_relevant": source.get("assume_relevant", False)},
                )
            )
            if len(articles) >= max_items:
                break
        return articles

    def _fetch_html_candidates(self, source: dict[str, Any]) -> list[Article]:
        response = self.session.get(source["url"], timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        anchors = []
        for selector in source.get("listing_selectors", []):
            anchors.extend(soup.select(selector))
        if not anchors:
            anchors = soup.find_all("a", href=True)

        include_patterns = source.get("include_patterns", [])
        exclude_patterns = source.get("exclude_patterns", [])
        same_domain_only = source.get("same_domain_only", False)
        external_only = source.get("external_only", False)
        max_items = self._resolve_source_limit(source)
        required_entry_keywords = [str(keyword) for keyword in source.get("required_entry_keywords", [])]

        articles: list[Article] = []
        seen_urls: set[str] = set()
        for anchor in anchors:
            href = anchor.get("href")
            if not href:
                continue
            url = absolute_url(source["url"], href)
            title = clean_text(anchor.get_text(" ", strip=True))
            if not title or len(title) < 8:
                continue
            if external_only and same_domain(url, source["url"]):
                continue
            if same_domain_only and not same_domain(url, source["url"]):
                continue
            if include_patterns and not any(pattern in url for pattern in include_patterns):
                continue
            if any(pattern in url for pattern in exclude_patterns):
                continue
            reference_text = self._build_anchor_reference_text(anchor, title)
            if required_entry_keywords and text_contains_keywords(reference_text, required_entry_keywords) == 0:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            published_text, published_at = self._extract_listing_published_at(anchor)
            metadata: dict[str, Any] = {"assume_relevant": source.get("assume_relevant", False)}
            if published_text:
                metadata["published_text"] = published_text
            articles.append(
                Article(
                    source_name=source["name"],
                    source_home=source.get("homepage_url", source["url"]),
                    url=url,
                    title=title,
                    published_at=published_at,
                    locale=source.get("locale", "zh"),
                    source_weight=float(source.get("source_weight", 1.0)),
                    forced_category=source.get("forced_category"),
                    metadata=metadata,
                )
            )
            if len(articles) >= max_items:
                break
        return articles

    def _resolve_source_limit(self, source: dict[str, Any]) -> int:
        runtime_limit = int(self.config["runtime"].get("article_limit_per_source", 10) or 10)
        if source.get("inherit_runtime_limit", True):
            return max(runtime_limit, 1)
        return max(int(source.get("max_items", runtime_limit) or runtime_limit), 1)

    def _build_anchor_reference_text(self, anchor, title: str) -> str:
        snippets = [title]
        current = getattr(anchor, "parent", None)
        depth = 0
        while current is not None and depth < 3:
            text = clean_text(current.get_text(" ", strip=True))
            if text:
                snippets.append(text)
            current = getattr(current, "parent", None)
            depth += 1
        return " ".join(snippets)

    def _hydrate_candidate(self, article: Article, source: dict[str, Any]) -> Article:
        if source.get("skip_hydration"):
            return article
        original_title = article.title
        response = self.session.get(article.url, timeout=self.timeout, headers={"Referer": source["url"]})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        json_ld_blocks = self._extract_json_ld_blocks(soup)
        json_ld_article = self._pick_primary_json_ld(json_ld_blocks)

        title = first_non_empty(
            self._meta_content(soup, "property", "og:title"),
            self._meta_content(soup, "name", "title"),
            json_ld_article.get("headline", ""),
            article.title,
        )
        description = first_non_empty(
            self._meta_content(soup, "name", "description"),
            self._meta_content(soup, "property", "og:description"),
            json_ld_article.get("description", ""),
            article.snippet,
        )

        published_text = first_non_empty(
            self._meta_content(soup, "property", "article:published_time"),
            self._meta_content(soup, "name", "pubdate"),
            self._meta_content(soup, "name", "parsely-pub-date"),
            json_ld_article.get("datePublished", ""),
            self._extract_published_at_text(soup, source),
            article.metadata.get("published_text", ""),
        )
        published_at = parse_datetime(published_text) or article.published_at

        body_text = first_non_empty(
            json_ld_article.get("articleBody", ""),
            self._extract_body_text(soup, source),
            description,
            article.snippet,
        )
        image_urls = self._extract_image_urls(soup, source, article.url, json_ld_article)

        if source.get("prefer_listing_title") and original_title:
            title = original_title

        article.title = title
        article.snippet = description or article.snippet
        article.published_at = published_at
        article.body_text = body_text
        article.image_urls = image_urls
        if published_text:
            article.metadata["published_text"] = published_text
        return article

    def _extract_body_text(self, soup: BeautifulSoup, source: dict[str, Any]) -> str:
        selectors = source.get("article_selectors", []) + GENERIC_ARTICLE_SELECTORS
        container = None
        for selector in selectors:
            selected = soup.select_one(selector)
            if selected:
                container = selected
                break
        if container is None:
            container = soup

        paragraphs: list[str] = []
        for node in container.find_all(["p", "li"], limit=120):
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= 25:
                paragraphs.append(text)
        return " ".join(paragraphs[:40]).strip()

    def _extract_image_urls(
        self,
        soup: BeautifulSoup,
        source: dict[str, Any],
        article_url: str,
        json_ld_article: dict[str, Any],
    ) -> list[str]:
        image_urls: list[str] = []

        candidates = self._normalize_image_candidates(json_ld_article.get("image", []))
        candidates.extend(
            filter(
                None,
                [
                    self._meta_content(soup, "property", "og:image"),
                    self._meta_content(soup, "name", "twitter:image"),
                ],
            )
        )

        selectors = source.get("image_selectors", []) + ["article img", "main img", ".entry-content img", "img"]
        for selector in selectors:
            selected_images = soup.select(selector)
            for img in selected_images:
                candidate = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or img.get("data-lazy-src")
                )
                if not candidate and img.get("srcset"):
                    candidate = img.get("srcset", "").split(" ")[0]
                if candidate:
                    candidates.append(candidate)
            if selected_images:
                break

        seen: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            if candidate.startswith("@") or candidate.startswith("{") or candidate.startswith("["):
                continue
            url = absolute_url(article_url, str(candidate))
            lowered = url.lower()
            if (
                not lowered.startswith("http")
                or lowered.startswith("data:")
                or lowered.endswith(".svg")
                or lowered.endswith("/@id")
                or "avatar" in lowered
                or "logo" in lowered
                or "icon" in lowered
            ):
                continue
            if url in seen:
                continue
            seen.add(url)
            image_urls.append(url)
            if len(image_urls) >= 5:
                break
        return image_urls

    def _meta_content(self, soup: BeautifulSoup, attr: str, key: str) -> str:
        node = soup.find("meta", attrs={attr: key})
        return clean_text(node.get("content")) if node and node.get("content") else ""

    def _extract_json_ld_blocks(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            blocks.extend(flatten_json_ld(parsed))
        return blocks

    def _pick_primary_json_ld(self, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        for block in blocks:
            if block.get("@type") in {"NewsArticle", "Article", "BlogPosting"}:
                return block
        return {}

    def _extract_published_at_text(self, soup: BeautifulSoup, source: dict[str, Any]) -> str:
        candidates: list[str] = []

        date_node = soup.select_one(".date")
        time_node = soup.select_one(".time")
        if date_node:
            combined = clean_text(date_node.get_text(" ", strip=True))
            if time_node:
                combined = f"{combined} {clean_text(time_node.get_text(' ', strip=True))}".strip()
            candidates.extend(self._extract_dates_from_text(combined) or [combined])

        selectors = source.get("date_selectors", []) + [
            "time",
            "[datetime]",
            ".date",
            ".time",
            ".post-date",
            ".entry-date",
            ".article-time",
            ".post-meta",
            ".entry-meta",
            ".article-meta",
        ]
        for selector in selectors:
            for node in soup.select(selector)[:4]:
                if node.get("datetime"):
                    candidates.append(clean_text(node.get("datetime")))
                if node.get("content"):
                    candidates.append(clean_text(node.get("content")))
                text = clean_text(node.get_text(" ", strip=True))
                candidates.extend(self._extract_dates_from_text(text))
                if text and len(text) <= 64:
                    candidates.append(text)

        for node in soup.select("article, main")[:2]:
            candidates.extend(self._extract_dates_from_text(node.get_text(" ", strip=True)))

        head_text = "\n".join(soup.get_text("\n", strip=True).splitlines()[:60])
        candidates.extend(self._extract_dates_from_text(head_text))

        for candidate in candidates:
            parsed = parse_datetime(candidate)
            if self._is_reasonable_published_at(parsed):
                return candidate
        return ""

    def _extract_listing_published_at(self, anchor) -> tuple[str, datetime | None]:
        candidates: list[str] = []
        containers = [anchor]
        current = getattr(anchor, "parent", None)
        depth = 0
        while current is not None and depth < 3:
            containers.append(current)
            for nearby in current.select("time, [datetime], .date, .time, .post-date, .entry-date")[:4]:
                if nearby.get("datetime"):
                    candidates.append(clean_text(nearby.get("datetime")))
                text = clean_text(nearby.get_text(" ", strip=True))
                candidates.extend(self._extract_dates_from_text(text))
            current = getattr(current, "parent", None)
            depth += 1

        for node in containers:
            text_getter = getattr(node, "get_text", None)
            if not callable(text_getter):
                continue
            if hasattr(node, "get") and node.get("datetime"):
                candidates.append(clean_text(node.get("datetime")))
            text = clean_text(node.get_text(" ", strip=True))
            candidates.extend(self._extract_dates_from_text(text))
            if text and len(text) <= 48:
                candidates.append(text)

        for candidate in candidates:
            parsed = parse_datetime(candidate)
            if self._is_reasonable_published_at(parsed):
                return candidate, parsed
        return "", None

    def _extract_dates_from_text(self, text: str) -> list[str]:
        if not text:
            return []
        extracted: list[str] = []
        for pattern in PUBLISHED_PATTERNS:
            matches = pattern.findall(text)
            if not matches:
                continue
            if isinstance(matches[0], tuple):
                extracted.extend(clean_text(match[0]) for match in matches if match and match[0])
            else:
                extracted.extend(clean_text(match) for match in matches if match)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in extracted:
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def _is_reasonable_published_at(self, value: datetime | None) -> bool:
        if value is None:
            return False
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return 2015 <= normalized.year <= now.year + 1

    def _normalize_image_candidates(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            candidates = []
            if value.get("url"):
                candidates.append(str(value["url"]))
            return candidates
        if isinstance(value, list):
            flattened: list[str] = []
            for item in value:
                flattened.extend(self._normalize_image_candidates(item))
            return flattened
        return []

    def _report_source_progress(self, *, index: int, total: int, source_name: str, message: str) -> None:
        if not self.progress_callback:
            return
        progress = 10 + int((index / max(total, 1)) * 20)
        self.progress_callback(
            {
                "progress": progress,
                "stage": "fetching",
                "message": message,
                "details": {"source_name": source_name, "completed_sources": index, "total_sources": total},
            }
        )
