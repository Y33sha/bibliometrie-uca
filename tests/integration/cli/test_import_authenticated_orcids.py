"""Smoke test de `import_authenticated_orcids` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI de maintenance qui code en dur `persons_rh.email`/`person_id` (résolution email → personnes) et `person_identifiers.id_type`/`id_value`/`person_id`/`status` (porteur actuel d'un ORCID) : un renommage les casserait en silence. L'écriture du statut passe par le service application et n'est pas couverte ici. Sur une base vide, les deux requêtes valident tables et colonnes sans ligne à retourner.
"""

from interfaces.cli.maintenance.import_authenticated_orcids import (
    fetch_current_orcid_holders,
    resolve_email_to_persons,
)


def test_import_authenticated_orcids_schema_coupled_sql(sa_sync_conn):
    assert resolve_email_to_persons(sa_sync_conn) == {}
    assert fetch_current_orcid_holders(sa_sync_conn, ["0000-0002-1825-0097"]) == {}
