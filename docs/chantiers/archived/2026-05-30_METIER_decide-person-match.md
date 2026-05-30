# Chantier — Cascade unifiée de matching personnes (`decide_person_match`)

Commencé le 2026-05-15

Terminé le 2026-05-30

## Contexte

Le pipeline persons (`application/pipeline/persons/create_persons_from_source_authorships.py`) exécute la cascade de matching personne en **4 boucles séquentielles indépendantes** sur `all_authorships`. Chaque étape skip ce qui est déjà rattaché par les précédentes ; la hiérarchie de fiabilité n'est pas exprimée comme une décision pure unique mais résulte implicitement de l'ordre des appels.

Hiérarchie actuelle (de la plus fiable à la moins) :

1. **Cross-source par publication × position auteur** (`step1_cross_source`) — on relie une signature à la `person_id` connue d'une autre source à la même `(publication_id, author_position)`. Garde-fou `names_compatible`. Court-circuit méga-paper (≤ 50 auteurs, `MAX_AUTHORS_CROSS_SOURCE` dans `domain/persons/matching.py`).
2. **IdRef** (`step1b_idref`) — PPN SUDOC via `person_identifiers`, filtre `status != 'rejected'`.
3. **ORCID** (`step2_orcid`) — toutes sources confondues (filtré pour OpenAlex/WoS via `keep_orcid_if_name_matches` pré-cascade).
4. **`person_name_forms`** (`step3_name_forms`) — matching par nom normalisé, avec création si forme inconnue et `allow_create=True`.

**Briques déjà en place côté domain** ([domain/persons/matching.py](../../domain/persons/matching.py)) :

- `decide_cross_source_match(authorship_source, last_norm, first_norm, candidates, total_author_count)` — étape 1.
- `decide_match_by_identifier(value, identifier_map)` — étapes 1b (IdRef) et 2 (ORCID).
- `decide_name_form_outcome(person_ids, allow_create)` — étape 3.

Manque un décideur d'orchestration unique (`decide_person_match`) qui agrège les sous-décisions et trie selon la hiérarchie de fiabilité. Permettrait de tester toute la cascade hors BDD et de modifier l'ordre sans toucher 4 boucles.

## Décisions

1. **Refactor pur avant peaufinage logique**. Phase 1 reproduit la logique actuelle (cross-source → IdRef → ORCID toute source → name_forms) en restructurant la cascade en un décideur pur + 1 boucle d'application. Phase 2 modifie la logique (hiérarchie cible).
2. **Hiérarchie cible** (Phase 2), du signal le plus fiable au moins fiable :
   1. **ORCID déposé par l'auteur** (`ORCID_MATCH_SOURCES` : crossref ∪ openalex `raw_orcid` ∪ hal — cf. décision 3).
   2. **`hal_person_id`** (compte HAL).
   3. **IdRef**.
   4. **Cross-source par publication × position auteur** (avec garde-fou méga-paper). Reculé après les identifiants : inopérant au bootstrap (suppose des matchings préexistants).
   5. **Name matching**.
3. **ORCID fiable = ORCID déposé par l'auteur, pas ORCID résolu par la source.** Audit `data/raw_store` + crossref live (27 doublets OA∩crossref, 48 paires d'auteurs avec ORCID des deux côtés) : OpenAlex porte deux ORCID par authorship — `raw_orcid` (niveau authorship, recopié de la métadonnée brute de la source amont, = ORCID Crossref pour les articles à éditeur) et `author.orcid` (entité désambiguïsée par le clustering OA, régulièrement fautif). Le `raw_orcid` coïncide à 100 % avec l'ORCID Crossref sur le recouvrement ; aucun désaccord. Conséquence : on traite crossref, le `raw_orcid` OpenAlex et l'ORCID HAL (TEI `label_xml`) comme signal ORCID fiable, regroupés dans `ORCID_MATCH_SOURCES`. WoS (`PreferredORCID`) en est exclu. La provenance n'est **pas** tracée sur `person_identifiers` (la restriction s'applique au signal de matching, pas à l'enregistrement de l'identifiant).
4. **Matching par identifiant, pas par source** (modèle « B »). Une `source_authorship` n'a qu'une source ; un sous-classement de l'ORCID par source (crossref-orcid > hal-orcid) ne vaut pas la complexité. La fiabilité-par-source est encodée par le gate de sources sur la phase ORCID (`ORCID_MATCH_SOURCES`) — seul cas mixte (idref et hal_person_id n'ont pas de source non fiable). Asymétrie connue et acceptée : un ORCID déposé via HAL hérite du risque d'attribution HAL mais reste traité au tiroir ORCID.
5. **Tiroir HAL = `hal_person_id` seul.** `idhal ⊆ hal_person_id` : audit `raw_store/hal` (493 positions) → 0 authorship avec `idhal` sans `hal_person_id`, et `hal_person_id` en couvre 55 de plus. Matcher sur `idhal` est superflu (ce qui matche sur `idhal` aurait matché sur `hal_person_id`), et `idhal` n'apporte aucune garantie de fiabilité supplémentaire.
6. **Seuil méga-paper conservé**. `MAX_AUTHORS_CROSS_SOURCE = 50` déjà implémenté dans `decide_cross_source_match`, cohérent avec `MAX_AUTHORS_CONFLICT = 50` côté admin.
7. **Statuts `pending`/`confirmed`/`rejected` inchangés**. Un identifier `rejected` n'est jamais utilisé pour le matching (`fetch_*_to_person_map` filtre déjà `status != 'rejected'`). `pending` et `confirmed` restent utilisés indistinctement ; restreindre aux `confirmed` est différé.

## Phasage

### Phase 1 — Refactor structurel pur (logique préservée)

- [x] **Implémenter `decide_person_match`** dans `domain/persons/matching.py`. Signature :

   ```python
   @dataclass(frozen=True)
   class PersonMatchDecision:
       action: Literal["match", "create", "skip"]
       person_id: int | None = None
       reason: str = ""  # 'cross_source' | 'idref' | 'orcid' | 'single_name' | 'name_ambiguous' | …

   def decide_person_match(
       *,
       cross_source_match: int | None,
       idref_match: int | None,
       orcid_match: int | None,
       name_form_outcome: NameFormDecision,
   ) -> PersonMatchDecision: ...
   ```

   Pur, testable sans BDD. Reproduit l'ordre actuel.

- [x] **Tests unitaires sur toutes les branches** de la cascade : match cross-source, match idref, match orcid, name_form single match, name_form ambiguous, name_form create, name_form skip (create interdit).
- [x] **Refactor `create_persons_from_source_authorships.py`** : passer de 4 boucles à 1 boucle. Prefetch des 4 lookups en début de `run` + boucle unique avec appel `decide_person_match`. Suppression des fonctions `step1_cross_source`, `step1b_idref`, `step2_orcid`, `step3_name_forms`.
- [x] **Nettoyage** : docstring du module remplacé par la nouvelle architecture (cascade unifiée + 4 sous-décisions). Les 5 `Any` résiduels signalés par `CODE_chasse-aux-any` sont levés (`all_authorships: list[dict[str, Any]]`). Bonus : commit/rollback sortis de `run()` vers le CLI (pattern plus testable).
- [x] **Tests d'intégration** : `test_dedup_persons.py` refondu en 6 scénarios `run()` (vs 10 sur les steps supprimés). `test_idempotence.py:_run_create_persons` adapté pour appeler `run()`. La logique pure des sous-décisions reste couverte par `test_matching.py` (26 unit tests).

### Phase 2 — Peaufinage hiérarchie (post-refactor)

**Réordonner la cascade par fiabilité du signal** (cf. décisions 2-5). Phases par type d'identifiant (modèle B), du plus fiable au moins fiable. Le cross-source recule après les identifiants : en tête il est inopérant au bootstrap (n=0, suppose des matchings préexistants).

Ordre implémenté dans `decide_person_match` :

1. **ORCID déposé par l'auteur** (`ORCID_MATCH_SOURCES` : crossref ∪ openalex `raw_orcid` ∪ hal ; WoS exclu).
2. **`hal_person_id`** (compte HAL).
3. **IdRef** (HAL TEI, ScanR, theses.fr).
4. **Cross-source** par publication × position (avec garde-fou méga-paper).
5. **Name matching**.

#### Fiabilisation de l'ORCID (fait)

- [x] **Normaliseur OpenAlex → `raw_orcid`** au lieu de `author.orcid` (`_extract_openalex_orcid`).
- [x] **Suppression du garde-fou par nom** (`keep_orcid_if_name_matches` + `source_data.display_name` OA) : inutile sur `raw_orcid`, qui est déposé par l'auteur. Code mort supprimé.
- [x] **ORCID restreint aux sources à dépôt auteur** comme signal de matching (`ORCID_MATCH_SOURCES`, gate côté cascade). WoS exclu. L'enregistrement de l'identifiant reste agnostique.

#### Réordonnancement de la cascade (fait)

- [x] **ORCID en tête, cross-source reculé en position 4** (`decide_person_match` : orcid → hal_person_id → idref → cross_source → name_form).
- [x] **Ajout `hal_person_id`** : map prefetch `fetch_hal_account_to_person_map` + argument `hal_match` au décideur. Sous-décision `decide_match_by_identifier` réutilisée telle quelle.

> Effet sur le stock : ces changements modifient la normalisation OA (ORCID stocké) et la cascade. Le stock existant porte encore l'ancien `author.orcid` jusqu'au full rerun `raw_hash=null`.

## Questions ouvertes

- **Matching cross-source sur méga-papers** : le seuil `MAX_AUTHORS_CROSS_SOURCE = 50` court-circuite le cross-source au-delà. Suffit-il, ou faut-il restreindre davantage ? Mesure préalable du ratio matchings utiles / faux positifs sur les papers à 30-50 auteurs encore couverts par le matching. À examiner après Phase 1.

- **Statuts `pending` vs `confirmed`** : aujourd'hui les deux sont utilisés indistinctement pour le matching. Restreindre aux `confirmed` réduirait le bruit mais fragiliserait la cascade sur des identifiers récents non encore validés. À reconsidérer plus tard.

- **Doublons probables via conflits d'identifiant** : un `CannotAttributeConflict` lors de l'ajout d'identifiants (personne P matchée, mais un autre identifiant de l'authorship est déjà détenu par une personne Q) signale que P et Q sont probablement la même personne. Aujourd'hui le signal est loggé puis perdu. Le capturer pour un check post-pipeline relève de l'observabilité — porté par [`CODE_observabilite-robustesse-pipeline`](CODE_observabilite-robustesse-pipeline.md), pas par ce chantier. La cascade ne fusionne jamais deux personnes existantes, donc aucun garde-fou de fusion (`check_can_merge_persons`) n'est requis ici.

## Liens

- Pattern de référence (décision pure déjà en domain) : [`resolve_doi_conflict`](../../domain/publication.py)
- Briques sous-décisions déjà migrées : [`domain/persons/matching.py`](../../domain/persons/matching.py)
- Phase 5 de `CODE_rich-domain-model.md` (refactor `create_persons_from_source_authorships` côté entités) — débloquée après Phase 1 de ce chantier.



## idées à intégrer
* signaux supplémentaires (affiliation notamment) pour trancher entre homonymes
