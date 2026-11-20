"""Framework-agnostic API routing shared by Azure Functions (function_app.py) and the local dev server.

GET   /api/minicodes                 ?tags=&contentType=&level=&presenter=&language=&from=&to=&top=&skip=&sort=
GET   /api/minicodes/{id}            detail + chapters (timestamps)
GET   /api/search                    ?q=&tags=&presenter=&from=&to=... facets + grouped chunk hits with timestamps
GET   /api/taxonomy                  tag ids + labels for the filter UI
GET   /api/manage/minicodes/{id}      admin view (LLM output, overrides, audit)
PATCH /api/manage/minicodes/{id}      title/tag/summary corrections (override LLM values; null reverts)
POST  /api/manage/enrich              {"force": bool, "ids": [...]} enrich + index
POST  /api/manage/reindex             rebuild search documents from the catalogue
Admin routes use the `manage/` prefix: Azure Functions reserves routes starting with `admin`.
Multi-valued filters accept repeated parameters or comma-separated values (OR within, AND across).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from minicode.api.auth import AuthError, Principal
from minicode.enrichment.repository import PatchError, apply_patch, validate_patch
from minicode.search.backend import Filters, IndexNotFound
from minicode.taxonomy import load_taxonomy

log = logging.getLogger(__name__)
MAX_TOP = 100
JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}


@dataclass
class ApiRequest:
    method: str
    path: str  # e.g. "/api/minicodes/abc"
    params: Mapping[str, list[str]] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def one(self, name: str, default: str | None = None) -> str | None:
        values = self.params.get(name) or []
        return values[0] if values and values[0] != "" else default

    def many(self, *names: str) -> list[str]:
        out: list[str] = []
        for name in names:
            for v in self.params.get(name) or []:
                out.extend(x.strip() for x in v.split(",") if x.strip())
        return list(dict.fromkeys(out))

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except json.JSONDecodeError as e:
            raise BadRequest(f"invalid JSON body: {e.msg}") from e


@dataclass
class ApiResponse:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=lambda: dict(JSON_HEADERS))

    def json_bytes(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False, default=str).encode("utf-8")


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


def error(status: int, message: str, **extra: Any) -> ApiResponse:
    return ApiResponse(status, {"error": message, **extra})


def parse_filters(req: ApiRequest, include_hidden: bool = False) -> Filters:
    taxonomy = load_taxonomy()
    tags = req.many("tags", "topics")
    unknown = [t for t in tags if t not in taxonomy.topic.tag_ids()]
    if unknown:
        raise BadRequest(f"unknown tags: {', '.join(unknown)}")
    content_types = req.many("contentType", "type")
    if bad := [c for c in content_types if c not in taxonomy.content_type.tag_ids()]:
        raise BadRequest(f"unknown contentType: {', '.join(bad)}")
    try:
        levels = [int(v) for v in req.many("level")]
        return Filters(
            topics=tags, content_types=content_types, levels=levels, presenters=req.many("presenter"),
            languages=req.many("language"), date_from=req.one("from"), date_to=req.one("to"), include_hidden=include_hidden,
        )
    except ValueError as e:
        raise BadRequest("level must be an integer and from/to must be YYYY-MM-DD") from e


def paging(req: ApiRequest, default_top: int) -> tuple[int, int]:
    try:
        top, skip = int(req.one("top", str(default_top))), int(req.one("skip", "0"))
    except ValueError as e:
        raise BadRequest("top and skip must be integers") from e
    if not 1 <= top <= MAX_TOP or skip < 0:
        raise BadRequest(f"top must be 1-{MAX_TOP} and skip >= 0")
    return top, skip


Handler = Callable[[ApiRequest, Principal, dict[str, str]], ApiResponse]


class Api:
    """`components` is a minicode.settings.Components (or a test double with the same attributes)."""

    def __init__(self, components: Any) -> None:
        self.c = components
        self.routes: list[tuple[str, re.Pattern[str], bool, Handler]] = []
        for method, pattern, admin, handler in (
            ("GET", r"minicodes", False, self.list_minicodes),
            ("GET", r"minicodes/(?P<id>[^/]+)", False, self.get_minicode),
            ("GET", r"search", False, self.search),
            ("GET", r"taxonomy", False, self.taxonomy),
            ("GET", r"manage/minicodes/(?P<id>[^/]+)", True, self.admin_get),
            ("PATCH", r"manage/minicodes/(?P<id>[^/]+)", True, self.admin_patch),
            ("POST", r"manage/enrich", True, self.admin_enrich),
            ("POST", r"manage/reindex", True, self.admin_reindex),
        ):
            self.routes.append((method, re.compile(rf"^/?(?:api/)?{pattern}/?$"), admin, handler))

    def handle(self, req: ApiRequest) -> ApiResponse:
        path = req.path.split("?", 1)[0]
        matched = [(m, rx.match(path), admin, h) for m, rx, admin, h in self.routes if rx.match(path)]
        if not matched:
            return error(404, "not found")
        route = next((r for r in matched if r[0] == req.method.upper()), None)
        if route is None:
            resp = error(405, "method not allowed")
            resp.headers["Allow"] = ", ".join(sorted({r[0] for r in matched}))
            return resp
        _, match, admin, handler = route
        try:
            principal = self.c.authenticator.require(req.headers, admin=admin)
            return handler(req, principal, match.groupdict())  # type: ignore[union-attr]
        except AuthError as e:
            resp = error(e.status, e.message)
            if e.status == 401:
                resp.headers["WWW-Authenticate"] = e.www_authenticate
            return resp
        except BadRequest as e:
            return error(400, str(e))
        except PatchError as e:
            return error(400, str(e))
        except NotFound as e:
            return error(404, str(e) or "not found")
        except IndexNotFound:
            return error(503, "search index not built yet - run enrichment/indexing (POST /api/manage/enrich)")
        except Exception:  # noqa: BLE001 - never leak internals
            log.exception("unhandled API error on %s %s", req.method, path)
            return error(500, "internal error")

    # --- read endpoints -------------------------------------------------------------------------

    def list_minicodes(self, req: ApiRequest, p: Principal, _: dict[str, str]) -> ApiResponse:
        top, skip = paging(req, 20)
        try:
            body = self.c.search_service.list_minicodes(parse_filters(req), top, skip, req.one("sort", "date") or "date")
        except ValueError as e:
            raise BadRequest(str(e)) from e
        return ApiResponse(200, body)

    def get_minicode(self, req: ApiRequest, p: Principal, args: dict[str, str]) -> ApiResponse:
        view = self.c.search_service.get_minicode(args["id"], admin=False)
        if view is None:
            raise NotFound(f"minicode {args['id']} not found")
        return ApiResponse(200, view)

    def search(self, req: ApiRequest, p: Principal, _: dict[str, str]) -> ApiResponse:
        q = req.one("q", "") or ""
        if len(q) > 300:
            raise BadRequest("q must be at most 300 characters")
        top, skip = paging(req, 10)
        return ApiResponse(200, self.c.search_service.search(q, parse_filters(req), top, skip))

    def taxonomy(self, req: ApiRequest, p: Principal, _: dict[str, str]) -> ApiResponse:
        t = load_taxonomy()
        body = {dim: [{"id": tag.id, "label": tag.label} for tag in getattr(t, dim).tags]
                for dim in ("topic", "content_type", "level")}
        return ApiResponse(200, {**body, "version": t.version})

    # --- admin endpoints ------------------------------------------------------------------------

    def admin_get(self, req: ApiRequest, p: Principal, args: dict[str, str]) -> ApiResponse:
        view = self.c.search_service.get_minicode(args["id"], admin=True)
        if view is None:
            raise NotFound(f"minicode {args['id']} not found")
        return ApiResponse(200, view)

    def admin_patch(self, req: ApiRequest, p: Principal, args: dict[str, str]) -> ApiResponse:
        doc = self.c.repository.get(args["id"])
        if doc is None or doc.get("status") == "deleted":
            raise NotFound(f"minicode {args['id']} not found")
        patch = validate_patch(req.json())
        entry = apply_patch(doc, patch, user=p.display)
        self.c.repository.upsert(doc)
        self.c.repository.add_audit(entry)
        try:
            self.c.indexer.update_metadata(doc["id"])
        except KeyError:  # index not created yet (nothing indexed); next reindex picks the change up
            log.warning("search index missing while patching %s", doc["id"])
        return ApiResponse(200, self.c.search_service.get_minicode(doc["id"], admin=True))

    def admin_enrich(self, req: ApiRequest, p: Principal, _: dict[str, str]) -> ApiResponse:
        body = req.json() or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        ids = body.get("ids")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
            raise BadRequest("ids must be a list of strings")
        summary = self.c.enrichment_pipeline.run(force=bool(body.get("force")), only=ids)
        indexed = self.c.indexer.sync(summary.changed, summary.deleted)
        return ApiResponse(200, {"enrichment": summary.to_dict(), "index": indexed})

    def admin_reindex(self, req: ApiRequest, p: Principal, _: dict[str, str]) -> ApiResponse:
        return ApiResponse(200, {"index": self.c.indexer.sync()})
