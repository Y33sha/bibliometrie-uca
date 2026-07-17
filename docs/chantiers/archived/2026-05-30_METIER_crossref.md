# Chantier — Exploitation de l'API CrossRef

Commencé le 2026-04-27

**État au 2026-05-30** — Phases 1 et 2 livrées (ingestion DOI-driven + arbitrage `doc_type` type / sous-type). Décisions de clôture du reste :

- **Phase 3 (promotion ORCID `pending → confirmed`) : abandonnée.** La confirmation / le rejet des identifiants est une action admin manuelle, sans impact sur le pipeline (elle ne change que l'affichage UI). L'automatiser est risqué pour un gain nul côté traitement. Dossier fermé ; éventuellement rouvrable à un stade beaucoup plus mature du projet.
- **Phase 4 (discovery par ORCID) : sortie du chantier, en pause.** Pas spécifique à Crossref — s'envisage sur plusieurs sources. Noté dans TODO ; candidate à un chantier dédié multi-source.
- **Phase 5 (relations entre publications) : hors scope.** Couverte par [`METIER_relations-publications`](METIER_relations-publications.md), auquel Crossref contribuera pour une petite part.
- **Phase 6 (discovery par affiliation) : évaluée sur dump prod le 2026-05-30, recall insuffisant pour une source primaire.** Détail ci-dessous.

## Contexte

CrossRef est l'autorité officielle de l'enregistrement des DOI. Ses métadonnées sont déposées par les éditeurs au moment de l'enregistrement et sont, sur certains champs, plus fiables que celles de HAL/OpenAlex/WoS.

Le chantier vise à exploiter CrossRef sur **trois axes complémentaires**, sans en faire une source de découverte primaire (la voie affiliation/ROR a été écartée — voir « Pistes écartées » ci-dessous).

### Trois rôles attendus

1. **Arbitrage de métadonnées** — résolution des conflits inter-sources sur le `doc_type`, complément sur le journal, les dates (issued / online / print), la license, les funders.
2. **Confirmation d'identité auteur via ORCID article-level** — un ORCID déposé par l'éditeur dans les métadonnées CrossRef est une preuve forte du lien auteur ↔ personne (contrairement à OpenAlex où l'ORCID est attaché à une entité auteur algorithmique, parfois fausse).
3. **Relations entre publications** — preprint-of, version-of, translation-of, has-dataset, etc. Alimente le chantier « relations entre publications » (TODO_LAURA.md ligne 82).

*Rôle 1 = cœur du chantier (livré, Phases 1-2). Rôle 2 abandonné (cf. en-tête, Phase 3). Rôle 3 déplacé vers [`METIER_relations-publications`](METIER_relations-publications.md).*

## Périmètre fonctionnel

### Inclus

- Ingestion CrossRef DOI-driven dans les tables `source_*` existantes (`source_publications` / `source_authorships`) avec `source='crossref'`, à partir des DOI déjà connus dans les autres sources. *(livré, Phases 1-2)*
- Insertion de `crossref` dans `SOURCE_PRIORITY` (2ᵉ position) → arbitrage automatique de toutes les métadonnées canoniques via `refresh_from_sources` existant. *(livré)*
- Mapping de la taxonomie `doc_type` CrossRef vers l'enum canonique dans `domain/doc_types.py`. *(livré)*

### Exclus

- Aucune modification des signatures existantes (auteurs, affiliations, structures).
- Promotion d'ORCID `pending → confirmed` (abandonnée, cf. en-tête / Phase 3).
- Discovery par ORCID (sortie du chantier, multi-source — cf. Phase 4).
- Relations entre publications (→ [`METIER_relations-publications`](METIER_relations-publications.md)).
- Aucune couverture des DOI DataCite (10.5281 Zenodo, 10.6084 figshare, etc.) — cf. [`METIER_doi-ra-datacite`](METIER_doi-ra-datacite.md).
- Aucune couverture des publis sans DOI (HAL collection-only, etc.).

## Architecture cible

### Tables

CrossRef s'intègre dans l'architecture source-agnostique existante en tant que nouvelle valeur `source = 'crossref'`. **Aucune table dédiée n'est créée pour les publications, authorships, persons ou structures.**

- **`source_publications`** (existante) : insertion avec `source = 'crossref'`, `source_id = doi`. Les champs canoniques sont mappés directement (`doi`, `title`, `pub_year`, `doc_type`, `language`, `container_title`, `cited_by_count`, `oa_status`, `is_retracted`, `keywords`, `journal_id`, `external_ids`). Les spécificités CrossRef (license, funders, dates multiples issued/online/print, indexed-date pour l'idempotence) vont dans `meta jsonb`. La référence ISSN va dans `external_ids` ou `biblio` selon la convention en vigueur (à vérifier sur les autres extracteurs).
- **`source_authorships`** (existante) : un row par auteur de la publi CrossRef, `source = 'crossref'`. Les chaînes d'affiliation brutes (déjà connues comme génériques/tronquées côté CrossRef) vont dans `source_data jsonb`. **À noter** : pas de `source_authorship_addresses` à alimenter pour CrossRef puisque les affiliations sont des chaînes plates sans adresse exploitable.
- **`publication_relations`** : hors scope de ce chantier — la modélisation des relations entre publications est traitée dans [`METIER_relations-publications`](METIER_relations-publications.md). Crossref (`relation`) y sera une source d'alimentation parmi d'autres (DataCite `relatedIdentifiers`, etc.).

### Code

- **`infrastructure/sources/crossref/`** : client API (polite pool avec mailto, gestion 429, retry exponentiel), pagination cursor.
- **`application/pipeline/normalize/normalize_crossref.py`** + ports + queries : normalizer CrossRef, sur le modèle des autres (cf. `normalize_scanr`, `normalize_theses`, etc.) — alimente `source_publications` / `source_authorships` avec `source='crossref'`.
- **Modifications dans `domain/`** :
  - `domain/sources.py` : ajouter `"crossref"` à `ALL_SOURCES` et à `SOURCE_PRIORITY` (2ᵉ position) ; ajout à l'enum `source_type` côté SQL via migration.
  - `domain/doc_types.py` : ajouter une entrée `"crossref"` dans `_SOURCE_MAPS`.
- **Pas de phase d'arbitrage dédiée** : l'arbitrage des métadonnées canoniques est déjà fait par `refresh_from_sources` (`application/publications.py`) via `SOURCE_PRIORITY`, qui prendra automatiquement en compte CrossRef après ingestion.

### Place dans le pipeline

CrossRef s'insère comme **une nouvelle source au même titre que ScanR et theses.fr** :
- **Phase d'extraction CrossRef** dans le pipeline d'imports (sur le modèle de l'extracteur theses.fr).
- **Phase `normalize_crossref`** alimente `source_publications` / `source_authorships`.
- **Phases existantes** (`build_authorships`, `refresh_from_sources` indirectement, etc.) consomment automatiquement la nouvelle source via `SOURCE_PRIORITY`.

Intégration dans `run_pipeline.py` avec ses propres `--only` / `--from` et inclusion dans le filtrage `--sources`.

## Phases d'implémentation

Découpage proposé (chaque phase = chantier autonome mergeable indépendamment) :

### Phase 0 — Spike & validation ✅
- [x] Tester l'API sur ~100 DOI représentatifs UCA (HAL, OA, WoS, ScanR, theses)
- [x] Mesurer la couverture réelle ORCID par tranche d'année
- [x] Mesurer la couverture des relations (preprint, etc.)
- [x] Valider le format JSON et identifier les champs réellement exploitables
- [x] **Livrable** : `docs/chantiers/crossref-spike.md` + script `interfaces/cli/crossref_spike.py` (script supprimé après le spike, le rapport reste).

### Phase 1 — Extracteur + normalizer DOI-driven
- [x] Migration SQL : ajout de `'crossref'` à l'enum `source_type` (migration 009)
- [x] Ajout de `"crossref"` à `ALL_SOURCES`, `BIBLIO_SOURCES` et `SOURCE_PRIORITY` (2ᵉ position) dans `domain/sources.py`
- [x] Client API `infrastructure/sources/crossref/fetch_missing_doi.py` (polite pool via mailto, retry, gestion 404 → `not_found=TRUE`)
- [x] Wiring dans `run_pipeline.py` + dispatcher CLI `interfaces/cli/pipeline/fetch_missing_doi.py`
- [x] Normalizer CrossRef : ports (`application/ports/normalize_crossref.py`) + queries (`infrastructure/queries/normalize_crossref.py`) + orchestrator (`application/pipeline/normalize/normalize_crossref.py`) + CLI (`interfaces/cli/pipeline/normalize_crossref.py`) — alimentation de `source_publications` / `source_authorships` (colonnes canoniques + `meta`/`source_data`/`biblio` pour le reste). `doc_type` stocké NULL en attendant la phase 2.
- [x] Wiring du normalizer dans `run_pipeline.phase_normalize` (avant scanr/hal/oa/wos, après theses)
- [ ] Tests d'intégration sur un petit lot
- **Livrable** : `source_publications` / `source_authorships` alimentées avec `source='crossref'` pour les DOI déjà présents dans `publications`, idempotent

### Phase 2 — Mapping `doc_type` & arbitrage type / sous-type ✅
- [x] `_SOURCE_MAPS["crossref"]` ajouté dans `domain/doc_types.py` (taxonomie CrossRef → enum canonique : `journal-article` → `article`, `book-chapter` → `book_chapter`, `monograph`/`edited-book`/`reference-book` → `book`, `posted-content`/`preprint` → `preprint`, `dissertation` → `thesis`, `proceedings-article` → `conference_paper`, `peer-review` → `peer_review`, etc.)
- [x] `"crossref"` déjà inséré en 2ᵉ position dans `SOURCE_PRIORITY` (cf phase 1A).
- [x] Modification de `_first_doc_type` dans `application/publications.py` : si la source prioritaire (CrossRef) renvoie `article` mais qu'une source moins prioritaire (HAL, OA…) connaît un sous-type plus précis (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction), on préfère le sous-type. Évite la régression identifiée dans le spike (~11 % des publis : `review`/`book_review`/`data_paper`/`poster` HAL écrasés en `article` par CrossRef).
- [x] Liste `ARTICLE_SUBTYPES` définie côté `domain/doc_types.py` (cohérent avec le reste de la taxonomie). Sémantique « sous-type prime sur type générique » documentée dans le code.
- [x] Tests unit : `TestCrossRefDocTypeMap` (couverture taxonomie) + `TestFirstDocTypeArbitration` (5 cas d'arbitrage).
- **Pas de migration nécessaire** : `refresh_from_sources` consomme déjà `_first_doc_type`, le changement est transparent au prochain refresh des publis CrossRef-touchées.

### Phase 3 — Promotion d'ORCID `pending` → `confirmed` ❌ (abandonnée)

Décision 2026-05-30 : abandonnée. La confirmation / le rejet des identifiants est une fonction admin manuelle, sans impact sur le pipeline (seul l'affichage UI dépend du statut). Une promotion automatisée est risquée pour un bénéfice nul côté traitement. Rouvrable éventuellement à un stade beaucoup plus mature du projet.

Pour mémoire, le concept était : pour une `source_authorship` Crossref portant un ORCID déjà présent en `pending` dans `person_identifiers` et rattachée à la même `person_id` (confirmée indépendamment de l'ORCID), promouvoir l'ORCID en `confirmed`. La circularité (si l'ORCID est lui-même la clé de rattachement) imposait de vérifier une confirmation par une autre source à la même position.

### Phase 4 — Discovery via ORCID confirmé ➡ (sortie du chantier, en pause)

Décision 2026-05-30 : sortie de ce chantier. La découverte par ORCID n'est pas propre à Crossref — elle s'envisage sur plusieurs sources (DataCite, OpenAlex…). Notée dans TODO ; candidate à un chantier dédié multi-source. Non instruite ici.

Pour mémoire, le gate exploratoire envisagé : pour un échantillon d'ORCIDs confirmés, interroger `filter=orcid:<ORCID>` et confronter aux DOI déjà connus toutes sources confondues, décision go/no-go selon le gain en DOI nouveaux.

### Phase 5 — Relations entre publications ➡ (hors scope)

Décision 2026-05-30 : hors scope de ce chantier. La modélisation est traitée dans [`METIER_relations-publications`](METIER_relations-publications.md) ; Crossref (`relation`) y contribuera pour une petite part, aux côtés de DataCite `relatedIdentifiers` et autres. Pour mémoire, sur l'échantillon spike la couverture `relation` n'était que de ~2 %.

### Phase 6 — Discovery par affiliation 🔬 (évaluée le 2026-05-30 — recall insuffisant)

Mesure refaite sur un dump récent de la prod (quasi jumeau), avec la bonne requête. Le spike d'origine (237 847 hits, 81 % de nouveaux sur base locale) était trompeur : il interrogeait `query.affiliation=Université Clermont Auvergne`, dont le token « université » matche des centaines de milliers d'affiliations universitaires sans rapport, et comparait à une base non représentative.

Requête correcte : `query.affiliation=Clermont Auvergne`. Le filtre est un match par tokens Elasticsearch — l'ordre des mots, le tiret et « Université »/« University » sont sans effet ; les deux tokens « Clermont » + « Auvergne » suffisent et évitent le bruit « université ».

Résultats (filtre `from-pub-date:2020,until-pub-date:2026`) :

| Mesure | Valeur |
|---|---:|
| Hits annoncés par Crossref | 8 510 |
| DOIs paginés (cursor cassé sur 500 transitoire à ~82 %) | 7 000 |
| Base — publis avec DOI Crossref 2020-2026 (dénominateur) | 20 231 |
| Découvertes retrouvées dans ce sous-ensemble | 5 347 (**recall 26 %**) |
| Nouveaux candidats (absents de la base) | 1 642 |

**Constat : recall faible (~26 %).** Crossref n'indexe la chaîne d'affiliation que pour une minorité de ses dépôts (beaucoup d'éditeurs ne la déposent pas) — la query est donc aveugle aux ~3/4 des publications Crossref UCA déjà connues. L'affiliation-driven Crossref **ne peut pas être une source de découverte primaire** ; au mieux un filet d'appoint ramenant ~1 600-2 000 nouveaux candidats, à valider en précision (le token-match « Clermont » + « Auvergne » peut capter du non-UCA : CHU, Sigma Clermont, INRAE Auvergne…).

**Précision des nouveaux candidats** (échantillon de 50, métadonnées Crossref relues à l'œil) : **14 % d'UCA stricts** (affiliation nommant Université Clermont Auvergne / UCA / labos UCA), ~34 % si le CHU de Clermont-Ferrand est compté dans le périmètre. 16 % sont des institutions clermontoises non-UCA (SIGMA Clermont / Clermont INP, INRAE seul, Michelin), et **50 % du pur bruit de token** (« Clermont » en Floride/Kentucky/Ohio, « Auvergne » comme région ⇒ Lyon/Grenoble/Saint-Étienne). Histogramme des années : `2020:10 2021:8 2022:6 2023:4 2024:6 2025:13 2026:3` — léger sur-poids du récent (2025-26 = 32 %), confirmant pour la *fraction utile* l'hypothèse « Crossref sort avant les autres sources », mais le gros du nouveau n'est ni récent ni UCA.

**Décision (2026-05-30) : no-go sur l'extracteur affiliation-driven Crossref.** Recall faible (26 %) **et** précision faible (~14-34 %) sur ce qu'il ajoute → rendement net ≈ 230-560 vraies publis UCA noyées dans ~2/3 de bruit, non ingérables sans filtre de précision. Coût disproportionné pour un filet d'appoint. Le DOI-driven (Phase 1, livré) reste le bon usage de Crossref. La piste « rattraper les publis récentes en avance sur une source » relève du re-fetch périodique ([`DATA_cycle-vie-staging`](DATA_cycle-vie-staging.md)), pas de ce chantier.

Si l'apport est jugé suffisant, l'implémentation cible reste : module `infrastructure/sources/crossref/fetch_uca_publications.py` (affiliation-driven, analogue HAL/OpenAlex) réutilisant le normalizer Crossref existant (Phase 1), en pagination `offset` (8 510 < cap offset 10 000 — évite le cursor qui casse). Cousin DataCite affiliation-driven : cf. [`METIER_doi-ra-datacite`](METIER_doi-ra-datacite.md) Phase 3.

Spike : [`interfaces/cli/oneshot/crossref_affiliation_discovery_spike.py`](../../interfaces/cli/oneshot/crossref_affiliation_discovery_spike.py).

## Considérations techniques

- **Polite pool** : mettre `User-Agent` avec mailto, ce qui donne accès au pool prioritaire et évite les rate-limits agressifs.
- **Pagination** : `offset` capé à 10 000, au-delà utiliser `cursor=*`. Concerne uniquement les requêtes par ORCID (phase 4) — les fetchs par DOI sont unitaires.
- **Idempotence** : clé `doi`, upsert avec mise à jour si `indexed` (date d'indexation CrossRef) plus récente que `last_fetched_at`.
- **Volume initial** : à mesurer en phase 0 — combien de DOI uniques dans `publications` aujourd'hui ? À 50ms/req polite pool, 100k DOI ≈ 1h30 séquentiel, parallélisable.
- **Mises à jour incrémentales** : refetch périodique des DOI dont `indexed` a évolué (filtre `from-index-date`).
- **Logging** : `setup_logger` standard, traçer les conflits `doc_type` et les ORCIDs promus en `confirmed` pour audit.

## Décisions actées

1. **Position de CrossRef dans l'ordre d'autorité des sources** : insertion en 2ᵉ position dans la constante existante `SOURCE_PRIORITY` (`domain/sources.py`).
   - Ordre cible : `("theses", "crossref", "scanr", "hal", "openalex", "wos")`.
   - Aucun nouveau mécanisme à concevoir : `SOURCE_PRIORITY` est déjà la source unique de vérité utilisée par `refresh_from_sources` (`application/publications.py`) pour arbitrer **tous les champs canoniques** (doi, doc_type, pub_year, journal_id, oa_status, container_title, language, abstract, keywords, countries, topics, biblio, meta, is_retracted), ainsi que par `propagate_author_position` dans `build_authorships`.
   - CrossRef sera donc prioritaire sur HAL/OA/WoS pour l'ensemble de ces champs, et cédera la priorité à theses.fr (qui fait autorité sur les métadonnées de thèse).
   - Une seule ligne à modifier : la définition de `SOURCE_PRIORITY` dans `domain/sources.py`. L'effet se propage automatiquement partout où la constante est consommée.

2. **Stockage des champs CrossRef-spécifiques** : tout dans `meta jsonb` / `source_data jsonb` des tables `source_*` existantes pour démarrer.
   - Pas de colonnes dédiées créées maintenant pour `license` et `funders`.
   - Promotion possible plus tard si un usage le justifie. Pour l'instant : la `license` n'a pas vocation à être exposée dans l'UI (le statut OA ouvert/fermé suffit), et les `funders` ne sont pas une donnée demandée par les utilisateurs (à reconsidérer si besoin).

3. **Fréquence de refetch** : intégration aux deux modes `--mode weekly` et `--mode monthly` (alias full) de `run_pipeline`, avec stratégies distinctes.
   - **Mode weekly** : interrogation uniquement des DOI **absents du staging CrossRef** (incrémental, pas de refetch des DOI déjà ingérés). Les métadonnées CrossRef qui nous intéressent bougent peu.
   - **Mode full** : ré-interrogation possible de l'ensemble du corpus et comparaison de hash pour détecter les changements. À mettre en place de manière conservative, et **à évaluer à l'usage** — peut-être pas pertinent en pratique si les variations s'avèrent négligeables.

4. **Discovery via ORCID** : sortie de ce chantier (cf. Phase 4) — pas spécifique à Crossref, candidate à un chantier dédié multi-source.

## Risques & open questions

- **Mapping `doc_type` CrossRef ↔ canonique** : plusieurs cas non triviaux (`posted-content` peut être preprint ou commentary, `book-chapter` vs `monograph` vs `reference-entry`…). À concevoir avec exemples réels en phase 0.

## Crossref absent de `build_authorships.all_sources`

[`build_authorships.py:20-26`](application/pipeline/authorships/build_authorships.py#L20)
hardcode 5 sources (HAL, OpenAlex, WoS, ScanR, theses.fr) — Crossref
manque. La liste sert à plusieurs étapes :

- **Étape 2** (link FK `source_authorships.authorship_id` →
  `authorships.id` via `link_source_authorships_to_authorship_for`) :
  Crossref insère bien des `source_authorships`, donc devrait y figurer
  pour que ses authorships soient reliées à la table de vérité. **Bug
  potentiel** ou décision non documentée.
- **Étape 4** (propagation `in_perimeter` + `structure_ids`) :
  Crossref n'a pas de `structure_ids` (affiliations brutes texte uniquement)
  → exclusion légitime à ce niveau.

À investiguer : vérifier si les `source_authorships` Crossref sont
correctement reliées à `authorships` aujourd'hui. Si non → ajouter
Crossref à la liste mais avec gestion différenciée selon l'étape, ou
scinder en deux constantes (`AUTHORSHIPS_LINK_SOURCES` vs
`STRUCTURE_PROPAGATION_SOURCES`).

## Liens

- API doc : <https://api.crossref.org/swagger-ui/index.html>
- Tips REST API : <https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/>
- ROR adoption : <https://ror.org/blog/2024-07-25-re-introducing-participation-reports/>
- TODO_LAURA.md ligne 82 (relations entre publications)
