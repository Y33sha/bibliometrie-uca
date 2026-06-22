"""Tests d'intégration — cascade unifiée `create_persons_from_source_authorships.run`.

Vérifie le câblage complet (prefetch → décision → effets DB) sur une vraie base
PostgreSQL. La logique pure des sous-décisions est testée hors BDD dans
`tests/unit/domain/persons/test_matching.py`.

Périmètre des scénarios :

- Match cross-source : authorship rattachée à la `person_id` d'une autre
  source à la même `(publication_id, author_position)`.
- Match par identifier : ORCID connu (confirmed) → matche ; ORCID rejected →
  pas de match.
- Match par name_form : forme connue uniquement (rattache) / ambiguë (skip).
- Création : forme inconnue, auteur autorisé → crée.
- Import des identifiants : tout match propage les identifiants de
  l'authorship vers la personne (statut `pending`, vérifiables admin).
"""

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.persons import add_name_form, create_person
from application.pipeline.persons.create_persons_from_source_authorships import run
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

_queries = PgPersonsCreateQueries()
_logger = logging.getLogger("test")


# ── Helpers ──────────────────────────────────────────────────────


def _seed_identifier(conn, person_id, id_type, id_value, status, source="auto"):
    """Seed direct d'un person_identifiers avec statut arbitraire.

    `application.persons.add_identifier` ne prend plus de `status` en paramètre
    (toujours `pending` à l'insertion). Pour préparer un état `confirmed` ou
    `rejected` en début de test, on passe par SQL.
    """
    conn.execute(
        text("""
            INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
            VALUES (:pid, :it, :iv, CAST(:src AS identifier_origin),
                    CAST(:st AS identifier_status))
        """),
        {"pid": person_id, "it": id_type, "iv": id_value, "src": source, "st": status},
    )


def _reject_pair(conn, publication_id, person_id):
    """Seed une paire rejetée dans `rejected_authorships`."""
    conn.execute(
        text(
            "INSERT INTO rejected_authorships (publication_id, person_id) "
            "VALUES (:pub, :pid) ON CONFLICT DO NOTHING"
        ),
        {"pub": publication_id, "pid": person_id},
    )


def _insert_publication(conn, title="Test Pub", pub_year=2024):
    from domain.normalize import normalize_text

    return conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, doc_type, pub_year)
            VALUES (:title, :norm, 'article', :pub_year) RETURNING id
        """),
        {"title": title, "norm": normalize_text(title), "pub_year": pub_year},
    ).scalar_one()


def _insert_source_document(conn, source, source_id, publication_id):
    return conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
            VALUES (:src, :sid, 'Test', 2024, :pub_id) RETURNING id
        """),
        {"src": source, "sid": source_id, "pub_id": publication_id},
    ).scalar_one()


def _insert_authorship(
    conn,
    source,
    source_publication_id,
    raw_author_name,
    *,
    position=0,
    in_perimeter=True,
    person_id=None,
    identifiers=None,
):
    """Insère une source_authorship.

    `identifiers` est un dict pour `person_identifiers` (JSONB) :
    ex. `{"orcid": "0000-...", "idref": "...", "hal_person_id": 42, ...}`.
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position,
             in_perimeter, person_id, raw_author_name, person_identifiers,
             author_name_normalized)
        VALUES (:src, :sd, :pos, :in_perim, :person_id,
                :raw, :person_identifiers, normalize_name_form(:raw))
        RETURNING id
    """).bindparams(
        bindparam("person_identifiers", type_=JSONB),
    )
    return conn.execute(
        stmt,
        {
            "src": source,
            "sd": source_publication_id,
            "pos": position,
            "in_perim": in_perimeter,
            "person_id": person_id,
            "raw": raw_author_name,
            "person_identifiers": identifiers,
        },
    ).scalar_one()


def _get_person_id(conn, authorship_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :id"),
        {"id": authorship_id},
    ).scalar_one_or_none()


def _get_person_identifiers(conn, person_id):
    rows = conn.execute(
        text("SELECT id_type, id_value FROM person_identifiers WHERE person_id = :pid"),
        {"pid": person_id},
    ).all()
    return {(r.id_type, r.id_value) for r in rows}


def _run_cascade(conn):
    run(conn, _queries, _logger, person_repo=person_repository(conn))


# ── Scénarios ────────────────────────────────────────────────────


class TestCascadeRun:
    def test_cross_source_links_and_imports_identifiers(self, sa_sync_conn):
        """Cross-source : authorship OA non-rattachée + HAL rattachée même position
        → matche, et les identifiants OA sont importés."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))

        hal_sd = _insert_source_document(sa_sync_conn, "hal", "hal-100", pub)
        _insert_authorship(
            sa_sync_conn,
            "hal",
            hal_sd,
            "Jean Dupont",
            position=3,
            person_id=person_id,
            identifiers={"hal_person_id": "111"},
        )

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W111", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "J Dupont",
            position=3,
            identifiers={"orcid": "0000-0001-9999-8888"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == person_id
        ids = _get_person_identifiers(sa_sync_conn, person_id)
        assert ("orcid", "0000-0001-9999-8888") in ids

    def test_known_orcid_links(self, sa_sync_conn):
        """ORCID confirmé en base → matche la bonne personne."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "orcid", "0000-0001-2345-6789", "confirmed")

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W333", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "J Dupont",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == person_id

    def test_known_hal_person_id_links(self, sa_sync_conn):
        """`hal_person_id` confirmé en base + nom compatible → matche la bonne personne."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "hal_person_id", "123456", "confirmed")

        hal_sd = _insert_source_document(sa_sync_conn, "hal", "hal-200", pub)
        hal_as = _insert_authorship(
            sa_sync_conn,
            "hal",
            hal_sd,
            "Jean Dupont",
            identifiers={"hal_person_id": "123456"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) == person_id

    def test_identifier_match_rejected_on_incompatible_name(self, sa_sync_conn):
        """Corroboration par le nom : un identifiant confirmé pointant une personne
        au nom incompatible avec la signature ne rattache pas (corruption éparse —
        un identifiant recopié sur le mauvais co-auteur). La cascade retombe sur le
        name_form (ici inconnu → création), pas sur la personne ciblée par l'identifiant."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "hal_person_id", "123456", "confirmed")

        hal_sd = _insert_source_document(sa_sync_conn, "hal", "hal-201", pub)
        hal_as = _insert_authorship(
            sa_sync_conn,
            "hal",
            hal_sd,
            "Toto Inconnu",
            identifiers={"hal_person_id": "123456"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) != person_id

    def test_rejected_orcid_ignored(self, sa_sync_conn):
        """ORCID `rejected` en base → ignoré par le matching."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "orcid", "0000-0001-9999-0000", "rejected")

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W444", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-9999-0000"},
        )

        _run_cascade(sa_sync_conn)

        # Pas le rattachement par ORCID rejected ; la cascade peut fallback sur
        # name_form qui ne match pas non plus → création (pas le person_id seedé).
        assert _get_person_id(sa_sync_conn, oa_as) != person_id

    def test_wos_orcid_not_used_as_match_signal(self, sa_sync_conn):
        """ORCID porté par une authorship WoS → ignoré comme signal de matching.

        L'ORCID WoS (`PreferredORCID`) est attribué par le matching algorithmique
        interne de Web of Science, régulièrement fautif. Même quand il pointe vers
        un ORCID confirmé en base, il ne doit pas rattacher l'authorship (cf.
        `ORCID_MATCH_SOURCES`). Le nom ne matchant pas non plus → pas de
        rattachement à la personne seedée.
        """
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "orcid", "0000-0001-2345-6789", "confirmed")

        wos_sd = _insert_source_document(sa_sync_conn, "wos", "WOS:111", pub)
        wos_as = _insert_authorship(
            sa_sync_conn,
            "wos",
            wos_sd,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, wos_as) != person_id

    def test_name_form_match_imports_identifiers(self, sa_sync_conn):
        """Match par name_form → identifiers importés en pending (pour vérification
        manuelle ultérieure). Sans cet import, une base initialement vide n'aurait
        jamais d'identifiers, vu que la 1ère authorship créerait la personne et les
        suivantes (matching name_form) ne propageraient rien."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Martin", "Pierre", repo=person_repository(sa_sync_conn))

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W666", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "Pierre Martin",
            identifiers={"orcid": "0000-0002-3456-7890"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == person_id
        ids = _get_person_identifiers(sa_sync_conn, person_id)
        assert ("orcid", "0000-0002-3456-7890") in ids

    def test_ambiguous_name_form_stays_orphan(self, sa_sync_conn):
        """Nom mappé à 2 personnes (homonymes) → skip, pas de rattachement."""
        pub = _insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        # "J Dupont" devient ambigu (initiale J → match les deux)
        add_name_form(pid1, "J Dupont", repo=person_repository(sa_sync_conn))
        add_name_form(pid2, "J Dupont", repo=person_repository(sa_sync_conn))

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W777", pub)
        oa_as = _insert_authorship(sa_sync_conn, "openalex", oa_sd, "J Dupont")

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) is None

    def test_rejected_pair_blocks_identifier_match(self, sa_sync_conn):
        """Paire (publi, personne) dans `rejected_authorships` → un match par
        identifiant vers cette personne est annulé. La cascade ne ré-attache
        pas le `person_id` rejeté à la `source_authorship`."""
        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        _seed_identifier(sa_sync_conn, person_id, "orcid", "0000-0001-2345-6789", "confirmed")
        _reject_pair(sa_sync_conn, pub, person_id)

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W999", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) != person_id

    def test_rejected_candidate_disambiguates_ambiguous_name_form(self, sa_sync_conn):
        """2 homonymes partagent la forme de nom ; l'un est rejeté pour la publi
        → l'élimination ne laisse qu'une candidate → match univoque vers l'autre
        (désambiguïsation par élimination)."""
        pub = _insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        add_name_form(pid1, "J Dupont", repo=person_repository(sa_sync_conn))
        add_name_form(pid2, "J Dupont", repo=person_repository(sa_sync_conn))
        _reject_pair(sa_sync_conn, pub, pid1)

        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W778", pub)
        oa_as = _insert_authorship(sa_sync_conn, "openalex", oa_sd, "J Dupont")

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == pid2

    def test_unknown_name_creates_person_with_identifiers(self, sa_sync_conn):
        """Forme inconnue + authorship-auteur → crée la personne et importe ses
        identifiants."""
        pub = _insert_publication(sa_sync_conn)
        oa_sd = _insert_source_document(sa_sync_conn, "openalex", "W888", pub)
        oa_as = _insert_authorship(
            sa_sync_conn,
            "openalex",
            oa_sd,
            "Inconnu Nouveau",
            identifiers={"orcid": "0000-0003-1111-2222"},
        )

        _run_cascade(sa_sync_conn)

        pid = _get_person_id(sa_sync_conn, oa_as)
        assert pid is not None

        last_name = sa_sync_conn.execute(
            text("SELECT last_name FROM persons WHERE id = :pid"), {"pid": pid}
        ).scalar_one()
        assert last_name == "Nouveau"

        ids = _get_person_identifiers(sa_sync_conn, pid)
        assert ("orcid", "0000-0003-1111-2222") in ids
