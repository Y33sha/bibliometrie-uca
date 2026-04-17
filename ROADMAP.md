# Roadmap transmission DSI

## 2. Résilience pipeline — Bloquant

- [ ] Alerting sur échec pipeline (email ou webhook)

## 5. Base de données

- [ ] Documenter le schéma des colonnes JSONB (`meta`, `source_data`, `external_ids`)
- [ ] Ajouter un audit trail pour les opérations destructives (fusions, suppressions)

## 6. Validation pipeline

- [ ] Checks automatiques post-pipeline (comptages, orphelins, anomalies)

# Niveau 0 — instrumenter avant de toucher.

linter: ruff
formateur (ruff format)
type checker (mypy mode permissif : 73 erreurs)
coverage. pytest --cov
tests de caractérisation sur les endpoints/fonctions critiques => services, routers

# Niveau 1 — architecture et découpage.

abstraire la logique commune aux sources
creuser architecture hexagonale

Questions à poser à ton code : y a-t-il une séparation claire entre couche données (accès SQL), couche métier (logique bibliométrique, règles de matching, algorithme pays), couche API (FastAPI routes, sérialisation), et couche présentation (Svelte) ?

- Classe BaseExtractor / BaseNormalizer — factoriser la boilerplate (pagination, insertion staging, hash, idempotence). Chaque source implémente juste build_query(), extract_id(), extract_doi() etc.
- Module facets pour les facettes dynamiques des filtres (logique très présente dans publications.py et persons.py, dupliquée).
Ce qui reste dans les routers (pas une priorité) :

Construction de COUNT FILTER WHERE pour chaque bucket de facette (APC, HAL status) — difficile à factoriser sans introduire des abstractions
Tri dynamique par colonne (ORDER BY CASE) — très local aux endpoints
Sérialisation spécifique de la réponse

# Niveau 2 — frontières et contrats. 
exceptions custom

# Niveau 4 — logique. 
complexité cyclomatique
code dupliqué
magic values (constantes métier: enum; valeurs config)

# Niveau 5 — dépendances et dette externe.
Les versions sont-elles épinglées (lockfile : uv.lock, poetry.lock, requirements.txt figé) ? Y a-t-il des paquets non utilisés (deptry, pip-audit) ? Des vulnérabilités connues (pip-audit) ? Python est-il sur une version maintenue ? Les migrations BDD sont-elles gérées par un outil (Alembic) ou à la main ?

# Niveau 6 — documentation vivante et DX. 
Ta mention des docstrings entre ici. Élargis à : y a-t-il un README qui permet à toi-dans-deux-ans de remonter l'environnement de dev en 15 minutes ? Un CONTRIBUTING.md ou équivalent qui dit "comment ajouter une nouvelle source de données" ? Un schéma d'archi versionné avec le code ? Les endpoints FastAPI ont-ils des descriptions OpenAPI correctes (c'est quasi-gratuit avec Pydantic) ? Un pre-commit hook qui fait tourner ruff+mypy+tests évite la dérive.

# Niveau 7 — Svelte / front. 
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

Un principe transversal : **une PR, un type de changement**. Un commit qui renomme + factorise + change le comportement est inauditable même par soi-même trois mois plus tard. Formatage d'abord (un commit), renommages ensuite, déplacements de code ensuite, changements de comportement en dernier — chaque catégorie dans son propre commit/PR.

je peux te donner des pointeurs quand on arrivera à la fin du 12-Factor, pour ne pas mélanger — les plus pertinents pour ton profil (app web, Python, solo ou petite équipe) sont probablement Beyond the Twelve-Factor App (Kevin Hoffman, 2016, qui ajoute 3 facteurs et en revisite certains à l'ère Kubernetes), et côté code lui-même plutôt que déploiement, le Zen of Python pour la philo, les Google Engineering Practices (surtout le guide de code review) et le livre A Philosophy of Software Design de John Ousterhout (2018) qui est court, dense, et vise exactement le genre de questions d'architecture qu'on évoquait au niveau 1.