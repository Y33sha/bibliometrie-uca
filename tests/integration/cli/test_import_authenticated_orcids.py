"""Smoke test des lectures de `import_authenticated_orcids` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

L'import de maintenance résout email → personnes (`persons_rh.email`/`person_id`) et sonde le porteur actuel d'un ORCID (`person_identifiers.id_type`/`id_value`/`person_id`/`status`) via `PgPersonRepository` — `map_rh_emails_to_person_ids` et `find_identifier_holders` : un renommage les casserait en silence. L'écriture du statut passe par le service application et n'est pas couverte ici. Sur une base vide, les deux requêtes valident tables et colonnes sans ligne à retourner.
"""

from infrastructure.repositories.person_repository import PgPersonRepository


def test_import_authenticated_orcids_schema_coupled_sql(sa_sync_conn):
    repo = PgPersonRepository(sa_sync_conn)
    assert repo.map_rh_emails_to_person_ids() == {}
    assert repo.find_identifier_holders("orcid", ["0000-0002-1825-0097"]) == {}
