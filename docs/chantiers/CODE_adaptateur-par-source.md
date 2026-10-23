# Chantier — Une source, un adaptateur

## Contexte

### Déclaration d'une source

Ajouter une source touche une quinzaine de tables et de listes :

- le registre `domain/sources/registry.py` : `Source`, `SOURCE_LABELS`, `HARVESTED_SOURCES`, `DOI_SEARCHABLE_SOURCES`, `SOURCE_PRIORITY`, `STRUCTURE_API_SOURCES` ;
- `PERSON_SEARCHED_SOURCES` dans `pipeline/graph.py`, les sources du mode `full` dans `pipeline/runtime/modes.py` ;
- une table par phase ou par réglage : `harvest`, `harvest_by_person`, `fetch_missing`, `fetch_stale`, `normalize`, `change_detection`, `api_params`, `config` ;
- la copie de `SOURCE_LABELS` dans le frontend (`$lib/sources.ts`).

Des tests vérifient les tables de `harvest` et de `normalize`. Une source absente d'une autre table lève `KeyError` à l'exécution.

Les politiques de source sont des littéraux dans les orchestrateurs :

- WoS sur option : `modes.py`, `harvest.py`, `signals.py` ;
- theses.fr hors fenêtre d'années : `theses/harvest.py`, `common/harvest.py`, `fetch_stale.py`, `delete_source_records_out_of_window.py` ;
- mode `daily` réduit à HAL : `modes.py` et `harvest.py` ;
- agence d'enregistrement de Crossref et de DataCite : `fetch_missing.py` et `graph.py`.

`harvest` et `harvest_by_person` dupliquent le câblage des nœuds, la construction du client ScanR et la capture de `HarvestConfigError`.

### Recherche et écriture dans `staging`

La boucle « chercher un identifiant, écrire le résultat dans `staging` » existe en cinq copies : `common/fetch_missing.py`, `common/fetch_stale.py`, `hal/fetch_missing.py`, `theses/fetch_missing.py`, `openalex/fetch_truncated.py`. Chacune range elle-même les trois issues : trouvé, introuvable, indisponible. Les méthodes `insert` des six `DoiSearch` sont presque identiques. `oa_status.py` (Unpaywall) et `enrich_journals_from_openalex.py` ont leur propre boucle réseau.

Les identifiants d'un enregistrement source (identifiant, DOI, troncature des auteurs OpenAlex) se recalculent à chaque point d'entrée : moissonnage, recherche par DOI, recherche par personne, relecture.

### Débit, circuit-breaker et réessais

Trois mécanismes règlent le débit d'une source :

- une pause par worker après chaque requête : `request_delay_s` des `DoiSearch`, `HAL_DELAY`, `THESES_DELAY` ;
- le `Throttle` synchrone de WoS ;
- `RequestPace`, un rythme commun à tous les workers, employé par le Sudoc seulement.

Avec une pause par worker, le débit dépend du temps de réponse. Les réglages de WoS sont répétés dans `wos/fetch_missing.py` et `wos/fetch_stale.py`.

Débit mesuré sur le run 328, avant le budget de débit par source, et sur le run 331, avec ce budget (2026-10-23, poste personnel, hors réseau universitaire) :

| Tâche | Run 328 | Run 331 |
|---|---|---|
| `harvest.hal` | 5 567 doc en 326 s : 17 doc/s | 6 385 doc en 360 s : 18 doc/s |
| `harvest.openalex` | 6 989 doc en 93 s : 75 doc/s | 7 489 doc en 98 s : 77 doc/s |
| `harvest.scanr` | 4 414 doc en 75 s : 59 doc/s | 6 095 doc en 194 s : 31 doc/s |
| `harvest.theses` | 2 612 parcourues en 9 s | 2 612 parcourues en 7 s |
| `harvest.datacite` | 649 doc en 8 s : 81 doc/s | 577 doc en 8 s : 69 doc/s |
| `harvest_by_person.scanr` | 2 526 doc en 81 s : 31 doc/s | 3 023 doc en 102 s : 30 doc/s |
| `harvest_by_person.hal` | 1 943 doc en 150 s : 13 doc/s | 2 413 doc en 157 s : 15 doc/s |
| `harvest_by_person.openalex` | 4 103 doc en 167 s : 25 doc/s | 4 810 doc en 181 s : 27 doc/s |
| `harvest_by_person.crossref` | 901 doc en 320 s | 800 doc en 261 s |
| `harvest_by_person.datacite` | 390 doc en 381 s | 417 doc en 210 s |
| `fetch_truncated` | 643 req en 177 s : 3,6 req/s | 780 req en 219 s : 3,6 req/s |
| `fetch_missing.openalex` | 4 req | 298 req en 41 s : 7,3 req/s |

Aucun 429 ni réessai sur le run 331. Seul `fetch_missing.openalex` approche son budget (8 req/s). Les moissonnages restent sous leur budget : leur débit suit le temps de réponse. ScanR rend des pages de 1 000 documents, soit sept requêtes pour 6 095 documents : son ralentissement vient du temps de réponse, pas du budget.

Le circuit-breaker circule par deux canaux. `access_source` le pose dans une ContextVar, que lisent les clients HTTP et `run_fetch_pool`. L'exécuteur des nœuds le passe aussi en argument, jusqu'aux callbacks `breaker_tripped=` des moissonneurs.

`http_retry.py` contient deux copies de la boucle de réessai, synchrone et asynchrone. À l'épuisement des réessais, la synchrone lève `SourceUnavailableError`, l'asynchrone l'erreur d'origine.

### Normalisation

`SourceNormalizer` fait la boucle de la normalisation. Chaque source réécrit la séquence d'écriture : conteneurs, métadonnées, enregistrement source, contributions sources, `mark_done`.

## Décisions

- Le profil de chaque source (`SourceProfile`, dans `domain/sources/registry.py`) déclare ce que le pipeline en fait : libellé, capacités, rôle d'agence d'enregistrement de DOI, politiques, débit. Le graphe, les modes et le domaine le lisent : leurs contrats d'import leur interdisent `pipeline.ingestion`.
- Chaque source expose un adaptateur dans `<source>/__init__.py`, par des fabriques paresseuses : client, moissonneurs, recherche par DOI, relecture, normaliseur, empreinte, identité d'une notice. Les tables des phases se construisent depuis la liste des adaptateurs. Un test vérifie que chaque adaptateur a exactement les capacités de son profil.
- L'API sert les libellés des sources au frontend, et calcule les liens vers les portails des sources (`source_record_url`).
- theses.fr suit la fenêtre d'années du run, comme les autres sources, par l'année de soutenance. Les thèses en cours sont toujours retenues.
- Une boucle de recherche commune range les trois issues. Les cinq canaux la paramètrent. L'adaptateur lui fournit l'identité d'une notice.
- Le débit de chaque source est un budget en requêtes par seconde, avec les autres réglages d'accès aux API (`api_params.py`). Le run l'injecte dans le contexte de phase, comme le contrôle des identifiants ; le circuit-breaker posé par l'accès à la source porte le rythme correspondant (`Pace`), que chaque requête HTTP respecte.
- La ContextVar est le seul canal du circuit-breaker. Toute requête s'exécute sous le breaker d'une source.
- Une fonction sans I/O classe chaque tentative. Deux enveloppes, synchrone et asynchrone, l'exécutent. L'épuisement des réessais lève `SourceUnavailableError`, quelle qu'en soit la cause.
- La classe de base de la normalisation fait la séquence d'écriture. Une source fournit l'analyse d'une ligne de `staging`.

## Phasage

### Phase 1 — Circuit-breaker

- [x] Paramètre `breaker` retiré des nœuds et des callbacks des moissonneurs. b9b9aa2cc

### Phase 2 — Réessais

- [x] Classement des tentatives et ses deux enveloppes, avec une seule issue à l'épuisement. a347cc389
- [x] Scripts hors pipeline sous le breaker de leur source. a347cc389

### Phase 3 — Adaptateur et registre

- [x] Profil des sources, d'où se tirent les listes de sources, les identifiants de personne cherchés, les agences d'enregistrement, les sources sur option et le mode quotidien. ad79d4099
- [x] Protocole de l'adaptateur, implémenté pour les sept sources. a764e373b
- [x] Tables des phases construites depuis les adaptateurs. a764e373b
- [x] Test : chaque adaptateur a exactement les capacités de son profil. a764e373b
- [x] Libellés des sources servis par l'API au frontend, et liens vers les portails des sources calculés par l'API. b95cee119

### Phase 4 — Boucle de recherche commune et écriture dans `staging`

- [x] Débit réel de chaque source mesuré sur un run, avant la boucle commune (run 328).
- [x] Identifiants d'un enregistrement source fournis par l'adaptateur à tous les points d'entrée. c379eeb1c
- [x] Boucle commune et écriture des trois issues, pour les cinq canaux, effacement des échecs compris. 8f90a39b2
- [x] `upsert_staging` dans `StagingStore`, qui reçoit sa connexion à la construction. c379eeb1c

### Phase 5 — Débit

- [x] Budget de débit de chaque source, avec les réglages d'accès aux API, injecté dans le contexte de phase. 6532f97c8 ae2b644c0
- [x] Rythme de la source (`Pace`), porté par son circuit-breaker, à la place des pauses par worker, du `Throttle` et de `RequestPace`. 6532f97c8
- [x] Débit réel de chaque source mesuré sur un run, comparé à la mesure de la phase 4 (run 331).

### Phase 6 — Politiques de source

- [x] theses.fr dans la fenêtre d'années : moissonnage, relecture, suppression hors fenêtre, qui épargne les thèses en cours. d8fd9c470
- [x] Câblage commun de `harvest` et de `harvest_by_person`. a764e373b 490ad11b1

### Phase 7 — Normalisation

- [x] Séquence d'écriture dans la classe de base.

### Phase 8 — Documentation

- [ ] Mise à jour de `docs/sources` et de `docs/pipeline`.

## Questions ouvertes

- Optimisation de `harvest_by_person` : plusieurs lots en vol par source, et `select` Crossref pour écarter les champs inutiles. Le temps d'une requête vient du volume des enregistrements de grandes collaborations (5 Mio pour 25 documents DataCite, 13 Mio pour 100 documents Crossref), pas de la recherche (0,3 s).
