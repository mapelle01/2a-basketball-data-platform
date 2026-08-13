from uuid import uuid4

import pytest

from feb_score.domain.competition.model import Competition, RoundDefinition
from feb_score.domain.value_objects import CompetitionId, ExternalId, SeasonCode


def test_define_season_and_rounds():
    competition = Competition(
        external_id=ExternalId("comp-123"),
        competition_id=CompetitionId(str(uuid4())),
        name="FEB League",
    )

    season = competition.define_season(SeasonCode("2025-2026"), rules_version="rules-v1")
    assert season.season_code.value == "2025-2026"
    assert competition.get_season(SeasonCode("2025-2026")) is season

    round_1 = RoundDefinition(number=1, label="Round 1")
    season.add_round(round_1)
    assert season.rounds[0] is round_1

    with pytest.raises(ValueError):
        competition.define_season(SeasonCode("2025-2026"), rules_version="rules-v1")

    with pytest.raises(ValueError):
        RoundDefinition(number=0, label="Bad Round")

    with pytest.raises(ValueError):
        RoundDefinition(number=1, label="")

    with pytest.raises(ValueError):
        season.add_round(RoundDefinition(number=1, label="Round 1 duplicate"))
