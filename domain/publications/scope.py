"""Types de document admissibles en publication."""

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
