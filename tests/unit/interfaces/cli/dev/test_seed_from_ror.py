"""Traduction des fiches ROR en seed d'établissement."""

from interfaces.cli.dev.seed_from_ror import (
    build_institution_seed,
    child_structure_type,
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


def test_acronyms_require_word_boundary_and_context():
    forms = name_forms(LAB, context_id=1)

    assert forms["loria"] == (True, [1])
    assert forms["laboratoire lorrain de recherche en informatique"] == (False, None)
    assert forms["umr7503"] == (False, None)


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
    assert _section(seed, "structure_tutelles").rows == [(1, 1, 2)]
    assert _section(seed, "perimeters").rows == [(1, "lorraine", "UL", [1])]
    assert [row[:2] for row in _section(seed, "config").rows] == [
        ("perimeter_extraction", "lorraine")
    ]
    assert seed.skipped == [GARDENS]
