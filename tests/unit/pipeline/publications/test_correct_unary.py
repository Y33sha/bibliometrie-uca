"""Tests purs de `compute_update` : correction unaire idempotente."""

import logging
from unittest.mock import MagicMock

from domain.source_records.corrections import stash_entry
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.metadata_correction.rules import MetadataForCorrection
from domain.source_records.metadata_correction.source_record import (
    CorrectedSourceRecord,
    UnaryCorrection,
)
from pipeline.transformation.publications.correction.correct_unary import (
    compute_update,
    compute_updates,
    hal_origin_ids,
    run,
    tally_corrections,
)
from pipeline.transformation.publications.correction.correction_store import (
    CorrectionUpdate,
    UnaryCorrectionRow,
)


def _active(identifiers):
    """Valeurs des identifiants actifs, par type."""
    values: dict[str, list[str]] = {}
    for i in identifiers:
        if i.removed_by is None:
            values.setdefault(i.id_type.value, []).append(i.value)
    return {k: sorted(v) for k, v in values.items()}


def _update(source_record: UnaryCorrectionRow) -> CorrectionUpdate | None:
    return compute_update(source_record)


def test_tally_corrections_compte_les_regles():
    updates = [
        CorrectionUpdate(
            2,
            UnaryCorrection(
                CorrectedSourceRecord(
                    "thesis",
                    None,
                    None,
                    {"doc_type": stash_entry("article", "THESIS_WITH_SERIAL_TO_ARTICLE")},
                ),
                (),
            ),
        ),
        # deux champs corrigés sur un même enregistrement source : un enregistrement source, deux déclenchements
        CorrectionUpdate(
            3,
            UnaryCorrection(
                CorrectedSourceRecord(
                    "media",
                    "green",
                    None,
                    {
                        "doc_type": stash_entry("article", "SERIAL_TYPE_MEDIA_TO_MEDIA"),
                        "oa_status": stash_entry("closed", "EMBARGO_EXPIRED_TO_GREEN"),
                    },
                ),
                (),
            ),
        ),
        # correction défaite : mise à jour sans règle
        CorrectionUpdate(4, UnaryCorrection(CorrectedSourceRecord("article", None, None, {}), ())),
    ]
    corrected, rule_counts = tally_corrections(updates)
    assert corrected == 2
    assert rule_counts == {
        "THESIS_WITH_SERIAL_TO_ARTICLE": 1,
        "SERIAL_TYPE_MEDIA_TO_MEDIA": 1,
        "EMBARGO_EXPIRED_TO_GREEN": 1,
    }


_ROW_FIELDS = ("id", "source_id", "corrections", "identifiers")


def _ids(id_type, *values, removed_by=None):
    return tuple(
        SourceIdentifier(id_type, v, SourceIdentifierRole.SECONDARY, removed_by) for v in values
    )


def _hal(*values, removed_by=None):
    return _ids(SourceIdentifierType.HAL_ID, *values, removed_by=removed_by)


def _source_record(**overrides: object) -> UnaryCorrectionRow:
    """Ligne de correction unaire ; une clé hors des champs de la ligne est un fait des règles."""
    row: dict[str, object] = {
        "id": 1,
        "source_id": "W1",
        "corrections": {},
        "identifiers": (),
    }
    facts: dict[str, object] = {
        "source": "openalex",
        "title": "Un titre quelconque",
        "doc_type": "article",
        "doi": None,
        "serial_id": None,
        "embargo_expired": False,
        "self_declared_preprint": False,
        "declares_conference": False,
        "in_proceedings_volume": False,
        "journal_diamond": False,
        "author_count": 1,
    }
    for key, value in overrides.items():
        (row if key in _ROW_FIELDS else facts)[key] = value
    return UnaryCorrectionRow(**row, facts=MetadataForCorrection(**facts))  # type: ignore[arg-type]


def test_no_rule_returns_none():
    assert _update(_source_record(doc_type="article")) is None


def test_thesis_with_serial_id_and_publisher_doi_is_mistyped_article():
    # Erreur de type d'OpenAlex ou de ScanR : un article typé thèse, rattaché à une revue, avec un DOI d'éditeur (hors du registre des thèses), devient un article.
    upd = _update(_source_record(doc_type="thesis", serial_id=42, doi="10.1016/j.ex.2020.01.001"))
    assert upd is not None
    assert upd.corrected.columns.doc_type == "article"
    assert upd.corrected.columns.corrections == {
        "doc_type": {"raw": "thesis", "corrected_by": "THESIS_WITH_SERIAL_TO_ARTICLE"}
    }


def test_thesis_with_serial_id_but_thesis_registry_doi_stays_thesis():
    # Un DOI ABES (registre des thèses françaises) est celui de la thèse : la revue vient de la version publiée, et le type reste thèse.
    assert _update(_source_record(doc_type="thesis", serial_id=42, doi="10.70675/abc123")) is None


def test_thesis_with_serial_id_no_doi_stays_thesis():
    # Sans DOI, rien ne distingue l'erreur de type de la confusion avec la version publiée : le type reste thèse.
    assert _update(_source_record(doc_type="thesis", serial_id=42, doi=None)) is None


def test_real_thesis_without_serial_id_untouched():
    assert _update(_source_record(doc_type="thesis", serial_id=None)) is None


def test_retrait_par_cluster_garde():
    """La correction unaire garde le retrait d'identifiants noté par le retrait par groupe : aucune mise à jour."""
    identifiers = (*_hal("hal-1", removed_by="ACTES_VS_COMMUNICATION"), *_hal("hal-2"))
    row = _source_record(identifiers=identifiers)
    assert _update(row) is None


def test_retrait_par_cluster_compose_avec_la_conflation_these():
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            identifiers=(
                *_hal("tel-01", "hal-99"),
                *_hal("hal-5", removed_by="ACTES_VS_COMMUNICATION"),
            ),
        )
    )
    assert upd is not None
    assert _active(upd.corrected.identifiers) == {"hal_id": ["hal-99"]}
    assert [i.removed_by for i in upd.corrected.identifiers] == [
        "THESIS_WITH_SERIAL_TO_ARTICLE",
        None,
        "ACTES_VS_COMMUNICATION",
    ]


def test_thesis_to_article_strips_dissertation_keys():
    # Thèse confondue avec sa version publiée : l'enregistrement source corrigé en article perd le NNT et les hal_id tel- et dumas-, et garde ses autres identifiants.
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            identifiers=(
                *_ids(SourceIdentifierType.NNT, "2020X"),
                *_hal("tel-01", "hal-99"),
                *_ids(SourceIdentifierType.PMID, "123"),
            ),
        )
    )
    assert upd is not None
    assert upd.corrected.columns.doc_type == "article"
    assert _active(upd.corrected.identifiers) == {"hal_id": ["hal-99"], "pmid": ["123"]}
    assert {i.value: i.removed_by for i in upd.corrected.identifiers} == {
        "2020X": "THESIS_WITH_SERIAL_TO_ARTICLE",
        "tel-01": "THESIS_WITH_SERIAL_TO_ARTICLE",
        "hal-99": None,
        "123": None,
    }
    assert tally_corrections([upd]) == (1, {"THESIS_WITH_SERIAL_TO_ARTICLE": 1})


def test_thesis_to_article_without_dissertation_keys_leaves_identifiers():
    # Erreur de type sans identifiant de thèse : identifiants inchangés.
    identifiers = _ids(SourceIdentifierType.PMID, "123")
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            identifiers=identifiers,
        )
    )
    assert upd is not None
    assert upd.corrected.columns.doc_type == "article"
    assert _active(upd.corrected.identifiers) == {"pmid": ["123"]}
    assert upd.corrected.identifiers == identifiers


def test_serial_id_wins_over_theses_fr_url_conflation():
    # Un enregistrement source à URL theses.fr, avec une revue et un DOI d'éditeur, devient un article. `serial_id_present: False` restreint la règle d'URL ; `doi_prefix_not_in` distingue l'article publié (DOI d'éditeur) d'une thèse à DOI ABES.
    upd = _update(
        _source_record(
            doc_type="thesis",
            serial_id=42,
            doi="10.1016/j.ex.2020.01.001",
            urls=["https://theses.fr/2020X"],
        )
    )
    assert upd is not None
    assert upd.corrected.columns.doc_type == "article"
    assert (
        upd.corrected.columns.corrections["doc_type"]["corrected_by"]
        == "THESIS_WITH_SERIAL_TO_ARTICLE"
    )


def test_serial_media_corrects_and_stashes_the_value_before_correction():
    upd = _update(_source_record(source="hal", doc_type="article", serial_type="media"))
    assert upd is not None
    assert upd.corrected.columns.doc_type == "media"
    assert upd.corrected.columns.corrections == {
        "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_theses_fr_url_corrects_doc_type_and_stashes_raw():
    upd = _update(_source_record(doc_type="article", urls=["https://theses.fr/2020ABCD"]))
    assert upd is not None
    assert upd.corrected.columns.doc_type == "thesis"
    assert upd.corrected.columns.corrections == {
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}
    }


def test_already_corrected_is_idempotent_noop():
    source_record = _source_record(
        doc_type="thesis",
        urls=["https://theses.fr/2020ABCD"],
        corrections={"doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}},
    )
    assert _update(source_record) is None


def test_self_heals_when_rule_no_longer_applies():
    # doc_type mis à 'media' par une règle de revue, pour une revue d'un autre type : la correction est défaite, et le type brut 'article' revient.
    source_record = _source_record(
        doc_type="media",
        serial_type=None,
        corrections={"doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}},
    )
    upd = _update(source_record)
    assert upd is not None
    assert upd.corrected.columns.doc_type == "article"
    assert upd.corrected.columns.corrections == {}


def test_expired_embargo_promotes_oa_status_to_green():
    # oa_status `embargoed` et embargo échu (constaté à la lecture de la source) : `green`, la valeur brute est conservée dans `corrections`.
    upd = _update(_source_record(oa_status="embargoed", embargo_expired=True))
    assert upd is not None
    assert upd.corrected.columns.oa_status == "green"
    assert upd.corrected.columns.corrections["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def test_active_embargo_oa_status_untouched():
    # Embargo en cours : aucune mise à jour.
    assert _update(_source_record(oa_status="embargoed", embargo_expired=False)) is None


def test_null_doc_type_left_null_when_no_rule():
    assert _update(_source_record(doc_type=None)) is None


def test_preserves_unmanaged_corrections_keys():
    # La clé `doi`, gérée par le retrait des DOI par groupe, survit à la correction unaire.
    source_record = _source_record(
        doc_type="article",
        urls=["https://theses.fr/2020ABCD"],
        corrections={"doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    upd = _update(source_record)
    assert upd is not None
    assert upd.corrected.columns.corrections == {
        "doi": {"raw": "10.1/book", "corrected_by": "OUVRAGE_VS_CHAPITRE"},
        "doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"},
    }


def test_le_journal_compte_seulement_les_documents_corriges_par_une_regle(caplog):
    """Une correction défaite donne une mise à jour, sans compter comme une correction."""
    queries = MagicMock()
    queries.fetch_missing_hal_ids.return_value = frozenset()
    queries.delete_missing_hal_locations.return_value = 0
    queries.fetch_for_unary_correction.return_value = [
        _source_record(
            id=1,
            doc_type="media",
            corrections={
                "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
            },
        ),
        _source_record(id=2, doc_type="article", urls=["https://theses.fr/2020ABCD"]),
    ]
    with caplog.at_level(logging.INFO, logger="test"):
        run(MagicMock(), queries, logging.getLogger("test"))
    assert "  ├─ 1 document à corriger" in caplog.messages


# Dépôts HAL introuvables


def test_depot_hal_introuvable_retire_des_identifiants_et_des_liens():
    """Cas réel : l'enregistrement OpenAlex W4287257393 cite le dépôt hal-03178520, introuvable dans HAL."""
    row = _source_record(
        identifiers=(
            *_hal("hal-03178520", "hal-03263588"),
            *_ids(SourceIdentifierType.PMID, "1"),
        ),
        urls=["https://hal.science/hal-03178520", "https://hal.inrae.fr/hal-03263588/document"],
    )
    upd = compute_update(row, missing_hal_ids={"hal-03178520"})
    assert upd is not None
    assert _active(upd.corrected.identifiers) == {"hal_id": ["hal-03263588"], "pmid": ["1"]}
    assert upd.corrected.columns.urls == ["https://hal.inrae.fr/hal-03263588/document"]
    assert upd.corrected.columns.corrections["urls"] == stash_entry(
        row.facts.urls, "HAL_DEPOSIT_MISSING_TO_REMOVED"
    )
    assert tally_corrections([upd]) == (1, {"HAL_DEPOSIT_MISSING_TO_REMOVED": 1})

    corrected = _source_record(
        identifiers=upd.corrected.identifiers,
        urls=upd.corrected.columns.urls,
        corrections=upd.corrected.columns.corrections,
    )
    assert compute_update(corrected, missing_hal_ids={"hal-03178520"}) is None


def test_dernier_depot_hal_introuvable_vide_les_liens():
    row = _source_record(
        identifiers=_hal("hal-03178520"),
        urls=["https://hal.science/hal-03178520"],
    )
    upd = compute_update(row, missing_hal_ids={"hal-03178520"})
    assert upd is not None
    assert _active(upd.corrected.identifiers) == {}
    assert upd.corrected.columns.urls is None


def test_depot_hal_retrouve_restaure_identifiants_et_liens():
    raw_urls = ["https://hal.science/hal-03178520"]
    rule = "HAL_DEPOSIT_MISSING_TO_REMOVED"
    corrected = _source_record(
        identifiers=_hal("hal-03178520", removed_by=rule),
        urls=None,
        corrections={"urls": stash_entry(raw_urls, rule)},
    )
    upd = compute_update(corrected)
    assert upd is not None
    assert _active(upd.corrected.identifiers) == {"hal_id": ["hal-03178520"]}
    assert upd.corrected.identifiers == _hal("hal-03178520")
    assert upd.corrected.columns.urls == raw_urls
    assert upd.corrected.columns.corrections == {}


# Enregistrements sources ScanR issus d'un dépôt HAL


def test_scanr_from_hal_takes_corrected_hal_type():
    """Un enregistrement source ScanR issu de HAL prend le type corrigé de l'enregistrement source HAL de son dépôt."""
    hal = _source_record(id=1, source="hal", source_id="hal-04565713", doc_type="poster")
    scanr = _source_record(id=2, source="scanr", source_id="halhal-04565713", doc_type="other")

    updates = compute_updates([hal, scanr], {"hal-04565713": hal}, frozenset())

    (scanr_update,) = [u for u in updates if u.id == 2]
    assert scanr_update.corrected.columns.doc_type == "poster"
    assert (
        scanr_update.corrected.columns.corrections["doc_type"]["corrected_by"]
        == "SCANR_FROM_HAL_TO_HAL_TYPE"
    )


def test_scanr_without_hal_deposit_keeps_its_type():
    scanr = _source_record(id=2, source="scanr", source_id="halhal-04565713", doc_type="other")
    assert compute_updates([scanr], {}, frozenset()) == []


def test_scanr_from_another_origin_keeps_its_type():
    scanr = _source_record(id=2, source="scanr", source_id="doi10.1/x", doc_type="other")
    hal = _source_record(id=1, source="hal", source_id="hal-04565713", doc_type="poster")
    assert [u.id for u in compute_updates([scanr], {"hal-04565713": hal}, frozenset())] == []


def test_hal_origin_ids():
    rows = [
        _source_record(source="scanr", source_id="halhal-04565713"),
        _source_record(source="scanr", source_id="doi10.1/x"),
        _source_record(source="hal", source_id="hal-04501427"),
    ]
    assert hal_origin_ids(rows) == ["hal-04565713"]
