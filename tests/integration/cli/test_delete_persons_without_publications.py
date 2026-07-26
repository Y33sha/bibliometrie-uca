"""Smoke test de `delete_persons_without_publications` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI de maintenance qui code en dur `persons`, `authorships`, `persons_rh`, `source_authorships.person_id`, `person_identifiers.person_id` et `person_name_forms.person_id` : un renommage les casserait en silence. Sur une base vide, comptes et écritures ne touchent aucune ligne mais valident tables et colonnes.
"""

from interfaces.cli.maintenance.delete_persons_without_publications import (
    count_targets,
    purge_targets,
)


def test_delete_persons_without_publications_schema_coupled_sql(sa_sync_conn):
    # Comptes de prévisualisation : les quatre requêtes s'exécutent (0 ligne sur base vide).
    assert count_targets(sa_sync_conn) == (0, 0, 0, 0)

    # Détachement puis suppression : valident leurs colonnes cibles (0 ligne).
    assert purge_targets(sa_sync_conn) == (0, 0)
