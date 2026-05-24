# Roadmap des roadmaps

*compléter et ajouter liens*

## DATA — Repenser la table `source_persons` (2026-04-28)

Clarification du rôle de la table `source_persons`. Elle était peuplée pour toutes les sources, y compris celles sans identité auteur stable (OA, WoS, auteurs HAL sans compte) avec des `source_id` synthétiques, impossibles à mapper utilement aux `persons` réelles. Le chantier restreint cette table aux sources avec identifiant stable (HAL avec`personId`, ScanR et theses.fr avec `idref`). Pour le reste, les informations servant à identifier les auteurs se trouvent dans `source_authorships` (nom brut, nom normalisé, PIDs si présents.)

*NB*. Le chantier **DATA_simplify-source-tables** va plus loin dans la simplification du schéma en supprimant `source_persons` et `source_structures`.

## METIER — Exploiter sujets et mots-clés (2026-04-30)

Les sujets et mots-clés étaient stockés dans `source_publications`mais pas exploités. Création des tables `subjects` et `subject_cooccurrences`. Création de la page sujets, création du nuage de mots dans les dashboards personne et labo.

## CODE — Déduplication de code frontend (2026-05-05)

Le composant `<PublicationsListView>` sert désormais pour 4 pages partageant le même tableau de publications avec filtres à facettes.

## CODE — Ports: clarification de leur répartition (2026-05-06)

Répartition des ports entre `domain/ports/` et `application/ports/` en fonction de règles explicites.

*NB*. Obsolète: tous les ports ont par la suite été centralisés dans `application/ports/` et les règles supprimées.

## CODE — Routers: inversion des dépendances (2026-05-06)

18 routers sur 20 importaient depuis `/infrastructure`, malgré l'interdiction documentée mais non enforcée. Mise en conformité et règle verrouillée par `import-linter`.

## CODE — Centralisation des règles métier dans `domain/` (2026-05-08)

Exploration de la codebase pour retrouver des invariants métier implicites dispersés dans `application/` et les rapatrier dans `domain/`.

## CODE — Suppression de la duplication sync/async (2026-05-09)

L'API FastAPI et le pipeline maintiennent deux familles de repositories quasi identiques : *sync* (utilisées par le pipeline et les CLI) et *async* (utilisées par les routes FastAPI). Déduplication et passage en *sync* partout. Les routes `def` sont exécutées dans un threadpool Starlette (~40 workers par défaut).

## CODE — Adoption de SQLAlchemy Core (2026-05-11)

Adoption de SQLAlchemy Core (pas l'ORM) comme *query builder* de
référence pour les queries dynamiques, en coexistence pragmatique
avec du SQL brut là où c'est plus lisible (CTE complexes, opérations
JSON spécifiques à PostgreSQL).

## CODE — Adoption d’Alembic pour la gestion des migrations (2026-05-11)

Remplacement du système maison (`infrastructure/db/migrate.py`) par Alembic pour la gestion des migrations.

## CODE — Suppression des `conn`/`cur` fossiles (2026-05-11)

Nettoyage post-migration SQLAlchemy. De nombreuses fonctions déclarent un argument `conn: Connection` ou `cur: Connection` qu'elles n'utilisent pas. Vestige du pattern psycopg où le curseur servait à `cur.execute(...)` directement.

## CODE — Pureté du module `domain/` (2026-05-12)

Des fichiers du `domain/` importaient `pydantic` pour modéliser des colonnes JSONB qui sont en réalité de l'I/O, pas du métier. Déplacement des `BaseModel` vers `infrastructure/db/jsonb_models/`. Interdiction des imports de bibliothèques tierces par `domain/`, verrouillée par `import-linter`.

## DATA — Normalisation du schéma `person_name_forms` (2026-05-13)

La table `person_name_forms` stocke les formes de nom normalisées, avec une colonne `person_ids` (personnes liées) et une colonne `sources` (sources où la forme de nom a été observée). Les deux ne sont pas corrélés: on ne sait pas de quelle source vient chaque forme pour chaque personne. Problème résolu en remplaçant les deux colonnes par une colonne JSONB `persons` au format `{ "<person_id>": ["src1", "src2"], ... }`.

*NB*. Ultérieurement, choix révisé: colonnes `person_id` INT (FK) et `sources` TEXT[]. Permet d'avoir une contrainte FK.

## CODE —
## CODE —
## CODE —
## CODE —
## CODE —
## CODE —
## CODE —
