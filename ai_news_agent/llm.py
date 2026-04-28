from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .filters import build_fallback_summary, extract_finance_info, extract_paper_info, infer_category, score_article
from .models import Article
from .utils import extract_json_objects, trim_text

try:
    import dashscope
except ImportError:  # pragma: no cover
    dashscope = None


VALID_CATEGORIES = {
    "ai_application",
    "ai_model",
    "ai_safety",
    "ai_investment",
    "research_paper",
}


class NewsAnalyzer:
    def __init__(self, config: dict[str, Any], logger, progress_callback=None) -> None:
        self.config = config
        self.logger = logger
        self.progress_callback = progress_callback
        llm_config = config.get("llm", {})
        self.enabled = bool(llm_config.get("enabled", True))
        self.model = llm_config.get("model", "qwen-turbo-latest")
        self.api_key_env = llm_config.get("api_key_env", "DASHSCOPE_API_KEY")
        self.temperature = llm_config.get("temperature", 0.2)
        self.top_p = llm_config.get("top_p", 0.8)
        self.max_workers = llm_config.get("max_workers", 4)
        self.filtering = config.get("filtering", {})
        summary_cfg = config.get("summary", {})
        quality_cfg = config.get("quality", {})
        self.summary_min_chars = int(summary_cfg.get("min_chars", 100))
        self.summary_max_chars = int(summary_cfg.get("max_chars", 300))
        self.min_quality_score = int(quality_cfg.get("min_score", 68))
        self._api_key = os.getenv(self.api_key_env, "")
        self._llm_available = self.enabled and bool(self._api_key) and dashscope is not None

    @property
    def llm_available(self) -> bool:
        return self._llm_available

    def analyze_articles(self, articles: list[Article]) -> list[Article]:
        if not articles:
            return []

        if not self._llm_available:
            self.logger.info("未检测到可用的 Qwen API，切换到规则摘要模式。")
            fallback_results: list[Article] = []
            total = max(len(articles), 1)
            for index, article in enumerate(articles, start=1):
                fallback_results.append(self._apply_fallback(article))
                self._report_progress(index, total, f"规则模式摘要处理中（{index}/{total}）...")
            return fallback_results

        results: list[Article] = []
        total = max(len(articles), 1)
        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(self._analyze_single, article): article for article in articles}
            for future in as_completed(future_map):
                article = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("Qwen 分析失败，已回退到规则模式：%s | %s", article.url, exc)
                    results.append(self._apply_fallback(article))
                completed += 1
                self._report_progress(completed, total, f"Qwen 摘要与翻译处理中（{completed}/{total}）...")
        return results

    def _analyze_single(self, article: Article) -> Article:
        system_prompt = (
            "你是一名用于政府内部晨报的AI产业资讯分析助手。"
            "请基于给定资讯，输出严格的 JSON 对象，不要输出任何解释、markdown 或代码块。"
        )
        user_prompt = f"""
请阅读以下资讯，并用中文输出 JSON，字段必须完整：
{{
  "title_zh": "中文标题，若原标题已是中文可保持不变",
  "category": "只能是 ai_application / ai_model / ai_safety / ai_investment / research_paper 之一",
  "importance_score": 0-100 的整数，
  "quality_score": 0-100 的整数，
  "quality_reason": "一句中文说明，解释资讯是否值得进入日报",
  "summary": "{self.summary_min_chars}-{self.summary_max_chars}字中文摘要，适合内部简报，英文内容必须转成中文表述",
  "key_points": ["2-4条中文要点"],
  "tags": ["最多4个标签"],
  "finance_info": {{
    "company": "",
    "round": "",
    "amount": "",
    "investors": "",
    "business": ""
  }},
  "paper_info": {{
    "venue": "",
    "institution": "",
    "takeaway": ""
  }}
}}

资讯标题：{article.title}
来源：{article.source_name}
发布时间：{article.published_at.isoformat() if article.published_at else "未知"}
正文摘要：{trim_text(article.snippet, 500)}
正文内容：{trim_text(article.body_text, 4000)}
"""

        response = dashscope.Generation.call(
            api_key=self._api_key,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            result_format="message",
            temperature=self.temperature,
            top_p=self.top_p,
        )

        content = self._extract_message_content(response)
        payloads = extract_json_objects(content)
        payload = payloads[0] if payloads else {}
        if not payload:
            raise ValueError(f"无法解析 Qwen 返回内容：{content[:200]}")

        article.title_zh = trim_text(payload.get("title_zh") or article.title, 80)
        if article.forced_category in VALID_CATEGORIES:
            article.category = article.forced_category
        else:
            category = str(payload.get("category", "")).strip()
            article.category = category if category in VALID_CATEGORIES else infer_category(article, self.filtering)
        fallback_summary, fallback_points = build_fallback_summary(
            article,
            min_chars=self.summary_min_chars,
            max_chars=self.summary_max_chars,
        )
        article.summary = trim_text(payload.get("summary") or fallback_summary, self.summary_max_chars + 20)
        article.key_points = self._normalize_list(payload.get("key_points")) or fallback_points
        article.tags = self._normalize_list(payload.get("tags"), max_items=4)
        article.finance_info = self._normalize_mapping(payload.get("finance_info"))
        article.paper_info = self._normalize_mapping(payload.get("paper_info"))
        article.metadata["quality_reason"] = trim_text(str(payload.get("quality_reason", "")).strip(), 100)

        raw_score = payload.get("importance_score", 0)
        try:
            article.importance_score = max(0.0, min(float(raw_score), 100.0))
        except (TypeError, ValueError):
            article.importance_score = score_article(article, self.filtering)

        try:
            quality_score = max(0, min(int(payload.get("quality_score", 0)), 100))
        except (TypeError, ValueError):
            quality_score = self._fallback_quality_score(article)
        article.metadata["quality_score"] = quality_score

        if article.category == "ai_investment" and not any(article.finance_info.values()):
            article.finance_info = extract_finance_info(article)
        if article.category == "research_paper" and not any(article.paper_info.values()):
            article.paper_info = extract_paper_info(article)
        return article

    def _apply_fallback(self, article: Article) -> Article:
        summary, key_points = build_fallback_summary(
            article,
            min_chars=self.summary_min_chars,
            max_chars=self.summary_max_chars,
        )
        article.title_zh = article.title if article.locale.startswith("zh") else ""
        article.summary = summary
        article.key_points = key_points
        article.category = infer_category(article, self.filtering)
        article.importance_score = score_article(article, self.filtering)
        article.metadata["quality_score"] = self._fallback_quality_score(article)
        article.metadata["quality_reason"] = "规则模式下按正文长度、时效性和关键词命中进行质量估计。"
        if article.category == "ai_investment":
            article.finance_info = extract_finance_info(article)
        if article.category == "research_paper":
            article.paper_info = extract_paper_info(article)
        return article

    def _extract_message_content(self, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, dict):
            return (
                response.get("output", {})
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        if hasattr(response, "output"):
            choices = getattr(response.output, "choices", [])
            if choices:
                message = getattr(choices[0], "message", None)
                if message is not None:
                    content = getattr(message, "content", "")
                    if isinstance(content, list):
                        return "".join(
                            str(item.get("text", "")) if isinstance(item, dict) else str(item)
                            for item in content
                        )
                    return str(content)
        return str(response)

    def _normalize_list(self, value: Any, max_items: int = 4) -> list[str]:
        if isinstance(value, list):
            return [trim_text(str(item).strip(), 60) for item in value if str(item).strip()][:max_items]
        return []

    def _normalize_mapping(self, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): trim_text(str(item).strip(), 60) for key, item in value.items() if str(item).strip()}

    def _fallback_quality_score(self, article: Article) -> int:
        score = 40
        if len(article.body_text) >= 500:
            score += 18
        elif len(article.body_text) >= 250:
            score += 10
        if article.published_at:
            score += 12
        if article.source_weight >= 1.2:
            score += 10
        elif article.source_weight >= 1.1:
            score += 6
        if len(article.title) >= 16:
            score += 4
        if article.category in {"ai_model", "ai_safety", "research_paper"}:
            score += 6
        return min(score, 100)

    def _report_progress(self, completed: int, total: int, message: str) -> None:
        if not self.progress_callback:
            return
        progress = 58 + int((completed / max(total, 1)) * 16)
        self.progress_callback(
            {
                "progress": progress,
                "stage": "analyzing",
                "message": message,
                "details": {"completed_articles": completed, "total_articles": total},
            }
        )
