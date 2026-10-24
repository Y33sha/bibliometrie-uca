# Chantier — Typage des tests et des scripts ponctuels

## Contexte

pyrefly vérifie les tests et les scripts ponctuels (`interfaces/cli/oneshot/`) avec une sous-configuration de `pyproject.toml`. Elle garde les erreurs qui signalent du code cassé : import d'un nom ou d'un module inexistant, nom inconnu, mot-clé inconnu, gestionnaire de contexte invalide. Elle coupe quinze catégories, faute de types dans ce code.

Au 2026-10-24, les catégories coupées représentent dans les tests environ 9 350 erreurs d'annotation (`unannotated-return`, `implicit-any-parameter`, `implicit-any-type-argument`) et 670 autres. Ces dernières sont surtout des accès que l'analyse ne prouve pas sûrs : `bad-index` (206), `bad-argument-type` (198), `missing-attribute` (94), `unsupported-operation` (76), `not-iterable` (56). Les scripts ponctuels en comptent une vingtaine.

## Décisions

- Les catégories se réactivent une à une, de la moins coûteuse à la plus coûteuse.
- Une catégorie réactivée l'est pour les tests et les scripts ponctuels à la fois.

## Phasage

### Phase 1 — Accès non prouvés

- [ ] `read-only`, `no-matching-overload`, `bad-assignment`, `bad-return`.
- [ ] `not-iterable`, `unsupported-operation`.
- [ ] `missing-attribute`, `bad-argument-type`, `bad-index`.

### Phase 2 — Annotations

- [ ] `explicit-any`, `no-any-return-implicit`, `no-any-return-explicit`.
- [ ] `implicit-any-type-argument`.
- [ ] `implicit-any-parameter`, `unannotated-return`.

## Questions ouvertes

- Annoter les quelque 9 000 fonctions de test sans type de retour apporte-t-il assez pour son coût ?
