"""Smoke test de `seed_journals_doi_prefix` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI de maintenance (cf. playbook nettoyer-journals-publishers) qui code en dur `journals.id`/`title`/`doi_prefix` et `publications.journal_id`/`doi` : un renommage les casserait en silence. Le calcul du préfixe (LCP, trim, filtres) relève de la logique Python, testée séparément. Sur une base vide, la sélection et l'UPDATE ne touchent aucune ligne mais valident tables et colonnes.
"""

from interfaces.cli.maintenance.seed_journals_doi_prefix import (
    SELECT_JOURNAL_DOIS,
    UPDATE_JOURNAL_PREFIX,
)


def test_seed_journals_doi_prefix_schema_coupled_sql(sa_sync_conn):
    # SELECT : valide la jointure journals/publications et l'agrégat des DOIs (0 ligne sur base vide).
    assert sa_sync_conn.execute(SELECT_JOURNAL_DOIS, {"min_pubs": 5}).all() == []

    # UPDATE : valide la colonne journals.doi_prefix (aucune ligne à mettre à jour sur base vide).
    assert (
        sa_sync_conn.execute(UPDATE_JOURNAL_PREFIX, {"p": "10.9999/smoke", "id": -1}).rowcount == 0
    )
