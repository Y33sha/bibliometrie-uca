"""Tests de l'agrégation cross-source (`domain.publications.aggregation.refresh_from_sources`).

Cible la priorité donnée aux enregistrements canoniques sur les formes secondaires convergées
(`secondary_ids`) : le titre et les autres scalaires viennent du parent, pas d'une pièce ; les
listes restent unionnées.
"""

import pytest

from domain.publications.aggregation import assign_publisher, refresh_from_sources
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from domain.publications.publication import Publication
from domain.source_records.source_record import SourceRecord


def _source_record(**overrides) -> SourceRecord:
    defaults = {
        "id": 1,
        "source": "datacite",
        "source_id": "s",
        "title": "Titre",
        "publication_year": 2020,
        "doc_type": "dataset",
        "doi": "10.9001/set",
        "journal_id": None,
        "monograph_id": None,
        "container_title": None,
        "language": None,
        "oa_status": None,
        "is_retracted": None,
        "abstract": None,
        "countries": (),
        "keywords": (),
        "urls": (),
        "topics": None,
        "biblio": None,
        "source_extras": None,
    }
    defaults.update(overrides)
    return SourceRecord(**defaults)  # type: ignore[arg-type]


def _publication() -> Publication:
    return Publication(id=10, title="obsolète", publication_year=2020)


# `openalex` prioritaire sur `datacite` : sans dépriorisation, la pièce OpenAlex gagnerait le titre.
_PRIORITY = ("openalex", "datacite")


def test_parent_wins_title_over_higher_priority_secondary_piece():
    parent = _source_record(
        id=1, source="datacite", title="Jeu de données phénotypiques", keywords=("blé",)
    )
    piece = _source_record(
        id=2, source="openalex", title="README_data.txt", keywords=("supplément",)
    )

    publication = _publication()
    refresh_from_sources(
        publication, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )

    # Le parent (canonique) gagne le titre malgré la priorité de source de la pièce.
    assert publication.title == "Jeu de données phénotypiques"
    # Les mots-clés restent unionnés toutes sources confondues.
    assert set(publication.keywords) == {"blé", "supplément"}


def test_secondary_fills_scalar_absent_on_parent():
    # Le parent n'a pas d'abstract : la pièce, reléguée, comble quand même le champ vide.
    parent = _source_record(id=1, source="datacite", abstract=None)
    piece = _source_record(id=2, source="openalex", abstract="Description du jeu de données")

    publication = _publication()
    refresh_from_sources(
        publication, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )
    assert publication.abstract == "Description du jeu de données"


def test_without_secondary_ids_source_priority_decides():
    # Comportement par défaut inchangé : sans dépriorisation, la source prioritaire gagne le titre.
    parent = _source_record(id=1, source="datacite", title="Jeu de données phénotypiques")
    piece = _source_record(id=2, source="openalex", title="README_data.txt")

    publication = _publication()
    refresh_from_sources(publication, [piece, parent], source_priority=_PRIORITY)
    assert publication.title == "README_data.txt"


def test_une_source_sans_doc_type_laisse_la_suivante_le_donner():
    """Le type vient de la première source qui en porte un, les silencieuses étant passées.

    Toutes les sources ne renseignent pas le type de document. La plus prioritaire restant muette, l'agrégation lit la suivante plutôt que de conclure à l'absence de type.
    """
    muette = _source_record(id=1, source="openalex", doc_type=None)
    parlante = _source_record(id=2, source="datacite", doc_type="dataset")

    publication = _publication()
    refresh_from_sources(publication, [muette, parlante], source_priority=_PRIORITY)
    assert publication.doc_type == "dataset"


def test_un_sous_type_d_article_prime_sur_l_article_generique():
    """Une source sans type, placée en tête, n'interrompt pas la recherche du sous-type."""
    muette = _source_record(id=1, source="openalex", doc_type=None)
    generique = _source_record(id=2, source="crossref", doc_type="article")
    precise = _source_record(id=3, source="datacite", doc_type="review")

    publication = _publication()
    refresh_from_sources(
        publication,
        [muette, generique, precise],
        source_priority=("openalex", "crossref", "datacite"),
    )
    assert publication.doc_type == "review"


def test_sans_source_l_agregation_est_refusee():
    with pytest.raises(ValueError, match=r"^refresh_from_sources requiert au moins une source"):
        refresh_from_sources(_publication(), [], source_priority=_PRIORITY)


class TestOrdreDesSources:
    def test_la_priorite_ordonne_des_sources_recues_dans_le_desordre(self):
        datacite = _source_record(id=1, source="datacite", title="Titre DataCite")
        openalex = _source_record(id=2, source="openalex", title="Titre OpenAlex")

        publication = _publication()
        refresh_from_sources(publication, [datacite, openalex], source_priority=_PRIORITY)
        assert publication.title == "Titre OpenAlex"

    def test_une_source_hors_priorite_passe_apres_les_sources_classees(self):
        inconnue = _source_record(id=1, source="wos", title="Titre WoS")
        classee = _source_record(id=2, source="datacite", title="Titre DataCite")

        publication = _publication()
        refresh_from_sources(publication, [inconnue, classee], source_priority=_PRIORITY)
        assert publication.title == "Titre DataCite"


class TestChampsAgreges:
    def test_chaque_champ_vient_de_la_source(self):
        source = _source_record(
            title="Blé <i>durum</i>",
            publication_year=2021,
            doi="10.1234/ABC",
            journal_id=7,
            monograph_id=9,
            container_title="Revue d'agronomie",
            language="fr",
            countries=("FR",),
            topics={"domaine": "agronomie"},
            biblio={"volume": "3"},
            source_extras={"licence": "cc-by"},
            is_retracted=True,
        )

        publication = _publication()
        refresh_from_sources(publication, [source], source_priority=_PRIORITY)
        assert publication.title_normalized == "ble durum"
        assert publication.publication_year == 2021
        assert publication.doi == DOI("10.1234/abc")
        assert publication.journal_id == 7
        assert publication.monograph_id == 9
        assert publication.container_title == "Revue d'agronomie"
        assert publication.language == "fr"
        assert publication.countries == ("FR",)
        assert publication.topics == {"datacite": {"domaine": "agronomie"}}
        assert publication.biblio == {"volume": "3"}
        assert publication.source_extras == {"licence": "cc-by"}
        assert publication.is_retracted is True

    def test_les_mots_cles_sont_dedoublonnes_sans_egard_a_la_casse(self):
        premiere = _source_record(id=1, source="openalex", keywords=("Blé",))
        seconde = _source_record(id=2, source="datacite", keywords=("blé", "maïs"))

        publication = _publication()
        refresh_from_sources(publication, [premiere, seconde], source_priority=_PRIORITY)
        assert publication.keywords == ("Blé", "maïs")

    def test_les_jsonb_fusionnent_par_cle_au_profit_de_la_source_prioritaire(self):
        premiere = _source_record(id=1, source="openalex", biblio={"volume": "3", "issue": "1"})
        seconde = _source_record(id=2, source="datacite", biblio={"volume": "4", "pages": "5-9"})

        publication = _publication()
        refresh_from_sources(publication, [premiere, seconde], source_priority=_PRIORITY)
        assert publication.biblio == {"volume": "3", "issue": "1", "pages": "5-9"}


class TestStatutOa:
    """Le statut OA tiré des sources et du verdict d'Unpaywall sur le DOI de la publication."""

    def test_le_statut_le_plus_ouvert_l_emporte(self):
        verte = _source_record(id=1, source="hal", oa_status="green")
        doree = _source_record(id=2, source="openalex", oa_status="gold")

        publication = _publication()
        refresh_from_sources(publication, [verte, doree], source_priority=("hal", "openalex"))
        assert publication.oa_status == "gold"

    def test_des_sources_muettes_donnent_un_statut_inconnu(self):
        publication = _publication()
        refresh_from_sources(
            publication, [_source_record(oa_status=None)], source_priority=_PRIORITY
        )
        assert publication.oa_status == OA_STATUS_UNKNOWN_DEFAULT

    def test_un_depot_en_archive_ouverte_tient_face_a_un_verdict_ferme(self):
        publication = _publication()
        refresh_from_sources(
            publication,
            [_source_record(source="hal", oa_status="green")],
            source_priority=("hal",),
            unpaywall={"10.9001/set": "closed"},
        )
        assert publication.oa_status == "green"

    def test_sans_depot_le_verdict_ferme_tient(self):
        publication = _publication()
        refresh_from_sources(
            publication,
            [_source_record(source="openalex", oa_status="gold")],
            source_priority=_PRIORITY,
            unpaywall={"10.9001/set": "closed"},
        )
        assert publication.oa_status == "closed"

    def test_le_verdict_vise_le_doi_de_la_publication(self):
        publication = _publication()
        refresh_from_sources(
            publication,
            [_source_record(source="openalex", oa_status="gold")],
            source_priority=_PRIORITY,
            unpaywall={"10.9001/autre": "closed"},
        )
        assert publication.oa_status == "gold"


class TestLicences:
    """Licence de la version éditeur par ordre de source, DataCite en tête pour un jeu de données ; licence du dépôt par HAL."""

    _ORDRE = ("hal", "openalex", "scanr", "crossref", "datacite")

    def test_crossref_avant_openalex_pour_un_article(self):
        sources = [
            _source_record(id=1, source="openalex", doc_type="article", license="cc-by-nc"),
            _source_record(id=2, source="crossref", doc_type="article", license="cc-by"),
            _source_record(
                id=3, source="hal", doc_type="article", license="repository-distribution"
            ),
        ]
        publication = _publication()
        refresh_from_sources(publication, sources, source_priority=self._ORDRE)
        assert (publication.license, publication.deposit_license) == (
            "cc-by",
            "repository-distribution",
        )

    def test_source_sans_licence_passee(self):
        sources = [
            _source_record(id=1, source="crossref", doc_type="article", license=None),
            _source_record(id=2, source="scanr", doc_type="article", license="cc-by-sa"),
        ]
        publication = _publication()
        refresh_from_sources(publication, sources, source_priority=self._ORDRE)
        assert (publication.license, publication.deposit_license) == ("cc-by-sa", None)

    def test_datacite_en_tete_pour_un_jeu_de_donnees(self):
        sources = [
            _source_record(id=1, source="openalex", doc_type="dataset", license="other-oa"),
            _source_record(id=2, source="datacite", doc_type="dataset", license="public-domain"),
        ]
        publication = _publication()
        refresh_from_sources(publication, sources, source_priority=self._ORDRE)
        assert publication.license == "public-domain"


class TestCollectionDeLaMonographie:
    def test_publication_sans_revue_prend_la_collection_de_sa_monographie(self):
        publication = _publication()
        refresh_from_sources(
            publication,
            [_source_record(monograph_id=9)],
            source_priority=_PRIORITY,
            monograph_journals={9: 7},
        )
        assert (publication.monograph_id, publication.journal_id) == (9, 7)

    def test_revue_d_une_source_passe_avant_la_collection(self):
        publication = _publication()
        refresh_from_sources(
            publication,
            [_source_record(monograph_id=9, journal_id=3)],
            source_priority=_PRIORITY,
            monograph_journals={9: 7},
        )
        assert publication.journal_id == 3


class TestAssignPublisher:
    """`assign_publisher` : titulaire du préfixe du DOI Crossref, à défaut éditeur des enregistrements sources."""

    _ORDRE = ("crossref", "hal", "openalex")

    def _publication(self, doc_type: str, doi: str | None = "10.1017/abc") -> Publication:
        return Publication(
            id=10,
            title="t",
            publication_year=2020,
            doc_type=doc_type,
            doi=DOI(doi) if doi else None,
        )

    def test_le_titulaire_du_prefixe_l_emporte_sur_les_sources(self):
        publication = self._publication("article")
        sources = [_source_record(id=1, source="crossref", publisher_id=7)]
        assign_publisher(
            publication, sources, source_priority=self._ORDRE, prefix_publishers={"10.1017": 3}
        )
        assert publication.publisher_id == 3

    def test_a_defaut_le_premier_editeur_dans_l_ordre_des_sources(self):
        publication = self._publication("article", doi=None)
        sources = [
            _source_record(id=1, source="openalex", publisher_id=9),
            _source_record(id=2, source="hal", publisher_id=None),
            _source_record(id=3, source="crossref", publisher_id=7),
        ]
        assign_publisher(publication, sources, source_priority=self._ORDRE)
        assert publication.publisher_id == 7

    def test_une_production_hebergee_n_a_pas_d_editeur(self):
        publication = self._publication("preprint")
        sources = [_source_record(id=1, source="crossref", publisher_id=7)]
        assign_publisher(
            publication, sources, source_priority=self._ORDRE, prefix_publishers={"10.1017": 3}
        )
        assert publication.publisher_id is None

    def test_le_prefixe_d_une_plateforme_d_editeurs_cede_a_l_editeur_des_sources(self):
        """Cairn (10.3917) est titulaire du préfixe et nommé par Crossref : l'éditeur vient de HAL."""
        publication = self._publication("article", doi="10.3917/mult.086.0194")
        sources = [
            _source_record(id=1, source="crossref", publisher_id=3),
            _source_record(id=2, source="hal", publisher_id=8),
        ]
        assign_publisher(
            publication, sources, source_priority=self._ORDRE, prefix_publishers={"10.3917": 3}
        )
        assert publication.publisher_id == 8
