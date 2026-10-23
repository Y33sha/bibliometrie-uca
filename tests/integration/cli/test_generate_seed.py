"""Smoke test de `generate_seed` : le script parcourt chaque table de référence sans buter sur une colonne ou une table périmée.

Les CLI oneshot ne sont pas testés (joués une fois) ; les CLI récurrents comme celui-ci ont un smoke test, pour qu'un renommage de schéma ne les casse pas silencieusement — pyrefly et ruff ne voient pas les identifiants SQL contenus dans les chaînes `text()`.
"""

from interfaces.cli.dev.generate_seed import COMMON_SEED, INSTITUTION_SEED, generate_seed
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
    # Les extractions OpenAlex, WoS, ScanR et theses.fr lisent l'institution dans `api_ids` : une base montée depuis le seed doit les porter.
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
    # Chaque seed supprime seulement ses propres clés : l'ordre de chargement est indifférent.
    assert "DELETE FROM config WHERE key NOT IN (" in common_sql
    assert "DELETE FROM config WHERE key IN (" in institution_sql
