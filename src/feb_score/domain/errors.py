from __future__ import annotations

from dataclasses import dataclass

from .common import DomainError


class InvalidMatchStateTransition(DomainError):
    pass


class InvalidScore(DomainError):
    pass


class MatchAlreadyFinalized(DomainError):
    pass


class UnknownPlayer(DomainError):
    pass


class InvalidPlayerRegistration(DomainError):
    pass


class InvalidCorrection(DomainError):
    pass


class UnauthorizedCorrection(DomainError):
    pass


class MissingMatchData(DomainError):
    pass


class InvalidStandingSnapshot(DomainError):
    pass


class InvalidLeaderboardCategory(DomainError):
    pass


class InvalidRatingCalculation(DomainError):
    pass


class InvalidPublication(DomainError):
    pass


class MatchNotFound(DomainError):
    pass


class EntityNotFound(DomainError):
    pass


class ContentGenerationError(DomainError):
    pass


class InvalidContentTransition(DomainError):
    pass


class InvalidContentEdit(DomainError):
    pass
