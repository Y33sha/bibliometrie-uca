"""Règles métier pures spécifiques à la source DataCite.

Interprétation des champs propres au schéma DataCite (réponse JSON:API
`api.datacite.org/dois/{doi}`, nœud `data.attributes`). Extracteurs et
nettoyeurs qui encapsulent les conventions DataCite pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API DataCite
(frontière dynamique avec une source externe, schéma non typé). Le `Any` est
délibéré, comme pour `domain.sources.crossref`.
"""

from __future__ import annotations

from typing import Any

from domain.publications.identifiers import clean_doi


def get_title(attributes: dict[str, Any]) -> str | None:
    """Titre principal : premier `titles[*].title` sans `titleType`
    (un `titleType` qualifie un sous-titre / titre alternatif / traduit).
    Fallback : premier titre disponible.
    """
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


def extract_datacite_pub_year(attributes: dict[str, Any], *, max_year: int) -> int | None:
    """Année de publication (`publicationYear`).

    Borne supérieure `max_year` (typiquement `current_year + 1`) : au-dessus,
    donnée polluée → None (le caller skippera, `refresh_from_sources`
    arbitrera). Borne inférieure 1500. `max_year` injecté pour la testabilité.
    """
    raw = attributes.get("publicationYear")
    if raw is None:
        return None
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    if 1500 <= year <= max_year:
        return year
    return None


def get_publisher_name(attributes: dict[str, Any]) -> str | None:
    """Nom de l'éditeur / dépôt (`publisher`).

    DataCite expose `publisher` comme chaîne (la plupart des cas) ou comme
    objet `{name, publisherIdentifier, ...}` (schéma 4.5). On gère les deux.
    """
    publisher = attributes.get("publisher")
    if isinstance(publisher, str) and publisher.strip():
        return publisher.strip()
    if isinstance(publisher, dict):
        name = publisher.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def get_container(attributes: dict[str, Any]) -> tuple[str | None, str | None]:
    """`(container_title, issn)` depuis `container`.

    Présent pour les contributions publiées dans une revue / série
    (`container.type` = Journal, Series…). Vide pour la majorité des datasets.
    L'ISSN n'est extrait que si `identifierType == 'ISSN'`.
    """
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


def get_abstract(attributes: dict[str, Any]) -> str | None:
    """Résumé : `descriptions` de `descriptionType == 'Abstract'` en priorité,
    sinon la première description disponible.
    """
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


def get_keywords(attributes: dict[str, Any]) -> list[str] | None:
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


def get_language(attributes: dict[str, Any]) -> str | None:
    """Code langue (`language`), normalisé en minuscules. Souvent absent."""
    lang = attributes.get("language")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()
    return None


def get_cited_by_count(attributes: dict[str, Any]) -> int | None:
    """Nombre de citations (`citationCount`)."""
    val = attributes.get("citationCount")
    return val if isinstance(val, int) else None


def extract_datacite_doc_type_token(attributes: dict[str, Any]) -> str | None:
    """Token brut de doc_type à stocker sur `source_publications.doc_type`.

    DataCite porte deux niveaux dans `types` : `resourceTypeGeneral`
    (vocabulaire contrôlé : JournalArticle, Preprint, Dataset, Text…) et
    `resourceType` (texte libre). On stocke un seul token, mappé ensuite par
    `domain.source_publications.doc_types._SOURCE_MAPS["datacite"]` :

    - `resourceTypeGeneral` spécifique (≠ Text / Other) → ce token ;
    - sinon `resourceType` libre s'il est renseigné ;
    - sinon le `resourceTypeGeneral` générique tel quel (mappé en `other`).
    """
    types = attributes.get("types")
    if not isinstance(types, dict):
        return None
    general = (types.get("resourceTypeGeneral") or "").strip()
    resource_type = (types.get("resourceType") or "").strip()
    if general and general.lower() not in {"text", "other"}:
        return general
    if resource_type:
        return resource_type
    return general or None


def _doi_related_identifiers(attributes: dict[str, Any]) -> list[dict[str, str]]:
    """`relatedIdentifiers` de type DOI, normalisés en
    `{"doi": <doi minuscule>, "relation_type": <relationType>}`.

    Conserve le `relationType` (`IsVersionOf`, `HasVersion`, `IsSupplementTo`,
    `IsPartOf`, `Cites`…) : c'est la matière des relations entre publications,
    et `IsVersionOf` porte le concept DOI (résolution concept/version).
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
        doi = clean_doi(entry.get("relatedIdentifier"))
        relation_type = entry.get("relationType")
        if doi and isinstance(relation_type, str) and relation_type:
            out.append({"doi": doi, "relation_type": relation_type})
    return out


# relationType DataCite qui dénotent une manifestation à rapatrier dans le
# corpus : même œuvre (versions, formes) ou œuvre étroitement liée (parties,
# suppléments). Les relations de citation (Cites / IsCitedBy / References /
# IsReferencedBy) en sont EXCLUES : elles désignent un lien bibliographique,
# pas une œuvre du périmètre — les verser dans le pool cross-import ferait
# ingérer toute la bibliographie citée. La nature complète des relations
# (citations comprises) reste tracée dans `meta.related_identifiers`.
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


def extract_related_dois(attributes: dict[str, Any], self_doi: str) -> list[str]:
    """DOI secondaires à rapatrier dans le corpus, hors DOI primaire, dédupliqués.

    Filtré sur `_CORPUS_RELATION_TYPES` (versions / formes / parties /
    suppléments) — pas les citations. Alimente `external_ids.related_dois`
    (pool cross-import). La liste typée complète vit dans
    `meta.related_identifiers`.
    """
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


def extract_datacite_meta(attributes: dict[str, Any]) -> dict[str, Any] | None:
    """Champs DataCite-spécifiques conservés en JSONB sur
    `source_publications.meta`.

    Whitelist : `related_identifiers` (DOI typés avec leur `relationType`,
    pour les relations et la résolution concept/version), `rights` (licences)
    et `funding` (financeurs).
    """
    meta: dict[str, Any] = {}
    related = _doi_related_identifiers(attributes)
    if related:
        meta["related_identifiers"] = related
    rights = attributes.get("rightsList")
    if isinstance(rights, list) and rights:
        meta["rights"] = rights
    funding = attributes.get("fundingReferences")
    if isinstance(funding, list) and funding:
        meta["funding"] = funding
    return meta or None
