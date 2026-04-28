from __future__ import annotations

from pathlib import Path


def write_source_stats(output_path: Path, metadata: dict, source_stats: list[dict]) -> Path:
    lines: list[str] = []
    lines.append("每日AI资讯抓取统计")
    lines.append(f"生成时间：{metadata['generated_at']}")
    lines.append(f"候选资讯总数：{metadata['candidate_count']}")
    lines.append(f"正文资讯总数：{metadata['article_count']}")
    lines.append("")
    lines.append("分站点统计：")
    lines.append("站点 | 启用 | 权重 | 计划抓取 | 抓取数 | 筛后数 | 去重后数 | 最终入选数 | 状态 | 备注")
    lines.append("-" * 100)

    for item in source_stats:
        lines.append(
            " | ".join(
                [
                    str(item.get("name", "")),
                    "是" if item.get("enabled", True) else "否",
                    f"{item.get('weight', 0):.2f}",
                    str(item.get("requested_limit", 0)),
                    str(item.get("fetched_count", 0)),
                    str(item.get("filtered_count", 0)),
                    str(item.get("deduplicated_count", 0)),
                    str(item.get("selected_count", 0)),
                    str(item.get("status", "")),
                    str(item.get("message", "")),
                ]
            )
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
