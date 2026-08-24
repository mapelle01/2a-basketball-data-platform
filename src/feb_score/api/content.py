from __future__ import annotations

from typing import Optional

from fastapi import Body, FastAPI, Query, Request, Response

from . import errors as err
from .auth import AuthenticationProvider
from ..domain.errors import InvalidContentTransition


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
        top_n: int = Query(default=5, ge=1, le=20, description="Max stories to select"),
    ):
        auth: AuthenticationProvider = request.app.state.auth
        principal = auth.authenticate(request)
        if principal is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        try:
            return request.app.state.gateway.run_content_pipeline(
                season_code, round_number, top_n
            )
        except ValueError as exc:
            return err.error_response(400, "INVALID_PARAMETER", str(exc))

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
