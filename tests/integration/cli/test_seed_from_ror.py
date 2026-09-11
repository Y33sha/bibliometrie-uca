"""Le seed produit à partir de fiches ROR se charge dans le schéma : ses lignes respectent les contraintes des tables."""

from pathlib import Path

from sqlalchemy import text

from interfaces.cli.dev.generate_seed import INSTITUTION_SEED, render_seed
from interfaces.cli.dev.seed_from_ror import build_institution_seed, parse_organization


def _record(ror_id: str, types: list[str], names: list[tuple[str, list[str]]], children=()):
    return {
        "id": f"https://ror.org/{ror_id}",
        "types": types,
        "names": [{"value": value, "types": kinds} for value, kinds in names],
        "relationships": [
            {"id": f"https://ror.org/{child}", "type": "child", "label": child}
            for child in children
        ],
    }


def test_seed_loads_into_schema(sa_sync_conn):
    root = parse_organization(
        _record(
            "04vfs2w97",
            ["education"],
            [("UL", ["acronym"]), ("Université de Lorraine", ["ror_display"])],
            children=["02vnf0c38", "022r5hc56"],
        )
    )
    children = [
        parse_organization(
            _record("02vnf0c38", ["facility"], [("LORIA", ["acronym"]), ("Loria", ["ror_display"])])
        ),
        # Nom court : la forme exige une frontière de mot, que la table impose.
        parse_organization(_record("022r5hc56", ["facility"], [("CRAN", ["ror_display"])])),
    ]
    seed = build_institution_seed(root, children, ["I90183372"], "lorraine")
    sql = render_seed(INSTITUTION_SEED.description, Path("seed.sql"), seed.sections)

    # La transaction du test encadre le chargement : le seed s'y joue sans ses propres bornes.
    body = sql.replace("BEGIN;", "").replace("COMMIT;", "")
    sa_sync_conn.exec_driver_sql(body)

    structures = sa_sync_conn.execute(text("SELECT code FROM structures ORDER BY id")).scalars()
    assert list(structures) == ["ul", "loria", "cran"]
    forms = sa_sync_conn.execute(
        text("SELECT form_text, is_word_boundary, requires_context_of FROM structure_name_forms")
    ).all()
    assert ("cran", True, None) in forms
    assert ("loria", True, [1]) in forms
