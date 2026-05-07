"""Doc_types hors périmètre métier : règle de scope explicite."""

OUT_OF_SCOPE_DOC_TYPES = frozenset({"peer_review", "memoir"})
"""Doc_types stockés en BDD mais hors de la logique métier aval.

Pour ces publications :
- on conserve ``publications``, ``source_publications``,
  ``source_authorships`` (trace de leur passage dans les sources, pas
  de perte d'info)
- on NE matche PAS leurs authorships à des personnes
  (``source_authorships.person_id`` reste NULL)
- on N'insère PAS de lignes dans la table canonique ``authorships``
- elles sont absentes des listings publics, facets, stats, périmètres
  laboratoire

Justifications :

- ``peer_review`` : reviews de papers, pas une contribution
  scientifique en soi (les comptes de publis seraient pollués).
- ``memoir`` : essentiellement DUMAS (Master), étudiants pas membres
  permanents UCA — les inclure dans le matching pollue ``persons``
  avec des comptes éphémères qui ne re-publieront probablement pas.

Implémenté à deux niveaux côté infrastructure :

1. Vue SQL ``v_active_publications`` (dans le schéma) : filtre tôt
   pour les jointures massives du pipeline (étape ``build_authorships``,
   ``fetch_unlinked_authorships``).
2. Filtres ``doc_type NOT IN ...`` répétés dans les queries de
   listing/facets/stats — tous doivent référencer cette constante via
   ``OUT_OF_SCOPE_DOC_TYPES_SQL`` plutôt que hardcoder la liste.

La vue SQL ne peut pas importer la constante Python directement ;
sa définition est figée dans une migration. Un test d'intégration
``tests/integration/infrastructure/db/test_active_publications_view.py``
vérifie que le contenu de la vue correspond bien à
``OUT_OF_SCOPE_DOC_TYPES``, comme garde-fou contre la divergence
silencieuse.
"""


OUT_OF_SCOPE_DOC_TYPES_SQL: str = (
    "(" + ", ".join(f"'{t}'" for t in sorted(OUT_OF_SCOPE_DOC_TYPES)) + ")"
)
"""Forme SQL ``('memoir', 'peer_review')`` pour les clauses ``NOT IN``.

Pattern symétrique à ``AUTHOR_SOURCES_SQL`` dans
``domain/sources/__init__.py``. Les clés sont triées pour produire
une représentation déterministe (utile pour les tests et les diffs).
"""
