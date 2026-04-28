from __future__ import annotations

import json
import threading
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from ai_news_agent.config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    load_config,
    load_web_config,
    merge_overrides,
    save_web_config,
)
from ai_news_agent.pipeline import DailyNewsPipeline


load_dotenv()

WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"
ASSET_VERSION = max(
    int((STATIC_DIR / "app.js").stat().st_mtime),
    int((STATIC_DIR / "styles.css").stat().st_mtime),
    int((TEMPLATES_DIR / "index.html").stat().st_mtime),
)

app = FastAPI(title="每日AI资讯智能体控制台")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
JOB_STORE: dict[str, dict[str, Any]] = {}
JOB_LOCK = threading.Lock()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    config = _public_config(load_web_config())
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "initial_config_json": json.dumps(config, ensure_ascii=False),
            "saved_config_path": str(_relative_to_project(PROJECT_ROOT / "config" / "saved_web_config.yaml")),
            "asset_version": ASSET_VERSION,
        },
    )


@app.get("/api/config/default")
async def get_default_config() -> JSONResponse:
    return JSONResponse({"config": _public_config(load_config(DEFAULT_CONFIG_PATH))})


@app.get("/api/config/current")
async def get_current_config() -> JSONResponse:
    return JSONResponse({"config": _public_config(load_web_config())})


@app.post("/api/config/save")
async def save_config_endpoint(payload: dict[str, Any]) -> JSONResponse:
    config = _normalize_payload(payload)
    saved_path = save_web_config(config)
    return JSONResponse(
        {
            "message": "配置已保存。",
            "saved_path": str(_relative_to_project(saved_path)),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config": _public_config(config),
        }
    )


@app.post("/api/generate")
async def generate_report(payload: dict[str, Any]) -> JSONResponse:
    config = _normalize_payload(payload)
    job_id = uuid4().hex
    with JOB_LOCK:
        JOB_STORE[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "message": "任务已创建，等待执行。",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": None,
            "error": "",
            "details": {},
        }

    worker = threading.Thread(target=_run_generate_job, args=(job_id, config), daemon=True)
    worker.start()
    return JSONResponse({"job_id": job_id, "status": "queued", "message": "日报生成任务已启动。"})


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str) -> JSONResponse:
    with JOB_LOCK:
        job = deepcopy(JOB_STORE.get(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return JSONResponse(job)


@app.get("/download")
async def download_file(path: str) -> FileResponse:
    requested = (PROJECT_ROOT / path).resolve()
    _ensure_allowed_path(requested)
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="文件不存在。")
    return FileResponse(path=str(requested), filename=requested.name)


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    cloned = json.loads(json.dumps(config, ensure_ascii=False))
    cloned.pop("_config_path", None)
    cloned.pop("_project_root", None)
    return cloned


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base_config = load_config(DEFAULT_CONFIG_PATH)
    base_sources = base_config.get("sources", [])
    cleaned = _public_config(payload)
    cleaned["runtime"] = cleaned.get("runtime", {})
    cleaned["summary"] = cleaned.get("summary", {})
    cleaned["quality"] = cleaned.get("quality", {})
    cleaned["document"] = cleaned.get("document", {})
    cleaned["llm"] = cleaned.get("llm", {})

    runtime = cleaned["runtime"]
    runtime["article_limit_per_source"] = int(runtime.get("article_limit_per_source", 10) or 10)
    runtime["max_articles_for_analysis"] = int(runtime.get("max_articles_for_analysis", 40) or 40)
    runtime["min_items_for_section_analysis"] = int(runtime.get("min_items_for_section_analysis", 2) or 2)
    runtime["max_items_per_section"] = int(runtime.get("max_items_per_section", 5) or 5)
    runtime["recent_hours"] = int(runtime.get("recent_hours", 168) or 168)
    runtime["start_date"] = runtime.get("start_date") or None
    runtime["end_date"] = runtime.get("end_date") or None

    summary = cleaned["summary"]
    summary["min_chars"] = int(summary.get("min_chars", 100) or 100)
    summary["max_chars"] = max(int(summary.get("max_chars", 300) or 300), summary["min_chars"])

    quality = cleaned["quality"]
    quality["min_score"] = int(quality.get("min_score", 68) or 68)

    llm = cleaned["llm"]
    llm["enabled"] = bool(llm.get("enabled", True))

    def source_value(source: dict[str, Any], base_source: dict[str, Any], key: str, default: Any = None) -> Any:
        if key in source:
            return source.get(key)
        if key in base_source:
            return base_source.get(key)
        return default

    normalized_sources: list[dict[str, Any]] = []
    for source in cleaned.get("sources", []):
        name = str(source.get("name", "")).strip()
        url = str(source.get("url", "")).strip()
        if not name or not url:
            continue
        base_source = next(
            (item for item in base_sources if item.get("name") == name or item.get("url") == url),
            {},
        )
        normalized_sources.append(
            {
                "name": name,
                "region": str(source_value(source, base_source, "region", "custom") or "custom"),
                "enabled": bool(source_value(source, base_source, "enabled", True)),
                "kind": str(source_value(source, base_source, "kind", "html") or "html"),
                "homepage_url": str(source_value(source, base_source, "homepage_url", url) or url).strip(),
                "url": url,
                "locale": str(source_value(source, base_source, "locale", "zh") or "zh"),
                "source_weight": float(source_value(source, base_source, "source_weight", 1.0) or 1.0),
                "max_items": int(source_value(source, base_source, "max_items", runtime["article_limit_per_source"]) or runtime["article_limit_per_source"]),
                "inherit_runtime_limit": bool(source_value(source, base_source, "inherit_runtime_limit", True)),
                "assume_relevant": bool(source_value(source, base_source, "assume_relevant", False)),
                "forced_category": str(source_value(source, base_source, "forced_category", "") or "").strip() or None,
                "skip_hydration": bool(source_value(source, base_source, "skip_hydration", False)),
                "prefer_listing_title": bool(source_value(source, base_source, "prefer_listing_title", False)),
                "same_domain_only": bool(source_value(source, base_source, "same_domain_only", False)),
                "external_only": bool(source_value(source, base_source, "external_only", False)),
                "listing_selectors": _normalize_string_list(source_value(source, base_source, "listing_selectors", [])),
                "include_patterns": _normalize_string_list(source_value(source, base_source, "include_patterns", [])),
                "exclude_patterns": _normalize_string_list(source_value(source, base_source, "exclude_patterns", [])),
                "article_selectors": _normalize_string_list(source_value(source, base_source, "article_selectors", [])),
                "image_selectors": _normalize_string_list(source_value(source, base_source, "image_selectors", [])),
                "date_selectors": _normalize_string_list(source_value(source, base_source, "date_selectors", [])),
                "required_entry_tags": _normalize_string_list(source_value(source, base_source, "required_entry_tags", [])),
                "required_entry_keywords": _normalize_string_list(source_value(source, base_source, "required_entry_keywords", [])),
            }
        )

    cleaned["sources"] = normalized_sources
    return merge_overrides(base_config, cleaned)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    return []


def _ensure_allowed_path(path: Path) -> None:
    allowed_roots = [
        (PROJECT_ROOT / "output").resolve(),
        (PROJECT_ROOT / "logs").resolve(),
        (PROJECT_ROOT / "config").resolve(),
    ]
    if not any(root == path or root in path.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="不允许访问该文件。")


def _download_link(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"/download?path={_relative_to_project(path).as_posix()}"


def _relative_to_project(path: Path) -> Path:
    return path.resolve().relative_to(PROJECT_ROOT.resolve())


def _run_generate_job(job_id: str, config: dict[str, Any]) -> None:
    def progress_callback(payload: dict[str, Any]) -> None:
        _update_job(
            job_id,
            status="running",
            progress=payload.get("progress", 0),
            stage=payload.get("stage", "running"),
            message=payload.get("message", ""),
            details=payload.get("details", {}),
        )

    try:
        _update_job(job_id, status="running", progress=2, stage="initializing", message="正在准备生成任务...")
        pipeline = DailyNewsPipeline(config, progress_callback=progress_callback)
        result = pipeline.run()
        result_payload = {
            "message": "日报生成完成。",
            "generated_at": result.finished_at.strftime("%Y-%m-%d %H:%M:%S"),
            "article_count": result.article_count,
            "candidate_count": result.candidate_count,
            "llm_used": result.llm_used,
            "config_summary": {
                "recent_hours": int(config.get("runtime", {}).get("recent_hours", 168)),
                "global_limit": int(config.get("runtime", {}).get("article_limit_per_source", 10)),
                "max_items_per_section": int(config.get("runtime", {}).get("max_items_per_section", 5)),
                "max_articles_for_analysis": int(config.get("runtime", {}).get("max_articles_for_analysis", 40)),
                "min_items_for_section_analysis": int(config.get("runtime", {}).get("min_items_for_section_analysis", 2)),
                "quality_min_score": int(config.get("quality", {}).get("min_score", 68)),
                "summary_min_chars": int(config.get("summary", {}).get("min_chars", 100)),
                "summary_max_chars": int(config.get("summary", {}).get("max_chars", 300)),
                "start_date": config.get("runtime", {}).get("start_date"),
                "end_date": config.get("runtime", {}).get("end_date"),
            },
            "files": {
                "docx": _download_link(result.output_path),
                "markdown": _download_link(result.markdown_path) if result.markdown_path else None,
                "stats": _download_link(result.stats_path) if result.stats_path else None,
                "log": _download_link(result.log_path),
            },
            "paths": {
                "docx": str(_relative_to_project(result.output_path)),
                "markdown": str(_relative_to_project(result.markdown_path)) if result.markdown_path else "",
                "stats": str(_relative_to_project(result.stats_path)) if result.stats_path else "",
                "log": str(_relative_to_project(result.log_path)),
            },
            "source_stats": result.source_stats,
        }
        _update_job(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            message="日报生成完成。",
            result=result_payload,
        )
    except Exception as exc:  # noqa: BLE001
        _update_job(
            job_id,
            status="failed",
            progress=100,
            stage="failed",
            message="日报生成失败，请查看日志或重试。",
            error=f"{exc}\n{traceback.format_exc()}",
        )


def _update_job(job_id: str, **updates: Any) -> None:
    with JOB_LOCK:
        job = JOB_STORE.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
