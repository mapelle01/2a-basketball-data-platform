"""FASE 13 — Authentication and authorization boundary (HTTP).

The client NEVER declares its role. Identity is established here from a real
credential (API key), and the role comes from the *principal*, not from the
request body. The HTTP layer then derives the domain ``Actor`` from the
authenticated principal, so a request cannot forge ``role=admin``.

Boundary:

    HTTP ──> Authentication ──> Authorization ──> CommandGateway ──> Application

* ``AuthenticationProvider`` is the seam: swap ``ApiKeyAuthenticationProvider``
  for OAuth/SSO later without touching the API routes or the gateway.
* ``Principal`` separates identity (id) from role/permisos (role).
* Authorization is a policy over the command catalog: every command declares a
  minimum role; ``system > admin > editor``. Reads/contracts/health/ready are
  public by design (documented).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Request

from ..domain.value_objects import ROLE_LEVELS, Actor, role_meets

# Authorization policy per command. Every command is a privilege: no command is
# anonymous. Attribution-only fields in payloads (e.g. proposed_by.id) are kept
# for records; the ROLE used for any domain decision always comes from the
# authenticated principal (see the approve/propose handlers).
COMMAND_ROLES: Dict[str, str] = {
    "create_or_update_match": "editor",
    "finalize_match": "editor",
    "propose_correction": "editor",
    "approve_correction": "admin",
    "register_player_to_squad": "editor",
    "generate_standing_snapshot": "editor",
    "generate_leaderboard": "editor",
    "compute_player_rating": "editor",
    "create_publication": "admin",
    "backfill_season": "admin",
    "upsert_match_stats": "editor",
    "backfill_catalog": "admin",
}

VALID_ROLES = tuple(ROLE_LEVELS)


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. Identity (id) is independent of role."""

    id: str
    role: str

    def to_actor(self) -> Actor:
        return Actor(id=self.id, role=self.role)


def required_role(command_type: str) -> Optional[str]:
    return COMMAND_ROLES.get(command_type)


def is_authorized(command_type: str, principal: Optional[Principal]) -> bool:
    """True when ``principal`` may run ``command_type``."""
    required = required_role(command_type)
    if required is None:
        return False  # unknown command: authorization never grants it
    if principal is None:
        return False
    return role_meets(principal.role, required)


class AuthenticationProvider(ABC):
    """Establishes the caller's identity from a request. Returns None when the
    request carries no valid credentials (anonymous)."""

    @abstractmethod
    def authenticate(self, request: Request) -> Optional[Principal]:
        raise NotImplementedError


class ApiKeyAuthenticationProvider(AuthenticationProvider):
    """API-key authentication.

    Keys are configured ONLY via environment (never committed): the
    ``FEB_SCORE_API_KEYS`` variable is a list of ``key=principal_id:role``
    entries separated by ``;``, e.g.::

        FEB_SCORE_API_KEYS="svc_ingest=ingest:system;admin_1=admin-1:admin;ed_1=editor-1:editor"

    The key is accepted from ``Authorization: Bearer <key>`` (preferred) or
    ``X-API-Key: <key>``. Invalid/absent keys yield no principal (anonymous).
    """

    def __init__(self, keys: Dict[str, Principal]) -> None:
        if not keys and not isinstance(keys, dict):
            raise TypeError("keys must be a mapping key -> Principal")
        self._keys = keys

    @classmethod
    def from_env(cls, raw: Optional[str] = None) -> "ApiKeyAuthenticationProvider":
        raw = raw if raw is not None else os.environ.get("FEB_SCORE_API_KEYS", "")
        keys: Dict[str, Principal] = {}
        for entry in raw.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            if "=" not in entry:
                raise ValueError(f"invalid API key entry (expected key=id:role): {entry!r}")
            key, identity = entry.split("=", 1)
            if ":" not in identity:
                raise ValueError(f"invalid API key identity (expected id:role): {entry!r}")
            principal_id, role = identity.split(":", 1)
            if role not in ROLE_LEVELS:
                raise ValueError(f"invalid API key role {role!r}; must be one of {VALID_ROLES}")
            if not key or not principal_id:
                raise ValueError(f"empty API key or principal id in {entry!r}")
            keys[key] = Principal(id=principal_id, role=role)
        return cls(keys)

    @staticmethod
    def _extract_key(request: Request) -> Optional[str]:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return request.headers.get("x-api-key")

    def authenticate(self, request: Request) -> Optional[Principal]:
        key = self._extract_key(request)
        if not key:
            return None
        return self._keys.get(key)