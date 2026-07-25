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

- L'organisation par consommateur (API de lecture / phases pipeline / agrégats) est conservée : le chantier vise les deux frictions (vocabulaire, placement des tables de service), pas une refonte du découpage.
- `queries/api` reste tel quel : lecture seule, cohérent avec le vocabulaire CQRS.

## Phasage

### A — État des lieux détaillé

- [x] Inventorier, table par table, qui lit et qui écrit, et depuis quelle couche.
- [x] Séparer les tables d'agrégat métier des tables de service du pipeline.

Inventaire complet : [`CODE_couches-acces-donnees_inventaire.md`](CODE_couches-acces-donnees_inventaire.md). Constats pour la phase B : `queries/api` est strictement en lecture seule ; les agrégats cœur (`source_publications`, `source_authorships`, `publications`, `persons`, `authorships`, `addresses`, `journals`, `publishers`…) sont écrits par **deux** couches — `repositories/` pour l'admin/API, `queries/pipeline/` pour l'ETL ; `doi_prefixes` (service pipeline) est derrière un repository quand `staging` et `doi_lookups`, de même nature, ne le sont pas ; `doi_lookups` n'a pas de maison hors `sources/common.py` ; ~27 scripts `interfaces/cli/` écrivent en base directement.

### B — Règle-cible

- [ ] Trancher le vocabulaire de la couche pipeline : renommer pour dire qu'elle écrit, ou assumer et documenter « queries » comme accès BDD d'une phase.
- [ ] Poser le critère de placement d'une table (agrégat métier → repository ; service de pipeline → couche pipeline) et l'appliquer aux cas litigieux, `doi_prefixes` en tête.

### C — Application

- [ ] Aligner les modules mal placés sur la règle.
- [ ] Reloger la persistance d'extraction sortie de `infrastructure/sources` (phase E en attente du chantier `CODE_perimetre-infrastructure-sources`).

## Questions ouvertes

- **Renommer ou assumer ?** Renommer `queries/pipeline` (et ses ports) touche beaucoup de fichiers pour un gain de clarté à peser contre le churn. L'alternative est de documenter que « queries » y désigne l'accès BDD d'une phase, écritures comprises.
- **Critère de placement.** Qu'est-ce qui fait qu'une table relève d'un repository plutôt que de la couche pipeline ? `doi_prefixes`, `staging`, `doi_lookups`, `phase_executions` sont les cas à classer.
- **Granularité côté pipeline.** Un module par table ou par phase ? Le dossier mêle les deux : sous-packages (`normalize/`, `authorships/`…) et modules plats (`subjects.py`, `oa_status.py`).
