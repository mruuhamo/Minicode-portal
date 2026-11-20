"""Azure Functions entry point (Python v2 programming model).

Search API (Entra JWT validated in code; see minicode/api/routes.py for parameters):
* GET   /api/minicodes, /api/minicodes/{id}, /api/search, /api/taxonomy      Learning.Read scope / any signed-in user
* GET   /api/manage/minicodes/{id}, PATCH /api/manage/minicodes/{id}         Learning.Admin app role
* POST  /api/manage/enrich, /api/manage/reindex                              Learning.Admin app role
  (`manage/` not `admin/`: the Functions host reserves routes whose first segment is `admin`.)

Operations:
* GET  /api/health                                    anonymous liveness probe
* POST /api/manage/ingest?mode=backfill|incremental   manual ingestion run (function key)  &days=N &force=true
* timer `ingest_timer` (BACKFILL_SCHEDULE, default hourly): incremental ingest -> enrich changed -> index

Functions never block on Speech: submitted jobs are polled by the next run (manifest state).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from functools import cache

import azure.functions as func

from minicode.api.routes import Api, ApiRequest
from minicode.ingestion.config import Settings, build_pipeline
from minicode.ingestion.pipeline import PipelineConfig, RunSummary
from minicode.settings import AppSettings, Components

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
log = logging.getLogger("minicode.functions")


@cache
def _components() -> Components:
    return Components(AppSettings.from_env())


@cache
def _api() -> Api:
    return Api(_components())


def _run(mode: str, days: int | None = None, force: bool = False) -> RunSummary:
    settings = Settings.from_env()
    if days:
        settings.lookback_days = days
    pipeline = build_pipeline(settings, config=PipelineConfig(force=force))
    if mode == "backfill":
        return pipeline.run_backfill(since=datetime.now(UTC) - timedelta(days=settings.lookback_days))
    return pipeline.run_incremental()


def _to_api_request(req: func.HttpRequest) -> ApiRequest:
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(req.url)
    params = parse_qs(parts.query, keep_blank_values=True) or {k: [v] for k, v in req.params.items()}
    return ApiRequest(req.method, parts.path, params, dict(req.headers.items()), req.get_body() or b"")


def _dispatch(req: func.HttpRequest) -> func.HttpResponse:
    resp = _api().handle(_to_api_request(req))
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-type"}
    return func.HttpResponse(resp.json_bytes(), status_code=resp.status, headers=headers, mimetype="application/json",
                             charset="utf-8")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json")


# Search API: anonymous at the host level, the Entra bearer token is validated by the router.
@app.route(route="minicodes", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_minicodes(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="minicodes/{id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_minicode(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="search", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def search(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="taxonomy", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def taxonomy(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="manage/minicodes/{id}", methods=["GET", "PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
def manage_minicode(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="manage/enrich", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def manage_enrich(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="manage/reindex", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def manage_reindex(req: func.HttpRequest) -> func.HttpResponse:
    return _dispatch(req)


@app.route(route="manage/ingest", methods=["POST"])
def ingest(req: func.HttpRequest) -> func.HttpResponse:
    mode = req.params.get("mode", "incremental")
    if mode not in ("backfill", "incremental"):
        error = {"error": "mode must be backfill or incremental"}
        return func.HttpResponse(json.dumps(error), status_code=400, mimetype="application/json")
    try:
        days = int(req.params["days"]) if req.params.get("days") else None
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "days must be an integer"}), status_code=400, mimetype="application/json")
    summary = _run(mode, days=days, force=req.params.get("force", "").lower() == "true")
    body = {k: v for k, v in summary.to_dict().items() if k != "items"}
    return func.HttpResponse(json.dumps(body, default=str), status_code=200, mimetype="application/json")


def enrich_and_index() -> dict:
    c = _components()
    summary = c.enrichment_pipeline.run()
    index = c.indexer.sync(summary.changed, summary.deleted)
    return {"enrichment": dict(summary.counts), "index": index, "errors": len(summary.errors)}


@app.timer_trigger(schedule="%BACKFILL_SCHEDULE%", arg_name="timer", run_on_startup=False, use_monitor=True)
def ingest_timer(timer: func.TimerRequest) -> None:
    if os.environ.get("INGESTION_ENABLED", "true").lower() != "true":
        log.info("ingestion disabled (INGESTION_ENABLED != true)")
        return
    summary = _run("incremental")
    log.info("ingestion %s: %s errors=%d", summary.mode, dict(summary.outcomes), len(summary.errors))
    if os.environ.get("ENRICHMENT_ENABLED", "true").lower() == "true":
        log.info("enrichment: %s", enrich_and_index())
