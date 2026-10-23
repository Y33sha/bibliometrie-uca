"""Tests d'intégration — cascade de rattachement des personnes (`match` puis `create`).

Vérifie le câblage complet (prefetch → décision → effets DB) sur une vraie base
PostgreSQL. La logique pure des sous-décisions est testée hors BDD dans
`tests/unit/domain/persons/test_matching.py`.

Périmètre des scénarios :

- Match cross-source : contribution rattachée à la `person_id` d'une autre
  source à la même `(publication_id, author_position)`.
- Match par identifier : ORCID connu (confirmed) → matche ; ORCID rejected →
  pas de match.
- Match par name_form : forme connue uniquement (rattache) / ambiguë (skip).
- Création : forme inconnue, auteur autorisé → crée.
- Import des identifiants : tout match propage les identifiants de
  la contribution vers la personne (statut `pending`, vérifiables admin).
"""

import logging
from functools import partial

from sqlalchemy import text

from application.services.persons.core import add_name_form, create_person
from domain.normalize import normalize_text
from infrastructure.repositories import person_repository
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.groups import group_ungrouped
from tests.integration.helpers.persons import (
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

# Enregistrement source de 2024, de titre « Test ».
_source_record = partial(insert_source_record, title="Test", publication_year=2024)
_logger = logging.getLogger("test")


# ── Helpers ──────────────────────────────────────────────────────


def _set_name_form_status(conn, person_id, raw_name, status):
    """Force le statut du lien (forme de `raw_name`, person_id) dans `person_name_forms`."""
    conn.execute(
        text("""
            UPDATE person_name_forms SET status = CAST(:st AS identifier_status)
            WHERE person_id = :pid AND name_form = :name_form
        """),
        {"pid": person_id, "name_form": normalize_text(raw_name), "st": status},
    )


def _insert_contribution(
    conn,
    source,
    source_record_id,
    raw_author_name,
    *,
    position=0,
    in_perimeter=True,
    person_id=None,
    identifiers=None,
):
    """Insère une source_contribution.

    `identifiers` est un dict d'identifiants observés, dans les informations du contributeur
    (`contributor_information.identifiers`, JSONB) :
    ex. `{"orcid": "0000-...", "idref": "...", "hal_person_id": 42, ...}`.
    """
    normalized = normalize_text(raw_author_name)
    return insert_source_contribution(
        conn,
        source_record_id,
        source=source,
        author_position=position,
        raw_author_name=raw_author_name,
        author_name_normalized=normalized,
        identifiers=identifiers,
        person_id=person_id,
        in_perimeter=in_perimeter,
    )


def _get_person_id(conn, source_contribution_id):
    return conn.execute(
        text("SELECT person_id FROM source_contributions WHERE id = :id"),
        {"id": source_contribution_id},
    ).scalar_one_or_none()


def _get_person_identifiers(conn, person_id):
    rows = conn.execute(
        text("SELECT id_type, id_value FROM person_identifiers WHERE person_id = :pid"),
        {"pid": person_id},
    ).all()
    return {(r.id_type, r.id_value) for r in rows}


def _run_cascade(conn):
    group_ungrouped(conn)
    arbitrate_identifier_conflicts(conn, _logger, repo=PgPersonRepository(conn))
    run_cascade(conn, _logger, repo=PgPersonRepository(conn))


# ── Scénarios ────────────────────────────────────────────────────


class TestPasseDeCreation:
    """Ce que la seconde passe reprend : les contributions sources du périmètre restées sans personne."""

    def test_une_contribution_source_hors_perimetre_ne_cree_pas_de_personne(self, sa_sync_conn):
        """Un nom inconnu hors périmètre reste sans personne, sans en introduire une."""
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source="openalex", source_id="W1")
        source_contribution = _insert_contribution(
            sa_sync_conn, "openalex", source_record, "Inconnue Hors Perimetre", in_perimeter=False
        )

        avant = sa_sync_conn.execute(text("SELECT count(*) FROM persons")).scalar_one()
        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, source_contribution) is None
        assert sa_sync_conn.execute(text("SELECT count(*) FROM persons")).scalar_one() == avant

    def test_une_contribution_source_du_perimetre_cree_sa_personne(self, sa_sync_conn):
        """Le pendant : dans le périmètre, un nom inconnu introduit sa personne."""
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source="openalex", source_id="W2")
        source_contribution = _insert_contribution(
            sa_sync_conn, "openalex", source_record, "Inconnue Du Perimetre", in_perimeter=True
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, source_contribution) is not None


class TestIdentifierPromotion:
    def test_every_identifier_type_of_the_source_contribution_is_promoted(self, sa_sync_conn):
        """Chaque type d'identifiant de la contribution source, idhal compris, passe sur la personne qu'elle crée."""
        publication = insert_publication(sa_sync_conn)
        source_record = _source_record(sa_sync_conn, publication, source_id="hal-promo")
        identifiers = {
            "orcid": "0000-0002-1633-8730",
            "idref": "181370662",
            "hal_person_id": 11581,
            "idhal": "nina-radosevic-robin",
        }
        source_contribution = _insert_contribution(
            sa_sync_conn, "hal", source_record, "Radosevic-Robin Nina", identifiers=identifiers
        )

        _run_cascade(sa_sync_conn)

        person_id = _get_person_id(sa_sync_conn, source_contribution)
        assert _get_person_identifiers(sa_sync_conn, person_id) == {
            (id_type, str(value)) for id_type, value in identifiers.items()
        }


class TestCascadeRun:
    def test_cross_source_links_and_imports_identifiers(self, sa_sync_conn):
        """Cross-source : contribution OA non-rattachée + HAL rattachée même position
        → matche, et les identifiants OA sont importés."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))

        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-100")
        _insert_contribution(
            sa_sync_conn,
            "hal",
            hal_source_record,
            "Jean Dupont",
            position=3,
            person_id=person_id,
            identifiers={"hal_person_id": "111"},
        )

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W111"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
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
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn,
            person_id,
            id_type="orcid",
            id_value="0000-0001-2345-6789",
            status="confirmed",
        )

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W333"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
            "J Dupont",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == person_id

    def test_known_hal_person_id_links(self, sa_sync_conn):
        """`hal_person_id` confirmé en base + nom compatible → matche la bonne personne."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn, person_id, id_type="hal_person_id", id_value="123456", status="confirmed"
        )

        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-200")
        hal_as = _insert_contribution(
            sa_sync_conn,
            "hal",
            hal_source_record,
            "Jean Dupont",
            identifiers={"hal_person_id": "123456"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) == person_id

    def test_identifier_match_rejected_on_incompatible_name(self, sa_sync_conn):
        """Corroboration par le nom : un identifiant confirmé pointant une personne
        au nom incompatible avec la contribution source ne rattache pas (corruption éparse —
        un identifiant recopié sur le mauvais co-auteur). La cascade retombe sur le
        name_form (ici inconnu → création), pas sur la personne ciblée par l'identifiant."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn, person_id, id_type="hal_person_id", id_value="123456", status="confirmed"
        )

        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-201")
        hal_as = _insert_contribution(
            sa_sync_conn,
            "hal",
            hal_source_record,
            "Toto Inconnu",
            identifiers={"hal_person_id": "123456"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) != person_id

    def test_persons_name_forms_pending_with_persons_source_on_create(self, sa_sync_conn):
        """Les formes dérivées du nom et du prénom sont stockées `pending` avec la source 'persons', qui porte leur confirmation."""
        person_id = create_person("Brindacier", "Fifi", repo=person_repository(sa_sync_conn))
        rows = sa_sync_conn.execute(
            text(
                "SELECT name_form, status::text AS status, sources "
                "FROM person_name_forms WHERE person_id = :pid"
            ),
            {"pid": person_id},
        ).all()
        assert rows
        assert all(r.status == "pending" for r in rows)
        assert all("persons" in r.sources for r in rows)
        assert {r.name_form for r in rows} == {"fifi brindacier", "f brindacier"}

    def test_identifier_match_refused_when_name_form_rejected(self, sa_sync_conn):
        """Forme de nom `rejected` pour la personne : le match identifiant est refusé
        (corroboration), et le barreau name_form l'exclut aussi → pas de rattachement,
        même avec un nom par ailleurs compatible."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn, person_id, id_type="hal_person_id", id_value="111222", status="confirmed"
        )
        # "Jean Dupond" est compatible avec le nom de la personne, mais rejeté pour elle.
        insert_person_name_form(
            sa_sync_conn, person_id, name_form="jean dupond", sources=["hal"], status="rejected"
        )

        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-202")
        hal_as = _insert_contribution(
            sa_sync_conn,
            "hal",
            hal_source_record,
            "Jean Dupond",
            identifiers={"hal_person_id": "111222"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) != person_id

    def test_identifier_match_confirmed_name_form_overrides_token_incompat(self, sa_sync_conn):
        """Forme de nom `confirmed` pour la personne : le match identifiant est corroboré
        sans test de tokens — utile au changement de nom, où la contribution source n'a aucun token
        commun avec le nom de la personne."""
        publication = insert_publication(sa_sync_conn)
        person_a = create_person("Maneval", "Axelle", repo=person_repository(sa_sync_conn))
        person_b = create_person("Vanlander", "Bernard", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn, person_a, id_type="hal_person_id", id_value="987654", status="confirmed"
        )
        # "Van Lander" : aucun token commun avec "Maneval Axelle" (le test de tokens
        # échouerait), confirmée pour A ; aussi portée par B → barreau name_form ambigu.
        add_name_form(person_a, "Van Lander", repo=person_repository(sa_sync_conn))
        add_name_form(person_b, "Van Lander", repo=person_repository(sa_sync_conn))
        _set_name_form_status(sa_sync_conn, person_a, "Van Lander", "confirmed")

        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-203")
        hal_as = _insert_contribution(
            sa_sync_conn,
            "hal",
            hal_source_record,
            "Van Lander",
            identifiers={"hal_person_id": "987654"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, hal_as) == person_a

    def test_rejected_orcid_ignored(self, sa_sync_conn):
        """ORCID `rejected` en base → ignoré par le matching."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn,
            person_id,
            id_type="orcid",
            id_value="0000-0001-9999-0000",
            status="rejected",
        )

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W444"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-9999-0000"},
        )

        _run_cascade(sa_sync_conn)

        # Pas le rattachement par ORCID rejected ; la cascade peut fallback sur
        # name_form qui ne match pas non plus → création (pas le person_id seedé).
        assert _get_person_id(sa_sync_conn, oa_as) != person_id

    def test_wos_orcid_not_used_as_match_signal(self, sa_sync_conn):
        """ORCID porté par une contribution WoS → ignoré comme signal de matching.

        L'ORCID WoS (`PreferredORCID`) est attribué par le matching algorithmique
        interne de Web of Science, régulièrement fautif. Même quand il pointe vers
        un ORCID confirmé en base, il ne doit pas rattacher la contribution (cf.
        `ORCID_MATCH_SOURCES`). Le nom ne matchant pas non plus → pas de
        rattachement à la personne seedée.
        """
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn,
            person_id,
            id_type="orcid",
            id_value="0000-0001-2345-6789",
            status="confirmed",
        )

        wos_source_record = _source_record(
            sa_sync_conn, publication, source="wos", source_id="WOS:111"
        )
        wos_as = _insert_contribution(
            sa_sync_conn,
            "wos",
            wos_source_record,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, wos_as) != person_id

    def test_datacite_orcid_links(self, sa_sync_conn):
        """ORCID DataCite, déposé avec l'enregistrement source → signal de matching. Hors périmètre, seul l'identifiant peut rattacher la contribution source."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn,
            person_id,
            id_type="orcid",
            id_value="0000-0001-2345-6789",
            status="confirmed",
        )

        dc_source_record = _source_record(
            sa_sync_conn, publication, source="datacite", source_id="10.5281/zenodo.1"
        )
        dc_as = _insert_contribution(
            sa_sync_conn,
            "datacite",
            dc_source_record,
            "Jean Dupont",
            in_perimeter=False,
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, dc_as) == person_id

    def test_name_form_match_imports_identifiers(self, sa_sync_conn):
        """Match par name_form → identifiers importés en pending (pour vérification
        manuelle ultérieure). Sans cet import, une base initialement vide n'aurait
        jamais d'identifiers, vu que la 1ère contribution créerait la personne et les
        suivantes (matching name_form) ne propageraient rien."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Martin", "Pierre", repo=person_repository(sa_sync_conn))

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W666"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
            "Pierre Martin",
            identifiers={"orcid": "0000-0002-3456-7890"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == person_id
        ids = _get_person_identifiers(sa_sync_conn, person_id)
        assert ("orcid", "0000-0002-3456-7890") in ids

    def test_inverted_name_matches_by_name_form(self, sa_sync_conn):
        """Contribution source au nom et prénom inversés (« Martin » en prénom, « Pierre » en nom) : sa forme « nom prénom » rejoint Pierre Martin."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Martin", "Pierre", repo=person_repository(sa_sync_conn))
        source_record = _source_record(
            sa_sync_conn, publication, source="crossref", source_id="10.1/inverse"
        )
        inverted = insert_source_contribution(
            sa_sync_conn,
            source_record,
            source="crossref",
            raw_last_name="Pierre",
            raw_first_name="Martin",
            author_name_normalized="martin pierre",
            in_perimeter=True,
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, inverted) == person_id

    def test_created_person_takes_split_given_by_source(self, sa_sync_conn):
        """Une chaîne brute « Yannick Kitutila W. » et la même contribution source au nom séparé (HAL : « Kitutila W. », « Yannick ») : la personne créée prend le découpage de la source, quel que soit l'ordre des contributions sources."""
        publication = insert_publication(sa_sync_conn)
        scanr_source_record = _source_record(
            sa_sync_conn, publication, source="scanr", source_id="scanr-kitutila"
        )
        hal_source_record = _source_record(sa_sync_conn, publication, source_id="hal-kitutila")
        parsed = insert_source_contribution(
            sa_sync_conn,
            scanr_source_record,
            source="scanr",
            raw_author_name="Yannick Kitutila W.",
            contributor_information_id=upsert_split_contributor_information(
                sa_sync_conn, "yannick kitutila", "w"
            ),
            in_perimeter=True,
        )
        native = insert_source_contribution(
            sa_sync_conn,
            hal_source_record,
            raw_last_name="Kitutila W.",
            raw_first_name="Yannick",
            contributor_information_id=upsert_split_contributor_information(
                sa_sync_conn, "kitutila w", "yannick"
            ),
            in_perimeter=True,
        )

        _run_cascade(sa_sync_conn)

        person_id = _get_person_id(sa_sync_conn, native)
        assert _get_person_id(sa_sync_conn, parsed) == person_id
        name = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": person_id}
        ).one()
        assert tuple(name) == ("Kitutila W.", "Yannick")

    def test_ambiguous_name_form_stays_orphan(self, sa_sync_conn):
        """Nom mappé à 2 personnes (homonymes) → skip, pas de rattachement."""
        publication = insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        # "J Dupont" devient ambigu (initiale J → match les deux)
        add_name_form(pid1, "J Dupont", repo=person_repository(sa_sync_conn))
        add_name_form(pid2, "J Dupont", repo=person_repository(sa_sync_conn))

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W777"
        )
        oa_as = _insert_contribution(sa_sync_conn, "openalex", oa_source_record, "J Dupont")

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) is None

    def test_ambiguous_orphan_logged_with_competing_persons(self, sa_sync_conn, caplog):
        """La contribution source restée orpheline est journalisée avec son motif et les personnes que désigne sa forme."""
        publication = insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W778"
        )
        orphan = _insert_contribution(sa_sync_conn, "openalex", source_record, "J Dupont")
        group_ungrouped(sa_sync_conn)

        with caplog.at_level(logging.INFO, logger="test_orphelines"):
            run_cascade(
                sa_sync_conn,
                _logger,
                repo=PgPersonRepository(sa_sync_conn),
                orphans_log=logging.getLogger("test_orphelines"),
            )

        (line,) = [r.getMessage() for r in caplog.records if r.name == "test_orphelines"]
        assert f"contribution source {orphan} (openalex)" in line
        assert "ambiguous_name_form" in line
        assert f"[{pid1}, {pid2}]" in line

    def test_rejected_pair_blocks_identifier_match(self, sa_sync_conn):
        """Paire (publi, personne) dans `rejected_contributions` → un match par
        identifiant vers cette personne est annulé. La cascade ne ré-attache
        pas le `person_id` rejeté à la `source_contribution`."""
        publication = insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        insert_person_identifier(
            sa_sync_conn,
            person_id,
            id_type="orcid",
            id_value="0000-0001-2345-6789",
            status="confirmed",
        )
        insert_rejected_contribution(
            sa_sync_conn, publication, person_id=person_id, ignore_conflict=True
        )

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W999"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
            "Toto Inconnu",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) != person_id

    def test_rejected_candidate_disambiguates_ambiguous_name_form(self, sa_sync_conn):
        """2 homonymes partagent la forme de nom ; l'un est rejeté pour la publi
        → l'élimination ne laisse qu'une candidate → match univoque vers l'autre
        (désambiguïsation par élimination)."""
        publication = insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        add_name_form(pid1, "J Dupont", repo=person_repository(sa_sync_conn))
        add_name_form(pid2, "J Dupont", repo=person_repository(sa_sync_conn))
        insert_rejected_contribution(
            sa_sync_conn, publication, person_id=pid1, ignore_conflict=True
        )

        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W778"
        )
        oa_as = _insert_contribution(sa_sync_conn, "openalex", oa_source_record, "J Dupont")

        _run_cascade(sa_sync_conn)

        assert _get_person_id(sa_sync_conn, oa_as) == pid2

    def test_unknown_name_creates_person_with_identifiers(self, sa_sync_conn):
        """Forme inconnue + contribution-auteur → crée la personne et importe ses
        identifiants."""
        publication = insert_publication(sa_sync_conn)
        oa_source_record = _source_record(
            sa_sync_conn, publication, source="openalex", source_id="W888"
        )
        oa_as = _insert_contribution(
            sa_sync_conn,
            "openalex",
            oa_source_record,
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
