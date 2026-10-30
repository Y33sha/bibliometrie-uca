"""Phase `author_grouping`, sans validation de la transaction (`conn.commit` neutralisé)."""

import logging

import pytest
from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.author_grouping.author_grouping import build_contributions
from pipeline.transformation.publications.author_grouping.store import AuthorGroupingStore
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import mark, queued
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

logger = logging.getLogger("test_author_grouping")


@pytest.fixture
def conn(sa_sync_conn, monkeypatch):
    monkeypatch.setattr(sa_sync_conn, "commit", lambda: None)
    return sa_sync_conn


def _source_record(conn, publication_id, source, source_id, names, roles=None, positions=True):
    """Insère un enregistrement source et ses contributions sources, à partir de couples (nom de famille, prénom). Renvoie les identifiants des contributions sources."""
    source_record = insert_source_record(conn, publication_id, source=source, source_id=source_id)
    return [
        insert_source_contribution(
            conn,
            source_record,
            source=source,
            author_position=pos if positions else None,
            contributor_information_id=upsert_split_contributor_information(conn, last, first),
            roles=roles,
        )
        for pos, (last, first) in enumerate(names)
    ]


def _contributions(conn, publication_id):
    """Renvoie les contributions sources de chaque contribution de la publication : identifiant de contribution → ensemble de contributions sources."""
    rows = conn.execute(
        text("""
            SELECT g.id, gs.source_contribution_id FROM contributions g
            JOIN aligned_source_contributions gs ON gs.contribution_id = g.id
            WHERE g.publication_id = :p
        """),
        {"p": publication_id},
    ).all()
    out: dict[int, set[int]] = {}
    for gid, source_contribution_id in rows:
        out.setdefault(gid, set()).add(source_contribution_id)
    return out


def _run(conn):
    return build_contributions(conn, AuthorGroupingStore(conn), logger)


def test_un_identifiant_neutralise_reste_hors_de_l_alignement(conn):
    publication = insert_publication(conn)
    source_record = insert_source_record(conn, publication, source="crossref", source_id="c-neutre")
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        source="crossref",
        author_name_normalized="jean dupont",
        identifiers={"orcid": "0000-0001-2345-6789", "idref": "123456789"},
        neutralized_identifiers={"orcid": "shared", "idref": "misplaced"},
    )

    [row] = AuthorGroupingStore(conn).fetch_source_contributions([publication])

    assert (row.id, row.orcid, row.idref) == (source_contribution, "", "")


def test_les_contributions_sources_d_un_meme_auteur_sont_alignees(conn):
    publication = insert_publication(conn)
    hal = _source_record(
        conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "b"), ("durand", "c")]
    )
    oa = _source_record(conn, publication, "openalex", "W1", [("martin", "a"), ("durand", "c")])

    metrics = _run(conn)

    contributions = sorted(_contributions(conn, publication).values(), key=min)
    assert contributions == [{hal[0], oa[0]}, {hal[1]}, {hal[2], oa[1]}]
    assert metrics.details["summary"] == {"publications": 1, "groups": 3, "reference": 3, "name": 2}
    assert publication not in queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)


def _attached_contribution(conn, publication, source_contribution):
    """Rattache à une personne la contribution de `source_contribution` et renvoie son identifiant."""
    contribution = next(
        gid
        for gid, members in _contributions(conn, publication).items()
        if source_contribution in members
    )
    person = insert_person(conn, "Martin", first_name="Anne")
    conn.execute(
        text(
            "UPDATE contributions SET person_id = :person, resolution_mode = 'name' WHERE id = :g"
        ),
        {"person": person, "g": contribution},
    )
    mark(conn, Queue.PUBLICATION_CONTRIBUTIONS, [publication])
    return contribution, person


def _contribution_person(conn, contribution):
    return conn.execute(
        text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
        {"g": contribution},
    ).one()


def test_une_contribution_aux_contributions_sources_inchangees_garde_sa_personne(conn):
    publication = insert_publication(conn)
    hal = _source_record(conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "b")])
    _source_record(conn, publication, "openalex", "W1", [("martin", "a")])
    _run(conn)
    martin, person = _attached_contribution(conn, publication, hal[0])

    _run(conn)

    assert tuple(_contribution_person(conn, martin)) == (person, "name")


def test_une_contribution_recomposee_garde_son_identifiant_et_sa_personne_et_entre_dans_la_file(
    conn,
):
    """Un enregistrement source ajouté à la publication étend la contribution, qui garde son identifiant et sa personne ; sa personne est à redécider."""
    publication = insert_publication(conn)
    hal = _source_record(conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "b")])
    _source_record(conn, publication, "openalex", "W1", [("martin", "a")])
    _run(conn)
    martin, person = _attached_contribution(conn, publication, hal[0])
    _source_record(conn, publication, "crossref", "10.1/x", [("martin", "a"), ("petit", "b")])

    _run(conn)

    contributions = _contributions(conn, publication)
    assert hal[0] in contributions[martin] and len(contributions[martin]) == 3
    assert tuple(_contribution_person(conn, martin)) == (person, "name")
    assert martin in queued(conn, Queue.CONTRIBUTION_RESOLUTION)


def test_un_recalcul_sans_changement_laisse_les_appartenances_en_place(conn):
    publication = insert_publication(conn)
    _source_record(conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")])
    _source_record(conn, publication, "openalex", "W1", [("martin", "a"), ("petit", "b")])
    _run(conn)
    tuples = "SELECT source_contribution_id, ctid::text FROM aligned_source_contributions"
    before = dict(conn.execute(text(tuples)).all())
    mark(conn, Queue.PUBLICATION_CONTRIBUTIONS, [publication])

    _run(conn)

    assert dict(conn.execute(text(tuples)).all()) == before


def test_la_reconstruction_realigne_les_publications_non_marquees(conn):
    publication = insert_publication(conn)
    _source_record(conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "b")])
    _source_record(conn, publication, "openalex", "W1", [("martin", "a"), ("petit", "b")])
    _run(conn)
    conn.execute(text("DELETE FROM contributions WHERE publication_id = :p"), {"p": publication})

    metrics = build_contributions(conn, AuthorGroupingStore(conn), logger, rebuild=True)

    assert metrics.details["summary"]["publications"] >= 1
    assert len(_contributions(conn, publication)) == 2


def test_un_enregistrement_source_deplace_quitte_les_contributions_de_sa_publication(
    conn, monkeypatch
):
    """La contribution source passe aux contributions de la publication d'arrivée, même traitée dans un lot antérieur à la publication de départ."""
    monkeypatch.setattr(author_grouping, "BATCH_SIZE", 1)
    arrival = insert_publication(conn)
    departure = insert_publication(conn)
    _source_record(conn, arrival, "hal", "hal-1", [("martin", "anne")])
    moved = _source_record(conn, departure, "openalex", "W1", [("martin", "a")])
    _source_record(conn, departure, "crossref", "10.1/x", [("martin", "a")])
    _run(conn)
    conn.execute(
        text("UPDATE source_records SET publication_id = :p WHERE source_id = 'W1'"),
        {"p": arrival},
    )
    mark(conn, Queue.PUBLICATION_CONTRIBUTIONS, [arrival, departure])

    _run(conn)

    assert any(moved[0] in members for members in _contributions(conn, arrival).values())
    assert all(moved[0] not in members for members in _contributions(conn, departure).values())


def test_les_contributions_d_une_publication_supprimee_sont_supprimees(conn):
    publication = insert_publication(conn)
    _source_record(conn, publication, "hal", "hal-1", [("martin", "anne")])
    _source_record(conn, publication, "openalex", "W1", [("martin", "a")])
    _run(conn)
    conn.execute(text("DELETE FROM source_records WHERE publication_id = :p"), {"p": publication})
    conn.execute(text("DELETE FROM publications WHERE id = :p"), {"p": publication})

    _run(conn)

    assert _contributions(conn, publication) == {}
    orphans = conn.execute(
        text("""
            SELECT count(*) FROM aligned_source_contributions gs
            WHERE NOT EXISTS (SELECT 1 FROM contributions g WHERE g.id = gs.contribution_id)
        """)
    )
    assert orphans.scalar_one() == 0


def test_a_longueur_egale_scanr_ne_sert_pas_de_reference(conn):
    publication = insert_publication(conn)
    scanr = _source_record(
        conn, publication, "scanr", "doi10.1/x", [("hollandts", "xavier"), ("hollandts", "xavier")]
    )
    crossref = _source_record(
        conn,
        publication,
        "crossref",
        "10.1/x",
        [("valiorgue", "bertrand"), ("hollandts", "xavier")],
    )
    assert scanr[0] < crossref[0]

    _run(conn)

    references = conn.execute(
        text("""
            SELECT gs.source_contribution_id FROM aligned_source_contributions gs
            JOIN contributions g ON g.id = gs.contribution_id
            WHERE g.publication_id = :p AND gs.method = 'reference'
        """),
        {"p": publication},
    ).scalars()
    assert set(crossref) <= set(references)


def test_scanr_issu_d_un_depot_hal_present_s_aligne(conn):
    publication = insert_publication(conn)
    hal = _source_record(conn, publication, "hal", "hal-01234567", [("martin", "anne")])
    scanr = _source_record(conn, publication, "scanr", "halhal-01234567", [("martin", "anne")])

    _run(conn)

    assert {hal[0], scanr[0]} in _contributions(conn, publication).values()


def test_la_file_des_fusions_suspectes_retient_les_listes_disjointes(conn):
    """Deux œuvres réunies à tort : aucune contribution source d'auteur n'a de correspondant dans l'autre enregistrement source. La publication bien alignée reste hors de la file."""
    merged = insert_publication(conn)
    _source_record(conn, merged, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")])
    _source_record(conn, merged, "openalex", "W1", [("durand", "claire"), ("leroy", "denis")])
    aligned = insert_publication(conn)
    _source_record(conn, aligned, "hal", "hal-2", [("martin", "anne"), ("petit", "bruno")])
    _source_record(conn, aligned, "openalex", "W2", [("martin", "a"), ("petit", "b")])

    _run(conn)

    queries = publications_queries(conn)
    assert queries.suspect_merges_count() == 1
    [suspect] = queries.suspect_merges(page=1, per_page=10).publications
    assert (
        suspect.publication_id,
        suspect.source_contributions,
        suspect.matched_source_contributions,
    ) == (
        merged,
        4,
        0,
    )
    assert sorted((n.source, n.matched_source_contributions) for n in suspect.source_records) == [
        ("hal", 0),
        ("openalex", 0),
    ]


def _duplicate_of(conn, source_contributions):
    rows = conn.execute(
        text("SELECT id, duplicate_of FROM source_contributions WHERE id = ANY(:ids)"),
        {"ids": source_contributions},
    )
    return dict(rows.all())


def test_les_copies_d_une_liste_restent_hors_des_contributions(conn):
    publication = insert_publication(conn)
    names = [("martin", "anne"), ("petit", "bruno"), ("durand", "claire")]
    hal = _source_record(conn, publication, "hal", "hal-1", names + names)
    oa = _source_record(conn, publication, "openalex", "W1", names)

    _run(conn)

    originals = dict.fromkeys(hal[:3])
    copies = dict(zip(hal[3:], hal[:3], strict=True))
    assert _duplicate_of(conn, hal) == originals | copies
    assert sorted(_contributions(conn, publication).values(), key=min) == [
        {hal[i], oa[i]} for i in range(3)
    ]


def test_une_contribution_source_qui_n_est_plus_copiee_perd_son_duplicate_of(conn):
    publication = insert_publication(conn)
    hal = _source_record(
        conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "bruno")]
    )
    conn.execute(
        text("UPDATE source_contributions SET duplicate_of = :a WHERE id = :b"),
        {"a": hal[0], "b": hal[1]},
    )

    _run(conn)

    assert _duplicate_of(conn, hal) == {hal[0]: None, hal[1]: None}


def test_les_roles_s_alignent_ensemble(conn):
    """Un conseiller scientifique HAL (`sad`) s'aligne avec la même personne, auteur chez OpenAlex."""
    publication = insert_publication(conn)
    names = [("bahier porte", "christelle"), ("schweitzer", "zoe")]
    hal = _source_record(conn, publication, "hal", "ujm-1", names, roles=["contributor"])
    oa = _source_record(conn, publication, "openalex", "W1", [("ferrier", "beatrice"), *names])

    _run(conn)

    contributions = _contributions(conn, publication).values()
    assert {hal[0], oa[1]} in contributions and {hal[1], oa[2]} in contributions


def test_le_jury_sans_position_s_aligne_par_le_nom(conn):
    publication = insert_publication(conn)
    theses = _source_record(
        conn,
        publication,
        "theses",
        "2020UCFA0001",
        [("durand", "paul"), ("dupont", "jean")],
        roles=["thesis_director"],
        positions=False,
    )
    hal = _source_record(
        conn, publication, "hal", "tel-1", [("dupont", "j")], roles=["thesis_director"]
    )

    _run(conn)

    assert {theses[1], hal[0]} in _contributions(conn, publication).values()


_ORCID = "0000-0002-1825-0097"


def _homonyms_with_orcid(conn, status):
    """Insère deux homonymes de même initiale dans l'enregistrement source HAL. L'enregistrement source OpenAlex a une contribution source réduite à l'initiale. Son ORCID est rattaché avec `status` à une personne du prénom du second."""
    publication = insert_publication(conn)
    hal = _source_record(conn, publication, "hal", "hal-1", [("xu", "zhihao"), ("xu", "zehua")])
    source_record = insert_source_record(conn, publication, source="openalex", source_id="W1")
    information_id = upsert_split_contributor_information(conn, "xu", "z", {"orcid": _ORCID})
    oa = insert_source_contribution(
        conn, source_record, source="openalex", contributor_information_id=information_id
    )
    person = insert_person(conn, "Xu", first_name="Zehua")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status=status)
    return publication, hal, oa


def test_le_prenom_d_un_identifiant_confirme_aligne_les_initiales(conn):
    publication, hal, oa = _homonyms_with_orcid(conn, "confirmed")

    _run(conn)

    assert {hal[1], oa} in _contributions(conn, publication).values()


def test_le_prenom_d_un_identifiant_en_attente_reste_ignore(conn):
    publication, hal, oa = _homonyms_with_orcid(conn, "pending")

    _run(conn)

    assert {hal[0], oa} in _contributions(conn, publication).values()


def _dirty(conn, publication_id):
    return publication_id in queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)


def test_l_alignement_marque_les_contributions_pour_la_recomposition_de_leurs_attributs(conn):
    publication = insert_publication(conn)
    _source_record(conn, publication, "hal", "hal-1", [("martin", "anne"), ("petit", "b")])

    _run(conn)

    contributions = set(_contributions(conn, publication))
    assert len(contributions) == 2
    assert queued(conn, Queue.CONTRIBUTION_ATTRIBUTES) == contributions


def test_le_marquage_d_une_publication_supprimee_est_ignore_puis_supprime(conn):
    publication = insert_publication(conn)
    conn.execute(text("DELETE FROM publications WHERE id = :p"), {"p": publication})
    assert _dirty(conn, publication)

    metrics = _run(conn)

    assert metrics.seen == 0
    assert not _dirty(conn, publication)


def test_un_marquage_fait_pendant_l_alignement_reste_en_file(conn):
    """Le marquage d'une publication marquée de nouveau après le relevé de la file survit à l'effacement des marquages traités."""
    publication = insert_publication(conn)
    store = AuthorGroupingStore(conn)
    store.snapshot_queued_publications()
    mark(conn, Queue.PUBLICATION_CONTRIBUTIONS, [publication])

    store.delete_processed_marks([publication])
    store.drop_snapshot()

    assert _dirty(conn, publication)


def test_une_decision_sur_l_identifiant_marque_la_publication_a_realigner(conn):
    publication, _, _ = _homonyms_with_orcid(conn, "pending")
    _run(conn)

    conn.execute(
        text("UPDATE person_identifiers SET status = 'confirmed' WHERE id_value = :v"),
        {"v": _ORCID},
    )

    assert _dirty(conn, publication) is True


def test_un_changement_de_prenom_marque_la_publication_a_realigner(conn):
    publication, _, _ = _homonyms_with_orcid(conn, "confirmed")
    _run(conn)

    conn.execute(
        text(
            "UPDATE persons SET first_name_normalized = 'zhihao'"
            " WHERE id = (SELECT person_id FROM person_identifiers WHERE id_value = :v)"
        ),
        {"v": _ORCID},
    )

    assert _dirty(conn, publication) is True
