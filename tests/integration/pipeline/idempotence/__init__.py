"""Tests d'idempotence des phases du pipeline.

Principe : insérer des données de staging, lancer la phase, compter les
résultats, relancer, vérifier que les compteurs n'ont pas bougé.

Un fichier par phase (`normalize_<source>`, `persons`, `authorships`,
`affiliations`), plus `normalize_inter_source` pour la combinatoire
multi-sources. Les helpers vraiment partagés vivent dans `_helpers.py`.

Tournent sur la base `bibliometrie_test` (cf. `conftest.py` parent).
"""
