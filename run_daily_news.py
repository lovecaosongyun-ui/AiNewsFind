from __future__ import annotations

import argparse

from dotenv import load_dotenv

from ai_news_agent.config import load_config, merge_overrides
from ai_news_agent.pipeline import DailyNewsPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成每日 AI 资讯 docx 日报。")
    parser.add_argument("--config", type=str, default=None, help="自定义配置文件路径。")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 Qwen API，使用规则摘要。")
    parser.add_argument("--max-items-per-section", type=int, default=None, help="每个模块最多保留的资讯数量。")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    config = load_config(args.config)

    overrides = {}
    if args.skip_llm:
        overrides.setdefault("llm", {})["enabled"] = False
    if args.max_items_per_section is not None:
        overrides.setdefault("runtime", {})["max_items_per_section"] = args.max_items_per_section

    config = merge_overrides(config, overrides)
    pipeline = DailyNewsPipeline(config)
    result = pipeline.run()

    print(f"日报已生成：{result.output_path}")
    if result.markdown_path:
        print(f"Markdown 已生成：{result.markdown_path}")
    if result.stats_path:
        print(f"统计 TXT 已生成：{result.stats_path}")
    print(f"正文资讯数：{result.article_count}")
    print(f"日志文件：{result.log_path}")


if __name__ == "__main__":
    main()
