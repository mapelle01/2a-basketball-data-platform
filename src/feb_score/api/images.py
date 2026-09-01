"""Image gallery + operator overrides.

Card imagery defaults to the official FEB URLs. When FEB has no image, or a poor
one, an operator can upload a replacement here; it is stored in the database
(the container filesystem is wiped on every deploy) and the render path picks it
up ahead of FEB.

Routes:
  GET    /v1/images/gallery                     the browser gallery (public read)
  GET    /v1/images/catalog?season=...          players+teams with image status
  GET    /v1/images/{kind}/{external_id}        serve an override's bytes (404 if none)
  PUT    /v1/images/{kind}/{external_id}        upload/replace an override (auth)
  DELETE /v1/images/{kind}/{external_id}        remove an override (auth)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse

from . import errors as err
from .auth import AuthenticationProvider

VALID_KINDS = ("player", "team")
# A portrait/crest is ~10-25 KB; the ceiling leaves room for a large PNG while
# refusing anything that is plainly not an avatar.
MAX_UPLOAD_BYTES = 512 * 1024
ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")


def register_image_routes(app: FastAPI) -> None:

    def _authed(request: Request):
        auth: AuthenticationProvider = request.app.state.auth
        return auth.authenticate(request)

    @app.get(
        "/v1/images/gallery",
        tags=["images"],
        summary="Browse and replace player/team imagery",
        description="A page showing every player and team of a season with its "
        "current image, and an upload control to replace one. Reads are public; "
        "uploads require the API key (kept only for the tab session).",
        response_class=HTMLResponse,
    )
    def image_gallery_page():
        return HTMLResponse(
            (Path(__file__).with_name("images_gallery.html")).read_text(encoding="utf-8")
        )

    @app.get(
        "/v1/images/catalog",
        tags=["images"],
        summary="List a season's players and teams with image status",
        description="For each player and team with stats in the season: name, "
        "the FEB image URL, and whether an operator override exists.",
    )
    def image_catalog(
        request: Request,
        season: str = Query(..., description="Season code, e.g. 2024-2025"),
    ):
        return request.app.state.gateway.list_image_catalog(season)

    @app.get(
        "/v1/images/{kind}/{external_id}",
        tags=["images"],
        summary="Serve an operator image override",
        description="Returns the override's bytes for this player/team, or 404 "
        "if none exists (the caller should then use the FEB URL).",
        response_class=Response,
    )
    def get_image_override(kind: str, external_id: str, request: Request):
        if kind not in VALID_KINDS:
            return err.error_response(400, "INVALID_PARAMETER", "kind must be player or team")
        ov = request.app.state.gateway.get_image_override(kind, external_id)
        if ov is None:
            return err.error_response(404, "NOT_FOUND", "no override for this entity")
        return Response(
            content=ov["image"],
            media_type=ov["content_type"],
            headers={"Cache-Control": "no-cache"},
        )

    @app.put(
        "/v1/images/{kind}/{external_id}",
        tags=["images"],
        summary="Upload or replace an image override",
        description="Body is the raw image (Content-Type image/jpeg, image/png "
        "or image/webp), up to 512 KiB. Authenticated. The next render of any "
        "card featuring this player/team uses it.",
    )
    async def put_image_override(kind: str, external_id: str, request: Request):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if kind not in VALID_KINDS:
            return err.error_response(400, "INVALID_PARAMETER", "kind must be player or team")
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_TYPES:
            return err.error_response(
                415, "UNSUPPORTED_MEDIA_TYPE",
                f"content type must be one of {', '.join(ALLOWED_TYPES)}",
            )
        raw = await request.body()
        if not raw:
            return err.error_response(400, "INVALID_PARAMETER", "empty image body")
        if len(raw) > MAX_UPLOAD_BYTES:
            return err.error_response(
                413, "PAYLOAD_TOO_LARGE",
                f"image exceeds {MAX_UPLOAD_BYTES // 1024} KiB",
            )
        return request.app.state.gateway.put_image_override(
            kind, external_id, raw, content_type
        )

    @app.delete(
        "/v1/images/{kind}/{external_id}",
        tags=["images"],
        summary="Remove an image override",
        description="Deletes the override so the entity reverts to its FEB image "
        "(or initials). Authenticated. 404 if there was no override.",
    )
    def delete_image_override(kind: str, external_id: str, request: Request):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if kind not in VALID_KINDS:
            return err.error_response(400, "INVALID_PARAMETER", "kind must be player or team")
        removed = request.app.state.gateway.delete_image_override(kind, external_id)
        if not removed:
            return err.error_response(404, "NOT_FOUND", "no override to remove")
        return {"removed": True, "kind": kind, "external_id": external_id}

    # ------------------------------------------------- media library (multi-photo)
    #
    # The media library holds MANY photos per entity with rights metadata; the
    # renderer picks the primary approved one at generate time. Legacy override
    # endpoints above stay live so nothing already deployed breaks; new work
    # goes here.

    @app.get(
        "/v1/media/{kind}/{external_id}",
        tags=["media"],
        summary="List all photos held for one entity",
        description="Metadata only, newest first — no bytes. Public read.",
    )
    def list_media(kind: str, external_id: str, request: Request):
        if kind not in VALID_KINDS:
            return err.error_response(400, "INVALID_PARAMETER", "kind must be player or team")
        return {"kind": kind, "external_id": external_id,
                "assets": request.app.state.gateway.list_media_assets(kind, external_id)}

    @app.get(
        "/v1/media/asset/{asset_id}/image",
        tags=["media"],
        summary="Serve the bytes of one media asset",
        response_class=Response,
    )
    def get_media_image(asset_id: str, request: Request):
        img = request.app.state.gateway.get_media_image(asset_id)
        if img is None:
            return err.error_response(404, "NOT_FOUND", "no asset with that id")
        return Response(
            content=img["image"], media_type=img["content_type"],
            headers={"Cache-Control": "public, max-age=600"},
        )

    @app.post(
        "/v1/media/{kind}/{external_id}",
        tags=["media"],
        summary="Upload a new photo into the media library",
        status_code=201,
        description="Raw image body (Content-Type image/jpeg, image/png or "
        "image/webp), up to 512 KiB. Metadata (photographer, source, license, "
        "notes) travels as query parameters so a plain PUT works. The new asset "
        "lands as 'alternate' and un-approved unless the entity has no photos "
        "yet — then it starts as primary so the entity is not left empty.",
    )
    async def upload_media(
        kind: str, external_id: str, request: Request,
        approved: bool = Query(False),
        source: str = Query(""),
        source_url: str = Query(""),
        photographer: str = Query(""),
        license_type: str = Query(""),
        commercial_use: bool = Query(False),
        notes: str = Query(""),
    ):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if kind not in VALID_KINDS:
            return err.error_response(400, "INVALID_PARAMETER", "kind must be player or team")
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_TYPES:
            return err.error_response(
                415, "UNSUPPORTED_MEDIA_TYPE",
                f"content type must be one of {', '.join(ALLOWED_TYPES)}",
            )
        raw = await request.body()
        if not raw:
            return err.error_response(400, "INVALID_PARAMETER", "empty image body")
        if len(raw) > MAX_UPLOAD_BYTES:
            return err.error_response(
                413, "PAYLOAD_TOO_LARGE",
                f"image exceeds {MAX_UPLOAD_BYTES // 1024} KiB",
            )
        return request.app.state.gateway.add_media_asset(
            kind, external_id, raw, content_type,
            approved=approved,
            source=source or None, source_url=source_url or None,
            photographer=photographer or None,
            license_type=license_type or None,
            commercial_use=commercial_use,
            notes=notes or None,
        )

    @app.post(
        "/v1/media/asset/{asset_id}/promote",
        tags=["media"],
        summary="Make this asset the primary photo for its entity",
        description="Demotes whichever asset was primary. Authenticated.",
    )
    def promote_media(asset_id: str, request: Request):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not request.app.state.gateway.promote_media_primary(asset_id):
            return err.error_response(404, "NOT_FOUND", "no asset with that id")
        return {"asset_id": asset_id, "role": "primary"}

    @app.post(
        "/v1/media/asset/{asset_id}/approve",
        tags=["media"],
        summary="Approve (or un-approve) a media asset for use",
        description="Only approved assets are ever picked by the renderer.",
    )
    def approve_media(asset_id: str, request: Request, approved: bool = Query(True)):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not request.app.state.gateway.set_media_approved(asset_id, approved):
            return err.error_response(404, "NOT_FOUND", "no asset with that id")
        return {"asset_id": asset_id, "approved": approved}

    @app.delete(
        "/v1/media/asset/{asset_id}",
        tags=["media"],
        summary="Delete a media asset permanently",
    )
    def delete_media(asset_id: str, request: Request):
        if _authed(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not request.app.state.gateway.delete_media_asset(asset_id):
            return err.error_response(404, "NOT_FOUND", "no asset with that id")
        return {"removed": True, "asset_id": asset_id}
