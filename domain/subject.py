"""Concept métier Sujet : libellé canonique + annotations multi-ontologies.

Un sujet = un libellé observé sur des publications, dédupliqué sur
`lower(label)`. Les ontologies qui l'ont annoté sont listées dans
`subjects.ontologies` (JSONB) au format :

    {"hal_domain": ["info"], "theses_discipline": ["informatique"]}

Les valeurs sont des listes : on agrège les codes intra-ontologie quand
plusieurs concepts source partagent le même libellé feuille (ex `info` et
`scco.comp` chez HAL, tous deux libellés "Informatique").

Un sujet sans aucune ontologie (`ontologies = {}`) correspond à un
mot-clé libre observé tel quel sur une publication. Voir
docs/chantiers/sujets-mots-cles.md.
"""

# ── Ontologies reconnues ────────────────────────────────────────
# Conventions par ontologie :
# - openalex_topic    : id = lower(display_name) ; hiérarchie 4 niveaux
#                       exposée via `parent_id`/`level`. 0=domain, 1=field,
#                       2=subfield, 3=topic.
# - openalex_keyword  : id = lower(display_name).
# - hal_domain        : id = code HAL CCSD ('info', 'chim.anal', …) ;
#                       label dérivé de `domain.hal_domains` (feuille).
# - wos_subject       : id = lower(label).
# - wos_heading       : id = lower(label).
# - rameau            : id = lower(label).
# - theses_discipline : id = lower(label).
# - scanr_domain      : id = lower(label).

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


def normalize_label(label: str) -> str:
    """Trim + collapse interne pour les libellés de sujet avant insertion.

    On ne touche ni à la casse ni aux accents : la déduplication se fait
    en SQL via `lower(label)` (index unique). On préserve la forme
    originale du premier insert dans `subjects.label`.
    """
    return " ".join(label.split())
