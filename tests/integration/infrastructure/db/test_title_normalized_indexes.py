"""Index des titres normalisés : un titre plus long qu'une entrée d'index btree s'écrit."""

import secrets

import pytest
from sqlalchemy import text

# Texte aléatoire, donc peu compressible : environ 8 000 octets dans l'entrée d'index, au-delà des 2 704 octets d'un btree.
_LONG_TITLE = secrets.token_hex(4000)

_INSERTS = {
    "source_records": "INSERT INTO source_records (source, source_id, title, title_normalized, publication_year)"
    " VALUES ('openalex', 'W7223893444', :t, :t, 2026)",
    "publications": "INSERT INTO publications (title, title_normalized, publication_year) VALUES (:t, :t, 2026)",
    "serials": "INSERT INTO serials (title, title_normalized) VALUES (:t, :t)",
    "monographs": "INSERT INTO monographs (title, title_normalized) VALUES (:t, :t)",
}


@pytest.mark.parametrize("table", _INSERTS)
def test_un_titre_long_s_ecrit_et_se_retrouve(sa_sync_conn, table):
    sa_sync_conn.execute(text(_INSERTS[table]), {"t": _LONG_TITLE})
    found = sa_sync_conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE title_normalized = :t"), {"t": _LONG_TITLE}
    ).scalar()
    assert found == 1
