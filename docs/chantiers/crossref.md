# Chantier — Exploitation de l'API CrossRef
Commencé le 2026-04-27
**En pause depuis 2026-04-28** — phases 1 et 2 livrées (ingestion + arbitrage `doc_type` avec gestion type / sous-type). Phases 3-5 (promotion ORCID, discovery, relations) reportées : sur l'échantillon CrossRef actuel (dominé par des méga-papers JAMA sans ORCID), l'utilité concrète est trop faible pour valider la logique. Reprise envisageable quand le corpus CrossRef sera plus représentatif (= cycles d'ingestion supplémentaires sur des DOIs non-mega) et qu'on pourra mesurer a priori l'impact de la promotion `pending → confirmed`.

## Contexte

CrossRef est l'autorité officielle de l'enregistrement des DOI. Ses métadonnées sont déposées par les éditeurs au moment de l'enregistrement et sont, sur certains champs, plus fiables que celles de HAL/OpenAlex/WoS.

Le chantier vise à exploiter CrossRef sur **trois axes complémentaires**, sans en faire une source de découverte primaire (la voie affiliation/ROR a été écartée — voir « Pistes écartées » ci-dessous).

### Trois rôles attendus

1. **Arbitrage de métadonnées** — résolution des conflits inter-sources sur le `doc_type`, complément sur le journal, les dates (issued / online / print), la license, les funders.
2. **Confirmation d'identité auteur via ORCID article-level** — un ORCID déposé par l'éditeur dans les métadonnées CrossRef est une preuve forte du lien auteur ↔ personne (contrairement à OpenAlex où l'ORCID est attaché à une entité auteur algorithmique, parfois fausse).
3. **Relations entre publications** — preprint-of, version-of, translation-of, has-dataset, etc. Alimente le chantier « relations entre publications » (TODO_LAURA.md ligne 82).

### Pistes écartées

- **CrossRef comme source de découverte par affiliation** : `query.affiliation` est trop bruité (pas d'opérateurs booléens, pas de match exact), et le filtre `ror-id` souffre d'une adoption insuffisante par les éditeurs (≈16 % des records CrossRef ont des affiliations en mars 2025, ROR encore plus bas). Doublonnerait OpenAlex sans rien apporter.
- **CrossRef pour enrichir les signatures (labos, équipes, services)** : les métadonnées CrossRef sont aplaties par les éditeurs vers la tutelle générique (« University Clermont Auvergne »), sans labo. Les signatures restent du ressort de HAL/OpenAlex/WoS.

## Périmètre fonctionnel

### Inclus

- Ingestion CrossRef DOI-driven dans les tables `source_*` existantes (`source_publications` / `source_authorships` / `source_persons`) avec `source='crossref'`, à partir des DOI déjà connus dans les autres sources.
- Discovery secondaire driven-by-ORCID : interrogation par ORCID confirmé pour identifier d'éventuelles publis ratées par les autres sources. **Conditionnée à un travail exploratoire** (cf. phase 4) : abandonnée si le gain s'avère nul.
- Insertion de `crossref` dans `SOURCE_PRIORITY` (2ᵉ position) → arbitrage automatique de toutes les métadonnées canoniques via `refresh_from_sources` existant.
- Mapping de la taxonomie `doc_type` CrossRef vers l'enum canonique dans `domain/doc_types.py`.
- Mécanisme de promotion d'ORCID `pending` → `confirmed` via les ORCIDs CrossRef.
- Table `publication_relations` (à créer) alimentée par les `relation` CrossRef.

### Exclus

- Aucune modification des signatures existantes (auteurs, affiliations, structures).
- Aucune découverte par affiliation/ROR.
- Aucune couverture des DOI DataCite (10.5281 Zenodo, 10.6084 figshare, etc.) — gap connu, à traiter séparément si besoin.
- Aucune couverture des publis sans DOI (HAL collection-only, etc.).

## Architecture cible

### Tables

CrossRef s'intègre dans l'architecture source-agnostique existante en tant que nouvelle valeur `source = 'crossref'`. **Aucune table dédiée n'est créée pour les publications, authorships, persons ou structures.**

- **`source_publications`** (existante) : insertion avec `source = 'crossref'`, `source_id = doi`. Les champs canoniques sont mappés directement (`doi`, `title`, `pub_year`, `doc_type`, `language`, `container_title`, `cited_by_count`, `oa_status`, `is_retracted`, `keywords`, `journal_id`, `external_ids`). Les spécificités CrossRef (license, funders, dates multiples issued/online/print, indexed-date pour l'idempotence) vont dans `meta jsonb`. La référence ISSN va dans `external_ids` ou `biblio` selon la convention en vigueur (à vérifier sur les autres extracteurs).
- **`source_authorships`** (existante) : un row par auteur de la publi CrossRef, `source = 'crossref'`. Les chaînes d'affiliation brutes (déjà connues comme génériques/tronquées côté CrossRef) vont dans `source_data jsonb`. **À noter** : pas de `source_authorship_addresses` à alimenter pour CrossRef puisque les affiliations sont des chaînes plates sans adresse exploitable.
- **`source_persons`** (existante) : un row par auteur unique CrossRef, `source = 'crossref'`, `source_id` synthétique (DOI:position ou hash) faute d'identifiant CrossRef stable côté auteur. `orcid` rempli quand présent dans les métadonnées CrossRef. Le champ `meta`/`source_data` peut tracer le flag `authenticated-orcid` (voir note ci-dessous), à titre informatif uniquement.
- **`publication_relations`** (**à créer**) : `from_publication_id`, `to_publication_id` (ou DOI si la publi cible n'est pas connue), `relation_type` (preprint, version, translation, has-dataset…), `source` (crossref pour l'instant, extensible). C'est le seul vrai ajout de table — cross-source dès le départ pour ne pas refaire la migration plus tard.

> Note sur `authenticated-orcid` : champ non fiable de l'avis même de CrossRef (la quasi-totalité des ORCIDs sont à `false` parce que les éditeurs n'utilisent pas le workflow OAuth, pas parce que la vérif a échoué). On peut le stocker dans `source_data` pour traçabilité mais on ne s'en sert pas comme filtre de confiance.

### Code

- **`infrastructure/sources/crossref/`** : client API (polite pool avec mailto, gestion 429, retry exponentiel), pagination cursor.
- **`application/pipeline/normalize/normalize_crossref.py`** + ports + queries : normalizer CrossRef, sur le modèle des autres (cf. `normalize_scanr`, `normalize_theses`, etc.) — alimente `source_publications` / `source_authorships` / `source_persons` avec `source='crossref'`.
- **`application/pipeline/crossref_promote_orcids.py`** : phase de promotion d'ORCID `pending` → `confirmed`.
- **Modifications dans `domain/`** :
  - `domain/sources.py` : ajouter `"crossref"` à `ALL_SOURCES` et à `SOURCE_PRIORITY` (2ᵉ position) ; ajout à l'enum `source_type` côté SQL via migration.
  - `domain/doc_types.py` : ajouter une entrée `"crossref"` dans `_SOURCE_MAPS`.
- **Pas de phase d'arbitrage dédiée** : l'arbitrage des métadonnées canoniques est déjà fait par `refresh_from_sources` (`application/publications.py`) via `SOURCE_PRIORITY`, qui prendra automatiquement en compte CrossRef après ingestion.

### Place dans le pipeline

CrossRef s'insère comme **une nouvelle source au même titre que ScanR et theses.fr** :
- **Phase d'extraction CrossRef** dans le pipeline d'imports (sur le modèle de l'extracteur theses.fr).
- **Phase `normalize_crossref`** alimente `source_publications` / `source_authorships` / `source_persons`.
- **Phases existantes** (`build_authorships`, `refresh_from_sources` indirectement, etc.) consomment automatiquement la nouvelle source via `SOURCE_PRIORITY`.
- **Phase additionnelle `crossref_promote_orcids`** spécifique à CrossRef (cf. phase 3).

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
- [x] Entrée `"crossref"` ajoutée à `_SOURCE_CONFIG` dans `application/persons.py`
- [x] Client API `infrastructure/sources/crossref/fetch_missing_doi.py` (polite pool via mailto, retry, gestion 404 → `not_found=TRUE`)
- [x] Wiring dans `run_pipeline.py` + dispatcher CLI `interfaces/cli/pipeline/fetch_missing_doi.py`
- [x] Normalizer CrossRef : ports (`application/ports/normalize_crossref.py`) + queries (`infrastructure/db/queries/normalize_crossref.py`) + orchestrator (`application/pipeline/normalize/normalize_crossref.py`) + CLI (`interfaces/cli/pipeline/normalize_crossref.py`) — alimentation de `source_publications` / `source_authorships` / `source_persons` (colonnes canoniques + `meta`/`source_data`/`biblio` pour le reste). `doc_type` stocké NULL en attendant la phase 2.
- [x] Wiring du normalizer dans `run_pipeline.phase_normalize` (avant scanr/hal/oa/wos, après theses)
- [ ] Tests d'intégration sur un petit lot
- **Livrable** : `source_publications` / `source_authorships` / `source_persons` alimentées avec `source='crossref'` pour les DOI déjà présents dans `publications`, idempotent

### Phase 2 — Mapping `doc_type` & arbitrage type / sous-type ✅
- [x] `_SOURCE_MAPS["crossref"]` ajouté dans `domain/doc_types.py` (taxonomie CrossRef → enum canonique : `journal-article` → `article`, `book-chapter` → `book_chapter`, `monograph`/`edited-book`/`reference-book` → `book`, `posted-content`/`preprint` → `preprint`, `dissertation` → `thesis`, `proceedings-article` → `conference_paper`, `peer-review` → `peer_review`, etc.)
- [x] `"crossref"` déjà inséré en 2ᵉ position dans `SOURCE_PRIORITY` (cf phase 1A).
- [x] Modification de `_first_doc_type` dans `application/publications.py` : si la source prioritaire (CrossRef) renvoie `article` mais qu'une source moins prioritaire (HAL, OA…) connaît un sous-type plus précis (review, book_review, data_paper, poster, conference_paper, editorial, letter, erratum, retraction), on préfère le sous-type. Évite la régression identifiée dans le spike (~11 % des publis : `review`/`book_review`/`data_paper`/`poster` HAL écrasés en `article` par CrossRef).
- [x] Liste `ARTICLE_SUBTYPES` définie côté `domain/doc_types.py` (cohérent avec le reste de la taxonomie). Sémantique « sous-type prime sur type générique » documentée dans le code.
- [x] Tests unit : `TestCrossRefDocTypeMap` (couverture taxonomie) + `TestFirstDocTypeArbitration` (5 cas d'arbitrage).
- **Pas de migration nécessaire** : `refresh_from_sources` consomme déjà `_first_doc_type`, le changement est transparent au prochain refresh des publis CrossRef-touchées.

### Phase 3 — Promotion d'ORCID `pending` → `confirmed` ⏸ (en pause)

Concept : pour chaque `source_authorship` CrossRef portant un ORCID, si cet ORCID figure dans `person_identifiers` en statut `pending` ET que l'authorship est rattachée à la même `person_id` (validée par cross-source ≠ tautologie via l'ORCID lui-même), alors on a une preuve article-level côté éditeur → promotion en `confirmed`.

**Subtilité de logique identifiée** : le pipeline persons rattache via 4 étapes (HAL accounts, cross-source, IdRef/ORCID connu, name forms). Si l'ORCID pending est lui-même la clé de rattachement (Étape 2), la promotion devient circulaire. Pour valider la promotion il faut vérifier qu'une AUTRE source à la même position confirme la `person_id` indépendamment de l'ORCID. SQL d'exploration prêt (cf. discussion 2026-04-28).

**Mise en pause** : sur l'échantillon CrossRef actuel, 0 ORCID candidat trouvé (échantillon dominé par des méga-papers JAMA sans ORCID). Reprise quand le corpus CrossRef sera plus représentatif et que la mesure a priori sera fiable.

### Phase 4 — Discovery via ORCID confirmé ⏸ (en pause)

Gate exploratoire avant toute implémentation : pour un échantillon d'ORCIDs confirmés, interroger `filter=orcid:<ORCID>` sur CrossRef et confronter aux DOI déjà connus toutes sources confondues. Décision go/no-go selon le gain en DOI nouveaux.

**Mise en pause** : reportée en attendant un volume CrossRef représentatif et un set d'ORCIDs UCA confirmés stable.

### Phase 5 — Relations entre publications ⏸ (en pause)

Migration : création de `publication_relations` (cross-source) + extraction du champ `relation` de CrossRef. Affichage UI à concevoir séparément (TODO_LAURA.md ligne 82).

**Mise en pause** : sur l'échantillon spike, ~2 % de couverture relations — bénéfice immédiat trop modeste pour prioriser. Reprise quand le corpus CrossRef sera plus volumineux ou si un besoin UI spécifique émerge.

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

4. **Discovery via ORCID (Phase 4)** : on s'en tient au **matching DOI uniquement** dans un premier temps. Le matching par ORCID est conditionné à un travail exploratoire préalable.
   - Avant toute décision d'ingestion, mesurer combien de DOI nouveaux (absents de toutes les sources actuelles) seraient remontés en interrogeant CrossRef avec les ORCIDs confirmés UCA.
   - Si le gain est nul ou marginal → la phase 4 est abandonnée.
   - Si le gain est significatif → ré-ouvrir la décision sur la politique d'ingestion (auto vs. validation manuelle).

## Décisions à prendre (avant Phase 2 et au-delà)

Aucune pour l'instant — toutes les décisions structurantes ont été tranchées. De nouvelles questions pourront émerger en phase 0 (mapping `doc_type` notamment).

## Risques & open questions

- **Couverture ORCID inégale** : très bonne post-2018 chez les gros éditeurs commerciaux, médiocre avant. Si la phase 4 (discovery) est conservée à l'issue du gate exploratoire, le recall sera partiel — au mieux un filet de sécurité, jamais une source primaire.
- **Mapping `doc_type` CrossRef ↔ canonique** : plusieurs cas non triviaux (`posted-content` peut être preprint ou commentary, `book-chapter` vs `monograph` vs `reference-entry`…). À concevoir avec exemples réels en phase 0.
- **DataCite gap** : tous les DOI Zenodo, figshare, certains datasets ne sont **pas** dans CrossRef. Hors périmètre, mais à documenter clairement pour ne pas semer la confusion sur la couverture.
- **Promotion d'ORCID erronée** (phase 3) : risque qu'un ORCID CrossRef incorrect (cas rare mais pas nul, surtout sur les vieilles publis où l'éditeur a pu rentrer un ORCID sans vérif) déclenche une promotion `pending → confirmed` injustifiée. Politique conservatrice : exiger que l'ORCID soit déjà connu côté UCA en `pending` ET attaché à la même personne que la `source_authorship` CrossRef.
- **Volume requêtes** : à mesurer en phase 0 pour calibrer parallélisme et fréquence.

## Liens

- API doc : <https://api.crossref.org/swagger-ui/index.html>
- Tips REST API : <https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/>
- ROR adoption : <https://ror.org/blog/2024-07-25-re-introducing-participation-reports/>
- TODO_LAURA.md ligne 82 (relations entre publications)
