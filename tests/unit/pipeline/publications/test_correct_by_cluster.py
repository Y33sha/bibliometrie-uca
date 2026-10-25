"""Tests purs : corrections de DOI par cluster (convergence même-œuvre, ouvrage/chapitre,
chapitre/chapitre, volume d'actes/communication) + `compute_updates`."""

from domain.source_records.corrections import stash_entry
from domain.source_records.metadata_correction.shared_doi import (
    DoiClusterCase,
    DoiClusterDecision,
    DoiClusterMember,
    resolve_cluster_doi_corrections,
)
from pipeline.transformation.publications.correction.correct_by_cluster import (
    compute_updates,
    tally_doi_corrections,
)
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
)


def test_tally_doi_corrections_par_cas():
    updates = [
        DoiCorrectionUpdate(
            1, "10.9005/c", {"doi": stash_entry("10.9005/v1", "DATACITE_VERSION_TO_CONCEPT")}, {}
        ),
        DoiCorrectionUpdate(
            2, "10.9005/d", {"doi": stash_entry("10.9005/v2", "DATACITE_VERSION_TO_CONCEPT")}, {}
        ),
        DoiCorrectionUpdate(
            3, None, {"doi": stash_entry("10.9006/book", "OUVRAGE_VS_CHAPITRE")}, {}
        ),
    ]
    assert tally_doi_corrections(updates) == {
        "DATACITE_VERSION_TO_CONCEPT": 2,
        "OUVRAGE_VS_CHAPITRE": 1,
    }


def _row(
    row_id,
    doc_type,
    doi,
    title=None,
    corrections=None,
    raw_doi="10.1/x",
    canonical_doi=None,
    same_work_case=None,
    external_ids=None,
) -> DoiClusterRow:
    return DoiClusterRow(
        row_id,
        doc_type,
        doi,
        f"titre {'abcdefghij'[row_id % 10]}" if title is None else title,
        corrections or {},
        raw_doi,
        canonical_doi,
        same_work_case,
        external_ids=external_ids or {},
    )


_OWN_TITLE = object()


def _m(
    member_id, doc_type, title=_OWN_TITLE, canonical_doi=None, same_work_case=None
) -> DoiClusterMember:
    """Membre de groupe ; sans titre donné, chaque membre a le sien."""
    if title is _OWN_TITLE:
        title = f"titre {'abcdefghij'[member_id % 10]}"
    return DoiClusterMember(member_id, doc_type, title, canonical_doi, same_work_case)


def _resoudre(group, shared_doi="10.1/x"):
    """Décision pour un groupe dont le DOI partagé importe peu au cas testé."""
    return resolve_cluster_doi_corrections(group, shared_doi=shared_doi)


def test_un_doi_inconnu_de_doi_org_est_nulle_sur_tous_les_membres_avant_toute_autre_regle():
    group = [
        _m(1, "book"),
        _m(2, "book_chapter"),
        _m(
            3,
            "dataset",
            canonical_doi="10.1/c",
            same_work_case=DoiClusterCase.DATACITE_PACKAGE_PIECE,
        ),
    ]
    decisions = resolve_cluster_doi_corrections(group, shared_doi="10.1/x", unresolved=True)
    assert decisions == [
        DoiClusterDecision(i, None, DoiClusterCase.UNRESOLVED_DOI_TO_NULL) for i in (1, 2, 3)
    ]


# ── domaine pur : convergence même-œuvre ─────────────────────────────────


def test_same_work_all_converge_on_canonical():
    # Un membre (datacite) porte le DOI canonique + son cas ; tous convergent dessus.
    group = [
        _m(
            1,
            "dataset",
            canonical_doi="10.5281/zenodo.1",
            same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
        ),
        _m(2, "dataset"),
    ]
    assert _resoudre(group, "10.5281/zenodo.10") == [
        DoiClusterDecision(1, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
        DoiClusterDecision(2, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
    ]


def test_same_work_carries_its_case():
    # Le cas porté par le membre est restitué (variante, pièce de package…).
    for case in (DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY, DoiClusterCase.DATACITE_PACKAGE_PIECE):
        group = [_m(1, "dataset", canonical_doi="10.9/canon", same_work_case=case)]
        assert _resoudre(group, "10.9/forme") == [DoiClusterDecision(1, "10.9/canon", case)]


def test_same_work_takes_precedence_over_book_chapter():
    group = [
        _m(
            1,
            "book",
            canonical_doi="10.5281/zenodo.1",
            same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
        ),
        _m(2, "book_chapter"),
    ]
    cases = {d.case for d in _resoudre(group, "10.5281/zenodo.10")}
    assert cases == {DoiClusterCase.DATACITE_VERSION_TO_CONCEPT}


def test_version_d_un_autre_prefixe_reste_distincte():
    """Un preprint arXiv déclare `IsVersionOf` vers l'article publié : deux œuvres, pas une."""
    group = [
        _m(
            1,
            "article",
            canonical_doi="10.1007/jhep07(2023)066",
            same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
        ),
        _m(2, "preprint"),
    ]
    assert _resoudre(group, "10.48550/arxiv.2210.12000") == []


def test_copie_de_l_article_d_un_autre_prefixe_converge():
    """Une copie déposée à RWTH déclare `IsVariantFormOf` vers l'article publié : une seule œuvre."""
    group = [
        _m(
            1,
            "article",
            canonical_doi="10.1103/physrevd.105.012010",
            same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
        ),
    ]
    assert _resoudre(group, "10.18154/rwth-2022-02923") == [
        DoiClusterDecision(
            1, "10.1103/physrevd.105.012010", DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY
        )
    ]


def test_copie_de_preprint_d_un_autre_prefixe_reste_distincte():
    """Un working paper déposé au DESY déclare `IsVariantFormOf` vers l'article publié : deux œuvres."""
    group = [
        _m(
            1,
            "preprint",
            canonical_doi="10.1140/epjc/s10052-017-5315-6",
            same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
        ),
    ]
    assert _resoudre(group, "10.3204/pubdb-2017-13318") == []


def test_copie_de_preprint_du_meme_prefixe_converge():
    group = [
        _m(
            1,
            "preprint",
            canonical_doi="10.5281/zenodo.1",
            same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
        ),
    ]
    assert _resoudre(group, "10.5281/zenodo.2") == [
        DoiClusterDecision(1, "10.5281/zenodo.1", DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY)
    ]


def test_variante_du_meme_prefixe_converge():
    """Une version de logiciel Zenodo déclarée `IsVariantFormOf` rejoint son concept."""
    group = [
        _m(
            1,
            "software",
            canonical_doi="10.5281/zenodo.13354942",
            same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
        ),
    ]
    assert _resoudre(group, "10.5281/zenodo.17224613") == [
        DoiClusterDecision(1, "10.5281/zenodo.13354942", DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY)
    ]


def test_piece_de_dataset_converge_quel_que_soit_le_prefixe():
    """Une pièce rejoint son dataset parent, dont le DOI prend souvent une autre forme."""
    group = [
        _m(
            1,
            "dataset",
            canonical_doi="10.1594/pangaea.1",
            same_work_case=DoiClusterCase.DATACITE_PACKAGE_PIECE,
        ),
    ]
    assert _resoudre(group, "10.15454/fichier") == [
        DoiClusterDecision(1, "10.1594/pangaea.1", DoiClusterCase.DATACITE_PACKAGE_PIECE)
    ]


def test_version_d_un_autre_prefixe_laisse_les_regles_ouvrage_s_appliquer():
    """Sans convergence, un groupe ouvrage + chapitre reste traité comme tel."""
    group = [
        _m(
            1,
            "book",
            canonical_doi="10.1007/autre",
            same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
        ),
        _m(2, "book_chapter"),
    ]
    assert _resoudre(group, "10.4000/livre") == [
        DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)
    ]


# ── domaine pur : ouvrage/chapitre (divergence) ──────────────────────────


def test_book_and_chapter_chapter_loses_doi():
    group = [_m(1, "book"), _m(2, "book_chapter")]
    assert _resoudre(group) == [DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)]


def test_chapitre_au_titre_de_l_ouvrage_garde_le_doi():
    """Même œuvre typée livre par une source et chapitre par une autre : rien à corriger."""
    group = [_m(1, "book", "surf a contre courant"), _m(2, "book_chapter", "surf a contre courant")]
    assert _resoudre(group) == []


def test_only_book_no_correction():
    assert _resoudre([_m(1, "book")]) == []


def test_article_sharing_book_doi_is_ignored():
    group = [_m(1, "book"), _m(2, "book_chapter"), _m(3, "article")]
    assert _resoudre(group) == [DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)]


# ── domaine pur : chapitre/chapitre (nettoyage + containment + strict) ────


def test_chapters_distinct_titles_all_lose_doi():
    group = [
        _m(1, "book_chapter", "geographie de l environnement"),
        _m(2, "book_chapter", "le monde a la une"),
    ]
    decisions = _resoudre(group)
    assert {d.case for d in decisions} == {DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS}
    assert {d.id for d in decisions} == {1, 2}
    assert all(d.target_doi is None for d in decisions)


def test_chapters_same_title_no_correction():
    assert (
        _resoudre([_m(1, "book_chapter", "introduction"), _m(2, "book_chapter", "introduction")])
        == []
    )


def test_chapters_chapter_number_prefix_is_same():
    g = [
        _m(1, "book_chapter", "chapitre 14 les limnosystemes"),
        _m(2, "book_chapter", "les limnosystemes"),
    ]
    assert _resoudre(g) == []


def test_chapters_subtitle_truncation_is_same():
    g = [
        _m(1, "book_chapter", "contested concepts"),
        _m(2, "book_chapter", "contested concepts plutarch on common notions"),
    ]
    assert _resoudre(g) == []


def test_chapters_number_glued_to_a_word_is_same():
    g = [
        _m(1, "book_chapter", "covid19 et societe"),
        _m(2, "book_chapter", "covid et societe"),
    ]
    assert _resoudre(g) == []


def test_chapters_marker_inside_the_title_is_same():
    g = [
        _m(1, "book_chapter", "introduction partie generale"),
        _m(2, "book_chapter", "introduction generale"),
    ]
    assert _resoudre(g) == []


def test_chapter_without_title_is_not_compared():
    assert _resoudre([_m(1, "book_chapter", None), _m(2, "book_chapter", "introduction")]) == []


def test_same_work_case_without_canonical_doi_does_not_converge():
    group = [
        _m(1, "book", same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT),
        _m(2, "book_chapter"),
    ]
    assert _resoudre(group) == [DoiClusterDecision(2, None, DoiClusterCase.OUVRAGE_VS_CHAPITRE)]


def test_chapters_typo_is_false_positive_left_to_admin():
    g = [
        _m(1, "book_chapter", "les effets thermomecaniques"),
        _m(2, "book_chapter", "les effets thermomecanqiues"),
    ]
    assert _resoudre(g) != []  # déterministe, pas de fuzzy


# ── domaine pur : volume d'actes/communication ────────────────────────────


def test_communications_d_un_volume_perdent_le_doi():
    group = [
        _m(1, "proceedings", "proceedings of the 23rd international conference of ifors"),
        _m(2, "conference_paper", "proceedings of the 23rd international conference of ifors"),
        _m(3, "conference_paper", "transshipment station location problem"),
        _m(4, "poster", "total pain in palliative cancer patients"),
    ]
    assert _resoudre(group) == [
        DoiClusterDecision(3, None, DoiClusterCase.ACTES_VS_COMMUNICATION),
        DoiClusterDecision(4, None, DoiClusterCase.ACTES_VS_COMMUNICATION),
    ]


def test_titre_tronque_du_volume_garde_le_doi():
    group = [
        _m(1, "proceedings", "31st european congress on obesity eco 2024"),
        _m(2, "article", "31st european congress on obesity eco 2024 abstracts"),
    ]
    assert _resoudre(group) == []


def test_sans_volume_aucune_decision():
    group = [_m(1, "conference_paper", "a"), _m(2, "conference_paper", "b")]
    assert _resoudre(group) == []


def test_communication_sans_titre_garde_le_doi():
    group = [_m(1, "proceedings", "book of abstracts"), _m(2, "conference_paper", None)]
    assert _resoudre(group) == []


# ── compute_updates (orchestration mécanique) ────────────────────────────


def test_version_doi_substituted_to_concept():
    # raw_doi = la version ; canonique porté par le membre datacite → substitution + stash.
    datacite = _row(
        1,
        "dataset",
        "10.5281/zenodo.10",
        raw_doi="10.5281/zenodo.10",
        canonical_doi="10.5281/zenodo.1",
        same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    )
    hal = _row(2, "dataset", "10.5281/zenodo.10", raw_doi="10.5281/zenodo.10")
    updates = compute_updates([datacite, hal])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.doi == "10.5281/zenodo.1" for u in updates)
    assert all(
        u.corrections["doi"]
        == {"raw": "10.5281/zenodo.10", "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}
        for u in updates
    )


def test_copie_de_preprint_d_un_autre_prefixe_garde_son_doi():
    # Working paper déposé à RWTH → article publié chez un éditeur : deux œuvres, le DOI reste.
    row = _row(
        1,
        "preprint",
        "10.18154/rwth-1",
        raw_doi="10.18154/rwth-1",
        canonical_doi="10.1103/published",
        same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
    )
    assert compute_updates([row]) == []


def test_copie_de_l_article_prend_le_doi_publie():
    row = _row(
        1,
        "article",
        "10.18154/rwth-1",
        raw_doi="10.18154/rwth-1",
        canonical_doi="10.1103/published",
        same_work_case=DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
    )
    assert compute_updates([row]) == [
        DoiCorrectionUpdate(
            1,
            "10.1103/published",
            {"doi": {"raw": "10.18154/rwth-1", "corrected_by": "DATACITE_VARIANT_TO_PRIMARY"}},
            {},
        )
    ]


def test_preprint_deja_substitue_retrouve_son_doi():
    # Un preprint arXiv substitué par l'article publié récupère son DOI d'origine.
    row = _row(
        1,
        "article",
        "10.1007/jhep07(2023)066",
        corrections={
            "doi": {
                "raw": "10.48550/arxiv.2210.12000",
                "corrected_by": "DATACITE_VERSION_TO_CONCEPT",
            }
        },
        raw_doi="10.48550/arxiv.2210.12000",
        canonical_doi="10.1007/jhep07(2023)066",
        same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    )
    assert compute_updates([row]) == [DoiCorrectionUpdate(1, "10.48550/arxiv.2210.12000", {}, {})]


def test_package_piece_substituted_to_parent():
    row = _row(
        1,
        "dataset",
        "10.15454/abc/file1",
        raw_doi="10.15454/abc/file1",
        canonical_doi="10.15454/abc",
        same_work_case=DoiClusterCase.DATACITE_PACKAGE_PIECE,
    )
    assert compute_updates([row]) == [
        DoiCorrectionUpdate(
            1,
            "10.15454/abc",
            {"doi": {"raw": "10.15454/abc/file1", "corrected_by": "DATACITE_PACKAGE_PIECE"}},
            {},
        )
    ]


def test_concept_equal_to_canonical_is_noop():
    # Dépôt non versionné (canonique == DOI brut) : pas de substitution.
    row = _row(
        1,
        "dataset",
        "10.5281/zenodo.5",
        raw_doi="10.5281/zenodo.5",
        canonical_doi="10.5281/zenodo.5",
        same_work_case=DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    )
    assert compute_updates([row]) == []


def test_self_heals_when_canonical_gone():
    # Déjà substituée mais le canonique n'est plus dérivable → restaure le DOI brut.
    row = _row(
        1,
        "dataset",
        "10.5281/zenodo.1",
        corrections={
            "doi": {"raw": "10.5281/zenodo.10", "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}
        },
        raw_doi="10.5281/zenodo.10",
    )
    assert compute_updates([row]) == [DoiCorrectionUpdate(1, "10.5281/zenodo.10", {}, {})]


def test_chapter_doi_nulled_book_untouched():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x")
    assert compute_updates([book, chapter]) == [
        DoiCorrectionUpdate(
            2, None, {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}, {}
        )
    ]


def test_chapter_chapter_both_nulled():
    a = _row(1, "book_chapter", "10.1/x", title="premier chapitre distinct")
    b = _row(2, "book_chapter", "10.1/x", title="second chapitre autre")
    updates = compute_updates([a, b])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.doi is None for u in updates)
    assert all(
        u.corrections["doi"]["corrected_by"] == "CHAPITRES_TITRES_DIFFERENTS" for u in updates
    )


def test_idempotent_when_already_nulled():
    book = _row(1, "book", "10.1/x")
    chapter = _row(
        2,
        "book_chapter",
        None,
        corrections={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([book, chapter]) == []


def test_self_heals_when_book_gone():
    chapter = _row(
        2,
        "book_chapter",
        None,
        corrections={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([chapter]) == [DoiCorrectionUpdate(2, "10.1/x", {}, {})]


# ── identifiants partagés avec une œuvre qui perd le DOI ──────────────────


def test_volume_perd_le_hal_id_de_ses_communications():
    """Le dépôt HAL d'une communication, recopié par l'enregistrement source OpenAlex du volume, quitte cet enregistrement source."""
    volume = _row(
        1,
        "proceedings",
        "10.1/x",
        title="eapc abstract book",
        external_ids={"hal_id": ["hal-1", "hal-2"], "pmid": "99"},
    )
    communication = _row(
        2, "poster", "10.1/x", title="total pain", external_ids={"hal_id": ["hal-1"]}
    )
    updates = {u.id: u for u in compute_updates([volume, communication])}

    assert updates[1].doi == "10.1/x"
    assert updates[1].external_ids == {"hal_id": ["hal-2"], "pmid": "99"}
    assert updates[1].corrections["removed_external_ids"] == {
        "before": {"hal_id": ["hal-1", "hal-2"]},
        "removed": {"hal_id": ["hal-1"]},
        "corrected_by": "ACTES_VS_COMMUNICATION",
    }
    assert updates[2].doi is None
    assert updates[2].external_ids == {"hal_id": ["hal-1"]}


def test_ouvrage_perd_le_hal_id_de_son_chapitre():
    book = _row(1, "book", "10.1/x", external_ids={"hal_id": ["hal-9"]})
    chapter = _row(2, "book_chapter", "10.1/x", external_ids={"hal_id": ["hal-9"]})
    updates = {u.id: u for u in compute_updates([book, chapter])}
    assert updates[1].external_ids == {}


def test_retrait_stable_d_un_run_a_l_autre():
    volume = _row(
        1, "proceedings", "10.1/x", title="eapc abstract book", external_ids={"hal_id": ["hal-1"]}
    )
    communication = _row(
        2, "poster", "10.1/x", title="total pain", external_ids={"hal_id": ["hal-1"]}
    )
    first = {u.id: u for u in compute_updates([volume, communication])}
    volume = volume._replace(external_ids=first[1].external_ids, corrections=first[1].corrections)
    communication = communication._replace(doi=None, corrections=first[2].corrections)
    assert compute_updates([volume, communication]) == []


def test_identifiants_restaures_quand_la_divergence_disparait():
    volume = _row(
        1,
        "proceedings",
        "10.1/x",
        title="eapc abstract book",
        corrections={
            "removed_external_ids": {
                "before": {"hal_id": ["hal-1", "hal-2"]},
                "removed": {"hal_id": ["hal-1"]},
                "corrected_by": "ACTES_VS_COMMUNICATION",
            }
        },
        external_ids={"hal_id": ["hal-2"]},
    )
    assert compute_updates([volume]) == [
        DoiCorrectionUpdate(1, "10.1/x", {}, {"hal_id": ["hal-1", "hal-2"]})
    ]


def test_identifiant_propre_d_un_enregistrement_source_qui_garde_le_doi_reste_en_place():
    """Le chapitre OpenAlex recopie le dépôt HAL de l'enregistrement source qui garde le DOI : ce dépôt reste à lui."""
    book = _row(1, "book", "10.1/x", external_ids={"hal_id": ["hal-01234567"]})
    hal = _row(
        2,
        "conference_paper",
        "10.1/x",
        external_ids={"hal_id": ["hal-01234567"]},
    )._replace(source="hal", source_id="hal-01234567")
    chapter = _row(3, "book_chapter", "10.1/x", external_ids={"hal_id": ["hal-01234567"]})
    updates = {u.id: u for u in compute_updates([book, hal, chapter])}
    assert set(updates) == {3}


def test_sans_divergence_aucun_retrait():
    a = _row(1, "article", "10.1/x", external_ids={"hal_id": ["hal-1"]})
    b = _row(2, "article", "10.1/x", external_ids={"hal_id": ["hal-1"]})
    assert compute_updates([a, b]) == []


# ── dépôt HAL au DOI d'une autre œuvre ────────────────────────────────────


def _source_record(member_id, source, title, authors, doc_type="article"):
    return DoiClusterMember(
        member_id, doc_type, title, source=source, author_names=frozenset(authors)
    )


def test_depot_hal_d_une_autre_oeuvre_perd_le_doi():
    group = [
        _source_record(
            1, "crossref", "a brief history of oleds emitter development", {"zhang", "li"}
        ),
        _source_record(
            2, "hal", "synthesis of aromatic luminescent molecules", {"martin", "dupont"}
        ),
        _source_record(3, "openalex", "a brief history of oleds emitter development", {"zhang"}),
    ]
    assert _resoudre(group) == [
        DoiClusterDecision(2, None, DoiClusterCase.HAL_DOI_D_UNE_AUTRE_OEUVRE)
    ]


def test_depot_hal_au_titre_proche_garde_le_doi():
    """Liste d'auteurs réduite à la collaboration dans Crossref, titre au balisage près : même œuvre."""
    group = [
        _source_record(
            1,
            "crossref",
            "search for rm b s 0 oscillations using inclusive lepton events",
            {"collaboration"},
        ),
        _source_record(
            2,
            "hal",
            "search for b 0 s oscillations using inclusive lepton events",
            {"abreu", "adam"},
        ),
    ]
    assert _resoudre(group) == []


def test_depot_hal_avec_un_auteur_commun_garde_le_doi():
    group = [
        _source_record(1, "crossref", "l encampement du monde", {"agier"}),
        _source_record(2, "hal", "sociopoetique des migrations introduction", {"agier", "durand"}),
    ]
    assert _resoudre(group) == []


def test_enregistrement_source_crossref_sans_auteur_aucune_decision():
    group = [
        _source_record(1, "crossref", "comptes rendus de lecture", set()),
        _source_record(2, "hal", "jean chateauvert et gilles delavaud", {"martin"}),
    ]
    assert _resoudre(group) == []
