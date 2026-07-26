"""Smoke test de `import_persons` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI récurrent qui code en dur les colonnes de `persons` et `persons_rh` (INSERT) et la jointure de déduplication (`persons.last_name_normalized`/`first_name_normalized`, `persons_rh.department_name`/`role_title`) : un renommage les casserait en silence. Le parsing des fichiers RH relève de la logique Python et n'est pas couvert ici.
"""

from interfaces.cli.imports.import_persons import (
    INSERT_PERSON,
    INSERT_PERSON_RH,
    SELECT_DUPLICATE_PERSON,
)


def test_import_persons_schema_coupled_sql(sa_sync_conn):
    # INSERT persons : valide la liste de colonnes et le RETURNING id.
    person_id = sa_sync_conn.execute(
        INSERT_PERSON,
        {"last": "Durand", "first": "Marie", "ln": "durand", "fn": "marie"},
    ).scalar_one()

    # INSERT persons_rh : valide les colonnes de la fiche RH.
    sa_sync_conn.execute(
        INSERT_PERSON_RH,
        {
            "pid": person_id,
            "email": "marie.durand@uca.fr",
            "role": "MCF",
            "dept": "LMBP",
            "start": "2020-09-01",
            "end": None,
            "exp": "2026-01-15",
        },
    )

    # SELECT de déduplication : la personne insérée doit se retrouver via la jointure NULL-safe.
    found = sa_sync_conn.execute(
        SELECT_DUPLICATE_PERSON,
        {"ln": "durand", "fn": "marie", "dept": "LMBP", "role": "MCF"},
    ).first()
    assert found is not None and found.id == person_id
