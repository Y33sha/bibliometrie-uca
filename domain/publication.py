"""Règles métier publication, projections de lecture, façade sur les
identifiants.

Contenu :
- Projections (`PubByDoi`, `PubByNnt`, `PubByTitle`, `PubThesisCandidate`) :
  formes de résultat renvoyées par `PublicationRepository`.
- Règle d'agrégation OA multi-sources (`best_oa_status`, `OA_RANK`,
  `OA_STATUS_UNKNOWN_DEFAULT`).
- Décodage des titres double-encodés HTML (`clean_publication_title`).
- Façade ré-exportant `DOI`, `HALId`, `NNT`, `clean_doi`,
  `normalize_nnt`, `extract_hal_id_from_url` depuis
  `domain/publications/identifiers.py` — les nouveaux call sites
  importent directement depuis le module spécialisé.

Les modèles des colonnes JSONB (`external_ids`, `biblio`, `meta`,
`topics`) vivent côté infrastructure
(`infrastructure/db/jsonb_models/publication.py`) — c'est un détail
d'adapter de persistance, pas du métier.

Résolution de conflit DOI (`resolve_doi_conflict`,
`DoiConflictResolution`) : voir `domain/publications/dedup.py`.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Ré-exports — voir docstring du module.
from domain.publications.identifiers import (
    DOI,
    NNT,
    HALId,
    clean_doi,
    extract_hal_id_from_url,
    normalize_nnt,
)

__all__ = [
    "DOI",
    "HALId",
    "NNT",
    "clean_doi",
    "normalize_nnt",
    "extract_hal_id_from_url",
    "PubByDoi",
    "PubByNnt",
    "PubByTitle",
    "PubThesisCandidate",
    "OA_RANK",
    "OA_STATUS_UNKNOWN_DEFAULT",
    "best_oa_status",
    "clean_publication_title",
]

# ── Types de résultats de recherche ────────────────────────────────
# Utilisés par le port PublicationRepository et ses implémentations.
# Vivent dans le domaine car ils décrivent la forme d'un résultat
# métier, pas un détail d'infrastructure.
#
# Dataclasses avec `slots=True` pour occuper le mappage fait par
# `psycopg.rows.class_row(...)` : les noms de champs correspondent aux
# colonnes SELECT du repo.


@dataclass(frozen=True, slots=True)
class PubByDoi:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByNnt:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByTitle:
    id: int
    doi: str | None


@dataclass(frozen=True, slots=True)
class PubThesisCandidate:
    id: int
    doi: str | None


# ── Décodage des titres double-encodés HTML ────────────────────────
#
# OpenAlex et ScanR remontent parfois des titres avec un encodage HTML
# appliqué deux fois — par exemple "<i>Candida</i>" arrive en base sous
# la forme "&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;". On corrige au
# moment d'écrire dans `publications.title` pour que la couche canonique
# reste propre, indépendamment de la qualité du flux source.

_HTML_ENTITY_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_DOUBLE_ENCODED_RE = re.compile(r"&amp;(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _decode_html_entities_once(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name[1] in "xX" else int(name[1:])
                return chr(code)
            except (ValueError, OverflowError):
                return m.group(0)
        return _HTML_ENTITY_NAMED.get(name, m.group(0))

    return _HTML_ENTITY_RE.sub(repl, s)


def clean_publication_title(title: str | None) -> str | None:
    """Décode un titre double-encodé HTML, sinon le retourne tel quel.

    Détection : présence d'`&amp;` immédiatement suivi d'une entité connue
    (`lt`, `gt`, `amp`, `quot`, `apos`, `#NNN`, `#xHH`). Ce motif est la
    signature du double-encodage et ne se rencontre pas dans un titre
    normal (un `&amp;` isolé légitime style "Smith &amp; Jones" n'est pas
    suivi d'un nom d'entité, donc reste inchangé).

    Quand détecté, on décode deux niveaux pour retomber sur le HTML
    d'origine. Idempotent : un second appel sur le résultat ne change rien.
    """
    if not title or not _DOUBLE_ENCODED_RE.search(title):
        return title
    return _decode_html_entities_once(_decode_html_entities_once(title))


# ── Règles métier d'agrégation multi-sources ────────────────────────

# Classement des statuts OA : plus la valeur est grande, plus le
# statut est « ouvert ». Utilisé par `best_oa_status` pour choisir le
# statut le plus ouvert entre plusieurs sources.
OA_RANK: dict[str, int] = {
    "diamond": 7,
    "gold": 6,
    "hybrid": 5,
    "bronze": 4,
    "green": 3,
    "closed": 2,
    "unknown": 1,
}

# Valeur canonique de `publications.oa_status` quand aucune source n'a
# de signal exploitable. Convention : `source_publications.oa_status`
# accepte NULL (= la source ne s'est pas prononcée), mais au niveau
# canonique on matérialise l'absence de signal par 'unknown' (vraie
# valeur de l'enum, classée en queue d'`OA_RANK`). À utiliser comme
# fallback après `best_oa_status(...)` ou pour défaut sur
# `source_publications.oa_status` orphelin.
OA_STATUS_UNKNOWN_DEFAULT = "unknown"


def best_oa_status(statuses: Iterable[str | None]) -> str | None:
    """Retourne le statut OA le plus ouvert parmi `statuses`.

    Ordre décroissant : diamond > gold > hybrid > bronze > green > closed > unknown.
    Les valeurs None, vides ou inconnues sont ignorées. Retourne None
    si aucune valeur exploitable n'est fournie.
    """
    best: str | None = None
    best_rank = 0
    for s in statuses:
        if not s:
            continue
        r = OA_RANK.get(s, 0)
        if r > best_rank:
            best, best_rank = s, r
    return best
