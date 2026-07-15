# Lisibilité

## Contexte

Objectif : réduire la complexité inutile et organiser la complexité nécessaire pour qu'un développeur extérieur comprenne le code rapidement. Le critère de réussite est qu'un dossier, un module ou une fonction s'explique à quelqu'un qui découvre le projet, sans détour par l'histoire du code.

Méthode : dossier par dossier, module par module, sans ordre imposé. Cette passe précède les analyses transversales par fonctionnalité ou par agrégat, qui viendront ensuite s'appuyer sur un terrain déjà assaini. Au fil des passes, les problèmes repérés mais laissés à plus tard sont notés dans le Phasage à l'emplacement qui correspond à leur place dans l'arborescence, pour ne pas les perdre.

Leviers mobilisés selon les cas : réécriture, suppression ou factorisation de code ; réorganisation de l'arborescence ; réécriture de docstrings et de commentaires. On supprime au passage, systématiquement, les retours à la ligne non sémantiques dans les docstrings (chaque paragraphe s'écrit d'un trait), qui gênent la lecture en écran divisé.

Garde-fous : import-linter (contrats de couches), mypy, ruff et pytest restent verts de bout en bout. Toute réorganisation d'arborescence est mécanique et réversible, guidée par ces filets.

## Décisions

### `application/` — aligner le sommet sur un seul axe

Le sommet de `application/` mélange deux axes de classification : des subdivisions techniques (`ports/`, `pipeline/`) et des dossiers par agrégat du domaine, tous de forme identique (`commands.py` pour les command handlers d'écriture API, `core.py` pour les briques transaction-agnostiques réutilisées par le pipeline, les CLI et l'API). On regroupe l'axe par-agrégat pour rendre le sommet homogène.

- Les neuf services d'agrégat — `addresses`, `authorships`, `config`, `journals`, `perimeters`, `persons`, `publications`, `publishers`, `structures` — passent sous `application/services/`. « Application services » est le terme consacré pour cette couche.
- `ports/` et `pipeline/` restent au sommet : ce sont des subdivisions techniques, et `pipeline` est un sous-système nommé à part entière, avec sa propre structure interne.
- `application/observability/` (vide) est supprimé.
- `application/audit.py` reste au sommet : c'est une préoccupation transverse et technique (journalisation des opérations destructives dans `audit_log`), pas un agrégat. Il est renommé `audit_log.py` pour lever la confusion avec les scripts d'inspection `interfaces/cli/oneshot/audit_*.py`, qui portent le même mot dans un sens différent (inspecter une donnée, non journaliser un événement).
- `application/publishers_enrichment/` est fondu dans l'agrégat publishers, sous `services/publishers/enrichment/`. Tous les CLI de maintenance délèguent leur logique à `application.<agrégat>` ; ce package à plat était le seul orphelin de ce patron. Son port `ports/publishers_enrichment.py` est conservé — dès que la logique vit dans `application/`, la couche interdit d'y toucher `infrastructure` en direct, donc le port n'est pas spéculatif — et sa place au sein de `ports/` se décide lors de la passe dédiée.

Cible :

```
application/
  ports/
  pipeline/
  services/
    addresses/  authorships/  config/  journals/  perimeters/
    persons/  publications/  publishers/  structures/
  audit_log.py
```

### Scinder le contrat des règles de correction de sa projection de lecture

`SourcePublicationForCorrection` (`domain/source_publications/correction.py`) confond deux choses. Elle est construite par splat positionnel — `SourcePublicationForCorrection(*row)` — depuis le `_SELECT` de `infrastructure/queries/pipeline/metadata_correction.py` : ses 19 champs et leur ordre sont les colonnes de ce SELECT. C'est une projection de lecture de la phase `metadata_correction`, et c'est la seule de cette phase à vivre hors du port `application/ports/pipeline/metadata_correction.py`, où logent ses cinq homologues (`DoiClusterRow`, `JournalByDoiRow`, `CorrectionUpdate`, `DoiCorrectionUpdate`, `JournalCorrectionUpdate`). C'est aussi, par ailleurs, le contrat d'entrée de `effective_metadata`, fonction pure du domaine.

De cette confusion découlent les deux symptômes. Cinq champs (`source_id`, `pub_year`, `container_title`, `language`, `apc_amount`) sont sélectionnés en SQL, portés par la dataclass, et lus par personne. Et le second appelant, `_apply_canonical_doc_type_correction`, doit se faire passer pour une ligne du SELECT : il invente `id=pub.id or 0`, `source="canonical"`, `source_id=str(pub.id)` et six autres valeurs de remplissage.

On sépare les deux. Le contrat des règles reste dans `domain/`, réduit aux dix champs que les prédicats d'`_AppliesTo` lisent (`title`, `doc_type`, `doi`, `journal_id`, `oa_status`, `journal_type`, `oa_model`, `urls`, `embargo_expired`, `self_declared_preprint`) : c'est la signature d'une fonction pure qui encode des règles métier. La projection de ligne descend dans le port auprès de ses homologues, garde le couplage à l'ordre du SELECT — local au port et à son adapter — porte les quatre champs que la phase seule utilise (`id` pour persister, `source` pour `map_doc_type`, `external_ids` et `raw_metadata` pour le stash et l'hydratation), et se projette vers le contrat du domaine.

**Périmètre de la correction canonique.** La correction de métadonnées est l'affaire des `source_publications`. Son extension à la publication canonique traite un cas précis : l'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne, donc deux champs d'une même publication peuvent venir de deux sources et former une combinaison qu'aucune source ne portait. Le cas d'école est `THESIS_WITH_JOURNAL_TO_ARTICLE` : `doc_type` = `thesis` de theses.fr, `journal_id` de Crossref. D'où la règle de rejouabilité : une règle se rejoue sur la publication si et seulement si ses prédicats lisent des champs que l'agrégation arbitre.

- `urls` et `self_declared_preprint` sont des faits d'un enregistrement source, sans contrepartie canonique : les règles qui les lisent ne se rejouent pas.
- Aucune règle d'`oa_status` ne se rejoue, `oa_model` reste donc hors du contrat canonique. Une correction d'`oa_status` appliquée sur une `source_publication` remonte d'elle-même : l'agrégation retient le statut le plus ouvert, et `best_oa_status` classe `gold` au-dessus de `hybrid` comme `green` au-dessus de `closed`. Le rejeu canonique n'ajoute rien et se heurterait à l'autorité d'Unpaywall, que l'agrégation protège dès que `unpaywall_checked_at` est posé. Vaut pour `HYBRID_FULL_OA_TO_GOLD` comme pour `EMBARGO_EXPIRED_TO_GREEN`.

La frontière tient donc à un principe unique : le rejeu canonique répare les combinaisons de champs nées de l'arbitrage, sur les champs dont la valeur canonique est un arbitrage — pas sur ceux qu'une source atteste seule, ni sur ceux qu'une autorité externe tranche.

**Nommage.** `declares_preprint` vaut `jsonb_exists(sp.meta->'relation', 'is-preprint-of')` : l'enregistrement déclare être le preprint d'une autre œuvre. Le nom se lit « déclare avoir un preprint », qui est le sens inverse — et cette clé existe, `has-preprint`, mappée en `HAS_PREPRINT` dans `domain/publications/relations.py`. Renommé `self_declared_preprint`.

## Phasage

### Phase 1 - `application/`

Réorganisation du sommet :

- [x] Supprimer `observability/` (vide).
- [x] Créer `application/services/` et y déplacer les neuf agrégats (`ec5c7879`).
- [x] Renommer `audit.py` → `audit_log.py` (`5b96b61f`).
- [x] Fondre `publishers_enrichment/` dans `services/publishers/enrichment/` (`7a14b517`). Le port reste à `ports/publishers_enrichment.py` ; son placement se décide en 1.2.
- [ ] Passe docstrings du dossier : retours à la ligne non sémantiques, formulations, présent intemporel.

#### 1.1 - `application/pipeline`

16 phases (`PHASE_ORDER`) pour 14 dossiers, écart réconcilié :

- [x] `resolve_ra` sorti de `publishers_journals/resolve_doi_prefixes.py` vers `pipeline/resolve_ra/run.py` ; volet publisher isolé en `publishers_journals/resolve_publishers.py` (`bd6f5061`).
- [x] `cooccurrences` (sous-étape de `subjects`, absente de `PHASE_ORDER`) nichée en `pipeline/subjects/cooccurrences.py` (`b7dfbaa6`).
- `refresh_stale` et `refetch_truncated` restent dans `extract/` (opérations d'extraction) — cohérent, statu quo.
- [x] `normalize/base.py` : argparse vestigial (`--limit`/`--reset`/`--batch-size`, `run(argv)`) retiré, avec le mécanisme `--reset` mort en production — port `reset_processed_flag` et impl compris ; la re-normalisation passe par le re-import `raw_hash=null` (`de2a86ef`). `extract/base.py` n'était pas concerné : son `args` est un `Namespace` construit par l'orchestrateur, pas un parsing CLI.
- [x] `pipeline/persons/` : cascade refondue (découpe de `cascade.py`, une seule cascade pour match/create, gate méga-paper supprimé, cross-source incrémental, `reset` renommé `arbitrate_identifier_conflicts`) — fiche dédiée `archived/2026-07-12_CODE_phase-persons.md`.
- [x] `pipeline/subjects/` : ingestion et modèle dégraissés (mots-clés libres sortis, `ontologies` et `score` supprimés, cinq ingestors → cinq extracteurs purs) — traité par la fiche dédiée `archived/2026-07-12_CODE_simplification-sujets.md`.
- [x] Plomberie async factorisée : les quatre orchestrateurs à interrogation externe (cross-import HAL, cross-import DOI, re-fetch des works tronqués, refresh du stale) partagent `application/pipeline/_fetch_pool.py` (`run_fetch_pool` : pool de workers, écritures sérialisées, commit par lot). Retire au passage la barrière du gather-par-paquet de `refetch_truncated` (`18f3a7cd`, `23e46131`).
- [x] Sélection des sources cibles factorisée (`select_targets` dans `signals.py`) : `refresh_stale` et `cross_imports` partageaient le même prologue avant `filter_configured` (`5869d731`).
- [x] `cross_imports` : commit du cross-import DOI rendu à l'orchestrateur applicatif — les six adapters `fetch_missing_doi` committaient dans l'infra (`84b8bd6e`) ; sélection des cibles DOI clarifiée (`a5e4a3e6`).
- [x] `refetch_truncated` : params morts (`dry_run`/`limit`) et log de fin redondant retirés (`19dacfc8`).
- [x] `extract` : boilerplate des cinq extracteurs remonté dans `SourceExtractor` (2ᵉ générique `AdapterT`, helper `_stop_on_tripped`), sélection des sources simplifiée (`67bbc23f`, `607b547f`). L'asymétrie WoS ajouté (`extract`, base = sources par défaut du mode) vs soustrait (`refresh_stale`/`cross_imports`, base = registre exhaustif) est conservée : la règle opt-in est la même, seule la base diffère de nature.
- [x] `metadata_correction` : loop de persistance par lots factorisé (`persist_in_batches` dans `_persist.py`, interne au package), une seule constante de taille de lot au lieu de trois (`aa87af36`).

#### 1.2 - `application/services`

- [ ] `persons/core.py` : `import_authenticated_orcids` est une opération d'ingestion (lecture d'ORCID authentifiés depuis une source externe pour les injecter) logée dans le référentiel d'écriture de l'agrégat, où elle détonne. À requalifier.
- [x] `publishers/enrichment/` : sous-package (réduit à un seul module) aplati en module plat `enrich_country.py` ; payload OpenAlex typée + boucle par batch extraite dans `_enrich_batch` → exceptions `ruff C901` et override mypy `disallow-any` retirées (`0a8f95f8`).
- [ ] `commands.py` : l'alias d'import du module `core` diffère d'un service à l'autre (`structures_service`, `journals`, `publications_service`, `publishers`). Harmoniser sur une convention unique.
- [ ] `publications/core.py` (`_apply_canonical_doc_type_correction`) : vue de correction — voir *Scinder le contrat des règles de correction de sa projection de lecture* en Décisions, et le phasage en 1.2.1.
- [x] `publications/core.py` (`merge_publications`) : chemin de fusion et règle `absorb` — traité par la fiche dédiée `archived/2026-07-12_CODE_merge-publications.md`.
- [x] `publications/core.py` : passe docstrings. Le module revendiquait un accès exclusif en écriture démenti par le pipeline, qui appelait `pub_repo.create` en direct — seul `repo.create` de la couche application à court-circuiter son service, là où les phases `persons` et `normalize` passent par `create_person` et `find_or_create_journal`. `create_publication` porte les valeurs de semis (`title` = titre normalisé, `doc_type` à `other`, `oa_status` par défaut) ; `repo.create` perd `journal_id`, `container_title` et `language`, que tous ses appelants fixaient à `None` (`abed5138`, `6bfbf94a`).

##### 1.2.1 - Vue de correction des métadonnées

Traverse `domain/`, `application/ports`, `application/pipeline/metadata_correction` et `infrastructure/queries` : le service publications n'en est que le symptôme visible.

- [x] Contrat des règles (`MetadataForCorrection`) réduit aux dix champs lus, dans `domain/source_publications/correction.py` (`71337ec6`).
- [x] Projection de ligne de la phase (`UnaryCorrectionRow`) déplacée dans `application/ports/pipeline/metadata_correction.py` ; les cinq champs morts sortent du `_SELECT` et des deux types (`71337ec6`).
- [x] `declares_preprint` → `self_declared_preprint` (`71337ec6`).
- [x] Appariement des lignes par nom plutôt que par rang, qui supprime le couplage entre l'ordre des champs et celui des colonnes (`b229c3ed`). Le reste du motif est noté en 2.6 et 2.7.
- [x] `_apply_canonical_doc_type_correction` construit le contrat sans valeurs inventées (`71337ec6`). L'`oa_status` sort du contrat canonique en entrée comme en sortie : les deux seules règles qui le lisent sont celles qui le corrigent, et aucune règle de `doc_type` ne le lit.
- [x] Rejouabilité au niveau canonique rendue structurelle. `_SOURCE_ONLY_PREDICATES` nomme les trois prédicats portant sur un fait propre à un enregistrement source ; `effective_doc_type_for_publication` écarte les règles qui en lisent un, sans les évaluer. L'exclusion tenait auparavant aux valeurs de remplissage du call site, et ne fonctionnait que parce que chaque prédicat concerné exige un signal **positif** : une règle de `doc_type` gardée par la forme négative (`embargo_expired: False` — la forme existe, cf. `journal_id_present: False`) se serait vérifiée à tort sur le canonique, en silence. La liste porte sur les **prédicats**, non sur les règles : elle décrit la forme du contrat, et ne bouge qu'à l'ajout d'un champ propre aux sources, quand une liste de règles aurait été à réviser à chaque règle ajoutée.

#### 1.3 - `application/ports`

- [ ] Placement du port `publishers_enrichment.py`, aujourd'hui à plat sous `ports/` (comme `config.py`). Sa place définitive se tranche en réorganisant `ports/`.
- [ ] `ports/pipeline/enrich.py` (`EnrichQueries`) : port grab-bag hérité de la phase monolithique `enrich`, depuis scindée en `oa_status` + `publishers_journals`. Il regroupe deux familles de requêtes disjointes (publications OA vs journaux/DOAJ) ; chaque phase tire des méthodes qu'elle n'utilise pas (violation d'*Interface Segregation*). À scinder en deux ports étroits — l'impl `PgEnrichQueries` implémentant les deux, ou se scindant elle aussi. Le nom `EnrichQueries` disparaît avec.

### Phase 2 - `infrastructure/`

#### 2.1 `db` : OK
#### 2.2 `jsonb_models` : OK
#### 2.3 `raw_store` : OK
#### 2.4 `observability` : OK

#### 2.5 `sources`

Racine (transverse) : passe docstrings/commentaires faite. Findings structurels remontés à la relecture :

- [ ] `common.py` — fourre-tout à éclater par préoccupation (ses voisins sont nommés par concern) : `staging.py` (écriture staging + hash), `cross_import.py` (pool DOI cross-import), et repli de la sélection stale dans/à côté de `refresh_stale_base.py`. `common.py` disparaît.
- [ ] `http_retry.py` + `http_retry_async.py` — factoriser la logique de décision pure (backoff, classification 429/4xx/5xx/body vide, règles breaker) ; les deux boucles d'I/O minces (sync `requests` / async `httpx`) cohabitent dans un seul fichier.
- [ ] `_API_BASE_URLS` (+ `get_api_base_urls`) sort de `config.py` vers un module dédié `api_urls.py` : ni des limites, ni de la config d'environnement.
- [ ] Un dossier par source : `ror.py`, `unpaywall.py` et le code de `doaj/__init__.py` passent en `<source>/client.py` (+ `__init__` mince). Racine = transverse seulement.
- [ ] Renvoi périmé : `openalex/__init__.py` prétend que l'URL de base vit en config DB — faux, c'est la constante `_API_BASE_URLS`.

#### 2.6 `queries`

- [ ] Construction des lignes par déballage positionnel (`Row(*row)`) : l'ordre des champs de la classe et celui des colonnes du `SELECT` forment un contrat unique, écrit dans deux couches et vérifié par rien — réordonner l'un sans l'autre range les valeurs dans les mauvais champs, en silence dès que les types sont compatibles. L'appariement par nom (`Row(**row._mapping)`) supprime le couplage et échoue bruyamment sur un nom manquant. Fait pour `UnaryCorrectionRow` ; restent `JournalByDoiRow` et `DoiClusterRow` (`pipeline/metadata_correction.py`).

#### 2.7 `repositories`

- [ ] Même motif de déballage positionnel qu'en 2.6, sur cinq repositories : `_PerimeterRow`, `_PublisherRow`, `_StructureRow`, `_JournalRow`, `_SourcePublicationViewRow`.


### Phase 3 - `interfaces/`

#### 3.1 - API

- [ ] `routers/admin/publication_duplicates.py` : docstrings hard-wrappées. Celle de `merge_duplicate_publications` réexplique le mécanisme du refresh, qui relève de `services/publications`. Le fait qui appartient au router est le choix du survivant (`sorted()`), et l'invariance du sens de fusion qui l'autorise.

#### 3.2 - Frontend

#### 3.3 - CLI

- [ ] CLI `maintenance/` : coquille-ification. `enrich_publishers` séquence ses trois étapes dans son `main()` au lieu de déléguer en un appel à un orchestrateur applicatif, contrairement à ses voisins.
- [ ] `maintenance/merge_publications.py` porte `# STATUS: oneshot` alors qu'il vit dans `maintenance/` et se décrit comme réutilisable (nettoyage en lot) — marqueur à revoir.
- [ ] Passe des CLI `maintenance/` et `oneshot/`.

### Phase 4 - `domain/`

- [ ] `source_publications/correction.py` (680 lignes) porte trois sujets, qui sont les trois sous-étapes de la phase `metadata_correction` — le module le documente déjà (« unaire : `doc_type`/`oa_status`/`external_ids` ; cluster : `doi` ; `journal_by_doi` : `journal_id` ») : le moteur de règles unaire (contrat, table `_RULES`, `effective_metadata`), la correction relationnelle par cluster DOI (`DoiClusterMember`, `resolve_cluster_doi_corrections`, `CONVERGENCE_CASES`), et le rattachement du journal par préfixe DOI (`resolve_journal_by_doi`). Candidat à la scission ; les deux derniers sujets raisonnent sur des `source_publications` et restent en place.
- [ ] Placement du moteur de règles unaire, seul sujet bi-niveau (alimenté par une `source_publication` comme par une publication canonique), à trancher après la scission. À noter : ce n'est pas une question de couches, `publications/` et `source_publications/` s'important déjà mutuellement (`source_publications/doc_types.py` et `keys.py` vers `publications/` ; `publications/aggregation.py` vers `source_publications/`). Aucun cycle créé ni supprimé par un déplacement.

## Questions ouvertes

- **Style de logging incohérent** (transverse). f-string vs `%`-lazy : ~79 occurrences sur 22 fichiers du seul `application/pipeline`, motif probablement plus large. Faible nuisance (le logging de progression et de bilan est une observabilité légitime, feeding `pipeline.log` que l'UI admin ressort par phase). Ne vaut le coup que couplé à un durcissement lint (règles ruff `G`/`LOG`) qui verrouille le style. Hors périmètre de ce chantier ; éventuel chantier dédié.
- **Convention « étape de phase = module »** (transverse). Certaines phases ont une étape numérotée dans leur docstring qui reste un appel inline dans le `phase.py`, alors que les étapes sœurs sont des modules dédiés (ex. l'étape `enforce` de la phase personnes, réduite à un appel `authorship_repo.enforce_confirmed_authorships()`). À trancher globalement : une étape mérite-t-elle toujours son module, ou l'appel inline se justifie-t-il quand elle ne porte pas de logique propre ? Recenser le motif dans les autres phases avant de fixer la règle.
