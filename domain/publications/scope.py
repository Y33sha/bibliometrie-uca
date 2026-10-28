"""Périmètre des publications : types de document admissibles, enregistrements sources écartés."""

from domain.publications.identifiers import DOI
from domain.publications.metadata import normalized_title

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "memoir", "physical_object"})
"""Types de document non admissibles : jamais matérialisés en publication.

Une œuvre dont le `doc_type` canonique résolu appartient à cet ensemble n'a pas de ligne
`publications` : le module du cycle de vie la supprime après l'arbitrage du type
(`pipeline/transformation/publications/lifecycle.py`). Ses `source_records` et
`source_contributions` subsistent, détachées : sans publication, elles ne génèrent ni
contribution canonique ni personne.

Justifications :

- `peer_review` : reviews de papers, pas une contribution scientifique en soi (les
  comptes de publications seraient pollués).
- `memoir` : essentiellement DUMAS (Master), étudiants pas membres permanents — les
  inclure polluerait `persons` de comptes éphémères.
- `physical_object` : échantillon ou instrument identifié par un DOI DataCite (IGSN des
  échantillothèques), pas un texte publié.

Deux points d'application : un enregistrement de l'un de ces types ne fonde pas de publication
à la réconciliation (`domain/publications/reconciliation.py`), et le module du cycle de vie
supprime la publication dont le type résolu est de cet ensemble. Retirer un type de cet
ensemble suffit à le réintégrer à la matérialisation.
"""

EXCLUDED_DOI_PREFIXES = frozenset({"10.60692"})
"""Préfixes DOI dont les enregistrements sources sont écartés de la réconciliation.

- `10.60692` : GRESIS (gresis.osc.int). Copies d'enregistrements OpenAlex aux titres traduits automatiquement, sans relation déclarée avec le DOI de l'éditeur.
"""

PARATEXT_TITLES = frozenset(
    normalized_title(title)
    for title in (
        "Auteurs",
        "Bibliographie",
        "Bibliographie sélective",
        "Contributors",
        "Front Matter",
        "Frontmatter",
        "Index",
        "Index des notions",
        "Index des personnes",
        "Les auteurs",
        "List of Authors",
        "List of Contributors",
        "Liste des auteurs",
        "Notes on Contributors",
        "README.txt",
        "References",
        "Sommaire",
        "Table des matières",
        "Table of Contents",
    )
)
"""Titres normalisés de paratexte : pages liminaires, listes d'auteurs, index, bibliographies. Leurs enregistrements sources sont écartés de la réconciliation."""


def is_excluded_source_record(doi: str | None, title_normalized: str | None) -> bool:
    """L'enregistrement source est écarté de la réconciliation : son DOI a un préfixe de `EXCLUDED_DOI_PREFIXES`, ou son titre normalisé est dans `PARATEXT_TITLES`."""
    parsed = DOI.try_parse(doi)
    if parsed is not None and parsed.prefix.value in EXCLUDED_DOI_PREFIXES:
        return True
    return title_normalized in PARATEXT_TITLES
