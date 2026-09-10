"""Tests de l'agrégation cross-source (`domain.publications.aggregation.refresh_from_sources`).

Cible la priorité donnée aux enregistrements canoniques sur les formes secondaires convergées
(`secondary_ids`) : le titre et les autres scalaires viennent du parent, pas d'une pièce ; les
listes restent unionnées.
"""

from datetime import UTC, datetime

import pytest

from domain.publications.aggregation import refresh_from_sources
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication


def _sp(**overrides) -> SourcePublication:
    defaults = {
        "id": 1,
        "source": "datacite",
        "source_id": "s",
        "title": "Titre",
        "pub_year": 2020,
        "doc_type": "dataset",
        "doi": "10.parent/set",
        "journal_id": None,
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
        "meta": None,
    }
    defaults.update(overrides)
    return SourcePublication(**defaults)  # type: ignore[arg-type]


def _pub() -> Publication:
    return Publication(id=10, title="obsolète", pub_year=2020)


# `openalex` prioritaire sur `datacite` : sans dépriorisation, la pièce OpenAlex gagnerait le titre.
_PRIORITY = ("openalex", "datacite")


def test_parent_wins_title_over_higher_priority_secondary_piece():
    parent = _sp(id=1, source="datacite", title="Jeu de données phénotypiques", keywords=("blé",))
    piece = _sp(id=2, source="openalex", title="README_data.txt", keywords=("supplément",))

    pub = _pub()
    refresh_from_sources(
        pub, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )

    # Le parent (canonique) gagne le titre malgré la priorité de source de la pièce.
    assert pub.title == "Jeu de données phénotypiques"
    # Les mots-clés restent unionnés toutes sources confondues.
    assert set(pub.keywords) == {"blé", "supplément"}


def test_secondary_fills_scalar_absent_on_parent():
    # Le parent n'a pas d'abstract : la pièce, reléguée, comble quand même le champ vide.
    parent = _sp(id=1, source="datacite", abstract=None)
    piece = _sp(id=2, source="openalex", abstract="Description du jeu de données")

    pub = _pub()
    refresh_from_sources(
        pub, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )
    assert pub.abstract == "Description du jeu de données"


def test_without_secondary_ids_source_priority_decides():
    # Comportement par défaut inchangé : sans dépriorisation, la source prioritaire gagne le titre.
    parent = _sp(id=1, source="datacite", title="Jeu de données phénotypiques")
    piece = _sp(id=2, source="openalex", title="README_data.txt")

    pub = _pub()
    refresh_from_sources(pub, [piece, parent], source_priority=_PRIORITY)
    assert pub.title == "README_data.txt"


def test_une_source_sans_doc_type_laisse_la_suivante_le_donner():
    """Le type vient de la première source qui en porte un, les silencieuses étant passées.

    Toutes les sources ne renseignent pas le type de document. La plus prioritaire restant muette, l'agrégation lit la suivante plutôt que de conclure à l'absence de type.
    """
    muette = _sp(id=1, source="openalex", doc_type=None)
    parlante = _sp(id=2, source="datacite", doc_type="dataset")

    pub = _pub()
    refresh_from_sources(pub, [muette, parlante], source_priority=_PRIORITY)
    assert pub.doc_type == "dataset"


def test_un_sous_type_d_article_prime_sur_l_article_generique():
    """Une source sans type, placée en tête, n'interrompt pas la recherche du sous-type."""
    muette = _sp(id=1, source="openalex", doc_type=None)
    generique = _sp(id=2, source="crossref", doc_type="article")
    precise = _sp(id=3, source="datacite", doc_type="review")

    pub = _pub()
    refresh_from_sources(
        pub, [muette, generique, precise], source_priority=("openalex", "crossref", "datacite")
    )
    assert pub.doc_type == "review"


def test_sans_source_l_agregation_est_refusee():
    with pytest.raises(ValueError, match=r"^refresh_from_sources requiert au moins une source"):
        refresh_from_sources(_pub(), [], source_priority=_PRIORITY)


class TestOrdreDesSources:
    def test_la_priorite_ordonne_des_sources_recues_dans_le_desordre(self):
        datacite = _sp(id=1, source="datacite", title="Titre DataCite")
        openalex = _sp(id=2, source="openalex", title="Titre OpenAlex")

        pub = _pub()
        refresh_from_sources(pub, [datacite, openalex], source_priority=_PRIORITY)
        assert pub.title == "Titre OpenAlex"

    def test_une_source_hors_priorite_passe_apres_les_sources_classees(self):
        inconnue = _sp(id=1, source="wos", title="Titre WoS")
        classee = _sp(id=2, source="datacite", title="Titre DataCite")

        pub = _pub()
        refresh_from_sources(pub, [inconnue, classee], source_priority=_PRIORITY)
        assert pub.title == "Titre DataCite"


class TestChampsAgreges:
    def test_chaque_champ_vient_de_la_source(self):
        source = _sp(
            title="Blé <i>durum</i>",
            pub_year=2021,
            doi="10.1234/ABC",
            journal_id=7,
            container_title="Revue d'agronomie",
            language="fr",
            countries=("FR",),
            topics={"domaine": "agronomie"},
            biblio={"volume": "3"},
            meta={"licence": "cc-by"},
            is_retracted=True,
        )

        pub = _pub()
        refresh_from_sources(pub, [source], source_priority=_PRIORITY)
        assert pub.title_normalized == "ble durum"
        assert pub.pub_year == 2021
        assert pub.doi == DOI("10.1234/abc")
        assert pub.journal_id == 7
        assert pub.container_title == "Revue d'agronomie"
        assert pub.language == "fr"
        assert pub.countries == ("FR",)
        assert pub.topics == {"datacite": {"domaine": "agronomie"}}
        assert pub.biblio == {"volume": "3"}
        assert pub.meta == {"licence": "cc-by"}
        assert pub.is_retracted is True

    def test_les_mots_cles_sont_dedoublonnes_sans_egard_a_la_casse(self):
        premiere = _sp(id=1, source="openalex", keywords=("Blé",))
        seconde = _sp(id=2, source="datacite", keywords=("blé", "maïs"))

        pub = _pub()
        refresh_from_sources(pub, [premiere, seconde], source_priority=_PRIORITY)
        assert pub.keywords == ("Blé", "maïs")

    def test_les_jsonb_fusionnent_par_cle_au_profit_de_la_source_prioritaire(self):
        premiere = _sp(id=1, source="openalex", biblio={"volume": "3", "issue": "1"})
        seconde = _sp(id=2, source="datacite", biblio={"volume": "4", "pages": "5-9"})

        pub = _pub()
        refresh_from_sources(pub, [premiere, seconde], source_priority=_PRIORITY)
        assert pub.biblio == {"volume": "3", "issue": "1", "pages": "5-9"}


class TestStatutOa:
    """Le statut le plus ouvert des sources, tant qu'Unpaywall n'a pas été interrogé."""

    _VERIFIE = datetime(2026, 1, 1, tzinfo=UTC)

    def test_le_statut_le_plus_ouvert_l_emporte(self):
        verte = _sp(id=1, source="hal", oa_status="green")
        doree = _sp(id=2, source="openalex", oa_status="gold")

        pub = _pub()
        refresh_from_sources(pub, [verte, doree], source_priority=("hal", "openalex"))
        assert pub.oa_status == "gold"

    def test_des_sources_muettes_donnent_un_statut_inconnu(self):
        pub = _pub()
        refresh_from_sources(pub, [_sp(oa_status=None)], source_priority=_PRIORITY)
        assert pub.oa_status == OA_STATUS_UNKNOWN_DEFAULT

    def test_un_depot_en_archive_ouverte_rouvre_un_statut_ferme_par_unpaywall(self):
        pub = _pub()
        pub.oa_status, pub.unpaywall_checked_at = "closed", self._VERIFIE
        refresh_from_sources(pub, [_sp(source="hal", oa_status="green")], source_priority=("hal",))
        assert pub.oa_status == "green"

    def test_sans_depot_le_statut_ferme_par_unpaywall_tient(self):
        pub = _pub()
        pub.oa_status, pub.unpaywall_checked_at = "closed", self._VERIFIE
        refresh_from_sources(
            pub, [_sp(source="openalex", oa_status="gold")], source_priority=_PRIORITY
        )
        assert pub.oa_status == "closed"

    def test_un_statut_ouvert_d_unpaywall_tient_malgre_un_depot(self):
        pub = _pub()
        pub.oa_status, pub.unpaywall_checked_at = "hybrid", self._VERIFIE
        refresh_from_sources(pub, [_sp(source="hal", oa_status="green")], source_priority=("hal",))
        assert pub.oa_status == "hybrid"
