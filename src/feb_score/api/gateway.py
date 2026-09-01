"""HTTP API boundary (FASE 11).

The ``CommandGateway`` is the ONLY surface the HTTP layer touches. It abstracts
the CommandRunner + Application handlers + repository wiring behind a narrow,
SQLite-free, aggregate-free contract.

The API package imports NOTHING from concrete persistence (no repositories, no
SQLite, no aggregates): errors raised through the gateway use the shared error
taxonomy (``ContractValidationError``, ``DomainError``, ``StaleVersionError``,
``InfrastructureError``) so the HTTP layer can map them without knowing the
implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ImageRenderingUnavailable(Exception):
    """This deployment cannot rasterise cards (no rasteriser installed).

    Defined on the PORT, not in the rendering module: the HTTP layer has to map
    the failure to a status code, and it may not import concrete infrastructure
    to do so. The adapter translates its own error into this one.
    """


class ImageRenderingFailed(Exception):
    """The rasteriser ran and refused the card."""


@dataclass(frozen=True)
class EventRef:
    """Lightweight, stable reference to a produced event (never the full event)."""

    event_id: str
    event_type: str


@dataclass(frozen=True)
class CommandResult:
    """The command was accepted and executed. Events are references only; their
    persistence/dispatch is the Application's responsibility (outbox semantics)."""

    command_id: str
    events: List[EventRef] = field(default_factory=list)


@dataclass(frozen=True)
class Readiness:
    ready: bool
    checks: Dict[str, str] = field(default_factory=dict)


class CommandGateway(ABC):
    @abstractmethod
    def run(
        self,
        command_type: str,
        *,
        command_id: str,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> CommandResult:
        """Execute a command. Raises (contract/domain/infrastructure) on failure."""
        raise NotImplementedError

    # Read side: minimal projections for verification (no business logic).
    @abstractmethod
    def get_match(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_player(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_competition(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_leaderboard(self, leaderboard_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_correction_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    # FASE 23.5 — season analytics reads (list DTOs, empty list when no data).
    # Metric validation raises ValueError (mapped to 400 by the HTTP layer).
    @abstractmethod
    def list_season_player_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_player_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_player_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # ------------------------------------------------------------ FASE 24
    # Match & player exploration reads (HTTP -> gateway -> ExplorationService).
    # A None result means the referenced entity does not exist (HTTP 404);
    # season filters never 404 on their own (they are filters, not resources).
    @abstractmethod
    def get_match_detail(self, external_id: str) -> Optional[Dict[str, Any]]:
        """A match plus its boxscore projection (team/player stats)."""
        raise NotImplementedError

    @abstractmethod
    def get_player_profile(
        self, season_code: str, player_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team_profile(
        self, season_code: str, team_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_players(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_teams(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_matches(
        self,
        season_code: str,
        *,
        competition_id: Optional[str] = None,
        round_number: Optional[int] = None,
        team_external_id: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_power_ranking(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_player_form_index(
        self, season_code: str, player_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team_form_index(
        self, season_code: str, team_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def system_status(self) -> Dict[str, Any]:
        """Operational metrics: entity counts, data freshness, pending events."""
        raise NotImplementedError

    @abstractmethod
    def readiness(self) -> Readiness:
        """Non-destructive dependency check (database reachable + schema version)."""
        raise NotImplementedError

    @abstractmethod
    def generate_match_result_content(
        self, match_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    # ------------------------------------------------ Content Engine pipeline
    @abstractmethod
    def preview_round_candidates(
        self, season_code: str, round_number: int
    ) -> Dict[str, Any]:
        """Detect every story for a round WITHOUT rendering or queuing — the
        list an operator picks from. Each candidate carries a stable
        ``story_key`` that ``run_content_pipeline`` accepts back."""
        raise NotImplementedError

    @abstractmethod
    def run_content_pipeline(
        self, season_code: str, round_number: int, top_n: int = 5,
        story_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run the Content Engine over a finalized round; returns a summary of
        the queued content items (no rendered SVG in the summary). When
        ``story_keys`` is given, generate exactly those candidates (from the
        preview) instead of the automatic top-N selection."""
        raise NotImplementedError

    @abstractmethod
    def list_content_queue(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_content_item(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def render_content_item(self, content_id: str) -> Optional[str]:
        """Return the rendered SVG string for a content item, or None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def render_content_item_png(
        self, content_id: str, width: int, height: int
    ) -> Optional[bytes]:
        """The publishable image: the card rasterised at post size, or None if
        the item is unknown. Raises ImageRenderingUnavailable when this
        deployment has no rasteriser, ImageRenderingFailed when it refuses."""
        raise NotImplementedError

    @abstractmethod
    def list_seasons(self) -> List[Dict[str, Any]]:
        """Seasons present in the database, newest first, each with its match
        count — the source for the season dropdowns in the operator pages."""
        raise NotImplementedError

    # ----------------------------------------------------------- explorer
    @abstractmethod
    def season_insights(self, season_code: str) -> Dict[str, Any]:
        """Discovery signals for a season: single-game records, double-double
        leaders and who is trending up. Read-only."""
        raise NotImplementedError

    @abstractmethod
    def explore_players(
        self, season_code: str, *,
        team: Optional[str] = None, nationality: Optional[str] = None,
        position: Optional[str] = None, min_age: Optional[int] = None,
        max_age: Optional[int] = None, min_games: Optional[int] = None,
        metric: str = "points", per_game: bool = False, limit: int = 25,
    ) -> Dict[str, Any]:
        """Free-form search over a season's players, for hunting content.
        Read-only. Raises ValueError on an unknown metric."""
        raise NotImplementedError

    @abstractmethod
    def generate_round_recap(self, season_code: str, round_number: int) -> Dict[str, Any]:
        """Generate the round-recap card for a round (detect -> run just that
        candidate). Raises ValueError when the round has no recap."""
        raise NotImplementedError

    # ---------------------------------------------------------- media library
    @abstractmethod
    def list_media_assets(self, kind: str, external_id: str) -> List[Dict[str, Any]]:
        """All photos held for that entity, newest first. Meta only, no bytes."""
        raise NotImplementedError

    @abstractmethod
    def get_media_image(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """The bytes + content-type for one asset, or None."""
        raise NotImplementedError

    @abstractmethod
    def add_media_asset(
        self, kind: str, external_id: str, image: bytes, content_type: str, *,
        approved: bool = False, source: Optional[str] = None,
        source_url: Optional[str] = None, photographer: Optional[str] = None,
        license_type: Optional[str] = None, commercial_use: bool = False,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a photo to the media library. New assets land as 'alternate' and
        un-approved by default — the operator promotes/approves them explicitly
        so nothing goes live without a review step."""
        raise NotImplementedError

    @abstractmethod
    def promote_media_primary(self, asset_id: str) -> bool:
        """Make this asset the primary one for its entity, demoting the previous
        primary. Returns False when the asset does not exist."""
        raise NotImplementedError

    @abstractmethod
    def set_media_approved(self, asset_id: str, approved: bool) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_media_asset(self, asset_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_stat_hero(
        self, season_code: str, *, player_id: str, metric: str = "points",
        per_game: bool = False, title: str, subtitle: Optional[str] = None,
        scope_label: Optional[str] = None, hero_style: str = "crest",
        hero_kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One player rendered as a single hero card, from a query. Two visual
        variants share the same facts: ``crest`` (photo-less, crest silhouette)
        and ``photo`` (player photo centrepiece). ``hero_kind`` picks the
        number: ``average`` (season / games), ``total`` (season aggregate),
        or ``peak`` (single-game max). Figures re-read server-side; raises
        ValueError on bad input. Returns the item."""
        raise NotImplementedError

    @abstractmethod
    def create_custom_five(
        self, season_code: str, *, title: str, subtitle: str = "",
        scope_label: Optional[str] = None, player_ids: Optional[List[str]] = None,
        show_rank: bool = True, **query: Any
    ) -> Dict[str, Any]:
        """Turn an explorer query into a queued card. The caller supplies the
        query and the wording, never the figures — those are re-read from the
        same source the explorer used. Returns the content item. Raises
        ValueError on an empty result or an unusable title."""
        raise NotImplementedError

    # ------------------------------------------------------------ imagery
    @abstractmethod
    def list_image_catalog(self, season_code: str) -> Dict[str, Any]:
        """Players and teams of a season with their image status: name, the FEB
        URL, and whether an operator override exists."""
        raise NotImplementedError

    @abstractmethod
    def get_image_override(
        self, kind: str, external_id: str
    ) -> Optional[Dict[str, Any]]:
        """An operator override's bytes + content type, or None if there is
        none. ``kind`` is 'player' or 'team'."""
        raise NotImplementedError

    @abstractmethod
    def put_image_override(
        self, kind: str, external_id: str, image: bytes, content_type: str
    ) -> Dict[str, Any]:
        """Store (or replace) an override. Returns its metadata."""
        raise NotImplementedError

    @abstractmethod
    def delete_image_override(self, kind: str, external_id: str) -> bool:
        """Remove an override (revert to FEB). True if one was removed."""
        raise NotImplementedError

    @abstractmethod
    def edit_content(
        self,
        content_id: str,
        *,
        section_label: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Hand-edit a card's on-image title and/or Instagram caption. Returns
        the updated item, or None if unknown. Raises when the card is not in an
        editable state."""
        raise NotImplementedError

    # ----------------------------------------------- content lifecycle actions
    # Each returns the updated item dict, or None if the content_id is unknown.
    # Illegal transitions raise a DomainError the HTTP layer maps to 409.
    @abstractmethod
    def approve_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def reject_content(self, content_id: str, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def schedule_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def publish_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError