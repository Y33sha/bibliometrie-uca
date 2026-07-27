# Rationaliser les couches d'accès aux données

## Contexte

Le projet accède à PostgreSQL par trois familles de modules, chacune doublée d'un jeu de ports dans `application/ports/` :

- **`infrastructure/queries/api/`** (ports `application/ports/api/`) : read-models du frontend. Lecture seule — aucune écriture.
- **`infrastructure/queries/pipeline/`** (ports `application/ports/pipeline/`) : accès BDD des phases du pipeline (normalize, affiliations, authorships, persons, publications, subjects, relations, countries, metadata_correction…). Lecture **et** écriture : une phase d'ETL lit ses entrées et matérialise ses sorties.
- **`infrastructure/repositories/`** (ports `application/ports/repositories/`) : accès aux agrégats (person, publication, journal, publisher, structure) et à quelques tables de service (doi_prefix, config, audit, perimeter). Lecture et écriture.

Le critère de découpage est le **consommateur** (API de lecture / phases du pipeline / agrégats métier), pas la distinction lecture/écriture. Cette organisation par consommateur est saine en soi. Deux frictions en émergent.

**Le nom « queries » ment sur la moitié pipeline.** `queries/pipeline` écrit massivement (marquage d'état, vidange de `staging`, matérialisation des sorties de phase) : ce sont des gateways de phase, pas des requêtes de lecture. Le vocabulaire CQRS (« query » = lecture) est cohérent sur `queries/api`, mais recopié à tort sur `queries/pipeline`.

**Le placement des tables de service du pipeline est arbitraire.** `doi_prefixes` (cache préfixe → Registration Agency + éditeur) est un repository ; `staging` et `doi_lookups` (payloads bruts, journal des DOI introuvables) vivent dans `queries/pipeline`. Même nature — caches et journaux de bord alimentés par le pipeline — deux maisons, sans règle discriminante.

Un repository qui lit n'est pas une anomalie : un repository lit et écrit son agrégat par définition (`get_by_id`, `find`, upsert). L'anomalie est le couple nom trompeur côté pipeline + placement sans règle des tables de service.

Le déclencheur est le chantier `CODE_perimetre-infrastructure-sources` : sa dernière phase (dissolution de `common.py`) doit sortir la persistance d'extraction — écritures `staging`, pool cross-import, sélection des rows périmées — hors de `infrastructure/sources`, et bute sur cette ambiguïté : où atterrissent des écritures de pipeline ?

## Décisions

- **Nature de l'application.** L'appli est hybride : un pipeline d'ingestion et de conformité — données externes sales, traitées par passes ensemblistes convergentes — qui alimente un domaine bibliométrique curé, où publications, personnes et structures sont corrigées à la main via l'admin et l'API. Le premier relève du data engineering (zones de raffinage, gateways, transformations SQL) ; le second du DDD tactique (agrégats, invariants garantis à l'écriture). Les fondre sous un vocabulaire unique — « repository » partout, « query » y compris quand ça écrit — est la source des incohérences. La cible nomme chaque partie selon sa nature.

- **Trois familles d'accès aux données dans `infrastructure/`**, nommées par leur rôle, chacune avec son miroir de ports dans `application/` :
  - `repositories/` — agrégats métier curés (person, publication, structure, journal, publisher) : lecture et écriture, invariants garantis à l'écriture.
  - `pipeline/` — gateways des phases du pipeline (staging, normalize, consolidation, tables de contrôle) : lecture et écriture ensemblistes, sans agrégat. Absorbe `queries/pipeline` et la persistance d'extraction logée dans `sources/common`.
  - `read_models/` — projections de lecture pour l'API et le frontend, en remplacement de `queries/api` : read side du CQRS, strictement en lecture.

- **Les 4 layers sont conservés.** Le changement se concentre dans `infrastructure/` (les familles d'accès) et son miroir `application/ports/`. `domain/` — value objects et règles de conformité — ne bouge pas : le pipeline l'applique pour nettoyer, les repositories le font respecter à la curation. `interfaces/` ne bouge pas non plus, hors le nettoyage indépendant des CLI.

- **La double écriture des agrégats cœur est assumée.** `source_publications`, `publications`, `persons` et consorts sont écrites par `pipeline/` (construction ETL) et par `repositories/` (correction admin/API). Deux voies légitimes, nommées chacune pour ce qu'elle est.

## Phasage

### A — État des lieux détaillé

- [x] Inventorier, table par table, qui lit et qui écrit, et depuis quelle couche.
- [x] Séparer les tables d'agrégat métier des tables de service du pipeline.

Inventaire complet : [`CODE_couches-acces-donnees_inventaire.md`](CODE_couches-acces-donnees_inventaire.md). Constats pour la phase B : `queries/api` est strictement en lecture seule ; les agrégats cœur (`source_publications`, `source_authorships`, `publications`, `persons`, `authorships`, `addresses`, `journals`, `publishers`…) sont écrits par **deux** couches — `repositories/` pour l'admin/API, `queries/pipeline/` pour l'ETL ; `doi_prefixes` (service pipeline) est derrière un repository quand `staging` et `doi_lookups`, de même nature, ne le sont pas ; `doi_lookups` n'a pas de maison hors `sources/common.py` ; ~27 scripts `interfaces/cli/` écrivent en base directement.

### B — Règle-cible

- [x] Trois familles d'accès nommées par leur rôle — `repositories/`, `pipeline/`, `read_models/` (cf. Décisions).

### C — `read_models`

- [x] Renommer `infrastructure/queries/api` → `infrastructure/read_models`, et le miroir `application/ports/api` → `application/ports/read_models`.
- [x] Repointer les call-sites (interfaces API, composition root).

Contrats `pyproject.toml` étendus à `read_models` : import-linter (module interdit aux routers + exception `deps.py`) et override mypy couche SQL. `infrastructure/queries/perimeter.py` (ni api ni pipeline) voit ses imports repointés ; sa relocation reste à trancher en phase D/E.

### D — Couche `pipeline`

- [x] `infrastructure/queries/pipeline` → `infrastructure/pipeline`.
- [x] Rapatrier la persistance d'extraction de `sources/common` (écritures `staging`, pool cross-import, sélection stale, `doi_lookups`) vers `pipeline/`. Reprend la phase E en pause du chantier `CODE_perimetre-infrastructure-sources`.

`common.py` est dissous : le hash de détection va dans `infrastructure/pipeline/change_detection.py` (utilitaire neutre, partagé extract/normalize/CLI) ; la persistance dans le package `infrastructure/pipeline/extract/` (`staging.py`, `cross_import.py`, `stale.py`). Sans port applicatif : les adapters `sources/*`, `refresh_stale_base` et `run_pipeline` appellent ces requêtes directement.

`infrastructure/queries/` conserve provisoirement `perimeter.py` (implémente à la fois un port pipeline et un port read_models — relocation à trancher) et `sources_sql.py`.

### E — Audit des repositories

- [x] Inventorier les méthodes de repositories, comme les tables en phase A.
- [x] Classer chaque méthode par consommateur réel et nature.
- [ ] Appliquer (cf. les quatre chantiers ci-dessous).

Audit complet : [`CODE_couches-acces-donnees_audit-repositories.md`](CODE_couches-acces-donnees_audit-repositories.md). Il établit **trois** consommateurs (pipeline / commande admin / bulk déclenché par l'humain), et un motif uniforme **command-service + data-mapper** : les invariants vivent dans `application/services/`, pas dans les repositories, et l'hydratation d'agrégat est vestigiale (`find_by_id` souvent inutilisé). Quatre chantiers d'application en découlent : (1) **descente pipeline** — `doi_prefix` en bloc, `journal`/`publisher` scindés (find-or-create + enrichissement → `pipeline/`, fusion → repository mince), plus `publication.update_oa_status`/`create` et `authorship.enforce_confirmed_authorships` ; (2) **catégorie bulk-admin** — trouver une maison aux opérations ensemblistes déclenchées par l'humain (pays, batch-assign, propagation de périmètre), ni phase pipeline ni commande d'agrégat ; (3) **ménage** — code mort, homonymes pipeline/admin, doublon `perimeter_structures`, contournement direct `journals.py:185` ; (4) **nommage** — repositories réservés aux vrais agrégats curés, gateways pour le reste.

### F — CLI

- [ ] Router les scripts `maintenance/` et `imports/` permanents qui écrivent en base via les couches ; laisser les `oneshot/` jetables.

## Questions ouvertes

- **`doi_prefixes`.** Peuplé par le pipeline (`resolve_ra`, `publishers_journals`) mais porteur de sens (préfixe → agence d'enregistrement → éditeur) et lu par l'API : table de service rangée en `pipeline/`, ou donnée de référence traitée à part ? À trancher en phase D.
- **Granularité de `pipeline/`.** Modules par phase (`normalize/`, `authorships/`…) ou par table ? L'existant mêle les deux.
- **Forme des conversions (phase E).** Quelles méthodes de repositories appelées par l'API sont des mutations plates à reconvertir en opérations d'agrégat, et sous quelle forme ? Dépend de l'inventaire des méthodes.
