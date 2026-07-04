"""Ordre-dépendance de la phase persons — canal nominal, générateur de formes unifié.

Deux signatures d'une **même personne** sans identifiant partagé, l'une en forme pleine
(« Jean Martin »), l'autre en forme initiale (« J Martin »), traitées dans un **seul** run
de création. L'ordre de traitement suit `sa.id` (ORDER BY déterministe de
`fetch_unlinked_authorships`).

La création live sème la map en mémoire via `compute_person_name_forms` (ordres +
initiales) : une signature initiale du même run rattrape une personne créée en forme
pleine. Reste une ordre-dépendance résiduelle, inhérente : une forme initiale ne peut pas
générer la forme pleine, donc « initiale puis pleine » sépare encore.

Ces tests n'appellent que `run()` (pas `populate`, qui committe et casserait le rollback
de la fixture) : l'isolation transactionnelle est donc préservée.
"""

import logging

from sqlalchemy import text

from application.pipeline.persons.create_persons_from_source_authorships import run
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository
from tests.integration.helpers.authorships import upsert_identity

_LOG = logging.getLogger("test")


def _seed_signature(conn, *, pub_id, raw_name, name_norm):
    """Publication + source_publication + signature in-périmètre non rattachée, portant
    l'identité `name_norm` (sans identifiant). L'id de la signature = `pub_id`, ce qui
    fixe l'ordre de traitement."""
    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (:p, :t, :t, 'article', 2024)
        """),
        {"p": pub_id, "t": f"pub {pub_id}"},
    )
    conn.execute(
        text("""
            INSERT INTO source_publications
                (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (:p, 'hal', :sid, :t, 2024, 'ART', :p)
        """),
        {"p": pub_id, "sid": f"hal-{pub_id}", "t": f"pub {pub_id}"},
    )
    identity = upsert_identity(conn, name_norm, None)
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position, in_perimeter,
                 person_id, raw_author_name, identity_id)
            VALUES (:p, 'hal', :p, 0, TRUE, NULL, :raw, :iid)
        """),
        {"p": pub_id, "raw": raw_name, "iid": identity},
    )


def _run_create(conn):
    run(conn, PgPersonsCreateQueries(), _LOG, person_repo=person_repository(conn))


def _martin_count(conn) -> int:
    return conn.execute(
        text("SELECT COUNT(*) FROM persons WHERE last_name_normalized = 'martin'")
    ).scalar_one()


def test_full_then_initial_merges(sa_sync_conn):
    """Forme pleine (id bas, traitée d'abord) puis initiale dans le même run : la personne
    créée en « Jean Martin » sème « j martin », la signature « J Martin » s'y rattache —
    une seule personne."""
    _seed_signature(sa_sync_conn, pub_id=95001, raw_name="Jean Martin", name_norm="jean martin")
    _seed_signature(sa_sync_conn, pub_id=95002, raw_name="J Martin", name_norm="j martin")
    _run_create(sa_sync_conn)
    assert _martin_count(sa_sync_conn) == 1


def test_initial_then_full_still_splits(sa_sync_conn):
    """Ordre-dépendance résiduelle : forme initiale (id bas) puis pleine dans le même run.
    « J Martin » ne peut pas générer « jean martin », donc « Jean Martin » crée une seconde
    personne. Documente la limite que le générateur de formes ne lève pas (fix ultérieur :
    matching par compatibilité de tokens au lookup)."""
    _seed_signature(sa_sync_conn, pub_id=95003, raw_name="J Martin", name_norm="j martin")
    _seed_signature(sa_sync_conn, pub_id=95004, raw_name="Jean Martin", name_norm="jean martin")
    _run_create(sa_sync_conn)
    assert _martin_count(sa_sync_conn) == 2
