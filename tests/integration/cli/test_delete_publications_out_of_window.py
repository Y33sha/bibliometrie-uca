"""Smoke test de `delete_publications_out_of_window` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI de maintenance qui code en dur beaucoup d'identifiants de schéma — `config`, `publications.pub_year`, `source_publications.source`, `source_authorships.in_perimeter`, `persons_rh`, `source_authorship_addresses.address_id`, `address_structures.address_id` : un renommage les casserait en silence. Sur une base vide, la sélection et les DELETE ne touchent aucune ligne mais valident tables et colonnes.
"""

from sqlalchemy import text

from interfaces.cli.maintenance.delete_publications_out_of_window import (
    count_dependents,
    fetch_cutoff,
    purge,
    select_target_pub_ids,
)


def test_delete_out_of_window_schema_coupled_sql(sa_sync_conn):
    # Ancre lue depuis config : valide la table et l'extraction jsonb.
    sa_sync_conn.execute(
        text("""
            INSERT INTO config (key, value) VALUES ('pipeline_start_year_full', '2020'::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """)
    )
    assert fetch_cutoff(sa_sync_conn) == 2020

    # Sélection des cibles et comptes des dépendants : SQL exécuté sur base vide (0 ligne).
    pub_ids = select_target_pub_ids(sa_sync_conn, 2020)
    assert pub_ids == []
    assert count_dependents(sa_sync_conn, [-1]) == (0, 0)

    # Les quatre DELETE valident leurs colonnes cibles (aucune ligne à supprimer sur base vide).
    purge(sa_sync_conn, [-1])
