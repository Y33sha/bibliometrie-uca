# Chantier — Complétude des identifiants externes & clés de déduplication

## Contexte

Les identifiants cross-source (`DOI`, `hal_id`, `NNT`, `pmid`, …) vivent dans `source_publications.external_ids` et servent de **clés de déduplication** : `decide_publication_match` ([`match_or_create_publications.py`](../../application/pipeline/publications/match_or_create_publications.py)) enchaîne DOI → NNT → HAL_ID → titre/année. `external_ids` est un **dict plat** → une seule valeur par clé.

### État de l'extraction par source (audit 2026-06-09, `data/raw_store`)

- **ScanR** — `externalIds` est une liste `{id, type}` avec les types **`doi`, `pmid`, `hal`, `nnt`** (`pmid` présent dans ~18 % des docs). `normalize_scanr` extrait **déjà** `hal_id`, `nnt` et `pmid` (22 838 SP en base) — rien à faire pour le PMID ScanR.
- **HAL** — `pmid` : le champ Solr canonique `pubmedid_s` n'est **pas dans `HAL_FIELDS`** ([`fields.py`](../../infrastructure/sources/hal/fields.py)) → pas moissonné. `pmcid` : déjà moissonné via `linkExtId_s="pubmedcentral"` + `linkExtUrl_s=…/pmc/PMC…`, mais non extrait. `normalize_hal` ne capte aucun des deux.
- **OpenAlex** — **Chaque location porte un `id` au format OAI-PMH structuré** : `doi:<doi>`, `pmh:oai:HAL:<halid>v1`, `pmh:oai:arXiv.org:<id>`, … — présent dans nos raw_data, **non exploité**. L'extraction actuelle (`extract_external_ids_from_urls`, [`domain/sources/openalex.py`](../../domain/sources/openalex.py)) ne lit que `landing_page_url`/`pdf_url` et garde le **premier** hal_id.

Identifiants visibles dans les URLs/`id` des locations OpenAlex : DOI, hal_id (tous sous-domaines `*.hal.science`/`hal.inrae.fr`/… — extracteur host-agnostique), NNT (`theses.fr`), PMID (`pubmed.ncbi`), **PMCID** (`ncbi.nlm.nih.gov/pmc`), **arXiv** (`arxiv.org`). `hdl.handle.net` (handle) est hétérogène → faible valeur comme clé.

### Lacunes

- **hal-id : un seul capté par document** (premier match), alors qu'une œuvre peut référencer plusieurs dépôts HAL (chapitres, versions, doublons légitimes). `fetch_missing_hal_id` ([`fetch_missing_hal_id.py`](../../infrastructure/sources/hal/fetch_missing_hal_id.py)) ne lit que la `primary_location` → ne fetch qu'un hal_id par document.
- **Audit hal-id manquants (2026-06-09)** : 8 867 documents OpenAlex référencent ≥2 hal-ids ; **11 675** hal-ids référencés manquent comme `source_publications` HAL ; parmi eux **3 709** sont référencés par des documents OpenAlex **in-périmètre** (`publication_id IS NOT NULL`, **3 108** documents) — enregistrements HAL pertinents manqués à la fois par le moissonnage HAL UCA (affiliation mal renseignée) et par `fetch_missing` (angle mort des locations secondaires). Les 7 966 restants ne viennent que d'OpenAlex hors-périmètre → non gênants.
- **pmid : capté nulle part de façon exploitable et jamais utilisé** comme clé (cité dans un commentaire de `match_or_create_publications`, mais pas de `find_by_pmid`, absent de `decide_publication_match`).
- **Conséquence** : couverture UCA incomplète + occasions de **dédup HAL légitime** manquées (même œuvre déposée deux fois sur HAL).

## Décisions

- **Extraire tous les identifiants disponibles** (`pmid`, `pmcid`, `arxiv`, …) de **toutes** les sources (HAL, ScanR, OpenAlex), dans `external_ids`.
- **hal-id capté via `location.id` (OAI-PMH) sur toutes les locations** OpenAlex — source structurée et exhaustive, qui remplace avantageusement le parsing d'URL et capte tous les dépôts HAL d'une œuvre.
- **Seul `hal_id` est multivalué** (`external_ids.hal_id` → liste). `DOI`/`NNT`/`pmid`/`pmcid`/`arxiv` sont **1:1 avec un document** : plusieurs valeurs distinctes = **signal de fausse fusion** (cf. [METIER_fusions-abusives-sources](METIER_fusions-abusives-sources.md)), pas un cas à multivaluer.
- **`pmid` devient une 4ᵉ clé de déduplication** (avec DOI, hal_id, NNT).
- **`fetch_missing_hal_id` scanne toutes les locations** (plus seulement la primary).
- Exploiter les hal-ids multivalués pour la **dédup HAL légitime** (vrais doublons), en coordination avec le chantier fusions (distinguer doublon légitime ↔ fausse fusion).
- **Hors-scope** : `handle` (`hdl.handle.net`) comme clé — trop hétérogène. `arxiv`/`pmcid` comme clés de dédup : extraction faite, mais usage en clé décidé plus tard.

## Phasage

### Phase 1 — Extraction des identifiants (sans changement de structure) ✓ (`05971e95`)

Capter `pmid`/`pmcid`/`arxiv_id` partout, en scalaires dans `external_ids`. VOs `PMID`/`PMCID`/`ArxivId` ajoutés (contrat DOI/NNT/HALId) + helpers `normalize_pmid`/`normalize_pmcid`/`normalize_arxiv_id` (URL ou id brut).

- [x] ScanR : `pmid` était **déjà** extrait (avec `hal_id`/`nnt`) — rien à faire.
- [x] HAL : `pubmedid_s` ajouté à `HAL_FIELDS` + `build_hal_external_ids` (pure) extrait `pmid` (pubmedid_s) et `pmcid`/`arxiv_id` (`linkExtUrl_s`).
- [x] OpenAlex : `arxiv_id` ajouté (pmid/pmcid déjà captés via URL) ; clés renommées `pmc`→`pmcid`, `arxiv`→`arxiv_id`.
- [x] Modèle `ExternalIds` : champ `pmc`→`pmcid`, ajout `arxiv_id`, validators via les VOs.

**Stock à rafraîchir** (action Laura) : `pubmedid_s` n'étant pas moissonné auparavant, le PMID HAL n'apparaîtra qu'après refetch HAL ; les `external_ids.pmc` OpenAlex existants restent sous l'ancienne clé jusqu'au prochain normalize.

### Phase 2 — PMID comme clé de déduplication ✓ (`09888363`)

- [x] `find_by_pmid` (port + repo) : lookup `external_ids->>'pmid'`.
- [x] `decide_publication_match` : cascade `DOI > NNT > HAL_ID > PMID > metadata` (PMID après les IDs exacts existants, avant le matching par métadonnées — conservateur).
- [x] `bulk_link_orphans_by_pmid` : Phase B step 4/4, bump `updated_at` (staleness).
- [x] Migration `idx_source_pubs_pmid` (index fonctionnel partiel, comme nnt/hal_id) — **à appliquer** (`alembic upgrade head` + `dump_schema`, action Laura).

### Phase 3 — hal-id multivalué (changement de structure) ✓ (`c115eb0a`)

`external_ids.hal_id` scalaire → `list[str]`.

- [x] Extraction OpenAlex : tous les hal-ids des locations via `location.id` (`pmh:oai:HAL:<halid>`) **+** URLs ; ScanR : tous les `externalIds` type=`hal` ; HAL natif : `[son hal_id]`.
- [x] Lecteurs en logique tableau (`unnest` / `@>`) : `find_by_hal_id`, `bulk_link_orphans_by_hal_id` (cible MIN déterministe), donor `merge`, `fetch_missing_hal_id` (×2, **toutes** locations). Modèle `ExternalIds.hal_id` → `list[str]` (validator normalise + dédoublonne).
- [x] Migration `a9d3f1c7e5b2` : scalaire→tableau in-place + index btree fonctionnel → **GIN** (membership) — **à appliquer** (`alembic upgrade head` + `dump_schema`). ⚠️ flag-day : appliquer **avant** de relancer le pipeline (les lecteurs attendent un tableau).
- Asymétrie assumée : seul `hal_id` multivalué (archives = multi-dépôt) ; `nnt`/`pmid`/`pmcid`/`arxiv` restent scalaires (≈1:1 ; audit : pmid 9, pmcid 4, arxiv 0, nnt 0 / 6000 works).

### Phase 4 — Récupération du stock manquant & dédup HAL légitime

**Opérationnelle, pas de nouveau code** : un recompute du stock (`raw_hash = null` sur le staging OpenAlex, action Laura) suffit, le code des Phases 1-3 fait le reste :

1. Re-normalisation → `external_ids.hal_id` reçoit la liste complète (tous les `location.id`).
2. `fetch_missing_hal_id` (phase `cross_imports`, étendue toutes-locations) fetch les ~**3 709** dépôts HAL manquants → nouveaux `source_publications` HAL.
3. `merge_pubs_by_hal_id` (array-aware) fusionne les publications partageant un hal-id.

Cibler le rerun sur les docs OpenAlex à ≥2 hal-ids (≈8 867) suffit.

## Questions ouvertes

- **Ordre du `pmid` dans la cascade** (avant/après hal_id/NNT ?). Fiable (PubMed) mais absent hors biomédecine.
- **`external_ids.hal_id` en liste** : migration de la forme JSONB existante + audit exhaustif des `external_ids->>'hal_id'`.
- **ScanR multivalué** : un document ScanR peut-il porter plusieurs `hal` dans `externalIds` (cas « 1 ScanR → plusieurs HAL » vu dans l'UI) ? À vérifier en base.
- **Récupération des 3 709** : fetch dédié maintenant, ou attendre un run avec `fetch_missing` étendu ? (~3,7 k fetches HAL).
- **`arxiv`/`pmcid` comme clés de dédup** : utiles (préprints, biomed) ou redondants avec DOI/PMID ? À trancher après extraction.
- **Doublons hal-id légitimes** : distinguer « même œuvre, 2 dépôts HAL » (à fusionner) de « 2 documents distincts » (cf. [METIER_fusions-abusives-sources](METIER_fusions-abusives-sources.md)) — la complétude alimente cet arbitrage sans le trancher.

## Liens

- [METIER_fusions-abusives-sources](METIER_fusions-abusives-sources.md) — connexe : les hal-ids manquants alimentent l'audit des fausses fusions, mais la complétude ne **corrige pas** les fusions par DOI ; et la dédup HAL légitime est l'envers (vrais doublons à fusionner).
- État actuel : [`normalize_openalex.py`](../../application/pipeline/normalize/normalize_openalex.py), [`domain/sources/openalex.py`](../../domain/sources/openalex.py) (`extract_external_ids_from_urls`), [`normalize_hal.py`](../../application/pipeline/normalize/normalize_hal.py), [`infrastructure/sources/hal/fields.py`](../../infrastructure/sources/hal/fields.py), [`infrastructure/sources/openalex/__init__.py`](../../infrastructure/sources/openalex/__init__.py) (`SELECT_FIELDS`), [`fetch_missing_hal_id.py`](../../infrastructure/sources/hal/fetch_missing_hal_id.py), [`match_or_create_publications.py`](../../application/pipeline/publications/match_or_create_publications.py) (`decide_publication_match`).
