"""Lecture des enregistrements sources DataCite par la normalisation : conventions des `attributes` d'une ressource JSON:API.

Les payloads sont les objets JSON bruts de l'API, sans schéma typé.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from domain.publications.identifiers import clean_doi, find_isbns
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str


def get_title(attributes: Mapping[str, JsonValue]) -> str | None:
    """Titre principal : le premier titre sans `titleType`, à défaut le premier titre. Un `titleType` qualifie un sous-titre, un titre alternatif ou traduit."""
    titles = attributes.get("titles") or []
    if not isinstance(titles, list):
        return None
    fallback: str | None = None
    for entry in titles:
        if not isinstance(entry, dict):
            continue
        value = entry.get("title")
        if not isinstance(value, str) or not value.strip():
            continue
        if not entry.get("titleType"):
            return value.strip()
        if fallback is None:
            fallback = value.strip()
    return fallback


def extract_datacite_publication_year(
    attributes: Mapping[str, JsonValue], *, max_year: int
) -> int | None:
    """Année de publication (`publicationYear`), si elle tient entre 1500 et `max_year`. Sans elle, la normalisation refuse l'enregistrement."""
    raw = attributes.get("publicationYear")
    # L'année arrive en nombre ou en texte selon le dépôt ; toute autre forme ne dit rien.
    if not isinstance(raw, str | int) or isinstance(raw, bool):
        return None
    try:
        year = int(raw)
    except ValueError:
        return None
    if 1500 <= year <= max_year:
        return year
    return None


def get_publisher_name(attributes: Mapping[str, JsonValue]) -> str | None:
    """Nom de l'éditeur ou de l'entrepôt (`publisher`), donné en chaîne ou, depuis le schéma 4.5, en objet `{name, publisherIdentifier, …}`."""
    publisher = attributes.get("publisher")
    if isinstance(publisher, str) and publisher.strip():
        return publisher.strip()
    if isinstance(publisher, dict):
        name = publisher.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def get_container(attributes: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """Titre et ISSN du `container`, que donnent les documents publiés dans une revue ou une série. L'ISSN vient seulement d'un identifiant de type `ISSN`."""
    container = attributes.get("container")
    if not isinstance(container, dict) or not container:
        return None, None
    title = container.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    issn = None
    if container.get("identifierType") == "ISSN":
        identifier = container.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            issn = identifier.strip()
    return title, issn


def get_isbns(attributes: Mapping[str, JsonValue]) -> list[str]:
    """ISBN du document (`own_isbns`), puis ceux de l'ouvrage qui le contient (`host_isbns`), dédoublonnés."""
    return list(dict.fromkeys([*own_isbns(attributes), *host_isbns(attributes)]))


def own_isbns(attributes: Mapping[str, JsonValue]) -> list[str]:
    """ISBN des identifiants du document (`identifiers`, `alternateIdentifiers`). L'ISBN d'un livre figure parmi ses identifiants. DataCite ne dit pas le support."""
    isbns: list[str] = []
    for key, value_key, type_key in (
        ("identifiers", "identifier", "identifierType"),
        ("alternateIdentifiers", "alternateIdentifier", "alternateIdentifierType"),
    ):
        for identifier in as_sequence(attributes.get(key)):
            entry = as_mapping(identifier)
            if (as_str(entry.get(type_key)) or "").upper() == "ISBN":
                isbns += find_isbns(as_str(entry.get(value_key)))
    return isbns


def host_isbns(attributes: Mapping[str, JsonValue]) -> list[str]:
    """ISBN des `relatedIdentifiers` de type ISBN et du conteneur quand son identifiant en est un. L'ISBN du livre d'un chapitre figure en `IsPartOf`."""
    isbns: list[str] = []
    for related in as_sequence(attributes.get("relatedIdentifiers")):
        entry = as_mapping(related)
        if (as_str(entry.get("relatedIdentifierType")) or "").upper() == "ISBN":
            isbns += find_isbns(as_str(entry.get("relatedIdentifier")))
    container = as_mapping(attributes.get("container"))
    if (as_str(container.get("identifierType")) or "").upper() == "ISBN":
        isbns += find_isbns(as_str(container.get("identifier")))
    return isbns


def get_container_pages(attributes: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """Première et dernière pages du `container`."""
    container = attributes.get("container")
    if not isinstance(container, dict):
        return None, None
    return as_str(container.get("firstPage")), as_str(container.get("lastPage"))


def get_abstract(attributes: Mapping[str, JsonValue]) -> str | None:
    """Résumé : `descriptions` de `descriptionType == 'Abstract'` en priorité, sinon la première description disponible."""
    descriptions = attributes.get("descriptions") or []
    if not isinstance(descriptions, list):
        return None
    fallback: str | None = None
    for entry in descriptions:
        if not isinstance(entry, dict):
            continue
        value = entry.get("description")
        if not isinstance(value, str) or not value.strip():
            continue
        if entry.get("descriptionType") == "Abstract":
            return value.strip()
        if fallback is None:
            fallback = value.strip()
    return fallback


def get_keywords(attributes: Mapping[str, JsonValue]) -> list[str] | None:
    """Mots-clés : `subjects[*].subject`, dédupliqués en préservant l'ordre."""
    subjects = attributes.get("subjects") or []
    if not isinstance(subjects, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for entry in subjects:
        if not isinstance(entry, dict):
            continue
        value = entry.get("subject")
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = value.strip()
        if cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
    return out or None


def get_language(attributes: Mapping[str, JsonValue]) -> str | None:
    """Code langue (`language`), normalisé en minuscules. Souvent absent."""
    lang = attributes.get("language")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()
    return None


def get_cited_by_count(attributes: Mapping[str, JsonValue]) -> int | None:
    """Nombre de citations (`citationCount`)."""
    val = attributes.get("citationCount")
    return val if isinstance(val, int) else None


def extract_datacite_doc_type_token(attributes: Mapping[str, JsonValue]) -> str | None:
    """Type brut du document (`raw_doc_type`), que traduit la table des types de DataCite (`map_doc_type`).

    DataCite donne deux niveaux dans `types` : `resourceTypeGeneral`, au vocabulaire contrôlé (JournalArticle, Preprint, Dataset, Text…), et `resourceType`, en texte libre. Le type brut est `resourceTypeGeneral` s'il est spécifique (hors Text et Other), à défaut `resourceType`, à défaut le `resourceTypeGeneral` générique, traduit en `other`.
    """
    types = attributes.get("types")
    if not isinstance(types, dict):
        return None
    general = (as_str(types.get("resourceTypeGeneral")) or "").strip()
    resource_type = (as_str(types.get("resourceType")) or "").strip()
    if general and general.lower() not in {"text", "other"}:
        return general
    if resource_type:
        return resource_type
    return general or None


# Types d'un document que publie une revue, une collection ou un recueil d'actes. La valeur contrôlée `JournalArticle` date du schéma 4.4 (2021) ; avant, un article se déclarait `Text`, avec « Journal article » ou « Article » en texte libre.
_PUBLISHED_TYPES = frozenset(
    {
        "Book",
        "BookChapter",
        "ConferencePaper",
        "ConferenceProceeding",
        "DataPaper",
        "JournalArticle",
    }
)
_ARTICLE_FREE_TEXT = frozenset({"article", "journal article"})
# Conteneur découpé dans une citation en texte libre (`SeriesInformation`) : volume dans le titre (« Physics letters / B 777 », « Journal of Instrumentation 16(07) »), année ou DOI dans les pages (« 162 (2018). doi:10.1016/… »).
_VOLUME_IN_TITLE = re.compile(r"/ .*\d|\d+\s*\(\d+\)\s*$")
_CITATION_IN_PAGES = re.compile(r"doi:|\((?:1[89]|20)\d\d\)", re.IGNORECASE)


def container_names_a_journal(
    doc_type_token: str | None, title: str, pages: Iterable[str | None]
) -> bool:
    """Le conteneur d'un enregistrement source DataCite désigne la revue, la collection ou le recueil d'actes qui publie le document.

    Le type brut (`extract_datacite_doc_type_token`) est celui d'un article, d'une communication, d'un recueil d'actes, d'un livre, d'un chapitre ou d'un data paper. Un préprint, un rapport, un logiciel ou un jeu de données n'a pas de revue. Le conteneur ne vient pas d'une citation en texte libre : les copies d'articles déposées par les entrepôts (GSI, DESY, RWTH) citent ainsi l'article publié, et DataCite en découpe mal le titre et les pages.
    """
    published_type = (
        doc_type_token in _PUBLISHED_TYPES
        or (doc_type_token or "").strip().lower() in _ARTICLE_FREE_TEXT
    )
    return (
        published_type
        and not _VOLUME_IN_TITLE.search(title)
        and not any(page and _CITATION_IN_PAGES.search(page) for page in pages)
    )


def _doi_related_identifiers(attributes: Mapping[str, JsonValue]) -> list[dict[str, str]]:
    """`relatedIdentifiers` de type DOI, normalisés en `{"doi": <doi minuscule>, "relation_type": <relationType>}`.

    Le `relationType` (`IsVersionOf`, `HasVersion`, `IsSupplementTo`, `IsPartOf`, `Cites`…) fonde les relations entre publications ; `IsVersionOf` désigne le DOI de concept d'une version.
    """
    related = attributes.get("relatedIdentifiers") or []
    if not isinstance(related, list):
        return []
    out: list[dict[str, str]] = []
    for entry in related:
        if not isinstance(entry, dict):
            continue
        if entry.get("relatedIdentifierType") != "DOI":
            continue
        doi = clean_doi(as_str(entry.get("relatedIdentifier")))
        relation_type = entry.get("relationType")
        if doi and isinstance(relation_type, str) and relation_type:
            out.append({"doi": doi, "relation_type": relation_type})
    return out


# `relationType` DataCite d'un document à rapatrier : même œuvre (versions, formes) ou œuvre étroitement liée (parties, suppléments).
# Les citations (Cites, IsCitedBy, References, IsReferencedBy) restent hors de la liste : la phase `fetch_missing` rapatrierait toute la bibliographie citée. `source_extras.related_identifiers` garde toutes les relations.
_CORPUS_RELATION_TYPES = frozenset(
    {
        "IsVersionOf",
        "HasVersion",
        "IsNewVersionOf",
        "IsPreviousVersionOf",
        "IsIdenticalTo",
        "IsVariantFormOf",
        "IsOriginalFormOf",
        "IsSupplementTo",
        "IsSupplementedBy",
        "IsPartOf",
        "HasPart",
    }
)


def extract_related_dois(attributes: Mapping[str, JsonValue], self_doi: str) -> list[str]:
    """DOI apparentés à rapatrier, hors DOI primaire et sans doublon : versions, formes, parties et suppléments (`_CORPUS_RELATION_TYPES`). Ils deviennent des identifiants liés, que la phase `fetch_missing` cherche dans chaque source."""
    self_doi_clean = clean_doi(self_doi)
    out: list[str] = []
    seen: set[str] = set()
    for item in _doi_related_identifiers(attributes):
        if item["relation_type"] not in _CORPUS_RELATION_TYPES:
            continue
        doi = item["doi"]
        if doi == self_doi_clean or doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def extract_datacite_source_extras(
    attributes: Mapping[str, JsonValue],
) -> Mapping[str, JsonValue] | None:
    """Champs propres à DataCite gardés dans `source_records.source_extras` : DOI apparentés avec leur `relationType`, licences (`rights`) et financeurs (`funding`)."""
    source_extras: dict[str, JsonValue] = {}
    related = _doi_related_identifiers(attributes)
    if related:
        source_extras[SourceExtra.RELATED_IDENTIFIERS] = related
    rights = attributes.get("rightsList")
    if isinstance(rights, list) and rights:
        source_extras[SourceExtra.RIGHTS] = rights
    funding = attributes.get("fundingReferences")
    if isinstance(funding, list) and funding:
        source_extras[SourceExtra.FUNDING] = funding
    return source_extras or None
