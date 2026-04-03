# Plan d'amélioration — Bibliométrie UCA

## Contexte

Ce prototype est destiné à être transmis à la DSI de l'UCA pour devenir une brique du SI Recherche. La DSI va principalement s'intéresser au **schéma de données, au pipeline et au backend API**. Le frontend actuel sera vraisemblablement remplacé (intégration au SI décisionnel et à l'ENT). L'authentification sera gérée par le CAS universitaire.

Ce plan se concentre donc sur ce qui rend le projet **transmissible, reproductible et fiable** — pas sur des fonctionnalités que la DSI reconstruira de son côté.

---

## ~~1. Conteneurisation et reproductibilité (Priorité #1)~~ FAIT

Réalisé en avril 2026.

- `docker-compose.yml` (dev, 3 services : PostgreSQL 18, backend FastAPI, frontend SvelteKit avec hot reload)
- `docker-compose.prod.yml` (prod, image unique backend + frontend buildé)
- Dockerfiles : `backend/Dockerfile`, `frontend/Dockerfile`, `Dockerfile` (prod multi-stage)
- `config/settings.docker.py` : configuration via variables d'environnement
- `.env.example` documenté
- Script d'init `db/docker-init/01-create-user.sh` pour créer l'utilisateur applicatif PostgreSQL
- `requirements.txt` avec versions figées + pytest/pytest-cov
- README mis à jour avec instructions Docker

---

## 2. Tests sur le cœur critique (Priorité #2)

**Pourquoi :** La déduplication des publications et des personnes est la valeur ajoutée principale du projet. Une régression silencieuse ici serait catastrophique. Pas besoin de viser 70% de couverture partout — il faut couvrir les cas limites déjà rencontrés.

### Actions

- **Tests de déduplication publications** (`services/publications.py`) :
  - Même DOI, même type → fusion correcte
  - Même DOI, types incompatibles (livre vs chapitre, article vs erratum) → pas de fusion
  - Titre similaire + même année + même journal → détection de doublon
  - Publication sans DOI → pas de faux positif
- **Tests de déduplication personnes** (`processing/create_persons_from_source_authorships.py`) :
  - Même ORCID → fusion
  - Même idHAL → fusion
  - Homonymes avec ORCID différents → pas de fusion
  - Variantes de noms (accents, tirets, initiales) → détection correcte
- **Tests des normalizers** :
  - `normalize_name()`, `clean_doi()`, `parse_raw_author_name()` — les tests existants dans `test_utils.py` sont un bon début, les compléter
  - Transformation staging → source pour chaque source (HAL, OpenAlex, WoS) avec des cas réels
- **Tests du pipeline** :
  - Vérifier que chaque phase est idempotente (deux exécutions consécutives = même résultat)
  - Vérifier la reprise (`--from <phase>`)
- **Infrastructure** : utiliser le `conftest.py` existant avec transaction rollback pour l'isolation

### Critère de succès

Les scénarios de déduplication connus (DOI livre/chapitre, homonymes, etc.) sont couverts par des tests qui passent. Un `pytest` dans la CI donne confiance.

---

## 3. Index PostgreSQL (Priorité #3)

**Pourquoi :** Quelques `CREATE INDEX` bien placés = 30 minutes de travail pour un gain de performance immédiat, sans ajouter de dépendance.

### Actions

Ajouter dans `db/schema.sql` (et appliquer sur la base existante) :

```sql
-- Publications : recherche par DOI, filtrage par année/type/OA
CREATE INDEX idx_publications_doi ON publications (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_publications_year_type ON publications (pub_year, doc_type);
CREATE INDEX idx_publications_uca ON publications (uca_flag) WHERE uca_flag = TRUE;

-- Authorships : jointures fréquentes
CREATE INDEX idx_authorships_person ON authorships (person_id);
CREATE INDEX idx_authorships_publication ON authorships (publication_id);
CREATE INDEX idx_authorships_uca ON authorships (is_uca) WHERE is_uca = TRUE;

-- Personnes : recherche par nom normalisé
CREATE INDEX idx_persons_name ON persons (last_name_normalized, first_name_normalized);

-- Source documents : lien vers publication_id (jointures)
CREATE INDEX idx_hal_docs_pub ON hal_documents (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX idx_openalex_docs_pub ON openalex_documents (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX idx_wos_docs_pub ON wos_documents (publication_id) WHERE publication_id IS NOT NULL;

-- Source authorships : lien vers person_id (pipeline personnes)
CREATE INDEX idx_hal_authorships_person ON hal_authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_openalex_authorships_person ON openalex_authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_wos_authorships_person ON wos_authorships (person_id) WHERE person_id IS NOT NULL;
```

Vérifier les performances avec `EXPLAIN ANALYZE` sur les requêtes les plus fréquentes des routers.

### Critère de succès

Les pages de l'application qui chargent lentement répondent en moins de 2 secondes.

---

## 4. Lisibilité du code (Priorité #4)

**Pourquoi :** La personne qui reprendra le code à la DSI ne connaît pas le domaine bibliométrique. Il faut qu'elle comprenne la logique sans avoir à tout deviner.

### Actions

- **Docstrings sur les fonctions clés** des services : `find_or_create()`, `merge_persons()`, les 6 passes de matching dans `create_persons_from_source_authorships.py`. Expliquer le *pourquoi*, pas le *comment*.
- **Typage Python** : ajouter des type hints sur les signatures des fonctions principales (paramètres et retours). Pas besoin d'être exhaustif — juste les services et les fonctions de processing.
- **Constantes nommées** : extraire les valeurs magiques (seuils de similarité, tailles de batch) en constantes en haut des fichiers.
- **Commentaires de contexte métier** : là où le code encode une règle bibliométrique non évidente (ex : "un chapitre et son ouvrage peuvent avoir le même DOI"), un commentaire bref aide.

### Critère de succès

Un développeur Python expérimenté mais ignorant de la bibliométrie peut lire un service et comprendre la logique métier sans aide extérieure.

---

## 5. Documentation de transmission (Priorité #5)

**Pourquoi :** Compléter la documentation existante (déjà bien avancée avec `architecture.md`, `pipeline.md`, `glossaire.md`) pour une transmission formelle.

### Actions

- **Diagramme du pipeline** : schéma Mermaid montrant les 9 phases, les tables en entrée/sortie de chaque phase, et les dépendances entre phases.
- **Diagramme du modèle de données** : schéma entité-relation des tables principales (truth + source), en Mermaid.
- **Guide d'exploitation** : comment lancer le pipeline (modes `full`, `monthly`, `weekly`), comment reprendre après une erreur, comment ajouter une source.
- **Note sur l'authentification** : documenter que l'auth actuelle est un placeholder admin simple, et que le CAS universitaire devra être branché en amont. Lister les endpoints qui nécessitent une authentification.
- **Limites connues et biais** : documenter les limites des sources (couverture HAL vs OpenAlex vs WoS), les cas de déduplication non résolus, les faux positifs connus.

### Critère de succès

Le document de transmission permet à un développeur DSI de comprendre l'architecture, installer le projet, et commencer à travailler dessus sans réunion préalable.

---

## 6. Migrations de schéma (Priorité #6)

**Pourquoi :** Le schéma est dans un seul fichier `db/schema.sql` de 3200 lignes. Toute modification oblige à comparer manuellement l'ancien et le nouveau schéma. Pour un projet qui va évoluer, c'est risqué.

### Actions

- **Scripts de migration numérotés** : créer un dossier `db/migrations/` avec des scripts SQL séquentiels (`001_initial_schema.sql`, `002_add_indexes.sql`, etc.).
- **Script d'application** : un petit script Python ou shell qui applique les migrations non encore exécutées (table `schema_migrations` avec le numéro de la dernière migration appliquée).
- **Rétrocompatibilité** : le fichier `schema.sql` actuel reste comme référence complète ; les migrations sont le mécanisme d'évolution.

### Critère de succès

On peut faire évoluer le schéma de manière incrémentale et traçable, sans risque de perdre des données.

---

## 7. CI GitHub Actions (Priorité #7)

**Pourquoi :** Automatiser les tests sur chaque push donne confiance et empêche les régressions. C'est aussi un signal de maturité pour la DSI.

### Actions

- **`.github/workflows/ci.yml`** :
  - Lancer `pytest` avec un PostgreSQL de test (service container GitHub Actions)
  - Vérifier que le build frontend passe (`npm run build`)
  - Optionnel : linter Python (`ruff`) pour la cohérence du style
- **Badge dans le README** : afficher le statut des tests

### Critère de succès

Un push qui casse un test de déduplication est détecté automatiquement avant merge.

---

## Ce qui a été écarté de ce plan

| Suggestion initiale | Pourquoi écartée |
|---|---|
| JWT + table users + rôles RBAC | La DSI branchera son propre système d'auth (CAS). Construire un RBAC maison serait du travail jeté. |
| Rate limiting (slowapi) | Relève de la config du reverse proxy (nginx), pas du code applicatif. L'appli sera derrière l'infra DSI. |
| Chiffrement des noms/ORCID (RGPD) | Les données de publications scientifiques sont publiques. Seul `persons_rh` contient des données peu sensibles, et l'appli sera interne à la communauté universitaire. |
| Redis pour le cache | Les index PostgreSQL suffiront pour le volume de données actuel. Redis ajoute une dépendance d'infrastructure inutile à ce stade. |

Ces sujets pourront être revisités par la DSI si le besoin se confirme en production.

---

## Ordre de travail suggéré

| Étape | Effort estimé | Impact |
|-------|--------------|--------|
| ~~1. Docker + variables d'env~~ | ~~1-2 jours~~ | ~~FAIT~~ |
| 2. Tests déduplication | 2-3 jours | Le cœur métier est protégé |
| 3. Index PostgreSQL | 1 heure | Performances immédiates |
| 4. Lisibilité code | 1-2 jours | Le code est compréhensible |
| 5. Documentation transmission | 1-2 jours | La DSI est autonome |
| 6. Migrations de schéma | 1 jour | Le schéma peut évoluer |
| 7. CI GitHub Actions | 1 heure | Les tests tournent automatiquement |

**Date de création** : Avril 2026
**Version** : 2.0
