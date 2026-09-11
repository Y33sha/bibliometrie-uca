"""Smoke test de `generate_seed` : le script parcourt chaque table de référence sans buter sur une colonne ou une table périmée.

Les CLI oneshot ne sont pas testés (joués une fois) ; les CLI récurrents comme celui-ci ont un smoke test, pour qu'un renommage de schéma ne les casse pas silencieusement — mypy et ruff ne voient pas les identifiants SQL portés par les chaînes `text()`.
"""

from sqlalchemy import text

from interfaces.cli.dev.generate_seed import COMMON_SEED, INSTITUTION_SEED, generate_seed


def test_generate_seed_walks_every_table(sa_sync_conn, tmp_path):
    # Une ligne dans `perimeters` exerce la sérialisation d'un array integer[] et le recalage de séquence.
    sa_sync_conn.execute(
        text(
            "INSERT INTO perimeters (code, name, root_structure_ids) "
            "VALUES ('smoke', 'Smoke', '{1,2}')"
        )
    )
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
    # Les extractions OpenAlex, WoS, ScanR et theses.fr lisent l'institution dans `api_ids` : une base montée depuis le seed doit les porter.
    sa_sync_conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type, api_ids) "
            "VALUES ('smoke', 'Smoke', 'universite', CAST(:api_ids AS jsonb))"
        ),
        {"api_ids": '{"openalex": ["I1"]}'},
    )
    out = tmp_path / "seed.sql"

    generate_seed(sa_sync_conn, INSTITUTION_SEED, out)

    content = out.read_text(encoding="utf-8")
    assert "hal_collection, api_ids) VALUES" in content
    assert """'{"openalex": ["I1"]}'""" in content


def test_generate_seed_splits_config_keys(sa_sync_conn, tmp_path):
    # Les clés de périmètre désignent des périmètres de l'établissement : elles suivent son seed, les autres clés vont au seed commun.
    sa_sync_conn.execute(
        text(
            "INSERT INTO config (key, value) "
            "VALUES ('perimeter_persons', '\"smoke\"'), ('unpaywall_max_per_run', '5') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    )
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
    # Chaque seed supprime seulement ses propres clés : l'ordre de chargement est indifférent.
    assert "DELETE FROM config WHERE key NOT IN (" in common_sql
    assert "DELETE FROM config WHERE key IN (" in institution_sql
