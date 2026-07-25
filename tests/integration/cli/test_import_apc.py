"""Smoke test de `import_apc` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI récurrent qui code en dur les colonnes d'`apc_payments` (INSERT) et les jointures de mapping (`publications.doi`, `journals.issn`/`eissn`, `publishers.name`) : un renommage les casserait en silence. Le parsing CSV relève de la logique Python et n'est pas couvert ici.
"""

from sqlalchemy import text

from interfaces.cli.imports.import_apc import (
    INSERT_APC_PAYMENT,
    map_dois,
    map_journals,
    map_publishers,
)

# Enregistrement minimal : toutes les colonnes de l'INSERT sont présentes (valeurs nulles admises).
_ROW = {
    "lab_name": None,
    "publisher_name": None,
    "publisher_type": None,
    "journal_name": None,
    "issn": None,
    "journal_type": None,
    "doi": None,
    "article_title": None,
    "amount_eur_ht": None,
    "billing_year": None,
    "pub_year": None,
    "budget": None,
    "institution": None,
    "institution_type": None,
    "coman_id": None,
    "all_surveys_answered": None,
    "shared_payment": None,
    "source_file": "smoke",
    "expense_type": None,
    "remarks": None,
}


def test_import_apc_schema_coupled_sql(sa_sync_conn):
    # INSERT : valide la liste de colonnes d'apc_payments.
    sa_sync_conn.execute(INSERT_APC_PAYMENT, [_ROW])
    assert sa_sync_conn.execute(text("SELECT COUNT(*) FROM apc_payments")).scalar_one() == 1

    # Mappings : valident les colonnes jointes (0 ligne à mapper sur une base vide, mais le SQL s'exécute).
    map_dois(sa_sync_conn)
    map_journals(sa_sync_conn)
    map_publishers(sa_sync_conn)
