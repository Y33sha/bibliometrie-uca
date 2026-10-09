import pytest

from domain.errors import ValidationError
from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType, ror_relations

UNIV, LABO, AUTRE, ABSENTE = (
    RorId(r) for r in ("01a8ajp46", "03vgfxd91", "02feahw73", "04kdfz702")
)


def _org(ror_id, *, parents=(), children=(), country="fr"):
    return RorOrganization(
        ror_id=ror_id,
        name="Organisation",
        country_code=country,
        types=frozenset({RorType.FACILITY}),
        status=RorStatus.ACTIVE,
        parent_ids=frozenset(parents),
        child_ids=frozenset(children),
    )


class TestRorOrganization:
    @pytest.mark.parametrize("country", ["FR", "fra", ""])
    def test_refuse_un_code_pays_hors_iso_minuscules(self, country):
        with pytest.raises(ValidationError, match="Code pays"):
            _org(UNIV, country=country)

    def test_refuse_un_nom_vide(self):
        with pytest.raises(ValidationError, match="sans nom"):
            RorOrganization(
                ror_id=UNIV,
                name="",
                country_code="fr",
                types=frozenset(),
                status=RorStatus.ACTIVE,
                parent_ids=frozenset(),
                child_ids=frozenset(),
            )


class TestRorRelations:
    def test_unit_les_declarations_des_deux_cotes(self):
        orgs = [_org(UNIV, children=[LABO]), _org(LABO, parents=[AUTRE]), _org(AUTRE)]
        assert ror_relations(orgs) == {(UNIV, LABO), (AUTRE, LABO)}

    def test_ecarte_les_organisations_absentes_de_la_liste(self):
        assert ror_relations([_org(LABO, parents=[ABSENTE])]) == frozenset()

    def test_ecarte_l_auto_reference(self):
        assert ror_relations([_org(UNIV, parents=[UNIV])]) == frozenset()
