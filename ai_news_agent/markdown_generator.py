from __future__ import annotations

from pathlib import Path

from .models import Article, SectionBundle


class MarkdownReportGenerator:
    def __init__(self, config: dict, logger) -> None:
        self.config = config
        self.logger = logger

    def generate(self, output_path: Path, sections: list[SectionBundle], metadata: dict) -> Path:
        lines: list[str] = []
        lines.append(f"# {self.config['document'].get('title', '每日AI资讯摘编')}")
        lines.append("")
        lines.append(f"- 生成时间：{metadata['generated_at']}")
        lines.append(f"- 候选资讯：{metadata['candidate_count']} 条")
        lines.append(f"- 正文资讯：{metadata['article_count']} 条")
        lines.append(f"- 摘要模式：{metadata['llm_mode']}")
        lines.append("")

        for section in sections:
            lines.append(f"## {section.label}")
            lines.append("")
            if not section.articles:
                lines.append("本模块当日未筛选到高置信度资讯。")
                lines.append("")
                continue
            for idx, article in enumerate(section.articles, start=1):
                lines.extend(self._article_lines(idx, article))
                lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def _article_lines(self, idx: int, article: Article) -> list[str]:
        published_label = (
            article.published_at.strftime("%Y-%m-%d %H:%M")
            if article.published_at
            else str(article.metadata.get("published_text") or "未知")
        )
        lines = [f"### {idx}. {article.display_title}"]
        lines.append(f"- 来源：{article.source_name}")
        lines.append(f"- 发布时间：{published_label}")
        quality_score = article.metadata.get("quality_score")
        if quality_score is not None:
            lines.append(f"- 质量评分：{quality_score}")
        lines.append(f"- 摘要：{article.summary}")
        for point_idx, point in enumerate(article.key_points[:3], start=1):
            lines.append(f"- 要点{point_idx}：{point}")
        lines.append(f"- 原文链接：{article.url}")
        return lines
