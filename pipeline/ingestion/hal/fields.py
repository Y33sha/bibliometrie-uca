"""Champs des notices HAL.

Champs Solr à récupérer dans les requêtes HAL : un champ absent de la liste n'est pas extrait de l'API. Lecture de l'identifiant et du DOI d'une notice.
"""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.sources.hal import hal_text_field
from domain.types import JsonValue

HAL_FIELDS = [
    "halId_s",
    "doiId_s",
    "title_s",
    "subTitle_s",
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
    # label_xml (TEI) : seul champ qui attache ORCID/IdRef à chaque auteur
    # par position. Les listes `authORCIDIdExt_s` / `authIdRefIdExt_s`
    # sont compactées (valeurs non-null seulement, pas d'alignement) et
    # ne sont donc pas demandées.
    "label_xml",
    "producedDateY_i",
    "publicationDate_s",
    "docType_s",
    "docSubType_s",
    "language_s",
    "journalTitle_s",
    "journalIssn_s",
    "journalEissn_s",
    "journalPublisher_s",
    "bookTitle_s",
    "publisher_s",
    "conferenceTitle_s",
    # Publication d'une communication : indicateur « avec actes », collections, titre de la source.
    "proceedings_s",
    "serie_s",
    "source_s",
    "openAccess_bool",
    "fileMain_s",
    # Licence du fichier déposé (URL), présente quand un fichier est déposé.
    "licence_s",
    "linkExtId_s",
    "linkExtUrl_s",
    "uri_s",
    "label_s",
    "collCode_s",
    "nntId_s",
    "pubmedid_s",
    "abstract_s",
    "keyword_s",
    # Domaines CCSD : `<code>_FacetSep_<libellé racine>/…/<libellé feuille>`, qui
    # porte le libellé de chaque niveau. `domain_s` n'expose que les codes.
    "fr_domainAllCodeLabel_fs",
    "volume_s",
    "issue_s",
    "page_s",
]

HAL_FIELDS_STR = ",".join(HAL_FIELDS)


def extract_id(doc: Mapping[str, JsonValue]) -> str:
    """Identifiant HAL d'une notice (champ `halId_s`), chaîne vide s'il manque."""
    return hal_text_field(doc.get("halId_s")) or ""


def extract_doi(doc: Mapping[str, JsonValue]) -> str | None:
    """DOI nettoyé d'une notice HAL (champ `doiId_s`).

    `doiId_s` arrive en scalaire depuis le moissonnage, en liste depuis la recherche par identifiant HAL : les deux formes sont gérées avant nettoyage.
    """
    return clean_doi(hal_text_field(doc.get("doiId_s")))
