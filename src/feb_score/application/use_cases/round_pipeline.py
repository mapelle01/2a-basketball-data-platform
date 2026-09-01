"""Round Pipeline — orchestrates the Content Engine end-to-end for one round.

Flow:
    Insight Engine → Content Planner → for each SELECTED story:
        Copy Generator → Template Renderer → Fact Validator → Visual
        Validator → Content Queue.

Domain modules stay pure; this file wires them together. Concrete
TemplateRenderer and AssetProvider implementations are injected — the
pipeline knows only the application-layer interfaces.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..content.interfaces import AssetProvider, ContentQueue, TemplateRenderer
from ...domain.content.bio import LeagueBio

from ...domain.content.copy import generate_copy
from ...domain.content.insights import MatchFactsInput, PlayerLineInput
from ...domain.content.planner import plan, score_story
from ...domain.content.queue import ContentItem, ContentStatus, InMemoryContentQueue
from ...domain.content.registry import DetectionContext, Scope, run_detectors
from ...domain.content.review import decide_review
from ...domain.content.season_aggregate import SeasonAggregate
from ...domain.content.season_insights import SeasonContext
from ...domain.content.story import StoryObject, StoryStatus, display_name_for
from ...domain.errors import InvalidContentEdit
from ...domain.content.templates import TEMPLATE_VERSION, TEMPLATES
from ...domain.content.validation import validate_copy, validate_visual


import dataclasses as _dataclasses


def _as_selected(story: StoryObject) -> StoryObject:
    """Mark a hand-picked story as SELECTED so the render loop takes it, scoring
    it for the priority field the metrics/queue expect."""
    return _dataclasses.replace(
        story, status=StoryStatus.SELECTED, priority=score_story(story).total
    )


DESIGN_SYSTEM_VERSION_DEFAULT = "1.0"


@dataclass(frozen=True)
class RunMetrics:
    """Observability for one pipeline run."""

    stories_detected: int = 0
    stories_selected: int = 0
    content_generated: int = 0      # newly queued items (excludes duplicates)
    duplicates_skipped: int = 0     # selected but already in the queue
    rejected: int = 0               # failed fact/visual validation
    pending_review: int = 0
    failed: int = 0                 # crashed during render/validate
    pending_template: int = 0       # selected but no template yet

    def to_dict(self) -> Dict[str, int]:
        return {
            "stories_detected": self.stories_detected,
            "stories_selected": self.stories_selected,
            "content_generated": self.content_generated,
            "duplicates_skipped": self.duplicates_skipped,
            "rejected": self.rejected,
            "pending_review": self.pending_review,
            "failed": self.failed,
            "pending_template": self.pending_template,
        }


@dataclass(frozen=True)
class RunResult:
    """Outcome of one pipeline run.

    * ``items``: content items newly rendered, validated and queued this run.
    * ``pending_template``: stories detected and selected but with no template
      yet (e.g. team streaks) — surfaced so their value isn't lost.
    * ``metrics``: counts for observability.
    """

    items: List[ContentItem] = field(default_factory=list)
    pending_template: List[StoryObject] = field(default_factory=list)
    metrics: RunMetrics = field(default_factory=RunMetrics)


class RoundPipeline:
    def __init__(
        self,
        renderer: TemplateRenderer,
        assets: AssetProvider,
        *,
        queue: ContentQueue | None = None,
        design_system_version: str = DESIGN_SYSTEM_VERSION_DEFAULT,
    ) -> None:
        self._renderer = renderer
        self._assets = assets
        self._queue: ContentQueue = queue or InMemoryContentQueue()
        self._design_system_version = design_system_version

    @property
    def queue(self) -> ContentQueue:
        return self._queue

    # Editing is allowed only while a card is still under the reviewer's hand;
    # once it is scheduled or out the door, or already rejected, it is frozen.
    EDITABLE_STATUSES = (ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED)

    def edit_content(
        self,
        content_id: str,
        *,
        section_label: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Optional[ContentItem]:
        """Hand-edit a queued card's on-image title and/or Instagram caption.

        The title (``section_label``) is drawn ON the card, so a change there
        re-renders the SVG; the caption is the post text and never touches the
        image, so editing it alone skips the render (and its asset fetch). A
        human edit flips ``edited`` on the item: the card then rides the curated
        path, human-verified, rather than being held to machine-generated copy.
        Numbers are untouched — only prose changes here — so the no-invention
        rule on the FACTS still holds.
        """
        import dataclasses

        item = self._queue.get(content_id)
        if item is None:
            return None
        if item.status not in self.EDITABLE_STATUSES:
            raise InvalidContentEdit(
                f"content {content_id} is {item.status.value}; only "
                f"pending-review or approved cards can be edited"
            )

        changed = False
        if section_label is not None:
            new_facts = {**item.story.facts, "section_label": section_label}
            item.story = dataclasses.replace(item.story, facts=new_facts)
            contract = TEMPLATES[item.template_id]
            data = self._build_render_data(item.story, item.copy or {}, item)
            template_file = f"{item.template_id}_v{contract.version.split('.')[0]}"
            item.rendered_svg = self._renderer.render(template_file, data)
            changed = True
        if caption is not None:
            item.copy = {**(item.copy or {}), "caption": caption}
            changed = True

        if changed:
            item.edited = True
            item.updated_at = datetime.utcnow()
            self._queue.update(item)
        return item

    def generate_one(self, story: StoryObject) -> ContentItem:
        """Render, validate and queue ONE story the caller built by hand.

        The detector path exists because the machine finds the story; this
        exists because sometimes the operator does. Everything downstream is
        identical — same copy generation, same FactValidator, same review
        policy — so a hand-made card is held to exactly the rules a detected
        one is. The only difference is who chose the framing.

        A card that fails validation is NOT queued: the operator is standing
        right there and can fix the title, whereas a detector run has nobody to
        ask and keeps the rejection as a record. The item comes back either way
        so the caller can say what went wrong.
        """
        if story.template_id is None:
            raise ValueError(f"story type {story.story_type.value} has no template")
        existing = self._queue.by_story_identity(story.identity_key)
        if existing is not None:
            return existing            # same query, same card: not a second one
        item = self._render_and_validate(_as_selected(story))
        if item.status in (ContentStatus.REJECTED, ContentStatus.FAILED):
            return item
        self._queue.add(item)
        return item

    _SCOPE_FAMILY = ((Scope.ROUND, "jornada"), (Scope.BIO, "ficha"), (Scope.SEASON, "temporada"))

    def detect_candidates(
        self,
        season_code: str,
        round_number: int,
        matches: Sequence[MatchFactsInput],
        player_lines: Sequence[PlayerLineInput],
        season_context: Optional[SeasonContext] = None,
        season: Optional[SeasonAggregate] = None,
        bio: Optional[LeagueBio] = None,
    ) -> List[Dict[str, Any]]:
        """Every story the detectors find for this round, WITHOUT rendering or
        queuing any of it — the "detect" half of detect-then-choose. Each
        candidate carries a stable ``story_key`` (its identity) that ``run`` can
        be handed back to generate exactly the chosen ones. Detection is pure, so
        the same round yields the same keys.
        """
        ctx = DetectionContext(
            season_code=season_code, round_number=round_number,
            matches=tuple(matches), player_lines=tuple(player_lines),
            season_context=season_context, season=season, bio=bio,
        )
        out: List[Dict[str, Any]] = []
        seen_keys = set()
        for scope, family in self._SCOPE_FAMILY:
            for story in run_detectors(ctx, {scope}):
                if story.template_id is None:
                    continue  # nothing can render it → not offerable
                key = story.identity_key
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({
                    "story_key": key,
                    "story_type": story.story_type.value,
                    "family": family,
                    "subject": self._subject_label(story),
                    "label": self._headline_label(story),
                    "priority": score_story(story).total,
                    "already_queued": self._queue.by_story_identity(key) is not None,
                })
        out.sort(key=lambda c: -c["priority"])
        return out

    @staticmethod
    def _subject_label(story: StoryObject) -> str:
        f = story.facts
        winner = f.get("biggest_win_winner") or {}
        return (
            f.get("player_name") or f.get("team_name")
            or f.get("top_scorer_name") or winner.get("team_name")
            or f.get("home_team_name") or "La jornada"
        )

    @staticmethod
    def _headline_label(story: StoryObject) -> str:
        f = story.facts
        if f.get("section_label"):
            return f["section_label"]
        return display_name_for(story.story_type)

    def run(
        self,
        season_code: str,
        round_number: int,
        matches: Sequence[MatchFactsInput],
        player_lines: Sequence[PlayerLineInput],
        top_n: int = 5,
        season_context: Optional[SeasonContext] = None,
        season: Optional[SeasonAggregate] = None,
        bio: Optional[LeagueBio] = None,
        only_keys: Optional[Sequence[str]] = None,
    ) -> "RunResult":
        # One call to the detector registry: every registered detector whose
        # scope has data runs and self-skips otherwise. Adding a pattern later
        # needs no change here.
        ctx = DetectionContext(
            season_code=season_code, round_number=round_number,
            matches=tuple(matches), player_lines=tuple(player_lines),
            season_context=season_context, season=season, bio=bio,
        )
        stories = run_detectors(ctx)

        if only_keys is not None:
            # Detect-then-choose: the operator already picked. Generate exactly
            # those stories — no priority cut, no per-type/subject cap; the human
            # made the selection the planner would otherwise make.
            wanted = set(only_keys)
            planned = [
                _as_selected(s) for s in stories if s.identity_key in wanted
            ]
        else:
            # Real novelty: which story types are already covered for this round?
            seen_types = self._seen_story_types(stories, season_code, round_number)
            planned = plan(stories, top_n=top_n, seen_story_types=seen_types)

        items: List[ContentItem] = []
        pending_template: List[StoryObject] = []
        duplicates = rejected = pending_review = failed = 0

        for story in planned:
            if story.status is not StoryStatus.SELECTED:
                continue
            if story.template_id is None:
                pending_template.append(story)
                continue
            # Dedup BEFORE rendering: never spend a render on a story already
            # queued (idempotent re-runs cost nothing).
            if self._queue.by_story_identity(story.identity_key) is not None:
                duplicates += 1
                continue

            item = self._render_and_validate(story)
            if not self._queue.add(item):
                duplicates += 1  # race: queued between the check and the add
                continue
            items.append(item)
            if item.status is ContentStatus.REJECTED:
                rejected += 1
            elif item.status is ContentStatus.PENDING_REVIEW:
                pending_review += 1
            elif item.status is ContentStatus.FAILED:
                failed += 1

        metrics = RunMetrics(
            stories_detected=len(stories),
            stories_selected=sum(1 for s in planned if s.status is StoryStatus.SELECTED),
            content_generated=len(items),
            duplicates_skipped=duplicates,
            rejected=rejected,
            pending_review=pending_review,
            failed=failed,
            pending_template=len(pending_template),
        )
        return RunResult(items=items, pending_template=pending_template, metrics=metrics)

    def _seen_story_types(self, stories, season_code, round_number):
        """Story types already present in the queue for this round (novelty)."""
        seen = set()
        checker = getattr(self._queue, "seen_story_type_in_round", None)
        if checker is None:
            return seen
        for story_type in {s.story_type for s in stories}:
            if checker(story_type.value, season_code, round_number):
                seen.add(story_type)
        return seen

    # ------------------------------------------------------------------

    def _render_and_validate(self, story: StoryObject) -> ContentItem:
        template_id = story.template_id
        contract = TEMPLATES[template_id]

        content = ContentItem(
            content_id=str(uuid.uuid4()),
            story=story,
            template_id=template_id,
            template_version=contract.version,
            design_system_version=self._design_system_version,
        )

        try:
            content.transition(ContentStatus.GENERATING)
            copy = generate_copy(story.to_dict())
            content.copy = copy.to_dict()
            content.transition(ContentStatus.GENERATED)

            data = self._build_render_data(story, copy.to_dict(), content)
            template_file = f"{template_id}_v{contract.version.split('.')[0]}"
            svg = self._renderer.render(template_file, data)
            content.rendered_svg = svg

            content.transition(ContentStatus.VALIDATING)
            validation_facts = {**story.facts, "round_number": story.round_number}
            fv = validate_copy(copy.to_dict(), validation_facts)
            content.fact_validation = fv.to_dict()

            vv = validate_visual(svg, contract.required_slots, data)
            content.visual_validation = vv.to_dict()

            if not (fv.ok and vv.ok):
                content.reject("failed fact/visual validation")
            else:
                # Passed validation → the review policy decides whether a human
                # must sign off before this can be scheduled/published.
                decision = decide_review(story)
                if decision.requires_review:
                    content.submit_for_review(decision.reason)
                else:
                    content.review_reason = decision.reason
                    content.approve()

        except Exception as exc:  # noqa: BLE001 - pipeline must never crash a round
            content.fail(f"{type(exc).__name__}: {exc}")

        return content

    def _build_render_data(
        self,
        story: StoryObject,
        copy: Dict[str, Any],
        content: ContentItem,
    ) -> Dict[str, Any]:
        assets: Dict[str, Any] = {}
        display: Dict[str, Any] = {}
        f = story.facts

        if story.template_id == "match_final":
            home_id = f.get("home_team_external_id", "")
            away_id = f.get("away_team_external_id", "")
            display = {
                # Graceful fallback: catalog name OR the real external_id. Never
                # blank, never invented (external_id is a genuine data platform id).
                "home_team": f.get("home_team_name") or home_id,
                "away_team": f.get("away_team_name") or away_id,
            }
            assets = {
                "home_team_color": self._assets.team_color(home_id),
                "home_team_initials": self._assets.team_logo(home_id).payload,
                "away_team_color": self._assets.team_color(away_id),
                "away_team_initials": self._assets.team_logo(away_id).payload,
            }

        if story.template_id == "player_of_round":
            player_id = f.get("player_external_id", "")
            team_id = f.get("team_external_id", "")
            display = {
                "player": f.get("player_name") or player_id,
                "team": f.get("team_name") or team_id,
            }
            # The provider decides what it can resolve: an official photo comes
            # back as a data URI, otherwise the statistical fallback returns
            # initials. Templates take whichever slot is filled.
            photo = self._assets.player_photo(player_id)
            assets = {"team_color": self._assets.team_color(team_id)}
            if photo.payload_type == "data_uri":
                assets["player_photo"] = photo.payload
                assets["player_initials"] = None
            else:
                assets["player_initials"] = photo.payload

        if story.template_id == "stat_hero":
            # Photo-less hero: the number is the protagonist; the crest is the
            # identity echo (keyed to a silhouette by the template).
            team_id = f.get("team_external_id", "")
            display = {
                "player": f.get("player_name") or f.get("player_external_id", ""),
                "team": f.get("team_name") or team_id,
            }
            crest = self._assets.team_logo(team_id)
            assets = {"team_crest": crest.payload} if crest.payload_type == "data_uri" else {}

        if story.template_id in ("best_five", "best_five_court"):
            # Resolve a photo + crest for each of the five, injected into the
            # render data only (the persisted facts stay pure). Missing images
            # fall back to initials per member.
            enriched = []
            for row in f.get("lineup", []):
                r = dict(row)
                photo = self._assets.player_photo(r.get("player_external_id", ""))
                if photo.payload_type == "data_uri":
                    r["photo_uri"] = photo.payload
                crest = self._assets.team_logo(r.get("team_external_id", ""))
                if crest.payload_type == "data_uri":
                    r["badge_uri"] = crest.payload
                enriched.append(r)
            story_dict = story.to_dict()
            story_dict["facts"]["lineup"] = enriched
            return {
                "story": story_dict, "copy": copy, "assets": {}, "display": {},
                "meta": {
                    "content_id": content.content_id,
                    "template_version": content.template_version,
                    "design_system_version": content.design_system_version,
                },
            }

        return {
            "story": story.to_dict(),
            "copy": copy,
            "assets": assets,
            "display": display,
            "meta": {
                "content_id": content.content_id,
                "template_version": content.template_version,
                "design_system_version": content.design_system_version,
            },
        }
