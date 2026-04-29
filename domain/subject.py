"""Concept métier Sujet (mot-clé libre ou concept ontologique).

Une publication est annotée par 0..N sujets, chacun étant soit :
- un **mot-clé libre** (`kind='free'`) : forme observée dans une source, sans
  ontologie de référence ; déduplication soft sur `(lower(label), language)`.
- un **concept** (`kind='concept'`) : terme contrôlé d'une ontologie identifiée
  (`ontology`) avec un identifiant stable (`ontology_id`) ; déduplication
  stricte sur `(ontology, ontology_id)`.

Pas d'ontologie pivot en première approche : chaque ontologie cohabite et
on agrège côté UI. Voir docs/chantiers/sujets-mots-cles.md.
"""

from typing import Literal

# ── Discriminant ────────────────────────────────────────────────

SubjectKind = Literal["free", "concept"]

SUBJECT_KINDS: frozenset[str] = frozenset({"free", "concept"})


# ── Ontologies reconnues ────────────────────────────────────────
# Chaque clé désigne un **vocabulaire** distinct ; l'`ontology_id` stocké
# dans `subjects.ontology_id` doit être stable pour cette ontologie.
#
# Conventions par ontologie :
# - openalex_topic    : `ontology_id` = identifiant OpenAlex (ex 'T10138').
#                       Hiérarchie 4 niveaux exposée via `parent_id`/`level`.
#                       Niveaux : 0=domain, 1=field, 2=subfield, 3=topic.
# - openalex_keyword  : `ontology_id` = identifiant OpenAlex du keyword.
# - hal_domain        : `ontology_id` = code HAL ('info.eea', 'sdv.bbm', …).
# - wos_subject       : `ontology_id` = `lower(label)` (pas d'ID stable côté WoS).
# - wos_heading       : idem.
# - rameau            : `ontology_id` = `lower(label)` (PPN RAMEAU non exposé
#                       systématiquement par theses.fr).
# - theses_discipline : `ontology_id` = `lower(label)`.
# - scanr_domain      : `ontology_id` = `lower(label)` (ScanR n'expose pas
#                       d'ID ontologique stable côté API publique).

ONTOLOGY_OPENALEX_TOPIC = "openalex_topic"
ONTOLOGY_OPENALEX_KEYWORD = "openalex_keyword"
ONTOLOGY_HAL_DOMAIN = "hal_domain"
ONTOLOGY_WOS_SUBJECT = "wos_subject"
ONTOLOGY_WOS_HEADING = "wos_heading"
ONTOLOGY_RAMEAU = "rameau"
ONTOLOGY_THESES_DISCIPLINE = "theses_discipline"
ONTOLOGY_SCANR_DOMAIN = "scanr_domain"

ONTOLOGIES: frozenset[str] = frozenset(
    {
        ONTOLOGY_OPENALEX_TOPIC,
        ONTOLOGY_OPENALEX_KEYWORD,
        ONTOLOGY_HAL_DOMAIN,
        ONTOLOGY_WOS_SUBJECT,
        ONTOLOGY_WOS_HEADING,
        ONTOLOGY_RAMEAU,
        ONTOLOGY_THESES_DISCIPLINE,
        ONTOLOGY_SCANR_DOMAIN,
    }
)


# ── Helpers de normalisation ────────────────────────────────────


def normalize_free_label(label: str) -> str:
    """Trim + collapse interne pour les mots-clés libres avant insertion.

    On ne touche ni à la casse ni aux accents : la déduplication se fait
    en SQL via `lower(label)` (index unique partiel). On préserve la forme
    originale du premier insert dans `subjects.label`.
    """
    return " ".join(label.split())
