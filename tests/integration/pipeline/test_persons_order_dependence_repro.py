"""Ordre-dépendance de la phase persons — canal nominal.

Deux signatures d'une **même personne** sans identifiant partagé, l'une en forme pleine
(« Jean Martin »), l'autre en forme initiale (« J Martin »). L'ordre de traitement suit
`sa.id` (ORDER BY déterministe de `fetch_unlinked_authorships`).

Dans un run isolé, la création live sème la map en mémoire via `compute_person_name_forms`
(ordres + initiales) : une signature initiale du même run rattrape une personne créée en
forme pleine, mais pas l'inverse — une initiale ne peut pas générer la forme pleine, donc
« initiale puis pleine » sépare encore. La réinitialisation nominale (re-orphelinage des
formes devenues ambiguës + GC des personnes vidées) referme ce résidu **sur plusieurs
runs**, dès que le peuplement canonique donne à « Jean Martin » sa forme initiale
« j martin » et la rend ambiguë.

Les tests n'appellent que `run()` (pas `populate`, qui committe et casserait le rollback de
la fixture) ; le peuplement des formes canoniques est simulé par `_populate_canonical_forms`.
"""

import logging

from sqlalchemy import text

from application.pipeline.persons.create_persons_from_source_authorships import run
from application.pipeline.persons.purge import purge
from domain.persons.name_forms import compute_person_name_forms
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


def _seed_cross_source_pair(conn, *, pub_id, sa1_id, raw1, norm1, sa2_id, raw2, norm2):
    """Une publication vue par HAL et OpenAlex, même auteur en position 0 mais deux graphies.
    Deux signatures non rattachées, à créer."""
    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (:p, :t, :t, 'article', 2024)
        """),
        {"p": pub_id, "t": f"pub {pub_id}"},
    )
    for sp_id, source in ((sa1_id, "hal"), (sa2_id, "openalex")):
        conn.execute(
            text("""
                INSERT INTO source_publications
                    (id, source, source_id, title, pub_year, doc_type, publication_id)
                VALUES (:sp, :src, :sid, :t, 2024, 'ART', :p)
            """),
            {
                "sp": sp_id,
                "src": source,
                "sid": f"{source}-{sp_id}",
                "t": f"pub {pub_id}",
                "p": pub_id,
            },
        )
    for sa_id, source, raw, norm in (
        (sa1_id, "hal", raw1, norm1),
        (sa2_id, "openalex", raw2, norm2),
    ):
        identity = upsert_identity(conn, norm, None)
        conn.execute(
            text("""
                INSERT INTO source_authorships
                    (id, source, source_publication_id, author_position, in_perimeter,
                     person_id, raw_author_name, identity_id)
                VALUES (:p, :src, :p, 0, TRUE, NULL, :raw, :iid)
            """),
            {"p": sa_id, "src": source, "raw": raw, "iid": identity},
        )


def _run_create(conn):
    run(conn, PgPersonsCreateQueries(), _LOG, person_repo=person_repository(conn))


def _populate_canonical_forms(conn):
    """Simule le peuplement des formes canoniques (source « persons » de `populate`) :
    chaque personne acquiert les variantes de son nom via `compute_person_name_forms` —
    initiales comprises, ce qui rend « j martin » commune à « J Martin » et « Jean Martin »."""
    for r in conn.execute(text("SELECT id, last_name, first_name FROM persons")).all():
        for form in compute_person_name_forms(r.last_name, r.first_name or ""):
            conn.execute(
                text(
                    "INSERT INTO person_name_forms (name_form, person_id, sources) "
                    "VALUES (:f, :p, ARRAY['persons']) ON CONFLICT DO NOTHING"
                ),
                {"f": form, "p": r.id},
            )


def _run_phase(conn):
    """Run complet de la phase personnes : rattachement/création, peuplement des formes, purge.

    Le peuplement est simulé (`populate` committe, incompatible avec le rollback de la fixture),
    la purge appelée directement — l'ordre reproduit `phase_persons`."""
    _run_create(conn)
    _populate_canonical_forms(conn)
    purge(conn, PgPersonsCreateQueries(), _LOG)


def _martin_count(conn) -> int:
    return conn.execute(
        text("SELECT COUNT(*) FROM persons WHERE last_name_normalized = 'martin'")
    ).scalar_one()


def _person_of(conn, sa_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :i"), {"i": sa_id}
    ).scalar_one()


def test_full_then_initial_merges(sa_sync_conn):
    """Forme pleine (id bas, traitée d'abord) puis initiale dans le même run : la personne
    créée en « Jean Martin » sème « j martin », la signature « J Martin » s'y rattache —
    une seule personne."""
    _seed_signature(sa_sync_conn, pub_id=95001, raw_name="Jean Martin", name_norm="jean martin")
    _seed_signature(sa_sync_conn, pub_id=95002, raw_name="J Martin", name_norm="j martin")
    _run_create(sa_sync_conn)
    assert _martin_count(sa_sync_conn) == 1


def test_initial_then_full_splits_in_a_single_run(sa_sync_conn):
    """Dans un run isolé, forme initiale (id bas) puis pleine : « J Martin » ne peut pas
    générer « jean martin », donc « Jean Martin » crée une seconde personne. Le résidu
    est levé sur plusieurs runs par la réinitialisation nominale — cf.
    `test_initial_then_full_converges_over_runs`."""
    _seed_signature(sa_sync_conn, pub_id=95003, raw_name="J Martin", name_norm="j martin")
    _seed_signature(sa_sync_conn, pub_id=95004, raw_name="Jean Martin", name_norm="jean martin")
    _run_create(sa_sync_conn)
    assert _martin_count(sa_sync_conn) == 2


def test_initial_then_full_converges_over_runs(sa_sync_conn):
    """Le résidu « initiale puis pleine » se résorbe en deux runs complets. Le premier crée
    « J Martin » et « Jean Martin » séparément ; le peuplement rend « j martin » ambiguë (c'est
    l'initiale de « Jean Martin »), et la purge supprime la personne réduite vidée. Au run
    suivant, « j martin » redevenue univoque, la signature libérée rejoint « Jean Martin »."""
    conn = sa_sync_conn
    _seed_signature(conn, pub_id=95003, raw_name="J Martin", name_norm="j martin")
    _seed_signature(conn, pub_id=95004, raw_name="Jean Martin", name_norm="jean martin")

    _run_phase(conn)  # crée A + B, peuple, purge la réduite
    assert _martin_count(conn) == 1  # la personne réduite a fondu dès ce run
    assert _person_of(conn, 95003) is None  # sa signature reste orpheline le temps d'un run

    _run_phase(conn)  # « j martin » univoque → la signature rejoint « Jean Martin »
    remaining = conn.execute(
        text("SELECT id, first_name_normalized FROM persons WHERE last_name_normalized = 'martin'")
    ).one()
    assert remaining.first_name_normalized == "jean"  # la forme pleine survit
    persons_on = (
        conn.execute(
            text("SELECT DISTINCT person_id FROM source_authorships WHERE id IN (95003, 95004)")
        )
        .scalars()
        .all()
    )
    assert persons_on == [remaining.id]  # les deux signatures sur la même personne


def test_ambiguous_form_reorphaned_when_homonym_appears(sa_sync_conn):
    """Sur-regroupement : « H Chanal » se colle d'abord à l'unique « Hervé Chanal » présent ;
    dès que « Hélène Chanal » coexiste et rend « h chanal » ambiguë, la signature réduite est
    re-orphelinée — elle ne reste pas collée au premier arrivé, quel que soit l'ordre."""
    conn = sa_sync_conn
    _seed_signature(conn, pub_id=95010, raw_name="Hervé Chanal", name_norm="herve chanal")
    _seed_signature(conn, pub_id=95011, raw_name="H Chanal", name_norm="h chanal")
    _run_phase(conn)
    assert _person_of(conn, 95011) is not None  # rattachée à l'unique candidat

    _seed_signature(conn, pub_id=95012, raw_name="Hélène Chanal", name_norm="helene chanal")
    _run_phase(conn)  # crée « Hélène Chanal » ; « h chanal » devient ambiguë → re-orphelinage

    assert _person_of(conn, 95011) is None  # orpheline, plus collée à Hervé


def test_cross_source_pair_merges_via_deferred_creation(sa_sync_conn):
    """« Jean Martin » (HAL) et « J-P Martin » (OpenAlex), même publication × position, sont le
    même auteur pour le cross-source (`names_compatible`), mais leurs formes de nom sont
    disjointes — le matching par nom ne les réunit pas. Traitée en premier, « Jean Martin » est
    différée puis créée ; « J-P Martin » la rejoint par cross-source au lieu de créer un doublon.
    Une seule personne."""
    conn = sa_sync_conn
    _seed_cross_source_pair(
        conn,
        pub_id=95020,
        sa1_id=95021,
        raw1="Jean Martin",
        norm1="jean martin",
        sa2_id=95022,
        raw2="J-P Martin",
        norm2="j p martin",
    )
    _run_create(conn)

    assert _martin_count(conn) == 1
    persons_on = (
        conn.execute(
            text("SELECT DISTINCT person_id FROM source_authorships WHERE id IN (95021, 95022)")
        )
        .scalars()
        .all()
    )
    assert len(persons_on) == 1 and persons_on[0] is not None  # les deux sur la même personne
