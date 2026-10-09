from unittest.mock import MagicMock

from application.services.structures.ror import import_ror_dump
from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType

UNIV, LABO = RorId("01a8ajp46"), RorId("03vgfxd91")


def _org(ror_id, *, children=()):
    return RorOrganization(
        ror_id=ror_id,
        name="Organisation",
        country_code="fr",
        types=frozenset({RorType.EDUCATION}),
        status=RorStatus.ACTIVE,
        parent_ids=frozenset(),
        child_ids=frozenset(children),
    )


def test_ecrit_les_organisations_et_leurs_relations_puis_commite():
    conn, repo = MagicMock(), MagicMock()
    orgs = [_org(UNIV, children=[LABO]), _org(LABO)]

    stats = import_ror_dump(conn, iter(orgs), version="v2.14", repo=repo)

    repo.replace_all.assert_called_once_with(orgs, frozenset({(UNIV, LABO)}), version="v2.14")
    conn.commit.assert_called_once()
    assert (stats.organizations, stats.relations) == (2, 1)
