"""Intégration : phase `author_grouping`, sur vraie base (`conn.commit` neutralisé)."""

import logging

import pytest
from sqlalchemy import text

from infrastructure.read_models.publications.suspect_merges import (
    suspect_merges,
    suspect_merges_count,
)
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.author_grouping.author_grouping import build_groups
from pipeline.transformation.publications.author_grouping.queries import AuthorGroupingQueries
from tests.integration.helpers.contributions import upsert_split_identity
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record

logger = logging.getLogger("test_author_grouping")


@pytest.fixture
def conn(sa_sync_conn, monkeypatch):
    monkeypatch.setattr(sa_sync_conn, "commit", lambda: None)
    return sa_sync_conn


def _notice(conn, publication_id, source, source_id, names, roles=None, positions=True):
    """Notice et ses signatures, à partir de couples (patronyme, prénom). Rend les identifiants des signatures."""
    notice = insert_source_record(conn, publication_id, source=source, source_id=source_id)
    return [
        insert_signature(
            conn,
            notice,
            source=source,
            author_position=pos if positions else None,
            contributor_information_id=upsert_split_identity(conn, last, first),
            roles=roles,
        )
        for pos, (last, first) in enumerate(names)
    ]


def _groups(conn, publication_id):
    """Signatures de chaque groupe de la publication : identifiant de groupe → ensemble de signatures."""
    rows = conn.execute(
        text("""
            SELECT g.id, gs.source_contribution_id FROM source_contribution_groups g
            JOIN source_contribution_group_members gs ON gs.group_id = g.id
            WHERE g.publication_id = :p
        """),
        {"p": publication_id},
    ).all()
    out: dict[int, set[int]] = {}
    for gid, sig in rows:
        out.setdefault(gid, set()).add(sig)
    return out


def _run(conn):
    return build_groups(conn, AuthorGroupingQueries(), logger)


def test_un_identifiant_neutralise_reste_hors_de_l_alignement(conn):
    pub = insert_publication(conn)
    notice = insert_source_record(conn, pub, source="crossref", source_id="c-neutre")
    signature = insert_signature(
        conn,
        notice,
        source="crossref",
        author_name_normalized="jean dupont",
        identifiers={"orcid": "0000-0001-2345-6789", "idref": "123456789"},
        neutralized_identifiers={"orcid": "shared", "idref": "misplaced"},
    )

    [row] = AuthorGroupingQueries().fetch_signatures(conn, [pub])

    assert (row.id, row.orcid, row.idref) == (signature, "", "")


def test_les_signatures_d_un_meme_auteur_sont_groupees(conn):
    pub = insert_publication(conn)
    hal = _notice(conn, pub, "hal", "hal-1", [("martin", "anne"), ("petit", "b"), ("durand", "c")])
    oa = _notice(conn, pub, "openalex", "W1", [("martin", "a"), ("durand", "c")])

    metrics = _run(conn)

    groups = sorted(_groups(conn, pub).values(), key=min)
    assert groups == [{hal[0], oa[0]}, {hal[1]}, {hal[2], oa[1]}]
    assert metrics.details["summary"] == {"publications": 1, "groups": 3, "reference": 3, "name": 2}
    dirty = conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": pub}
    )
    assert dirty.scalar_one() is False


def test_un_recalcul_garde_l_identifiant_et_la_personne_des_groupes(conn):
    pub = insert_publication(conn)
    hal = _notice(conn, pub, "hal", "hal-1", [("martin", "anne"), ("petit", "b")])
    _notice(conn, pub, "openalex", "W1", [("martin", "a")])
    _run(conn)
    martin = next(gid for gid, sigs in _groups(conn, pub).items() if hal[0] in sigs)
    person = insert_person(conn, "Martin", first_name="Anne")
    conn.execute(
        text("UPDATE source_contribution_groups SET person_id = :person WHERE id = :g"),
        {"person": person, "g": martin},
    )
    _notice(conn, pub, "crossref", "10.1/x", [("martin", "a"), ("petit", "b")])
    conn.execute(
        text("UPDATE publications SET contributions_dirty = true WHERE id = :p"), {"p": pub}
    )

    _run(conn)

    groups = _groups(conn, pub)
    assert hal[0] in groups[martin] and len(groups[martin]) == 3
    kept = conn.execute(
        text("SELECT person_id FROM source_contribution_groups WHERE id = :g"), {"g": martin}
    )
    assert kept.scalar_one() == person


def test_un_recalcul_sans_changement_laisse_les_appartenances_en_place(conn):
    pub = insert_publication(conn)
    _notice(conn, pub, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")])
    _notice(conn, pub, "openalex", "W1", [("martin", "a"), ("petit", "b")])
    _run(conn)
    tuples = "SELECT source_contribution_id, ctid::text FROM source_contribution_group_members"
    before = dict(conn.execute(text(tuples)).all())
    conn.execute(
        text("UPDATE publications SET contributions_dirty = true WHERE id = :p"), {"p": pub}
    )

    _run(conn)

    assert dict(conn.execute(text(tuples)).all()) == before


def test_une_notice_deplacee_quitte_les_groupes_de_sa_publication(conn, monkeypatch):
    """Régression : la publication d'arrivée est traitée dans un lot antérieur à celle de départ, dont un groupe contient encore la signature."""
    monkeypatch.setattr(author_grouping, "BATCH_SIZE", 1)
    arrival = insert_publication(conn)
    departure = insert_publication(conn)
    _notice(conn, arrival, "hal", "hal-1", [("martin", "anne")])
    moved = _notice(conn, departure, "openalex", "W1", [("martin", "a")])
    _notice(conn, departure, "crossref", "10.1/x", [("martin", "a")])
    _run(conn)
    conn.execute(
        text("UPDATE source_records SET publication_id = :p WHERE source_id = 'W1'"),
        {"p": arrival},
    )
    conn.execute(text("UPDATE publications SET contributions_dirty = true"))

    _run(conn)

    assert any(moved[0] in sigs for sigs in _groups(conn, arrival).values())
    assert all(moved[0] not in sigs for sigs in _groups(conn, departure).values())


def test_les_groupes_d_une_publication_supprimee_sont_supprimes(conn):
    pub = insert_publication(conn)
    _notice(conn, pub, "hal", "hal-1", [("martin", "anne")])
    _notice(conn, pub, "openalex", "W1", [("martin", "a")])
    _run(conn)
    conn.execute(text("DELETE FROM source_records WHERE publication_id = :p"), {"p": pub})
    conn.execute(text("DELETE FROM publications WHERE id = :p"), {"p": pub})

    _run(conn)

    assert _groups(conn, pub) == {}
    orphans = conn.execute(
        text("""
            SELECT count(*) FROM source_contribution_group_members gs
            WHERE NOT EXISTS (SELECT 1 FROM source_contribution_groups g WHERE g.id = gs.group_id)
        """)
    )
    assert orphans.scalar_one() == 0


def test_a_longueur_egale_scanr_ne_sert_pas_de_reference(conn):
    pub = insert_publication(conn)
    scanr = _notice(
        conn, pub, "scanr", "doi10.1/x", [("hollandts", "xavier"), ("hollandts", "xavier")]
    )
    crossref = _notice(
        conn, pub, "crossref", "10.1/x", [("valiorgue", "bertrand"), ("hollandts", "xavier")]
    )
    assert scanr[0] < crossref[0]

    _run(conn)

    references = conn.execute(
        text("""
            SELECT gs.source_contribution_id FROM source_contribution_group_members gs
            JOIN source_contribution_groups g ON g.id = gs.group_id
            WHERE g.publication_id = :p AND gs.method = 'reference'
        """),
        {"p": pub},
    ).scalars()
    assert set(crossref) <= set(references)


def test_la_file_des_fusions_suspectes_retient_les_listes_disjointes(conn):
    """Deux œuvres réunies à tort : aucune signature d'auteur n'a de correspondant dans l'autre notice. La publication bien alignée reste hors de la file."""
    merged = insert_publication(conn)
    _notice(conn, merged, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")])
    _notice(conn, merged, "openalex", "W1", [("durand", "claire"), ("leroy", "denis")])
    aligned = insert_publication(conn)
    _notice(conn, aligned, "hal", "hal-2", [("martin", "anne"), ("petit", "bruno")])
    _notice(conn, aligned, "openalex", "W2", [("martin", "a"), ("petit", "b")])

    _run(conn)

    assert suspect_merges_count(conn) == 1
    [suspect] = suspect_merges(conn, page=1, per_page=10).publications
    assert (suspect.publication_id, suspect.signatures, suspect.matched_source_contributions) == (
        merged,
        4,
        0,
    )
    assert sorted((n.source, n.matched_source_contributions) for n in suspect.notices) == [
        ("hal", 0),
        ("openalex", 0),
    ]


def _duplicate_of(conn, signatures):
    rows = conn.execute(
        text("SELECT id, duplicate_of FROM source_contributions WHERE id = ANY(:ids)"),
        {"ids": signatures},
    )
    return dict(rows.all())


def test_les_copies_d_une_liste_restent_hors_des_groupes(conn):
    pub = insert_publication(conn)
    names = [("martin", "anne"), ("petit", "bruno"), ("durand", "claire")]
    hal = _notice(conn, pub, "hal", "hal-1", names + names)
    oa = _notice(conn, pub, "openalex", "W1", names)

    _run(conn)

    originals = dict.fromkeys(hal[:3])
    copies = dict(zip(hal[3:], hal[:3], strict=True))
    assert _duplicate_of(conn, hal) == originals | copies
    assert sorted(_groups(conn, pub).values(), key=min) == [{hal[i], oa[i]} for i in range(3)]


def test_une_signature_qui_n_est_plus_copiee_perd_son_duplicate_of(conn):
    pub = insert_publication(conn)
    hal = _notice(conn, pub, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")])
    conn.execute(
        text("UPDATE source_contributions SET duplicate_of = :a WHERE id = :b"),
        {"a": hal[0], "b": hal[1]},
    )

    _run(conn)

    assert _duplicate_of(conn, hal) == {hal[0]: None, hal[1]: None}


def test_les_roles_s_alignent_ensemble(conn):
    """Régression : un conseiller scientifique HAL (`sad`) reste à part de la même personne, auteur chez OpenAlex."""
    pub = insert_publication(conn)
    names = [("bahier porte", "christelle"), ("schweitzer", "zoe")]
    hal = _notice(conn, pub, "hal", "ujm-1", names, roles=["contributor"])
    oa = _notice(conn, pub, "openalex", "W1", [("ferrier", "beatrice"), *names])

    _run(conn)

    groups = _groups(conn, pub).values()
    assert {hal[0], oa[1]} in groups and {hal[1], oa[2]} in groups


def test_le_jury_sans_position_s_aligne_par_le_nom(conn):
    pub = insert_publication(conn)
    theses = _notice(
        conn,
        pub,
        "theses",
        "2020UCFA0001",
        [("durand", "paul"), ("dupont", "jean")],
        roles=["thesis_director"],
        positions=False,
    )
    hal = _notice(conn, pub, "hal", "tel-1", [("dupont", "j")], roles=["thesis_director"])

    _run(conn)

    assert {theses[1], hal[0]} in _groups(conn, pub).values()


_ORCID = "0000-0002-1825-0097"


def _homonyms_with_orcid(conn, status):
    """Deux homonymes de même initiale dans la notice HAL. La notice OpenAlex a une signature réduite à l'initiale, dont l'ORCID est rattaché avec `status` à une personne du prénom du second."""
    pub = insert_publication(conn)
    hal = _notice(conn, pub, "hal", "hal-1", [("xu", "zhihao"), ("xu", "zehua")])
    notice = insert_source_record(conn, pub, source="openalex", source_id="W1")
    identity = upsert_split_identity(conn, "xu", "z", {"orcid": _ORCID})
    oa = insert_signature(conn, notice, source="openalex", contributor_information_id=identity)
    person = insert_person(conn, "Xu", first_name="Zehua")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status=status)
    return pub, hal, oa


def test_le_prenom_d_un_identifiant_confirme_aligne_les_initiales(conn):
    pub, hal, oa = _homonyms_with_orcid(conn, "confirmed")

    _run(conn)

    assert {hal[1], oa} in _groups(conn, pub).values()


def test_le_prenom_d_un_identifiant_en_attente_reste_ignore(conn):
    pub, hal, oa = _homonyms_with_orcid(conn, "pending")

    _run(conn)

    assert {hal[0], oa} in _groups(conn, pub).values()


def _dirty(conn, publication_id):
    return conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication_id}
    ).scalar_one()


def test_une_decision_sur_l_identifiant_marque_la_publication_a_regrouper(conn):
    pub, _, _ = _homonyms_with_orcid(conn, "pending")
    _run(conn)

    conn.execute(
        text("UPDATE person_identifiers SET status = 'confirmed' WHERE id_value = :v"),
        {"v": _ORCID},
    )

    assert _dirty(conn, pub) is True


def test_un_changement_de_prenom_marque_la_publication_a_regrouper(conn):
    pub, _, _ = _homonyms_with_orcid(conn, "confirmed")
    _run(conn)

    conn.execute(
        text(
            "UPDATE persons SET first_name_normalized = 'zhihao'"
            " WHERE id = (SELECT person_id FROM person_identifiers WHERE id_value = :v)"
        ),
        {"v": _ORCID},
    )

    assert _dirty(conn, pub) is True
