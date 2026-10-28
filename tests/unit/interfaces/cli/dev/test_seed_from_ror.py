"""Traduction des fiches ROR en seed d'établissement."""

from interfaces.cli.dev.seed_from_ror import (
    acronym_collection_accepted,
    build_institution_seed,
    child_structure_type,
    choose_collection,
    name_forms,
    parse_organization,
)


def _record(ror_id: str, types: list[str], names: list[tuple[str, list[str]]], children=()):
    return {
        "id": f"https://ror.org/{ror_id}",
        "types": types,
        "names": [{"value": value, "types": kinds} for value, kinds in names],
        "relationships": [
            {"id": f"https://ror.org/{child}", "type": "child", "label": child}
            for child in children
        ]
        + [{"id": "https://ror.org/02feahw73", "type": "parent", "label": "CNRS"}],
    }


ROOT = parse_organization(
    _record(
        "04vfs2w97",
        ["education", "funder"],
        [("UL", ["acronym"]), ("Université de Lorraine", ["ror_display", "label"])],
        children=["02vnf0c38", "05kxdq627"],
    )
)
LAB = parse_organization(
    _record(
        "02vnf0c38",
        ["facility"],
        [
            ("LORIA", ["acronym"]),
            ("Laboratoire Lorrain de Recherche en Informatique", ["label", "ror_display"]),
            ("UMR7503", ["alias"]),
        ],
    )
)
GARDENS = parse_organization(
    _record("05kxdq627", ["archive"], [("Jardins botaniques", ["ror_display"])])
)


def _section(seed, table_name):
    return next(s for s in seed.sections if s.table.name == table_name)


def test_parse_organization_keeps_names_and_children():
    assert ROOT.ror_id == "04vfs2w97"
    assert ROOT.name == "Université de Lorraine"
    assert ROOT.acronym == "UL"
    assert ROOT.child_ids == ("02vnf0c38", "05kxdq627")


def test_child_type_follows_ror_type():
    assert child_structure_type(LAB) == "labo"
    assert child_structure_type(GARDENS) is None


def test_single_word_forms_require_word_boundary_and_context():
    forms = name_forms(LAB, context_id=1)

    assert forms["loria"] == (True, [1])
    assert forms["laboratoire lorrain de recherche en informatique"] == (False, None)
    assert forms["umr7503"] == (True, None)


def test_single_word_alias_requires_context():
    dynamic = parse_organization(
        _record(
            "01gbppd30",
            ["facility"],
            [
                ("DynAMic", ["alias"]),
                ("Dynamique des Génomes et Adaptation Microbienne", ["ror_display", "label"]),
            ],
        )
    )

    assert name_forms(dynamic, context_id=1)["dynamic"] == (True, [1])


def test_single_word_display_name_becomes_acronym():
    cran = parse_organization(
        _record(
            "022r5hc56",
            ["facility"],
            [
                ("CRAN", ["label", "ror_display"]),
                ("Centre de Recherche en Automatique de Nancy", ["alias"]),
                ("UMR 7039", ["alias"]),
            ],
        )
    )

    assert cran.name == "Centre de Recherche en Automatique de Nancy"
    assert cran.acronym == "CRAN"


def test_unit_code_is_not_a_name():
    silva = parse_organization(
        _record("01d5v2p67", ["facility"], [("Silva", ["ror_display"]), ("UMR Silva", ["alias"])])
    )

    assert silva.name == "Silva"


def test_two_letter_acronym_is_dropped():
    assert "ul" not in name_forms(ROOT, context_id=None)


def test_seed_links_children_to_root_and_skips_untyped():
    seed = build_institution_seed(ROOT, [LAB, GARDENS], ["I90183372"], "lorraine")

    structures = _section(seed, "structures").rows
    assert [(row[0], row[1], row[4]) for row in structures] == [
        (1, "ul", "universite"),
        (2, "loria", "labo"),
    ]
    assert structures[0][-1] == {"openalex": ["I90183372"]}
    assert _section(seed, "structure_parents").rows == [(1, 1, 2)]
    assert _section(seed, "perimeters").rows == [(1, "lorraine", "UL", [1])]
    assert [row[:2] for row in _section(seed, "config").rows] == [
        ("perimeter_extraction", "lorraine"),
        ("perimeter_persons", "lorraine"),
        ("site_title", ""),
    ]
    assert seed.skipped == [GARDENS]


def test_seed_carries_hal_collections_by_ror():
    seed = build_institution_seed(
        ROOT, [LAB], [], "lorraine", {"04vfs2w97": "UNIV-LORRAINE", "02vnf0c38": "LORIA"}
    )

    assert [row[7] for row in _section(seed, "structures").rows] == ["UNIV-LORRAINE", "LORIA"]


class TestChooseCollection:
    SIZES = {"LAB": 1500, "UNIV": 130_000, "UFR": 11_000}

    def test_closest_collection_wins(self):
        candidates = [("UNIV", 525), ("LAB", 525), ("UFR", 400)]

        assert choose_collection(525, candidates, self.SIZES.__getitem__) == "LAB"

    def test_collection_covering_half_the_structure_is_required(self):
        assert choose_collection(1000, [("LAB", 400)], self.SIZES.__getitem__) is None

    def test_collection_much_larger_than_the_structure_is_rejected(self):
        assert choose_collection(74, [("UFR", 57), ("UNIV", 74)], self.SIZES.__getitem__) is None


def test_acronym_collection_needs_institution_majority():
    assert acronym_collection_accepted(collection_docs=3219, institution_docs=3218)
    assert not acronym_collection_accepted(collection_docs=1602, institution_docs=87)
    assert not acronym_collection_accepted(collection_docs=0, institution_docs=0)
