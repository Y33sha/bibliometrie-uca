"""Doc_types hors périmètre métier : règle de scope explicite."""

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "memoir"})
"""Doc_types exclus de la logique métier : jamais matérialisés en publication.

Une œuvre dont le ``doc_type`` canonique résolu appartient à cet ensemble n'a pas de ligne
``publications`` : ``refresh_from_sources`` la supprime après l'arbitrage du type
(``application/publications/core.py``), au même titre qu'une publication orpheline. Ses
``source_publications`` et ``source_authorships`` subsistent — trace de leur passage en
source — mais détachées : sans publication, elles ne génèrent ni authorship canonique ni
personne, les deux chemins exigeant une publication matérialisée.

Justifications :

- ``peer_review`` : reviews de papers, pas une contribution scientifique en soi (les
  comptes de publications seraient pollués).
- ``memoir`` : essentiellement DUMAS (Master), étudiants pas membres permanents — les
  inclure polluerait ``persons`` de comptes éphémères.

Point d'application unique : le gate de ``refresh_from_sources``. Retirer un type de cet
ensemble suffit à le réintégrer à la matérialisation.
"""
