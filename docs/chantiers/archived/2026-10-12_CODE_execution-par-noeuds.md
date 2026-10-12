# Chantier — Exécution du pipeline par nœuds

## Contexte

`pipeline/graph.py` déclare les nœuds du pipeline : une étape, sa phase, ce qu'elle lit et écrit, ses lectures du run précédent. L'ordre des phases, `PHASE_ORDER`, est celui de leurs nœuds.

`run.py` exécute les phases dans cet ordre. Chaque phase expose `build()`, dont le code fixe l'ordre de ses étapes. Les tests vérifient l'ordre déclaré des nœuds, pas l'ordre exécuté. Le graphe a donc pu diverger du code : il omettait la recherche de HAL par DOI et la relecture de Crossref, et recopiait des listes de sources que le domaine déclare.

Le journal du terminal suit déjà la structure du graphe : un cadre par phase, des sections (« Éditeurs », « Revues »), une ligne de bilan par étape. Les lignes de bilan de `publishers_journals` correspondent presque une à une à ses dix nœuds.

## Décisions

- **Le journal du terminal garde sa forme** : cadre par phase, titre de section, ligne de bilan par étape, barres de progression.
- **Un nœud interroge au plus une source.** Une étape qui interroge plusieurs sources se découpe en un nœud par source.
- **Une seule fonction d'accès à une source** : elle contrôle les identifiants, saute l'étape avec un avertissement s'ils manquent, pose le circuit-breaker et signale une source indisponible ou coupée. Tout appel à une API passe par elle, scripts compris.
- **`--only` et `--from` désignent une phase**, jamais un nœud : relancer une phase entière reste rapide.
- **Les métriques restent par phase**, dans `pipeline_phase_executions`. L'exécuteur rend les métriques de chaque nœud, avec sa durée. La phase les assemble.
- **La condition d'exécution d'un nœud reste dans la phase** (`NodeStep.when`) : mode, options, sources retenues.
- **Le graphe déclare les nœuds parallèles par un `lot`.** L'exécuteur lance ensemble les nœuds consécutifs d'un même lot.
- **Le graphe déclare la maintenance d'un nœud** (`VACUUM`, `ANALYZE`), sans dépendance. L'exécuteur la lance à la fin du nœud.

## Phasage

### Phase 1 — Une seule déclaration

- [x] `PHASE_ORDER` se déduit des groupes de `graph.py`. Les libellés et la liste des enrichissements deviennent des attributs de phase dans `graph.py`. Suppression de `phase_order.py`.
- [x] Les nœuds par source du graphe lisent les listes du domaine : `HARVESTED_SOURCES`, `ALL_SOURCES`, `DOI_SEARCHABLE_SOURCES`, `SOURCE_PRIORITY`.

### Phase 2 — Inventaire

- [x] Pour chaque phase, confronter les étapes de `build()` aux nœuds de `graph.py` : nœuds absents, étapes non déclarées, ordre. Tables dans l'[inventaire](2026-10-12_CODE_execution-par-noeuds_inventaire.md).
- [x] Pour chaque nœud, la section et la ligne de journal qui lui correspondent.

### Phase 3 — Corrections du graphe

- [x] `persons` : la purge tourne après `populate_person_name_forms`, mais ses lectures et écritures sont déclarées dans `persons.resolve`, placé avant. Un nœud `persons.purge` après `populate_person_name_forms`.
- [x] `merge_duplicate_journals` lit `journal_type`, l'APC, `oa_model`, `manual_fields` et `title` des revues sans les déclarer. Le graphe ignore donc qu'il dépend d'`enrich_journals_from_openalex`.
- [x] `normalize.prune_disappeared` ne déclare pas la suppression en cascade des signatures, de leurs adresses et ROR, des signatures confirmées et rejetées. `cleanup_orphan_identities` n'en dépend donc pas.
- [x] `publications.reconcile` lit `journals.journal_type` et `monographs.journal_id` sans les déclarer.
- [x] Lectures déclarées à tort : `language_forms` par `normalize.<source>`, les référentiels de publication par `normalize.theses`, `publications` par `subjects.usage`, `countries` par `countries.detect`, `source_publications.external_ids` par `oa_status.verify_unpaywall`.
- [x] `oa_status.verify_unpaywall` interroge Unpaywall sans déclarer de `network`.
- [x] Étapes sans nœud. L'import du dump ROR devient le nœud `affiliations.refresh_ror`. La seconde matérialisation de `perimeter_structures` disparaît : `run.py` le matérialise avant toute phase. Le `VACUUM` du staging et les deux `ANALYZE` des signatures sont déclarés comme maintenance de leur nœud, sans dépendance.
- [x] Les canaux de `fetch_missing` partagent une même déclaration, trop large pour chacun. Une phase peut déclarer les lectures et écritures communes à ses nœuds ; chaque canal ajoute les siennes.
- [x] Journal : `fetch_stale`, `resolve_ra` et `extract` en mode daily n'ont pas de titre de section. Les épinglages de `persons` et les documents disparus de `normalize` s'affichent sans branche.

Constats hors du graphe :

- [x] Les docstrings des modules `delete_empty_*` les situent dans `publishers_journals`. Ils tournent dans `authorships`.
- [x] `enrich_journals_from_openalex` attend entre ses requêtes le délai du DOAJ.
- [x] La docstring de `normalize.build` et celle de `preload_caches` décrivent un enrichissement des structures HAL que le code ne fait pas.

Accès aux sources :

- [x] Fonction d'accès à une source, `access_source`, dans `pipeline/ingestion/http/access_source.py`. Elle remplace `filter_configured`, les contrôles des moissonneurs OpenAlex, WoS et ScanR, et les trois formes du circuit-breaker. L'extraction de DataCite et `fetch_truncated` contrôlent ainsi leurs identifiants.
- [x] `resolve_publishers` se découpe en deux nœuds, Crossref et DataCite, qui choisissent leurs préfixes par agence d'enregistrement. `crossref_checked_at` et `datacite_checked_at` remplacent `publisher_checked_at`. Les préfixes d'agence inconnue passent par Crossref, puis par DataCite quand Crossref les a interrogés sans les trouver.

### Phase 4 — Exécution par nœuds

- [x] Exécuteur `pipeline/node_runner.py` : une phase fournit pour chaque nœud sa fonction, sa section et son libellé. L'exécuteur lance les nœuds dans l'ordre du graphe, ouvre la section quand elle change, puis écrit le bilan du nœud.
- [x] Conversion de toutes les phases.
- [x] Un nœud qui déclare un `network` s'exécute dans la fonction d'accès à sa source, posée par l'exécuteur.
- [x] L'exécuteur lance la maintenance déclarée d'un nœud à la fin du nœud. `authorships.build` se découpe en deux nœuds, pour que `ANALYZE authorships` tombe entre la création des paires et la propagation de leurs attributs.
- [x] L'exécuteur mesure la durée de chaque nœud, que les phases reportent dans leur table d'observabilité.
- [x] Mise à jour de la documentation, dont `publisher_checked_at` et `resolve_publishers` dans `docs/pipeline/05-publishers-journals.md`, `docs/agregats/publishers.md` et `docs/sources/`, et la matérialisation de `perimeter_structures` dans `docs/donnees/08-donnees-derivees.md`.

## Questions ouvertes

- Une dizaine de nœuds écrivent eux-mêmes une ligne « Terminé en X s ». L'exécuteur pourrait l'écrire, mais sa forme varie d'un nœud à l'autre.
- Les libellés des lignes de synchronisation d'`authorships` (« Attributs des liens », « Structures des liens ») sont peu intelligibles.
