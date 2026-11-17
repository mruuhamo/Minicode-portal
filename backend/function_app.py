"""Azure Functions entry point (Python v2 programming model).

* GET  /api/health                                   anonymous liveness probe
* POST /api/admin/ingest?mode=backfill|incremental   manual run (function key; Entra check in week 4)
       optional: &days=N  &force=true
* timer `ingest_timer` (BACKFILL_SCHEDULE, default hourly)  incremental sync: Graph delta, poll Speech jobs

Functions never block on Speech: submitted jobs are polled by the next run (manifest state).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta

import azure.functions as func

from minicode.ingestion.config import Settings, build_pipeline
from minicode.ingestion.pipeline import PipelineConfig, RunSummary

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
log = logging.getLogger("minicode.functions")


def _run(mode: str, days: int | None = None, force: bool = False) -> RunSummary:
    settings = Settings.from_env()
    if days:
        settings.lookback_days = days
    pipeline = build_pipeline(settings, config=PipelineConfig(force=force))
    if mode == "backfill":
        return pipeline.run_backfill(since=datetime.now(UTC) - timedelta(days=settings.lookback_days))
    return pipeline.run_incremental()


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json")


@app.route(route="admin/ingest", methods=["POST"])
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


@app.timer_trigger(schedule="%BACKFILL_SCHEDULE%", arg_name="timer", run_on_startup=False, use_monitor=True)
def ingest_timer(timer: func.TimerRequest) -> None:
    if os.environ.get("INGESTION_ENABLED", "true").lower() != "true":
        log.info("ingestion disabled (INGESTION_ENABLED != true)")
        return
    summary = _run("incremental")
    log.info("ingestion %s: %s errors=%d", summary.mode, dict(summary.outcomes), len(summary.errors))
