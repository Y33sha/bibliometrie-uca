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
- `application/publishers_enrichment/` est fondu dans l'agrégat publishers (module `services/publishers/enrich_country.py`). Tous les CLI de maintenance délèguent leur logique à `application.<agrégat>` ; ce package à plat était le seul orphelin de ce patron. Sa lecture — la sélection des éditeurs à enrichir — est un finder de l'agrégat Publisher : elle vit sur `PublisherRepository`, sans port dédié.

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

Un `commands.py` importe le `core` de son agrégat sous l'alias `<agrégat>_service` (`from application.services.journals import core as journals_service`). Le suffixe distingue le module du package homonyme du domaine, et vaut aussi pour le `core` d'un autre agrégat qu'un handler composerait (`authorships/commands.py` appelle `persons_service.create_person`).

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
- [x] Fondre `publishers_enrichment/` dans l'agrégat publishers (`7a14b517`).
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

Passes de relecture des neuf services d'agrégat.

- [x] `addresses` : `structures.py` → `structure_links.py`. Le module gère les rattachements adresse ↔ structure (table `address_structures`), pas des structures ; son nom reprenait celui d'un autre agrégat, d'où le même alias `structures_service` désignant deux modules dans deux `commands.py` voisins. Docstring du package rectifié : il annonçait un VO `Address` inexistant et décrivait le matching du pipeline (phases `affiliations` / `countries`) au lieu de la curation manuelle qu'il porte, en omettant `commands` (`d78e0a43`).
- [x] Docstrings des quatre services qui s'annonçaient « accès exclusif en écriture » (`publications`, `persons`, `journals`, `publishers`) : la formule était recopiée et fausse à la lettre partout. La ligne ne passe pas entre l'API et le pipeline — celui-ci respecte l'exclusivité pour tout l'éditorial (`find_or_create_journal`, `create_person`, `create_publication`, `refresh_from_sources`) — mais entre l'éditorial et le dérivé : `pub_count`, drapeau `is_in_doaj`, formes de nom sont recalculés en bloc, en un ordre SQL (`6bc83de4`).
- [x] Phrase « les lectures restent autorisées dans les routers (convention du projet) » bannie de `config` (deux fois) et `structures` : vestige de l'époque où les routers écrivaient du SQL (`ba891d8e`).
- [x] `perimeters` : le contrat d'édition était déclaré trois fois (`PerimeterUpdate` Pydantic côté API, `PerimeterUpdateFields` TypedDict au port, liste `allowed` en dur au service), et le typage détruit puis ré-affirmé par un `cast` — qui ne vérifie rien : `{"name": 123}` traversait mypy jusqu'à une colonne texte. Aligné sur le motif de `journals` (un modèle Pydantic déclaré une fois au port, partagé du router au repo) ; `.strip()` rendu déclaratif, issue de l'ajout typée en `StrEnum`, paire renommée d'après le repo (`0790a781`).
- [x] `journals` : `requalify_publications_for_journal` chargeait trois fois chaque publication pour compter les `doc_type` qui bougent ; deux relevés encadrant la boucle suffisent. `update_journal_apc` garde son absence de vérification d'existence — justifiée, son appelant boucle sur des ids issus d'une requête — et la docstring le dit (`51178a91`).
- [x] `config` : `update_config_value` sondait la clé avant de l'écrire, parce que l'implémentation finissait par `result.one()`. Le port rend `dict | None`, le service lève `NotFoundError` — une requête au lieu de deux, et l'absence dite dans la signature (`ba891d8e`).
- [x] `authorships` : `assign_orphan_authorship` rendait `False` quand la signature portait déjà une personne ; le command handler jetait ce retour et le router en faisait un 200. Lève `AuthorshipAlreadyAssignedError` (409) ou `NotFoundError` (`b6d9ae53`). Le corps du batch perd sa `source`, que le service ne recevait jamais et qui ne servait qu'à un filtre silencieux (`fdd40b67`).
- [x] Contrôle d'appartenance d'une source mutualisé en `domain/sources/registry.py::require_known_source` : trois endroits, trois messages (`b9857f74`). Il reste appelé par le router, qui ordonne les erreurs — valider le corps avant de lire la base.
- [x] `persons/core.py` : `import_authenticated_orcids` ne lit aucune source externe — elle reçoit des paires `(person_id, orcid)` déjà résolues et normalisées, et applique un statut. Le nom promettait une ingestion que le corps ne fait pas : renommée `authenticate_orcids`. L'ingestion réelle vit dans le CLI, notée en 3.3.
- [x] `publishers/enrichment/` : sous-package (réduit à un seul module) aplati en module plat `enrich_country.py` ; payload OpenAlex typée + boucle par batch extraite dans `_enrich_batch` → exceptions `ruff C901` et override mypy `disallow-any` retirées (`0a8f95f8`).
- [x] `commands.py` : l'alias d'import du module `core` divergeait (cinq en `<agrégat>_service`, deux en nom nu). Harmonisé sur `<agrégat>_service`, la forme majoritaire ; la convention est en Décisions.
- [x] `publications/core.py` (`_apply_canonical_doc_type_correction`) : vue de correction — voir *Scinder le contrat des règles de correction de sa projection de lecture* en Décisions, et le phasage en 1.2.1.
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

- [ ] **Le carton `repositories/` n'obéit à aucun critère.** La doc pose que « chaque repository d'agrégat expose `find_by_id(id) -> Entity | None` qui charge l'*aggregate root* » ; le `__init__.py` du dossier annonce des « agrégats du domaine » et range `Address` et `AuditLog` parmi eux, en oubliant `DoiPrefix`. Or sur dix ports, six seulement hydratent un root ; `audit`, `doi_prefix`, `address` et `authorship` n'hydratent rien — les trois premiers se déclarent d'ailleurs eux-mêmes « accès à la table », et `authorship_repository` se contredit entre son module (« agrégats Authorship ») et sa classe (« tables authorships et source_authorships »), quand la doc classe `Authorship` en entité fille de `Publication`. Le critère « partagé entre contextes » ne recouvre pas davantage le dossier : `address`, `structure` et `perimeter` ne sont jamais importés par le pipeline. Ni celui des écritures : `pipeline/authorships_build.py` et `pub_counts.py` sont des `*Queries` qui écrivent.
  L'axe défendable est « le contrat est le modèle » (un seul, donc partagé) contre « le contrat est une question » (par contexte, d'où `api/` et `pipeline/`). Les quatre intrus, plus `config.py` laissé à la racine faute de boîte, sont le résidu qui fait paraître la taxonomie arbitraire. Cible : `repositories/` réduit aux six vrais, et un carton d'accès table sans modèle pour les cinq autres. Restent à trancher son nom, et le renommage éventuel des classes (`AuditRepository` → `AuditStore`…) — churn large, `AuditRepository` étant importé partout.
- [ ] **Frontière Person / Authorship : à qui appartient `source_authorships.person_id` ?** Six méthodes de `PersonRepository` portent ce lien — `link_authorship`, `unlink_authorship`, `assign_orphan_sa`, `assign_orphan_source_authorships_to_person`, `null_person_id_for_name_form`, et `find_source_authorship_owner` qui le lit. La colonne vit sur `source_authorships`, donc côté Authorship ; mais ce sont des gestes pilotés par la personne. Selon la réponse elles basculent ou restent, et les signatures des services suivent (`link_authorship(..., repo: PersonRepository)` deviendrait `authorship_repo`), avec leurs appelants — cascade du pipeline, command handlers, router, tests. Mécanique et tenue par mypy, mais large. Ce qui écrivait la table `authorships` sans toucher au lien a déjà basculé (`4132786a`).
- [ ] `AuthorshipRepository` recalcule `in_perimeter` à deux granularités : `recompute_authorship_in_perimeter` (par paire publication/personne, action admin) et `recompute_in_perimeter_on_source_authorships` + `propagate_in_perimeter_to_authorships` (par lot d'adresses, après review). Le rapprochement des deux dans le même port (`4132786a`) rend la question visible ; reste à décider si elles fusionnent.
- [x] Port `publishers_enrichment.py` dissous plutôt que placé : sa seule lecture (sélection des éditeurs à `country` absent) est un finder de l'agrégat Publisher, passé sur `PublisherRepository` aux côtés de `find_publisher_by_openalex_id`. Le port à plat et son query service disparaissent ; `enrich_country` ne prend plus qu'un port pour l'agrégat, au lieu de deux en deux styles (`6e97bd27`).
- [x] `ports/pipeline/enrich.py` (`EnrichQueries`) : port grab-bag hérité de la phase monolithique `enrich`, scindé selon ses deux familles disjointes. La moitié OA reste un port de phase, renommée `oa_status.py` / `OaStatusQueries` d'après la phase qui la consomme. La moitié journaux est **dissoute** dans `JournalRepository` plutôt que placée, comme `publishers_enrichment` avant elle (`6e97bd27`) : ses quatre méthodes sont des accès mono-table à `journals`, et ses deux appelants jonglaient avec deux ports du même agrégat en deux styles (`conn` passé vs `conn` lié). Le SQL dupliqué en branches limit / sans-limit se replie sur `.limit(None)`. Les tests suivent la coupure ; leur doublon `test_enrich_queries.py` (deux tests sur le même module) fond dans `test_oa_status_queries.py`.

### Phase 2 - `infrastructure/`

#### 2.1 `db`

- [ ] `alembic check` est rouge : 38 opérations, dont six tables absentes de `tables.py` (`publication_relations`, `pipeline_phase_executions`, `confirmed_authorships`…) et 26 index divergents. Le métadonnée ne décrit pas le schéma. C'est le terrain d'une dérive silencieuse : le seul garde-fou du fichier est un contrôle que personne ne peut passer au vert, donc personne ne le lance — l'enum `source_type` y avait perdu `datacite` sans que rien ne le signale (`e47421a7`). Remettre `alembic check` au vert, puis le brancher en CI.
#### 2.2 `jsonb_models` : OK
#### 2.3 `raw_store` : OK
#### 2.4 `observability` : OK

#### 2.5 `sources`

Racine (transverse) : passe docstrings/commentaires faite. Findings structurels remontés à la relecture :

- [ ] `common.py` — fourre-tout à éclater par préoccupation (ses voisins sont nommés par concern) : `staging.py` (écriture staging + hash), `cross_import.py` (pool DOI cross-import), et repli de la sélection stale dans/à côté de `refresh_stale_base.py`. `common.py` disparaît.
- [ ] `http_retry.py` + `http_retry_async.py` — factoriser la logique de décision pure (backoff, classification 429/4xx/5xx/body vide, règles breaker) ; les deux boucles d'I/O minces (sync `requests` / async `httpx`) cohabitent dans un seul fichier.
- [ ] `_API_BASE_URLS` (+ `get_api_base_urls`) sort de `config.py` vers un module dédié `api_urls.py` : ni des limites, ni de la config d'environnement.
- [ ] Un dossier par source : `unpaywall.py` et le code de `doaj/__init__.py` passent en `<source>/client.py` (+ `__init__` mince). Racine = transverse seulement.
- [ ] Renvoi périmé : `openalex/__init__.py` prétend que l'URL de base vit en config DB — faux, c'est la constante `_API_BASE_URLS`.

#### 2.6 `queries`

- [ ] Motif fonction libre + classe adaptateur qui la délègue. La doc le justifie par la mutualisation entre contextes : le module héberge le SQL en fonctions libres, et plusieurs adaptateurs s'en servent (`subjects.py` expose `PgSubjectsQueries` pour le pipeline et `PgSubjectsAdminQueries` pour l'API). Là où le module n'a qu'un seul adaptateur, la classe se borne à déléguer et ne mutualise rien : `address_pub_count.py` en est un cas net (`PgAddressPubCountQueries.recompute_pub_count` → `recompute_pub_count`). Recenser les modules à adaptateur unique et replier le SQL dans la classe. Les tests qui appellent la fonction libre passeront par l'adaptateur — un test ne justifie pas l'existence d'une fonction de production, pas plus qu'un CLI oneshot destiné à disparaître.
  - [x] Cas le plus lourd du motif, traité par la fiche dédiée [Normalize : factoriser l'upsert des `source_publications`](archived/2026-07-17_CODE_normalize-upsert-source-publications.md) : les sept `upsert_<source>_source_publication` se replient sur un objet de transport `SourcePublicationRow` et une méthode de port unique. `application/ports/pipeline/normalize/` ne porte plus aucun port par source.
- [ ] Construction des lignes par déballage positionnel (`Row(*row)`) : l'ordre des champs de la classe et celui des colonnes du `SELECT` forment un contrat unique, écrit dans deux couches et vérifié par rien — réordonner l'un sans l'autre range les valeurs dans les mauvais champs, en silence dès que les types sont compatibles. L'appariement par nom (`Row(**row._mapping)`) supprime le couplage et échoue bruyamment sur un nom manquant. Fait pour `UnaryCorrectionRow` et `DoiClusterRow` ; reste `JournalByDoiRow` (`pipeline/metadata_correction.py`).
- [ ] `api/publications/list.py` : `_hal_status_clause_sync` porte le suffixe fossile d'une couche async retirée, comme les dépendances de l'API avant elle (`85f4c974`). Rien n'en distingue une variante asynchrone : il n'y en a pas.

#### 2.7 `repositories`

- [ ] Héritage explicite du Protocol par les adaptateurs : `PgConfig` et `PgConfigQueries` (`infrastructure/queries/config.py`) déclarent `class PgX(PortProtocol)` ; les dix `PgXxxRepository` ne l'implémentent que structurellement. La forme explicite fait vérifier l'implémentation par mypy dès la définition de la classe, quand la structurelle attend le site d'injection (`deps.py`, factories) — un écart de signature y passe inaperçu plus longtemps. À harmoniser.
- [ ] Même motif de déballage positionnel qu'en 2.6, sur cinq repositories : `_PerimeterRow`, `_PublisherRow`, `_StructureRow`, `_JournalRow`, `_SourcePublicationViewRow`.
- [ ] `person_repository/_authorships.py` suit la frontière tranchée en 1.3 : le sous-module ne porte plus que le lien `person_id` des signatures, et disparaît si le lien passe côté Authorship.


### Phase 3 - `interfaces/`

#### 3.1 - API

Passe faite sur `models/`, `deps.py`, `app.py` et les docstrings des dix-neuf routers.

- [x] `models/` : `MergePersons` et `AuthorshipExcludeResponse` étaient les copies de `MergeRequest` et `OkResponse`, déjà partagés ; re-export mort des types de `ports/api/_common.py` retiré (`20271ac0`). Docstrings allégées : chaque module réénumérait les projections vivant dans son port, et la règle s'énonçait de huit façons (`729441c9`).
- [x] `deps.py` : `SPAStaticFiles` n'était pas une dépendance — sortie en `spa.py`, avec le `PROJECT_ROOT` qu'elle recalculait à la main (`0920e16a`). Suffixe `_sync` retiré des 29 dépendances : sans pendant async, il ne distinguait rien (`85f4c974`). `require_admin` supprimé, le middleware couvrant déjà toutes les écritures (`b4b9a4ea`).
- [x] `app.py` : `/api/health` annonçait un pipeline en cours après un crash, faute du contrôle de PID que `read_status` porte (`d2afe1d1`) ; l'endpoint et `/api/metrics`, qu'aucun consommateur n'interrogeait, sont supprimés (`8fae017e`, `88a6a4b1`).
- [x] Docstrings des routers : une formule unique, hard-wraps déroulés, six messages d'erreur passés en français (`bd8d1eaa`, `49df8267`). Deux d'entre elles décrivaient une clôture de périmètre que les tests contredisent, et la publiaient dans le contrat TypeScript (`8e26875c`) ; celle de `auth.login` nommait une variable d'environnement inexistante (`d714738d`).
- [x] `logger = logging.getLogger(__name__)` déclaré par les dix-neuf routers, utilisé par aucun (`abb6d3f2`).
- [x] **Le format du jeton de session n'appartenait à personne**, et **l'underscore de `deps.py` ne protégeait rien** : `admin_user|timestamp` était composé par `routers/auth.py` et le conftest, découpé par `deps._verify_token` pour son horodatage, redécoupé par le middleware d'`app.py` pour son utilisateur — et les trois fonctions privées de `deps.py` étaient importées par trois modules. Les deux points n'en faisaient qu'un : une brique qui possède le format possède aussi sa signature. `interfaces/api/session.py` prend un nom (`issue_token`) et rend un nom (`read_session`) ; le format ne sort plus. Le séparateur est cherché depuis la fin, un nom qui le contient s'y perdant. Signature, expiration et formes illisibles gagnent des tests unitaires (`972a396d`).
- [x] **Le nombre de pages était recopié, non déduit.** `(total + per_page - 1) // per_page` était réécrit dans vingt adapters sous quatre formes qui divergeaient sur le résultat vide (zéro page ou une), dont une garde contre un `per_page` nul que `Query(ge=10)` interdit. Vingt modèles redéclaraient le même quadruplet. `PaginatedResponse` (`ports/api/_common.py`) porte `total`, `page` et `per_page` et calcule `pages` ; `page_count` sert la règle au seul site qui en a besoin hors modèle. Quatre réponses gagnent `per_page`, qu'elles utilisaient sans le publier (`9cad3c0b`).
- [x] `hal_problems` : `hal_missing_collections` rendait `None` pour un laboratoire introuvable comme pour un laboratoire sans collection, et le router affirmait la seconde cause des deux ; `NoMissingCollections` les nomme, d'où un 404 et un 400. Le détail des publications des deux pages de doublons se lit par lot (deux requêtes par page, contre deux par ligne). Le prédicat « deux comptes HAL distincts » ne s'écrit plus qu'une fois (`d5f76b49`).
- [ ] `routers/subjects.py` est public et consomme `SubjectsAdminQueries`, dont le nom annonce l'admin. Le port sert les deux ; son nom en désigne un seul.
- [ ] `PublicationMergeResponse` (`ok`, `target_id`, `source_id`) et `MergeResponse` (`merged`, `source_id`, `target_id`) disent la même chose sous deux formes. Laissées en place faute d'un motif clair — à trancher avec la fiche des exceptions, qui touche les mêmes endpoints.
- [ ] **Le test « qui l'appelle » n'a pas été passé sur les endpoints.** Il a suffi à condamner `/api/health` et `/api/metrics`, et une fonction morte du client frontend. Croiser chaque route avec les appels du frontend dirait lesquelles ne servent plus.
- [ ] `routers/admin/publication_duplicates.py` : la docstring de `merge_duplicate_publications` explique encore le rafraîchissement, qui relève de `services/publications`. Le fait qui appartient au router est le choix du survivant et l'invariance du sens de fusion qui l'autorise.

Deux findings ont leur fiche dédiée, tous deux traités : [Périmètre APC](archived/2026-07-17_CODE_apc-perimetre-au-router.md) — le périmètre APC était un alias de `perimeter_persons`, et les adapters le résolvent eux-mêmes ; et [Exceptions des routers](archived/2026-07-17_CODE_exceptions-des-routers.md) — les gardes de fusion, réparties à l'inverse selon l'agrégat, sont descendues dans les services, et les routers ne gardent que les traductions d'une lecture vide.

#### 3.2 - Frontend

- [ ] `src/lib/api/schema.ts` est généré depuis l'OpenAPI (`npm run types:gen`), mais aucun garde-fou ne vérifie qu'il suit : ni la CI ni les hooks pre-commit ne le régénèrent ni ne comparent. Il dérive donc en silence : deux régénérations faites au passage ont rattrapé, l'une une docstring de router, l'autre les docstrings et l'enum `journal_type` de tout un chantier. `svelte-check` ne le voit pas : le front appelle les routes par chemin, pas par `operationId`. Un contrôle de fraîcheur en CI (régénérer, échouer si le diff est non vide) fermerait la dérive.
- [ ] **Passe de `src/lib/api/` au test « qui l'appelle ».** `auth.ts` réécrivait ses trois types à la main plutôt que de lire le contrat généré, d'où trois dérives qu'aucun outil ne voyait : un champ `user` que l'API ne sert pas, un `login()` typé comme rendant `{authenticated}` quand l'endpoint rend `{ok}`, et un `health()` mort (`630d3dd7`, `88a6a4b1`). Les douze autres modules du dossier n'ont pas été relus ; ceux qui déclarent leurs types au lieu de les lire sont exposés au même écart silencieux.

#### 3.3 - CLI

- [ ] CLI `maintenance/` : coquille-ification. `enrich_publishers` séquence ses trois étapes dans son `main()` au lieu de déléguer en un appel à un orchestrateur applicatif, contrairement à ses voisins.
- [ ] `maintenance/import_authenticated_orcids.py` : l'ingestion vit ici, en SQL brut depuis `interfaces/cli/` — résolution email → personne sur `persons_rh`, puis sondage de `person_identifiers` pour prévoir les déplacements. Le service ne reçoit que des paires déjà résolues et normalisées. À faire descendre derrière un port, comme ses voisins.
- [ ] `imports/import_persons.py` : son `INSERT INTO persons` (lignes 265-276) duplique `repo.create`, et la ligne suivante appelle `refresh_person_name_forms` depuis le service — soit les deux moitiés de `create_person`, dont l'une réécrite en SQL. Remplacer par un appel à `create_person`. Le CLI calcule par ailleurs `last_norm`/`first_norm` pour sa requête de détection de doublon, ce que `repo.create` refait de son côté.
- [ ] `oneshot/seed_journals_doi_prefix.py` : à promouvoir en `maintenance/`, ou à intégrer au pipeline. Les préfixes DOI des revues alimentent la correction de métadonnées (`resolve_journal_by_doi`, sous-step `journal_by_doi` de la phase `metadata_correction`), or aucune phase n'écrit `journals.doi_prefix` : la colonne est semée une fois puis se périme — dette. Le script écrit la colonne en SQL brut dans une boucle ; son passage par `journals` service ne coûte rien.
- [ ] `maintenance/merge_publications.py` porte `# STATUS: oneshot` alors qu'il vit dans `maintenance/` et se décrit comme réutilisable (nettoyage en lot) — marqueur à revoir.
- [ ] Passe des CLI `maintenance/` et `oneshot/`.

### Phase 4 - `domain/`

- [ ] `source_publications/correction.py` (680 lignes) porte trois sujets, qui sont les trois sous-étapes de la phase `metadata_correction` — le module le documente déjà (« unaire : `doc_type`/`oa_status`/`external_ids` ; cluster : `doi` ; `journal_by_doi` : `journal_id` ») : le moteur de règles unaire (contrat, table `_RULES`, `effective_metadata`), la correction relationnelle par cluster DOI (`DoiClusterMember`, `resolve_cluster_doi_corrections`, `CONVERGENCE_CASES`), et le rattachement du journal par préfixe DOI (`resolve_journal_by_doi`). Candidat à la scission ; les deux derniers sujets raisonnent sur des `source_publications` et restent en place.
- [ ] Placement du moteur de règles unaire, seul sujet bi-niveau (alimenté par une `source_publication` comme par une publication canonique), à trancher après la scission. À noter : ce n'est pas une question de couches, `publications/` et `source_publications/` s'important déjà mutuellement (`source_publications/doc_types.py` et `keys.py` vers `publications/` ; `publications/aggregation.py` vers `source_publications/`). Aucun cycle créé ni supprimé par un déplacement.

### Phase 5 - `tests/`

- [x] `integration/infrastructure/queries/test_address_resolution.py` : sept tests passaient des tuples positionnels aux fonctions de résolution d'adresses, dont le contrat veut les `NamedTuple` `KeptPair` et `DetectedStructure`. Ils levaient `AttributeError` ; ceux qui passaient une liste vide n'y coupaient que parce que la fonction retourne avant la lecture (`b5055298`).
- [ ] Helpers locaux à suffixe `_sync` fossile : `_insert_config_sync`, `_insert_perimeter_sync`, `_create_struct_sync` (`integration/application/test_config_service.py`, `test_perimeters_service.py`). Même fossile qu'en 2.6 et qu'aux dépendances de l'API (`85f4c974`).

## Questions ouvertes

- **Place du primitif de correction unaire** (`compute_update`). `application/services/journals/core.py` l'importe depuis `application/pipeline/metadata_correction/correct_unary.py` : seul import `services` → `pipeline` de la couche, quand cinq modules du pipeline importent des services. Le service s'en sert dans `_correct_for_journal`, qui rejoue la correction unaire cantonnée à une revue après l'édition de son `journal_type` — soit la sous-étape de la phase, en plus petit. Le primitif est donc partagé entre la phase et un service, comme le sont `create_person` ou `refresh_from_sources` ; sauf que ceux-là vivent dans un service que le pipeline vient chercher, et qu'ici la flèche s'inverse. Le porter dans un service supposerait un `services/source_publications/`, qui n'existe pas — les `source_publications` n'ont pas de service d'agrégat, leurs écritures étant le fait des normalizers et des phases. À trancher avec le découpage de `domain/source_publications/correction.py` (phase 4), qui pose la même question un cran plus bas.

- **Style de logging incohérent** (transverse). f-string vs `%`-lazy : ~79 occurrences sur 22 fichiers du seul `application/pipeline`, motif probablement plus large. Faible nuisance (le logging de progression et de bilan est une observabilité légitime, feeding `pipeline.log` que l'UI admin ressort par phase). Ne vaut le coup que couplé à un durcissement lint (règles ruff `G`/`LOG`) qui verrouille le style. Hors périmètre de ce chantier ; éventuel chantier dédié.
- **Convention « étape de phase = module »** (transverse). Certaines phases ont une étape numérotée dans leur docstring qui reste un appel inline dans le `phase.py`, alors que les étapes sœurs sont des modules dédiés (ex. l'étape `enforce` de la phase personnes, réduite à un appel `authorship_repo.enforce_confirmed_authorships()`). À trancher globalement : une étape mérite-t-elle toujours son module, ou l'appel inline se justifie-t-il quand elle ne porte pas de logique propre ? Recenser le motif dans les autres phases avant de fixer la règle.
