"""Tests purs du retrait des DOI par groupe (ouvrage et chapitre, chapitres entre eux, volume d'actes et communication, dépôt HAL d'une autre œuvre) et de `compute_updates`."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.metadata_correction.shared_doi import (
    DoiClusterCase,
    DoiClusterDecision,
    DoiClusterMember,
    resolve_cluster_doi_corrections,
)
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
)
from pipeline.transformation.publications.correction.remove_identifiers import (
    compute_updates,
    tally_doi_corrections,
)


def _doi(value, removed_by=None, role=SourceIdentifierRole.SECONDARY):
    return SourceIdentifier(SourceIdentifierType.DOI, value, role, removed_by)


def test_tally_doi_corrections_par_cas():
    updates = [
        DoiCorrectionUpdate(1, (_doi("10.9005/a", "OUVRAGE_VS_CHAPITRE"),)),
        DoiCorrectionUpdate(2, (_doi("10.9005/b", "OUVRAGE_VS_CHAPITRE"), _doi("10.9005/c"))),
        DoiCorrectionUpdate(3, (_doi("10.9006/x", "UNRESOLVED_DOI_TO_NULL"),)),
    ]
    assert tally_doi_corrections(updates) == {
        "OUVRAGE_VS_CHAPITRE": 2,
        "UNRESOLVED_DOI_TO_NULL": 1,
    }


def _row(
    row_id,
    doc_type,
    doi=None,
    title=None,
    shared_doi="10.1/x",
    identifiers=(),
    has_target=False,
    doi_removed_by=None,
) -> DoiClusterRow:
    """Membre d'un groupe. `doi` s'écrit en tête de ses identifiants, retiré par `doi_removed_by`, quand `identifiers` ne contient aucun DOI."""
    ids = tuple(identifiers)
    if doi and not any(i.id_type is SourceIdentifierType.DOI for i in ids):
        ids = (_doi(doi, doi_removed_by), *ids)
    return DoiClusterRow(
        row_id,
        doc_type,
        f"titre {'abcdefghij'[row_id % 10]}" if title is None else title,
        shared_doi,
        has_target=has_target,
        identifiers=ids,
    )


def _hal(*values, removed_by=None):
    return tuple(
        SourceIdentifier(SourceIdentifierType.HAL_ID, v, SourceIdentifierRole.SECONDARY, removed_by)
        for v in values
    )


_PMID_99 = SourceIdentifier(SourceIdentifierType.PMID, "99", SourceIdentifierRole.SECONDARY)


def _active(identifiers):
    """Valeurs des identifiants actifs, par type."""
    values: dict[str, list[str]] = {}
    for i in identifiers:
        if i.removed_by is None:
            values.setdefault(i.id_type.value, []).append(i.value)
    return {k: sorted(v) for k, v in values.items()}


_OWN_TITLE = object()


def _m(member_id, doc_type, title=_OWN_TITLE) -> DoiClusterMember:
    """Membre de groupe ; sans titre donné, chaque membre a le sien."""
    if title is _OWN_TITLE:
        title = f"titre {'abcdefghij'[member_id % 10]}"
    return DoiClusterMember(member_id, doc_type, title)


def _resoudre(group, shared_doi="10.1/x"):
    """Décision pour un groupe dont le DOI partagé importe peu au cas testé."""
    return resolve_cluster_doi_corrections(group, shared_doi=shared_doi)


def test_un_doi_inconnu_de_doi_org_est_nulle_sur_tous_les_membres_avant_toute_autre_regle():
    group = [_m(1, "book"), _m(2, "book_chapter"), _m(3, "dataset")]
    decisions = resolve_cluster_doi_corrections(group, shared_doi="10.1/x", unresolved=True)
    assert decisions == [
        DoiClusterDecision(i, DoiClusterCase.UNRESOLVED_DOI_TO_NULL) for i in (1, 2, 3)
    ]


def test_le_doi_d_une_forme_secondaire_prime_sur_les_regles_ouvrage():
    group = [_m(1, "book"), _m(2, "book_chapter")]
    assert (
        resolve_cluster_doi_corrections(group, shared_doi="10.5281/zenodo.10", has_target=True)
        == []
    )


# Ouvrage et chapitre


def test_book_and_chapter_chapter_loses_doi():
    group = [_m(1, "book"), _m(2, "book_chapter")]
    assert _resoudre(group) == [DoiClusterDecision(2, DoiClusterCase.OUVRAGE_VS_CHAPITRE)]


def test_chapitre_au_titre_de_l_ouvrage_garde_le_doi():
    """Même œuvre typée livre par une source et chapitre par une autre : rien à corriger."""
    group = [_m(1, "book", "surf a contre courant"), _m(2, "book_chapter", "surf a contre courant")]
    assert _resoudre(group) == []


def test_only_book_no_correction():
    assert _resoudre([_m(1, "book")]) == []


def test_article_sharing_book_doi_is_ignored():
    group = [_m(1, "book"), _m(2, "book_chapter"), _m(3, "article")]
    assert _resoudre(group) == [DoiClusterDecision(2, DoiClusterCase.OUVRAGE_VS_CHAPITRE)]


# Chapitres entre eux


def test_chapters_distinct_titles_all_lose_doi():
    group = [
        _m(1, "book_chapter", "geographie de l environnement"),
        _m(2, "book_chapter", "le monde a la une"),
    ]
    decisions = _resoudre(group)
    assert {d.case for d in decisions} == {DoiClusterCase.CHAPITRES_TITRES_DIFFERENTS}
    assert {d.id for d in decisions} == {1, 2}


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


def test_chapters_typo_is_false_positive_left_to_admin():
    g = [
        _m(1, "book_chapter", "les effets thermomecaniques"),
        _m(2, "book_chapter", "les effets thermomecanqiues"),
    ]
    assert _resoudre(g) != []  # comparaison exacte des titres, sans tolérance aux fautes de frappe


# Volume d'actes et communication


def test_communications_d_un_volume_perdent_le_doi():
    group = [
        _m(1, "proceedings", "proceedings of the 23rd international conference of ifors"),
        _m(2, "conference_paper", "proceedings of the 23rd international conference of ifors"),
        _m(3, "conference_paper", "transshipment station location problem"),
        _m(4, "poster", "total pain in palliative cancer patients"),
    ]
    assert _resoudre(group) == [
        DoiClusterDecision(3, DoiClusterCase.ACTES_VS_COMMUNICATION),
        DoiClusterDecision(4, DoiClusterCase.ACTES_VS_COMMUNICATION),
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


# compute_updates


def test_un_groupe_au_doi_d_une_forme_secondaire_garde_son_doi():
    # Ouvrage et chapitre au DOI d'une version qui a une cible : aucun retrait.
    book = _row(1, "book", "10.5281/zenodo.10", shared_doi="10.5281/zenodo.10", has_target=True)
    chapter = _row(2, "book_chapter", "10.5281/zenodo.10", shared_doi="10.5281/zenodo.10")
    assert compute_updates([book, chapter]) == []


def test_un_chapitre_perd_le_doi_de_l_ouvrage_et_garde_le_sien():
    """Un chapitre OpenAlex cite son DOI et celui de l'ouvrage : il est membre des deux groupes."""
    own, book_doi = _doi("10.1/chapitre"), _doi("10.1/livre")
    book = _row(1, "book", "10.1/livre", title="le livre", shared_doi="10.1/livre")
    in_book_group = _row(
        2,
        "book_chapter",
        "10.1/chapitre",
        title="un chapitre",
        shared_doi="10.1/livre",
        identifiers=[own, book_doi],
    )
    in_own_group = in_book_group._replace(shared_doi="10.1/chapitre")

    updates = compute_updates([book, in_book_group, in_own_group])

    assert updates == [DoiCorrectionUpdate(2, (own, _doi("10.1/livre", "OUVRAGE_VS_CHAPITRE")))]


def test_chapter_doi_removed_book_untouched():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x")
    assert compute_updates([book, chapter]) == [
        DoiCorrectionUpdate(2, (_doi("10.1/x", "OUVRAGE_VS_CHAPITRE"),))
    ]


def test_chapter_chapter_both_removed():
    a = _row(1, "book_chapter", "10.1/x", title="premier chapitre distinct")
    b = _row(2, "book_chapter", "10.1/x", title="second chapitre autre")
    updates = compute_updates([a, b])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.identifiers == (_doi("10.1/x", "CHAPITRES_TITRES_DIFFERENTS"),) for u in updates)


def test_idempotent_when_already_removed():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x", doi_removed_by="OUVRAGE_VS_CHAPITRE")
    assert compute_updates([book, chapter]) == []


def test_self_heals_when_book_gone():
    chapter = _row(2, "book_chapter", "10.1/x", doi_removed_by="OUVRAGE_VS_CHAPITRE")
    assert compute_updates([chapter]) == [DoiCorrectionUpdate(2, (_doi("10.1/x"),))]


# Identifiants partagés avec une œuvre qui perd le DOI


def test_volume_perd_le_hal_id_de_ses_communications():
    """Le dépôt HAL d'une communication, recopié par l'enregistrement source OpenAlex du volume, quitte cet enregistrement source."""
    volume = _row(
        1,
        "proceedings",
        "10.1/x",
        title="eapc abstract book",
        identifiers=(*_hal("hal-1", "hal-2"), _PMID_99),
    )
    communication = _row(2, "poster", "10.1/x", title="total pain", identifiers=_hal("hal-1"))
    updates = {u.id: u for u in compute_updates([volume, communication])}

    assert _active(updates[1].identifiers) == {
        "doi": ["10.1/x"],
        "hal_id": ["hal-2"],
        "pmid": ["99"],
    }
    assert updates[1].identifiers == (
        _doi("10.1/x"),
        *_hal("hal-1", removed_by="ACTES_VS_COMMUNICATION"),
        *_hal("hal-2"),
        _PMID_99,
    )
    assert _active(updates[2].identifiers) == {"hal_id": ["hal-1"]}


def test_ouvrage_perd_le_hal_id_de_son_chapitre():
    book = _row(1, "book", "10.1/x", identifiers=_hal("hal-9"))
    chapter = _row(2, "book_chapter", "10.1/x", identifiers=_hal("hal-9"))
    updates = {u.id: u for u in compute_updates([book, chapter])}
    assert _active(updates[1].identifiers) == {"doi": ["10.1/x"]}


def test_retrait_stable_d_un_run_a_l_autre():
    volume = _row(1, "proceedings", "10.1/x", title="eapc abstract book", identifiers=_hal("hal-1"))
    communication = _row(2, "poster", "10.1/x", title="total pain", identifiers=_hal("hal-1"))
    first = {u.id: u for u in compute_updates([volume, communication])}
    volume = volume._replace(identifiers=first[1].identifiers)
    communication = communication._replace(identifiers=first[2].identifiers)
    assert compute_updates([volume, communication]) == []


def test_identifiants_restaures_quand_la_divergence_disparait():
    volume = _row(
        1,
        "proceedings",
        "10.1/x",
        title="eapc abstract book",
        identifiers=(*_hal("hal-1", removed_by="ACTES_VS_COMMUNICATION"), *_hal("hal-2")),
    )
    assert compute_updates([volume]) == [
        DoiCorrectionUpdate(1, (_doi("10.1/x"), *_hal("hal-1", "hal-2")))
    ]


def test_retrait_par_la_correction_unaire_garde():
    """Un identifiant retiré par une règle de la correction unaire reste retiré, et hors des clés de confirmation."""
    volume = _row(
        1,
        "proceedings",
        "10.1/x",
        title="eapc abstract book",
        identifiers=_hal("hal-1", removed_by="HAL_DEPOSIT_MISSING_TO_REMOVED"),
    )
    communication = _row(
        2,
        "poster",
        "10.1/x",
        title="total pain",
        identifiers=_hal("hal-1", removed_by="HAL_DEPOSIT_MISSING_TO_REMOVED"),
    )
    updates = {u.id: u for u in compute_updates([volume, communication])}
    assert set(updates) == {2}


def test_identifiant_propre_d_un_enregistrement_source_qui_garde_le_doi_reste_en_place():
    """Le chapitre OpenAlex recopie le dépôt HAL de l'enregistrement source qui garde le DOI : ce dépôt reste à lui."""
    book = _row(1, "book", "10.1/x", identifiers=_hal("hal-01234567"))
    hal = _row(
        2,
        "conference_paper",
        "10.1/x",
        identifiers=_hal("hal-01234567"),
    )._replace(source="hal", source_id="hal-01234567")
    chapter = _row(3, "book_chapter", "10.1/x", identifiers=_hal("hal-01234567"))
    updates = {u.id: u for u in compute_updates([book, hal, chapter])}
    assert set(updates) == {3}


def test_sans_divergence_aucun_retrait():
    a = _row(1, "article", "10.1/x", identifiers=_hal("hal-1"))
    b = _row(2, "article", "10.1/x", identifiers=_hal("hal-1"))
    assert compute_updates([a, b]) == []


# Dépôt HAL au DOI d'une autre œuvre


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
    assert _resoudre(group) == [DoiClusterDecision(2, DoiClusterCase.HAL_DOI_D_UNE_AUTRE_OEUVRE)]


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
