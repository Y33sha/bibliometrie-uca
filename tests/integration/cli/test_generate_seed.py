"""Smoke test de `generate_seed` : le script parcourt chaque table de référence sans buter sur une colonne ou une table périmée.

Les CLI oneshot ne sont pas testés (joués une fois) ; les CLI récurrents comme celui-ci ont un smoke test, pour qu'un renommage de schéma ne les casse pas silencieusement — mypy et ruff ne voient pas les identifiants SQL portés par les chaînes `text()`.
"""

from sqlalchemy import text

from interfaces.cli.dev.generate_seed import generate_seed


def test_generate_seed_walks_every_table(sa_sync_conn, tmp_path):
    # Une ligne dans `perimeters` exerce la sérialisation d'un array integer[] et le recalage de séquence.
    sa_sync_conn.execute(
        text(
            "INSERT INTO perimeters (code, name, root_structure_ids) "
            "VALUES ('smoke', 'Smoke', '{1,2}')"
        )
    )
    out = tmp_path / "seed.sql"

    # Chaque table déclenche un `SELECT <colonnes> FROM <table>` : une colonne périmée lèverait ici.
    generate_seed(sa_sync_conn, out)

    content = out.read_text(encoding="utf-8")
    assert content.startswith("-- Seed généré")
    assert "BEGIN;" in content
    assert "COMMIT;" in content
    assert "INSERT INTO perimeters (id, code, name, root_structure_ids)" in content
    assert "'{1, 2}'" in content
