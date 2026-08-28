from __future__ import annotations

import re
from typing import Optional

from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi import Body, FastAPI, Query, Request, Response

from . import errors as err
from .auth import AuthenticationProvider
from .gateway import ImageRenderingFailed, ImageRenderingUnavailable
from ..domain.errors import InvalidContentEdit, InvalidContentTransition


def register_content_routes(app: FastAPI) -> None:

    @app.get(
        "/v1/content/match-result/{match_external_id}",
        tags=["content"],
        summary="Generate match result content",
        description="Generates a structured content object for a finalized match: "
        "facts, highlights, headline, top performers and suggested channels. "
        "Returns 404 when the match does not exist or lacks a score.",
    )
    def get_match_result_content(match_external_id: str, request: Request):
        dto = request.app.state.gateway.generate_match_result_content(
            match_external_id
        )
        if dto is None:
            return err.error_response(
                404,
                "CONTENT_UNAVAILABLE",
                "match not found or has no score data for content generation",
            )
        return dto

    # -------------------------------------------------- Content Engine pipeline
    @app.post(
        "/v1/content/pipeline/rounds/{season_code}/{round_number}",
        tags=["content"],
        summary="Run the Content Engine over a finalized round",
        description="Detects stories, scores/selects the top N, generates copy, "
        "renders templates, validates facts and visuals, and queues the "
        "approved content. Authenticated (side-effectful: mutates the content "
        "queue). Returns a summary of the queued items (no rendered SVG).",
    )
    def run_content_pipeline(
        season_code: str,
        round_number: int,
        request: Request,
        body: dict = Body(default=None),
        top_n: int = Query(default=5, ge=1, le=20, description="Max stories to select"),
    ):
        auth: AuthenticationProvider = request.app.state.auth
        principal = auth.authenticate(request)
        if principal is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        # Detect-then-choose: when the caller sends story_keys (from the preview),
        # generate exactly those; otherwise fall back to the automatic top-N.
        story_keys = (body or {}).get("story_keys")
        if story_keys is not None and not isinstance(story_keys, list):
            return err.error_response(400, "INVALID_PARAMETER", "story_keys must be a list")
        try:
            return request.app.state.gateway.run_content_pipeline(
                season_code, round_number, top_n, story_keys=story_keys
            )
        except ValueError as exc:
            return err.error_response(400, "INVALID_PARAMETER", str(exc))

    @app.get(
        "/v1/content/pipeline/rounds/{season_code}/{round_number}/candidates",
        tags=["content"],
        summary="Preview the stories a round would generate",
        description="Runs detection only — no rendering, no queue writes — and "
        "returns every candidate story with a stable story_key, its family "
        "(jornada / ficha / temporada), subject and suggested priority. Feed the "
        "chosen keys back to the pipeline POST to generate exactly those. "
        "Authenticated.",
    )
    def preview_round_candidates(
        season_code: str, round_number: int, request: Request,
    ):
        if request.app.state.auth.authenticate(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        try:
            return request.app.state.gateway.preview_round_candidates(
                season_code, round_number
            )
        except ValueError as exc:
            return err.error_response(400, "INVALID_PARAMETER", str(exc))

    @app.get(
        "/v1/content/review",
        tags=["content"],
        summary="Review the content queue in a browser",
        description="A page listing the queue with a preview of every card and "
        "working approve/reject controls. Served from the same origin as the "
        "API so the browser can call it directly. The page itself is public "
        "like the other content reads; the ACTIONS still require an API key, "
        "which the page keeps only for the tab session.",
        response_class=HTMLResponse,
    )
    def content_review_page():
        return HTMLResponse(
            (Path(__file__).with_name("review_page.html")).read_text(encoding="utf-8")
        )

    @app.get(
        "/v1/content/queue",
        tags=["content"],
        summary="List content queue items",
        description="Lists queued content items, most important first. Optional "
        "status filter (detected, generating, generated, validating, approved, "
        "rejected, scheduled, published, failed).",
    )
    def list_content_queue(
        request: Request,
        status: Optional[str] = Query(default=None, description="Filter by status"),
    ):
        try:
            items = request.app.state.gateway.list_content_queue(status)
        except ValueError as exc:
            return err.error_response(400, "INVALID_PARAMETER", str(exc))
        return {"count": len(items), "items": items}

    @app.get(
        "/v1/content/items/{content_id}",
        tags=["content"],
        summary="Get a content item",
        description="Returns the content item metadata (story, copy, validation "
        "results, status). Use the /render.svg endpoint for the rendered image.",
    )
    def get_content_item(content_id: str, request: Request):
        dto = request.app.state.gateway.get_content_item(content_id)
        if dto is None:
            return err.error_response(404, "NOT_FOUND", "content item not found")
        return dto

    @app.get(
        "/v1/content/items/{content_id}/render.svg",
        tags=["content"],
        summary="Render a content item as SVG",
        description="Returns the rendered SVG for a content item "
        "(image/svg+xml). 404 if the item is unknown or was never rendered.",
        response_class=Response,
    )
    def render_content_item(content_id: str, request: Request):
        svg = request.app.state.gateway.render_content_item(content_id)
        if svg is None:
            return err.error_response(
                404, "NOT_FOUND", "content item not found or not rendered"
            )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get(
        "/v1/content/items/{content_id}/render.png",
        tags=["content"],
        summary="Render a content item as a publishable PNG",
        description="The card rasterised at Instagram post size (1080x1350 by "
        "default), served as a download. 404 if unknown or never rendered; 503 "
        "if this deployment has no rasteriser installed.",
        response_class=Response,
    )
    def render_content_item_png(
        content_id: str,
        request: Request,
        width: int = Query(default=1080, ge=270, le=2160),
        height: int = Query(default=1350, ge=270, le=2700),
    ):
        try:
            png = request.app.state.gateway.render_content_item_png(
                content_id, width, height
            )
        except ImageRenderingUnavailable as exc:
            return err.error_response(503, "RASTERIZER_UNAVAILABLE", str(exc))
        except ImageRenderingFailed as exc:
            return err.error_response(500, "RENDER_FAILED", str(exc))
        if png is None:
            return err.error_response(
                404, "NOT_FOUND", "content item not found or not rendered"
            )
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{_png_filename(request, content_id)}"'
            },
        )

    def _png_filename(request: Request, content_id: str) -> str:
        """A name worth saving: story and round, not a bare UUID. ASCII only —
        a Content-Disposition header is latin-1 on the wire."""
        item = request.app.state.gateway.get_content_item(content_id) or {}
        story = item.get("story") or {}
        parts = ["febscore"]
        if story.get("story_type"):
            parts.append(str(story["story_type"]))
        if story.get("round_number"):
            parts.append(f"j{story['round_number']}")
        parts.append(content_id[:8])
        stem = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", p).strip("-") for p in parts)
        return f"{stem}.png"

    @app.patch(
        "/v1/content/items/{content_id}",
        tags=["content"],
        summary="Edit a card's on-image title and/or Instagram caption",
        description="Hand-edits the title drawn on the card (re-rendering it) "
        "and/or the Instagram caption. Only the prose changes — the numbers on "
        "the card are untouched. Authenticated. 404 if unknown; 409 if the card "
        "is already scheduled, published or rejected; 400 if nothing to change.",
    )
    def edit_content(content_id: str, request: Request, body: dict = Body(...)):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        section_label = body.get("section_label")
        caption = body.get("caption")
        if section_label is None and caption is None:
            return err.error_response(
                400, "NOTHING_TO_EDIT",
                "provide section_label and/or caption",
            )
        # Empty strings are a real edit intent's enemy: a title cannot be blank
        # (the card would render an empty band), so reject it explicitly rather
        # than silently drawing nothing.
        if section_label is not None and not str(section_label).strip():
            return err.error_response(
                400, "INVALID_PARAMETER", "section_label cannot be blank",
            )
        try:
            dto = request.app.state.gateway.edit_content(
                content_id,
                section_label=section_label,
                caption=caption,
            )
        except InvalidContentEdit as exc:
            return err.error_response(409, "INVALID_EDIT", str(exc))
        if dto is None:
            return err.error_response(404, "NOT_FOUND", "content item not found")
        return dto

    @app.post(
        "/v1/content/queue/purge",
        tags=["content"],
        summary="Delete rejected and failed content items",
        description="Housekeeping for a queue that otherwise only grows. Only "
        "REJECTED and FAILED items are removed; anything live (pending review, "
        "approved, scheduled) or already published is never touched. "
        "Authenticated.",
    )
    def purge_content_queue(request: Request):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        return request.app.state.gateway.purge_content_queue()

    # ---------------------------------------------------- lifecycle actions
    def _authed(request: Request):
        auth: AuthenticationProvider = request.app.state.auth
        return auth.authenticate(request)

    def _lifecycle_action(request: Request, content_id: str, action, *args):
        """Shared boundary for the side-effectful lifecycle transitions:
        authenticate, run the gateway action, map 404 / illegal-transition."""
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        try:
            dto = action(content_id, *args)
        except InvalidContentTransition as exc:
            return err.error_response(409, "INVALID_TRANSITION", str(exc))
        if dto is None:
            return err.error_response(404, "NOT_FOUND", "content item not found")
        return dto

    @app.post(
        "/v1/content/items/{content_id}/review/approve",
        tags=["content"],
        summary="Approve a content item awaiting review",
        description="Moves a PENDING_REVIEW item to APPROVED. Authenticated. "
        "409 if the item is not awaiting review.",
    )
    def approve_content(content_id: str, request: Request):
        return _lifecycle_action(
            request, content_id, request.app.state.gateway.approve_content
        )

    @app.post(
        "/v1/content/items/{content_id}/review/reject",
        tags=["content"],
        summary="Reject a content item",
        description="Moves a VALIDATING/PENDING_REVIEW item to REJECTED. "
        "Authenticated. Optional JSON body {\"reason\": \"...\"}.",
    )
    def reject_content(content_id: str, request: Request, body: Optional[dict] = Body(default=None)):
        reason = (body or {}).get("reason") if isinstance(body, dict) else None
        return _lifecycle_action(
            request, content_id, request.app.state.gateway.reject_content, reason
        )

    @app.post(
        "/v1/content/items/{content_id}/schedule",
        tags=["content"],
        summary="Schedule an approved content item",
        description="Moves an APPROVED item to SCHEDULED. Authenticated. "
        "409 if the item is not approved.",
    )
    def schedule_content(content_id: str, request: Request):
        return _lifecycle_action(
            request, content_id, request.app.state.gateway.schedule_content
        )

    @app.post(
        "/v1/content/items/{content_id}/publish",
        tags=["content"],
        summary="Publish a scheduled content item",
        description="Delivers a SCHEDULED item via the configured publisher "
        "(dry-run by default) and moves it to PUBLISHED. Authenticated. "
        "409 if the item is not scheduled.",
    )
    def publish_content(content_id: str, request: Request):
        return _lifecycle_action(
            request, content_id, request.app.state.gateway.publish_content
        )
