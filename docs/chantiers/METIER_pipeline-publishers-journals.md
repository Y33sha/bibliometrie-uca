# Chantier — Pipeline : phase `publishers_journals` (référentiels enrichis)

Commencé le 2026-05-26

## Contexte

L'enrichissement des entités `publishers` et `journals` est aujourd'hui dispersé, ce qui rend l'ajout de nouvelles sources frictionnel et la cohérence inter-sources opaque.

- **`normalize`** crée les entités via `find_or_create_publisher` / `find_or_create_journal` (volontairement gardé là par [METIER_publishers-journals.md](METIER_publishers-journals.md) Phase 2). À ne PAS toucher.
- **`resolve_doi_prefixes`** (entre normalize et affiliations) renseigne `doi_prefixes` (avec son `ra` et son `crossref_member_id`) et lie `publisher_id` quand le nom Crossref matche `publisher_name_forms`. C'est de l'enrichissement de référentiel — mal rangé en phase top-level isolée.
- **`enrich`** mélange `enrich_oa_status` (Unpaywall, **per-publication**) et `enrich_journal_apc` (OpenAlex Sources, **per-journal** : APC, `is_in_doaj` flag, `journal_type` depuis 2026-05-26). Le carpe-lapin nuit à la lisibilité.
- **Import DOAJ CSV** vit comme script CLI manuel (`interfaces/cli/imports/import_doaj_csv.py`). Bootstrap-style, pas branché au pipeline régulier.
- **Aucune source pour `publishers.country` ni `publishers.publisher_type`** — ces colonnes restent NULL / `'unknown'` faute de phase d'enrichissement, alors qu'OpenAlex Publishers fournit `country_codes` + `ids.ror` gratuitement et que ROR permet ensuite de dériver un `publisher_type`.

**Objectif** : consolider tout l'enrichissement référentiel dans une unique phase pipeline `publishers_journals`, positionnée entre `normalize` et `affiliations`. Garder `enrich_oa_status` (Unpaywall) à sa place — c'est per-publication, hors-scope.

## Décisions à trancher

1. **Position dans le pipeline** — **tranché** : entre `normalize` et `affiliations`, à la place exacte de `resolve_doi_prefixes` (qui devient un sub-step interne).

2. **Sort de `enrich_journal_apc`** — **tranché** : à garder dans la nouvelle phase. Branche déjà `journal_type` (chantier 2026-05-26) qui doit rester actif. Pour les montants APC : audit préalable de cohérence APC OpenAlex vs APC DOAJ (cf. Phase 7) avant toute décision de retrait.

3. **`parent_publisher` d'OpenAlex** — **tranché** : NON, hors scope cette fois. À reposer si l'usage le justifie (consolidation auto "BMC → Springer Nature" = fusion automatique = chantier à risque).

4. **DOAJ — API ou CSV** — **tranché** : extracteur API pour intégrer dans la phase pipeline. Le CSV reste pour bootstrap / catch-up massif occasionnel mais sort du workflow régulier.

5. **ROR — comment alimenter** — **tranché** : exclusivement via `ids.ror` retourné par OpenAlex Publishers (= identifiant déjà résolu par OpenAlex, fiable). **Pas de matching par nom** (trop fragile). Pour les publishers sans `openalex_id`, le ROR reste NULL et le typage reste manuel.

6. **Mapping ROR `types` → notre `publisher_type`** — **à figer à l'audit** : proposition de départ ci-dessous, à valider sur l'échantillon réel (Phase 3).
   | ROR | publisher_type |
   |---|---|
   | `Company` | `commercial` |
   | `Education` | `academic_institution` |
   | `Government` | `academic_institution` |
   | `Archive` | `repository` |
   | `Nonprofit` | _à arbitrer_ — PLOS et eLife sont Nonprofit mais sentent le commercial en pratique |
   | `Facility` / `Healthcare` / `Other` | NULL (skip) |

7. **Politique d'écrasement** — **tranché** : sur tous les sub-steps d'enrichissement, écraser uniquement quand la valeur actuelle est NULL ou égale au défaut DB (`'unknown'` pour `publisher_type`, `'journal'` pour `journal_type`). Préserver les valeurs admin explicites. Flag `--force` pour passer outre, comme sur le backfill journal_type.

## Phases

Ordre par dépendance. Les phases 2, 3, 4, 5 sont indépendantes une fois la phase 1 livrée.

- **Phase 1 — Refonte structurelle.** Créer la phase pipeline `publishers_journals`. Déplacer `resolve_doi_prefixes` et `enrich_journal_apc` dedans. `enrich_oa_status` (Unpaywall) reste dans la phase `enrich` (per-publication).
- **Phase 2 — OpenAlex Publishers.** Nouveau sub-step. Lit `publishers.openalex_id`, fetche `/api/publishers/{id}`, pose `country` et `ror`.
- **Phase 3 — ROR → `publisher_type`.** Pour chaque publisher avec `ror` non-NULL, lookup ROR API → `types[0]` → mapping (cf. décision 6). Audit préalable de la distribution.
- **Phase 4 — DOAJ via API.** Extracteur DOAJ par ISSN. Stockage existant (`doaj_payload` JSONB, `doaj_imported_at`). Au passage : capturer l'URL de la fiche DOAJ du journal (typiquement `https://doaj.org/toc/{doaj_id}` ou équivalent à confirmer sur le payload API) pour le **lien depuis le badge DOAJ** (cf. Phase 6).
- **Phase 5 — Crossref Members (fallback `country`).** Pour les publishers sans `openalex_id` mais avec `crossref_member_id` posé par `doi_prefixes`, fetcher `/members/{id}` → parser `location` → ISO-2.
- **Phase 6 — Front : badge DOAJ → lien.** Substitue le badge passif par un lien vers `homepage_url` extrait du `doaj_payload` (Phase 4). Petit chantier UI.
- **Phase 7 — Audit APC OpenAlex vs DOAJ.** Comparer les montants sur les revues présentes dans les 2 sources. Décider si on garde l'APC OpenAlex, on bascule sur DOAJ uniquement, ou on stocke les deux.

## Phase 1 — Refonte structurelle

Livrée le 2026-05-26 (commit `d003bb9e`).

- [x] Créer `application/pipeline/publishers_journals/`.
- [x] Déplacer `application/pipeline/resolve_doi_prefixes.py` dedans.
- [x] Déplacer + renommer `enrich/enrich_journal_apc.py` → `publishers_journals/enrich_journals_from_openalex.py`. Fonction `run_enrich` renommée en `run_enrich_journals_from_openalex`.
- [x] Renommer la phase `enrich` (devenue misnomer) en `oa_status`. Module déplacé `enrich/enrich_oa_status.py` → `oa_status/run.py`. Fonction `run_enrich` → `run_enrich_oa_status`.
- [x] `run_pipeline.py` : registre PHASES mis à jour. `publishers_journals` remplace `resolve_doi_prefixes` au top-level ; `oa_status` remplace `enrich`. `phase_publishers_journals` orchestre les 2 sub-steps.
- [x] Adapter `application/pipeline/modes.py` : `run_enrich: bool` → `run_oa_status: bool` (gate phase Unpaywall). Ajout `run_journal_enrichment: bool` (gate le sub-step OpenAlex Sources dans `publishers_journals`). `resolve_doi_prefixes` tourne sans gate dans tous les modes (comportement préservé).
- [x] CLI entry-points synchronisés (`enrich_journal_apc.py` → `enrich_journals_from_openalex.py` ; imports updatés sur `enrich_oa_status.py` et `resolve_doi_prefixes.py`).
- [x] Imports synchronisés sur le oneshot `backfill_journal_types_from_openalex.py` et les tests (`test_enrich_oa_status_async.py`, `test_resolve_doi_prefixes.py`).
- [x] `pyproject.toml` : override mypy `application.pipeline.enrich.*` remplacé par les 2 nouveaux paths (tolérance JSON OpenAlex préservée).

## Phase 2 — OpenAlex Publishers

Livrée le 2026-05-26.

- [x] **Audit avant écriture** : 13.6% des publishers ont `openalex_id` non-NULL (26.7% des publishers actifs). Sous le seuil de 50% qu'on s'était fixé. Tentative de raccourci via `host_organization` retourné par OpenAlex Sources sur les journals → **abandonnée** : sur 664 publishers candidats, seuls 19 `safe` (3%), 205 `conflict` (= doublons locaux à fusionner), 25 `multi_host`, 415 `no_host` (OpenAlex ne lie pas la source à un Publisher). Décision : exécuter Phase 2 sur l'existant (les ~1006 publishers déjà OA) et **ouvrir deux chantiers séparés à terme** :
  - **Dédoublonnage publishers** : les 205 conflicts dévoilés par l'audit (script `interfaces/cli/oneshot/audit_publisher_openalex_via_journals.py`) sont une borne basse du nombre de doublons à fusionner via l'UI admin existante.
  - **Matching openalex_id par nom** : pour les publishers sans openalex_id (et dont OpenAlex possède bien l'entité Publisher), via `/publishers?search=`. Pas dans le scope de cette fiche — chantier risqué (validation manuelle requise).
- [x] **Migration Alembic** : `publishers.country` était déjà présent. Ajout de `publishers.ror text` via `a1b3c7d9e2f4_publishers_add_ror.py`. La contrainte UNIQUE initialement posée a été retirée par `c5d7e9f1a3b5_publishers_drop_ror_unique.py` après constat à l'usage qu'OpenAlex Publishers attribue parfois le même ROR à plusieurs entités distinctes (cas hiérarchique ou entités IRL distinctes type `CNRS Editions` vs `CNRS`). Le partage de ROR n'est pas un signal fiable de doublon — diagnostic différé au chantier de dédoublonnage. Plumbing complet : `domain.Publisher` (dataclass), `PublisherUpdateFields` (TypedDict), `_PublisherRow`, `find_by_id`, `merge_publisher_into`, DTOs `PublisherListItem` / `PublisherDetailResponse`.
- [x] **Sub-step `enrich_publishers_from_openalex`** : `application/pipeline/publishers_journals/enrich_publishers_from_openalex.py`. Itère sur `publishers.openalex_id IS NOT NULL AND (country IS NULL OR ror IS NULL)`, batch via filtre OpenAlex `ids.openalex:|` (l'API Publishers n'accepte pas le filtre `openalex:` simple comme l'API Sources). Écrit `country` (depuis `country_codes[0]`) et `ror` (depuis `ids.ror` parsé en short form). Politique d'écrasement « NULL only » : préserve les valeurs admin explicites.
- [x] **Branchement** : `phase_publishers_journals` appelle `_run_enrich_publishers_from_openalex` après `_run_enrich_journals_from_openalex`, gated par `MODES[mode].run_journal_enrichment` (= mode `full` uniquement, comme l'enrichissement journaux).
- [x] **CLI** : `interfaces/cli/pipeline/enrich_publishers_from_openalex.py` (--limit / --dry-run). Pas de script oneshot de backfill jugé nécessaire — la condition d'éligibilité `country IS NULL OR ror IS NULL` couvre déjà tous les publishers en première run après migration, et les re-runs ciblent automatiquement ceux pour qui le fetch a échoué.

## Phase 3 — ROR → publisher_type

Livrée le 2026-05-26.

- [x] **Audit préalable** (`audit_ror_types_for_publishers`) sur 393 publishers avec ROR. Distribution :
  - `education[+funder]` (182) → `academic_institution`
  - `funder+nonprofit` (50) + `nonprofit` seul (21) → `learned_society` (amalgame assumé : sociétés savantes ACM/IEEE + éditeurs nonprofit eLife/BioOne)
  - `company[+funder]` (39) → `commercial`
  - `archive[+facility]` (5) → `repository`
  - `government[+funder]` (14), `facility[+funder]` (34), `other[+funder]` (46), `healthcare[+funder]` (2) → **skip** (laissé `unknown` pour arbitrage manuel). `government` exclu car European Commission / CDC / Académies nationales ne sont pas des academic_institution.
  - Couverture : ~76% (297/393).
- [x] **Mapping figé côté domain** : `domain.publishers.publisher.map_ror_types`. Pas d'API ROR bulk endpoint (1 req par publisher), `ROR_DELAY=0.15` (= 6.66 req/s, sustained limit ROR).
- [x] **Fetcher infrastructure** : `infrastructure.sources.ror.fetch_ror_record` + `build_ror_user_agent`. Endpoint `/v2/organizations/{ror}` ; pas de retry élaboré (audit + skip si fail).
- [x] **Sub-step `enrich_publishers_from_ror`** : itère sur `publishers.ror IS NOT NULL AND publisher_type='unknown'`. Politique « unknown only » (préserve les valeurs admin explicites). Fetcher injecté pour respecter l'étanchéité DDD (application n'importe pas infrastructure).
- [x] **Branchement** : `phase_publishers_journals` appelle `_run_enrich_publishers_from_ror` après `_run_enrich_publishers_from_openalex` (consomme `publishers.ror` posé en Phase 2). Gated par `MODES[mode].run_journal_enrichment`.
- [x] **CLI** : `interfaces/cli/pipeline/enrich_publishers_from_ror.py` (--limit / --dry-run).

## Phase 4 — DOAJ via API

Livrée le 2026-05-26.

- [x] **Décision format payload** : mapper API → format CSV (clés du dump historique) plutôt que stocker l'API brute. Choix non orthodoxe assumé (cf. [docs/sources/10-doaj.md](../sources/10-doaj.md)) — préserve le front (`READABLE_DOAJ_FIELDS` qui hardcode les clés CSV), l'audit Phase 7 (`doaj_payload->>'APC amount'`), et la cohérence avec le bootstrap CSV qui reste fonctionnel. Une seule clé ajoutée vs CSV : `"DOAJ id"` (pour reconstruire l'URL fiche en Phase 6). Divergences API/CSV conservées : `Country of publisher` reste l'ISO-2 brut, `Languages…` reste les codes ISO-639-1.
- [x] **Extracteur API** : `infrastructure/sources/doaj/__init__.py` — `fetch_doaj_journal(issn, ...)` sur `GET https://doaj.org/api/search/journals/issn:{issn}` (wrapper `{total, results[]}`), polite pool via User-Agent (mailto). Mapper pur `to_csv_shape(record) → dict[str, str]`, tests unit dans `tests/unit/infrastructure/sources/test_doaj.py`.
- [x] **Sub-step `enrich_journals_from_doaj`** : `application/pipeline/publishers_journals/enrich_journals_from_doaj.py`. Itère sur les revues avec au moins un ISSN, essai successif `issn` → `eissn` → `issnl` (dédup + skip NULL), 1 à 3 requêtes / revue. Fetcher + mapper injectés (étanchéité DDD).
- [x] **Politique de rafraîchissement (stale-based)** : query `fetch_journals_needing_doaj_fetch(stale_days)` filtre `doaj_imported_at IS NULL OR doaj_imported_at < now() - make_interval(days => :stale_days)`. Défaut 30 j. Sur 404, `imported_at` est posé quand même (`payload=NULL`, `is_in_doaj=FALSE`) pour éviter de retenter les ~12 k revues hors-DOAJ à chaque pipeline. Pas de reset global (incrémental).
- [x] **Branchement pipeline** : `phase_publishers_journals` appelle `_run_enrich_journals_from_doaj` après `_run_enrich_journals_from_openalex` (DOAJ direct surclasse le `is_in_doaj` posé par OpenAlex), avant les sub-steps publishers. Gated par `MODES[mode].run_journal_enrichment`.
- [x] **CLI** : `interfaces/cli/pipeline/enrich_journals_from_doaj.py` (--limit / --stale-days / --dry-run).
- [x] **Catch-up CSV** : `interfaces/cli/imports/import_doaj_csv.py` reste utilisable pour bootstrap. Même format de stockage → pas de conflit. Doc 09-imports-manuels.md mise à jour pour rediriger vers la nouvelle fiche 10-doaj.md.

## Phase 5 — Crossref Members (fallback country)

Livrée le 2026-05-26.

- [x] **Audit préalable** (`audit_crossref_member_countries`) sur 1219 publishers sans `country` après Phase 2 et avec un `doi_prefixes.crossref_member_id` : **1162 / 1219 = 95% mapped**. C'est plus du double de la couverture Phase 2 (568 countries via OpenAlex). 56 `no_match` correspondent à des locations dégénérées (Crossref n'inclut pas le pays au bout : "Yerevan, AM", "Patiala, Punjab") ou à des formes absentes de `country_name_forms` (`Hong Kong SAR China`).
- [x] **Parseur domain** : `domain/publishers/crossref_location.py:parse_country_segment` (extraction du dernier segment de "City, State, Country"). Tests unit dans `tests/unit/domain/publishers/test_crossref_location.py`.
- [x] **Fetcher infrastructure** : `infrastructure/sources/crossref/members.py:fetch_crossref_member`. Endpoint `api.crossref.org/members/{id}`, polite pool via header `User-Agent` (cohérent avec les autres clients Crossref du projet).
- [x] **Sub-step `enrich_publishers_from_crossref_members`** : itère sur les candidats, fetche, parse, résout en ISO-2 via la table `country_name_forms` (chargée en bloc au démarrage). Politique « NULL only » garantie par le filtre côté query. Fetcher injecté pour respecter l'étanchéité DDD.
- [x] **Port + query** : `EnrichQueries.fetch_publishers_needing_country_from_crossref` (publisher_id + min(crossref_member_id) ; déterministe en cas de plusieurs members par publisher).
- [x] **Branchement pipeline** : `phase_publishers_journals` appelle `_run_enrich_publishers_from_crossref_members` après OpenAlex Publishers et avant le typage ROR. Gated par `MODES[mode].run_journal_enrichment`.
- [x] **CLI** : `interfaces/cli/pipeline/enrich_publishers_from_crossref_members.py` (--limit / --dry-run).
- [ ] **TODO connexe — enrichir `country_name_forms`** : 56 cas no_match dans l'audit (Hong Kong SAR China, Punjab, Yerevan, Dhaka, Nairobi, etc.). Soit ajouter les formes manquantes, soit améliorer le parseur (détecter les villes/régions sans pays). Hors-scope cette fiche, à juger selon le volume résiduel.

## Phase 6 — Front : badge DOAJ → lien vers la fiche DOAJ

Livrée le 2026-05-26.

- [x] **Exposition côté DTO** : `doaj_url: str | None` ajouté à `JournalOut` ET `JournalDetailResponse` (les deux pages où le badge est affiché). Calculé côté backend via `infrastructure.sources.doaj.build_doaj_toc_url` à partir de `doaj_payload->>'DOAJ id'`. Null quand le payload n'a pas la clé (cas import CSV bootstrap, ou `is_in_doaj=TRUE` posé par OpenAlex Sources sans fetch DOAJ direct).
- [x] **Format URL** : `https://doaj.org/toc/{id}` (la fiche DOAJ canonique), pas la homepage de la revue.
- [x] **Badge cliquable + fallback** : `journals/[id]` (header) et `JournalsListView` (cellule titre). Quand `doaj_url` est posé : `<a class="badge-doaj" href={...} target="_blank" rel="noopener">` ; sinon fallback sur l'ancien `<span>` (badge non cliquable, infobulle « Indexée dans DOAJ »). Style préservé, ajout `text-decoration: none` + hover plus foncé.
- [x] **Hors scope vs fiche initiale** : `admin/journals` n'a en réalité pas de badge DOAJ (juste une checkbox d'édition) — la fiche se trompait sur ce point, rien à patcher.
- [x] **Tests** : 3 tests intégration dans `test_journals_api.py` (DOAJ id présent → URL ; payload sans la clé → null ; listing aussi exposé).

## Phase 7 — Audit APC OpenAlex vs DOAJ

Audit livré le 2026-05-26.

- [x] **Script d'audit** : `interfaces/cli/oneshot/audit_apc_openalex_vs_doaj.py`, lecture pure. Parse les deux formats de payload DOAJ coexistant en base (format API Phase 4 : `{"APC amount": "2477", "APC currency": "USD"}` séparés ; format CSV récent : `{"APC amount": "3390 EUR; 4090 USD; 2990 GBP"}` composite multi-devises, plus de clé `APC currency`).

### Rapport (run du 2026-05-26 après import CSV bootstrap, avant que Phase 4 ait tourné)

Sur **1015 revues candidates** (APC OpenAlex non-null + payload DOAJ avec `APC amount`) :

| Catégorie | N | % |
|---|---|---|
| `comparable` (devise OA présente côté DOAJ) | 908 | 89% |
| `no_overlap` (devise OA absente des devises DOAJ) | 107 | 11% |
| `doaj_unparseable` | 0 | 0% |

Distribution des écarts relatifs (sur les 908 comparables, |OA − DOAJ| / max) :

| Bucket | N | % cumulé |
|---|---|---|
| identical (=0%) | 132 | 14.6% |
| ≤ 1% | +2 | 14.8% |
| ≤ 5% | +42 | 19.4% |
| ≤ 10% | +56 | 25.6% |
| ≤ 20% | +206 | 48.3% |
| ≤ 50% | +432 | 95.9% |
| > 50% | +37 | 100% |

Médiane = **20.8%**, p90 = 41.1%, p99 = 71.8%. Écart absolu moyen ≈ **566 €**.

**Pattern net** : OpenAlex sous-estime systématiquement (top 10 divergences : OA = 1/4 à 1/5 du montant DOAJ). Exemples :

- `Journal of Advanced Research` (Elsevier) : OA = 1200 USD vs DOAJ = 4400 USD
- `Case Studies in Construction Materials` : OA = 600 USD vs DOAJ = 2990 USD
- `Pharmacia` : OA = 100 EUR vs DOAJ = 800 EUR

Hypothèse : OpenAlex Sources stocke des montants obsolètes ou catégoriels (correspondence vs research article).

### Décision

**OpenAlex Sources écarté comme source APC de confiance.** Cible visée : DOAJ prioritaire, fallback OpenAlex pour les ~2 300 revues hors-DOAJ qui ont un APC OA — solution **explicitement bancale** assumée à court terme.

État actuel inchangé pour cette fiche : `journals.apc_amount` reste écrit par `enrich_journals_from_openalex`, le DTO le retourne tel quel. La bascule effective vers le fallback DOAJ et le retrait propre de l'APC OpenAlex sont reportés à un mini-chantier dédié (cascade complexe : adapter le sub-step OA, remplacer le filtre d'idempotence `apc_amount IS NULL` qui sert aujourd'hui à éviter le re-fetch perpétuel, gérer le wipe + repompage depuis `doaj_payload` des 3 309 valeurs déjà en base).

### Question ouverte

Trouver une source APC plus fiable que OpenAlex pour les revues **hors-DOAJ** (= ~2 300 revues couvertes uniquement par OA aujourd'hui). Pistes à explorer : OpenAPC (déjà utilisé pour les paiements UCA, cf. `docs/sources/09-imports-manuels.md`), CWTS Open APC, scraping des fee pages éditeur. Sans meilleure source, la bascule DOAJ-only sacrifierait cette couverture.

## Phase 8  — Documentation
- [ ] **Documentation pipeline**: ajouter et documenter la phase publishers_journals.
- [ ] **Documentation sources**: ajouter les nouvelles sources moissonnées.

## Questions ouvertes

- **`parent_publisher` d'OpenAlex** : faut-il consolider automatiquement les filiales sous le parent ? Risque de fusion abusive (BMC ≠ Springer Nature en pratique éditoriale). À reposer si on observe des problèmes de hiérarchie à l'usage.
- **Sources `country` d'OpenAlex sur les journals** : OpenAlex Sources retourne aussi un `country_codes` pour les journals. Diverge parfois du publisher (revue éditée par filiale dans un pays différent). À exploiter ? Hors-scope cette fiche.
- **Mapping ROR `Nonprofit`** : à figer après audit Phase 3 (PLOS / eLife / Hindawi sont les cas litigieux).
- ~~**Modes pipeline**~~ — **tranché Phase 1** : `phase_publishers_journals` tourne dans tous les modes (comme `resolve_doi_prefixes` historiquement). Le sub-step `enrich_journals_from_openalex` est gated par `MODES[mode].run_journal_enrichment` (True en `full` uniquement, comme l'était `run_enrich` historiquement pour le journal_apc).

## Chantiers connexes à ouvrir

Sortis du scope cette fiche après l'audit de Phase 2 :

- **Dédoublonnage publishers** : l'audit `audit_publisher_openalex_via_journals` a révélé au moins 205 doublons potentiels (publishers locaux distincts dont les journaux pointent vers le même `host_organization` OpenAlex, déjà attribué à un autre publisher local OA-typé). À fusionner via l'UI admin existante.
- **Matching openalex_id par nom** : pour les publishers actifs sans openalex_id (et dont OpenAlex Publishers possède bien l'entité), via `/publishers?search=<name>`. Validation manuelle requise — chantier risqué.

## Liens

- [METIER_publishers-journals.md](METIER_publishers-journals.md) — fiche d'origine (typage, biblio, DOAJ CSV, UI publique). Cette nouvelle fiche prolonge la décision Phase 2 « refonte gardée ouverte » côté **enrichissement** (l'entité-création reste où elle est).
- [METIER_doi-ra-datacite.md](METIER_doi-ra-datacite.md) — `doi_prefixes` consommé par Phase 5 (crossref_member_id).
- [METIER_doc-types.md](METIER_doc-types.md) — Phase 4b cohérence `doc_type` ↔ `journal_type`, alimentée indirectement par cette phase via `journal_type` correctement rempli.
