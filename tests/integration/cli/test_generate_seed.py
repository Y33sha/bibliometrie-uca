"""Smoke test de `generate_seed` : le script parcourt chaque table de référence sans buter sur une colonne ou une table périmée.

pyrefly et ruff ignorent les identifiants SQL des chaînes `text()` : ce test détecte un renommage de schéma qui casse le script.
"""

import json
from pathlib import Path

from sqlalchemy import text

from domain.config import INITIAL_CONFIG_VALUES, LABORATORY_TYPES_KEY
from infrastructure.db import tables
from interfaces.cli.dev.generate_seed import (
    COMMON_SEED,
    INSTITUTION_SEED,
    SeedSection,
    generate_seed,
    render_seed,
)
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.config import set_config
from tests.integration.helpers.structures import insert_perimeter, insert_structure


def test_generate_seed_walks_every_table(sa_sync_conn, tmp_path):
    # Une ligne dans `perimeters` exerce la sérialisation d'un array integer[] et le recalage de séquence.
    insert_perimeter(sa_sync_conn, "smoke", root_structure_ids=[1, 2], name="Smoke")
    common = tmp_path / "common.sql"
    institution = tmp_path / "institution.sql"

    # Chaque table déclenche un `SELECT <colonnes> FROM <table>` : une colonne périmée lèverait ici.
    generate_seed(sa_sync_conn, COMMON_SEED, common)
    generate_seed(sa_sync_conn, INSTITUTION_SEED, institution)

    for out in (common, institution):
        content = out.read_text(encoding="utf-8")
        assert content.startswith("-- Seed généré")
        assert "BEGIN;" in content
        assert "COMMIT;" in content
    content = institution.read_text(encoding="utf-8")
    assert "INSERT INTO perimeters (id, code, name, root_structure_ids)" in content
    assert "'{1, 2}'" in content


def test_generate_seed_exports_structure_api_ids(sa_sync_conn, tmp_path):
    # Les extractions OpenAlex, WoS, ScanR et theses.fr lisent l'institution dans `api_ids` : une base montée depuis le seed doit les contenir.
    insert_structure(
        sa_sync_conn,
        "smoke",
        name="Smoke",
        structure_type="universite",
        api_ids={"openalex": ["I1"]},
    )
    out = tmp_path / "seed.sql"

    generate_seed(sa_sync_conn, INSTITUTION_SEED, out)

    content = out.read_text(encoding="utf-8")
    assert "hal_collection, api_ids) VALUES" in content
    assert """'{"openalex": ["I1"]}'""" in content


def test_generate_seed_splits_config_keys(sa_sync_conn, tmp_path):
    # Les clés de périmètre désignent des périmètres de l'établissement : elles suivent son seed, les autres clés vont au seed commun.
    set_config(sa_sync_conn, "perimeter_persons", "smoke")
    set_config(sa_sync_conn, "unpaywall_max_per_run", 5)
    common = tmp_path / "common.sql"
    institution = tmp_path / "institution.sql"

    generate_seed(sa_sync_conn, COMMON_SEED, common)
    generate_seed(sa_sync_conn, INSTITUTION_SEED, institution)

    common_sql = common.read_text(encoding="utf-8")
    institution_sql = institution.read_text(encoding="utf-8")
    assert "VALUES ('perimeter_persons'" in institution_sql
    assert "VALUES ('perimeter_persons'" not in common_sql
    assert "VALUES ('unpaywall_max_per_run'" in common_sql
    assert "VALUES ('unpaywall_max_per_run'" not in institution_sql
    # Les délais de réinterrogation, que la migration pose, suivent le seed commun.
    assert "VALUES ('fetch_stale_after_days'" in common_sql
    # Le chargement d'un seed garde la configuration en base.
    assert "DELETE FROM config" not in common_sql + institution_sql


def test_common_seed_writes_initial_config_values(sa_sync_conn, tmp_path):
    """Le seed commun contient la valeur initiale de chaque clé commune, quelle que soit la valeur en base."""
    set_config(sa_sync_conn, "unpaywall_max_per_run", 5)
    set_config(sa_sync_conn, LABORATORY_TYPES_KEY, ["labo", "chu"])
    common = tmp_path / "common.sql"

    generate_seed(sa_sync_conn, COMMON_SEED, common)

    common_sql = common.read_text(encoding="utf-8")
    for key, value in INITIAL_CONFIG_VALUES.items():
        assert f"VALUES ('{key}', '{json.dumps(value)}'" in common_sql
    assert '\'["labo", "chu"]\'' not in common_sql


def test_seed_keeps_the_config_in_base(sa_sync_conn):
    """Le chargement du seed ajoute une clé absente et garde la valeur d'une clé présente."""
    set_config(sa_sync_conn, "unpaywall_max_per_run", 5)
    sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'sudoc_max_per_run'"))
    section = SeedSection(
        tables.config,
        [("unpaywall_max_per_run", 10_000, "d"), ("sudoc_max_per_run", 10_000, "d")],
        keep_existing=True,
    )
    sql = render_seed(COMMON_SEED.description, Path("seed.sql"), [section])

    sa_sync_conn.exec_driver_sql(sql.replace("BEGIN;", "").replace("COMMIT;", ""))

    values = dict(
        sa_sync_conn.execute(
            text(
                "SELECT key, value FROM config"
                " WHERE key IN ('unpaywall_max_per_run', 'sudoc_max_per_run')"
            )
        ).all()
    )
    assert values == {"unpaywall_max_per_run": 5, "sudoc_max_per_run": 10_000}


def test_seed_se_recharge_sur_une_base_remplie(sa_sync_conn):
    """Régression : le seed se recharge sur une base où un candidat d'adresse référence un pays."""
    ensure_country(sa_sync_conn, "fr", "Ancien nom")
    ensure_country(sa_sync_conn, "zz", "Absent du seed")
    address_id = insert_address(sa_sync_conn, "Clermont-Ferrand")
    sa_sync_conn.execute(
        text(
            "INSERT INTO address_country_candidates (address_id, country_code, method)"
            " VALUES (:a, 'fr', 'country_name')"
        ),
        {"a": address_id},
    )
    # Les migrations insèrent des villes des deux Congo : leurs pays restent référencés.
    rows = [("cd", "Rép. dém. du Congo"), ("cg", "Congo"), ("de", "Allemagne"), ("fr", "France")]
    section = SeedSection(tables.countries, rows)
    sql = render_seed(COMMON_SEED.description, Path("seed.sql"), [section])

    # La transaction du test encadre le chargement : le seed s'y joue sans ses propres bornes.
    sa_sync_conn.exec_driver_sql(sql.replace("BEGIN;", "").replace("COMMIT;", ""))

    countries = sa_sync_conn.execute(text("SELECT code, name FROM countries ORDER BY code")).all()
    assert [tuple(r) for r in countries] == rows
    candidate = sa_sync_conn.execute(
        text("SELECT country_code FROM address_country_candidates WHERE address_id = :a"),
        {"a": address_id},
    ).scalar_one()
    assert candidate == "fr"
