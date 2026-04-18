# Roadmap transmission DSI

## Chantier transition DDD
* repérer incohérences restantes (sql pas à sa place, dépendances dans le mauvais sens) et les corriger
* verrouiller les acquis: import-linter

## Chantier qualité du code: maintenabilité, auditabilité, scalabilité...
* mieux organiser le dossier tests
* audit 12 factors
* audit SOLID
* hook pre-commit (ruff, mypy, import-linter, tests)

## Chantier fonctionnalités (TODO_LAURA)


## Ancienne roadmap à terminer
- [ ] Alerting sur échec pipeline (email ou webhook)
- [ ] Checks automatiques post-pipeline (comptages, orphelins, anomalies)

## Divers, à réorganiser
### Niveau 0 — instrumenter avant de toucher.

linter: ruff
formateur (ruff format)
type checker (mypy mode permissif : 73 erreurs)
coverage. pytest --cov
tests de caractérisation sur les endpoints/fonctions critiques => services, routers

### Niveau 1 — architecture et découpage.

abstraire la logique commune aux sources
creuser architecture hexagonale

Questions à poser à ton code : y a-t-il une séparation claire entre couche données (accès SQL), couche métier (logique bibliométrique, règles de matching, algorithme pays), couche API (FastAPI routes, sérialisation), et couche présentation (Svelte) ?

- Classe BaseExtractor / BaseNormalizer — factoriser la boilerplate (pagination, insertion staging, hash, idempotence). Chaque source implémente juste build_query(), extract_id(), extract_doi() etc.
- Module facets pour les facettes dynamiques des filtres (logique très présente dans publications.py et persons.py, dupliquée).
Ce qui reste dans les routers (pas une priorité) :

Construction de COUNT FILTER WHERE pour chaque bucket de facette (APC, HAL status) — difficile à factoriser sans introduire des abstractions
Tri dynamique par colonne (ORDER BY CASE) — très local aux endpoints
Sérialisation spécifique de la réponse

### Niveau 4 — code. 
complexité cyclomatique
code dupliqué
magic values (constantes métier: enum; valeurs config)

### Niveau 5 — dépendances et dette externe.
Les versions sont-elles épinglées (lockfile : uv.lock, poetry.lock, requirements.txt figé) ? Y a-t-il des paquets non utilisés (deptry, pip-audit) ? Des vulnérabilités connues (pip-audit) ? Python est-il sur une version maintenue ? Les migrations BDD sont-elles gérées par un outil (Alembic) ou à la main ?

### Niveau 6 — documentation vivante et DX. 
Ta mention des docstrings entre ici. Élargis à : y a-t-il un README qui permet à toi-dans-deux-ans de remonter l'environnement de dev en 15 minutes ? Un CONTRIBUTING.md ou équivalent qui dit "comment ajouter une nouvelle source de données" ? Un schéma d'archi versionné avec le code ? Les endpoints FastAPI ont-ils des descriptions OpenAPI correctes (c'est quasi-gratuit avec Pydantic) ? Un pre-commit hook qui fait tourner ruff+mypy+tests évite la dérive.

### Niveau 7 — Svelte / front. 
Les stores sont-ils clairement séparés de la logique de composant ?
Les appels API sont-ils centralisés dans un module client ou dispersés ?
Les types TS (si tu utilises TS) sont-ils générés depuis ton OpenAPI plutôt que réécrits à la main ? C'est là que ta ligne "abstraire des composants, centraliser les styles" entre, mais la question de la génération de types depuis le backend est souvent plus rentable que la factorisation de composants.

Ordre concret que je suggère, vu ton contexte :

- Mettre en place linter + formateur + type checker + un filet de tests de caractérisation.
- Cartographier l'architecture actuelle (un diagramme des modules et de qui appelle qui).
- Identifier les couches qui fuient (route qui fait du SQL, module data qui connaît HTTP, etc.) et redresser une seule frontière à la fois.
- Typer les frontières (Pydantic partout aux entrées/sorties, Settings pour la config).
- Là tu attaques ta liste : déduplication SQL, constantes, code mort, docstrings, composants front.
- Documentation d'architecture et hooks pre-commit pour verrouiller les acquis.