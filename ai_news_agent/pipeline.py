from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .config import ensure_runtime_dirs
from .doc_generator import DocxReportGenerator
from .fetchers import NewsFetcher
from .filters import deduplicate_articles, infer_category, score_article, should_keep_article
from .http import build_session
from .llm import NewsAnalyzer
from .logging_utils import setup_logger
from .markdown_generator import MarkdownReportGenerator
from .models import PipelineResult, SectionBundle
from .stats_writer import write_source_stats
from .utils import is_recent


class DailyNewsPipeline:
    def __init__(self, config: dict[str, Any], progress_callback=None) -> None:
        self.config = config
        self.progress_callback = progress_callback
        ensure_runtime_dirs(self.config)
        self.logger, self.log_path = setup_logger(self.config["runtime"]["log_dir"])
        self.session = build_session(
            self.config["runtime"].get("user_agent", "Mozilla/5.0"),
            int(self.config["runtime"].get("retries", 3)),
        )
        self.fetcher = NewsFetcher(self.config, self.session, self.logger, progress_callback=self._relay_progress)
        self.analyzer = NewsAnalyzer(self.config, self.logger, progress_callback=self._relay_progress)
        self.generator = DocxReportGenerator(self.config, self.logger)
        self.markdown_generator = MarkdownReportGenerator(self.config, self.logger)

    def run(self) -> PipelineResult:
        started_at = datetime.now()
        runtime = self.config["runtime"]
        filtering = self.config.get("filtering", {})

        self._report_progress(3, "initializing", "正在准备运行环境与配置...")
        self.logger.info("开始执行每日 AI 资讯生成流程。")
        self._report_progress(8, "fetching", "正在抓取候选文章...")
        raw_articles = self.fetcher.collect_articles()
        self.logger.info("抓取到原始资讯 %s 条。", len(raw_articles))

        recent_hours = int(runtime.get("recent_hours", 72))
        date_range = self._resolve_date_range(runtime)
        self._report_progress(38, "filtering", "正在按时间范围和关键词进行初筛...")
        filtered = [
            article
            for article in raw_articles
            if self._within_selected_range(article.published_at, recent_hours, date_range)
            and should_keep_article(article, filtering, bool(article.metadata.get("assume_relevant")))
        ]
        self.logger.info("完成初筛，保留资讯 %s 条。", len(filtered))

        for article in filtered:
            article.category = article.forced_category or infer_category(article, filtering)
            article.importance_score = score_article(article, filtering)

        self._report_progress(48, "deduplicating", "正在进行去重与重要性排序...")
        deduplicated = deduplicate_articles(filtered)
        self.logger.info("完成去重，保留资讯 %s 条。", len(deduplicated))

        selected_for_analysis = self._select_for_analysis(deduplicated, filtering)

        llm_stage_text = "正在调用 Qwen 生成中文摘要、翻译英文内容并分类..." if self.analyzer.llm_available else "未启用 Qwen，正在使用规则模式生成摘要..."
        self._report_progress(58, "analyzing", llm_stage_text)
        analyzed_articles = self.analyzer.analyze_articles(selected_for_analysis)
        quality_threshold = int(self.config.get("quality", {}).get("min_score", 68))
        self._report_progress(76, "quality", "正在进行资讯质量评估与筛选...")
        quality_filtered = [
            article
            for article in analyzed_articles
            if int(article.metadata.get("quality_score", 0)) >= quality_threshold
        ]
        self.logger.info("完成质量筛选，保留资讯 %s 条。", len(quality_filtered))

        final_articles = quality_filtered or analyzed_articles
        for article in final_articles:
            if not article.importance_score:
                article.importance_score = score_article(article, filtering)

        self._report_progress(84, "images", "正在整理栏目并下载配图...")
        sections = self._build_sections(final_articles)
        temp_dir = Path(runtime["temp_dir"]) / started_at.strftime("%Y%m%d_%H%M%S")
        temp_dir.mkdir(parents=True, exist_ok=True)
        self._download_images(sections, temp_dir)

        timestamp = started_at.strftime(runtime.get("filename_time_format", "%Y%m%d_%H%M"))
        filename = runtime.get("document_name_template", "每日AI资讯_{timestamp}.docx").format(timestamp=timestamp)
        output_path = Path(runtime["output_dir"]) / filename
        markdown_path = Path(runtime["output_dir"]) / filename.replace(".docx", ".md")
        stats_path = Path(runtime["output_dir"]) / filename.replace(".docx", "_stats.txt")

        source_stats = self._build_source_stats(raw_articles, filtered, deduplicated, sections)

        metadata = {
            "generated_at": started_at.strftime("%Y-%m-%d %H:%M"),
            "candidate_count": len(raw_articles),
            "article_count": sum(len(section.articles) for section in sections),
            "recent_hours": recent_hours,
            "llm_mode": "Qwen API" if self.analyzer.llm_available else "规则摘要",
        }
        self._report_progress(92, "exporting", "正在生成 Word、Markdown 和统计文件...")
        self.generator.generate(output_path, sections, metadata)
        self.markdown_generator.generate(markdown_path, sections, metadata)
        write_source_stats(stats_path, metadata, source_stats)

        if not runtime.get("keep_temp_images", False):
            shutil.rmtree(temp_dir, ignore_errors=True)

        finished_at = datetime.now()
        self.logger.info("日报生成完成：%s", output_path)
        self._report_progress(100, "completed", "日报生成完成。")
        return PipelineResult(
            output_path=output_path,
            markdown_path=markdown_path,
            stats_path=stats_path,
            sections=sections,
            candidate_count=len(raw_articles),
            article_count=sum(len(section.articles) for section in sections),
            llm_used=self.analyzer.llm_available,
            started_at=started_at,
            finished_at=finished_at,
            log_path=self.log_path,
            source_stats=source_stats,
        )

    def _build_sections(self, articles: list) -> list[SectionBundle]:
        section_order = self.config["document"].get("sections", [])
        max_items_per_section = int(self.config["runtime"].get("max_items_per_section", 5))
        grouped: dict[str, list] = {section["key"]: [] for section in section_order}

        for article in articles:
            key = article.category or "ai_model"
            grouped.setdefault(key, []).append(article)

        bundles: list[SectionBundle] = []
        for section in section_order:
            articles_in_section = sorted(
                grouped.get(section["key"], []),
                key=lambda item: (item.forced_category == section["key"], item.importance_score),
                reverse=True,
            )[:max_items_per_section]
            bundles.append(SectionBundle(key=section["key"], label=section["label"], articles=articles_in_section))
        return bundles

    def _select_for_analysis(self, articles: list, filtering: dict[str, Any]) -> list:
        max_for_analysis = int(self.config["runtime"].get("max_articles_for_analysis", 25))
        min_per_section = int(self.config["runtime"].get("min_items_for_section_analysis", 1))
        section_keys = [section["key"] for section in self.config["document"].get("sections", [])]

        grouped: dict[str, list] = {key: [] for key in section_keys}
        for article in articles:
            article.category = article.category or infer_category(article, filtering)
            grouped.setdefault(article.category, []).append(article)

        selected: list = []
        selected_urls: set[str] = set()

        for key in section_keys:
            top_items = sorted(
                grouped.get(key, []),
                key=lambda item: (item.forced_category == key, item.importance_score),
                reverse=True,
            )[:min_per_section]
            for article in top_items:
                if article.url not in selected_urls:
                    selected.append(article)
                    selected_urls.add(article.url)

        remaining = sorted(articles, key=lambda item: item.importance_score, reverse=True)
        for article in remaining:
            if len(selected) >= max_for_analysis:
                break
            if article.url in selected_urls:
                continue
            selected.append(article)
            selected_urls.add(article.url)
        return selected[:max_for_analysis]

    def _report_progress(self, progress: int, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
        if self.progress_callback:
            self.progress_callback(
                {
                    "progress": max(0, min(int(progress), 100)),
                    "stage": stage,
                    "message": message,
                    "details": details or {},
                }
            )

    def _relay_progress(self, payload: dict[str, Any]) -> None:
        if self.progress_callback:
            self.progress_callback(payload)

    def _resolve_date_range(self, runtime: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
        start_date = runtime.get("start_date")
        end_date = runtime.get("end_date")
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.fromisoformat(str(start_date)).replace(tzinfo=timezone.utc)
        if end_date:
            end_dt = datetime.fromisoformat(str(end_date)).replace(tzinfo=timezone.utc) + timedelta(days=1)
        return start_dt, end_dt

    def _within_selected_range(
        self,
        published_at: datetime | None,
        recent_hours: int,
        date_range: tuple[datetime | None, datetime | None],
    ) -> bool:
        start_dt, end_dt = date_range
        if start_dt or end_dt:
            if published_at is None:
                return False
            normalized = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
            if start_dt and normalized < start_dt:
                return False
            if end_dt and normalized >= end_dt:
                return False
            return True
        return is_recent(published_at, recent_hours)

    def _build_source_stats(
        self,
        raw_articles: list,
        filtered: list,
        deduplicated: list,
        sections: list[SectionBundle],
    ) -> list[dict[str, Any]]:
        def count_by_source(items: list) -> dict[str, int]:
            counts: dict[str, int] = {}
            for item in items:
                counts[item.source_name] = counts.get(item.source_name, 0) + 1
            return counts

        raw_counts = count_by_source(raw_articles)
        filtered_counts = count_by_source(filtered)
        dedup_counts = count_by_source(deduplicated)
        final_counts = count_by_source([article for section in sections for article in section.articles])

        stats: list[dict[str, Any]] = []
        source_statuses = getattr(self.fetcher, "last_source_statuses", {})
        for source in self.config.get("sources", []):
            name = source["name"]
            status_info = source_statuses.get(name, {})
            stats.append(
                {
                    "name": name,
                    "enabled": bool(source.get("enabled", True)),
                    "region": source.get("region", ""),
                    "weight": float(source.get("source_weight", 1.0)),
                    "requested_limit": int(
                        status_info.get(
                            "requested_limit",
                            self.fetcher._resolve_source_limit(source),
                        )
                    ),
                    "fetched_count": raw_counts.get(name, status_info.get("fetched_count", 0)),
                    "filtered_count": filtered_counts.get(name, 0),
                    "deduplicated_count": dedup_counts.get(name, 0),
                    "selected_count": final_counts.get(name, 0),
                    "status": status_info.get("status", "unknown"),
                    "message": status_info.get("message", ""),
                }
            )
        return stats

    def _download_images(self, sections: list[SectionBundle], temp_dir: Path) -> None:
        timeout = int(self.config["runtime"].get("image_download_timeout_seconds", 20))
        for section in sections:
            downloaded = 0
            seen_urls: set[str] = set()
            for article in section.articles:
                for image_index, image_url in enumerate(article.image_urls):
                    if downloaded >= 2 or image_url in seen_urls:
                        continue
                    seen_urls.add(image_url)
                    try:
                        response = self.session.get(
                            image_url,
                            timeout=timeout,
                            headers={"Referer": article.url},
                        )
                        response.raise_for_status()
                        with Image.open(BytesIO(response.content)) as image:
                            if min(image.size) < 220:
                                continue
                            file_path = temp_dir / f"{section.key}_{downloaded + 1}_{image_index}.jpg"
                            converted = image.convert("RGB")
                            converted.thumbnail((1800, 1200))
                            converted.save(file_path, format="JPEG", quality=88)
                        article.local_image_paths.append(file_path)
                        downloaded += 1
                        if downloaded >= 2:
                            break
                    except (UnidentifiedImageError, OSError, ValueError) as exc:
                        self.logger.warning("图片处理失败 %s：%s", image_url, exc)
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning("图片下载失败 %s：%s", image_url, exc)
                if downloaded >= 2:
                    break
