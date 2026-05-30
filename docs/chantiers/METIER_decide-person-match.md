# Chantier — Cascade unifiée de matching personnes (`decide_person_match`)

Commencé le 2026-05-15

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
2. **Hiérarchie cible** (Phase 2) :
   1. **ORCID déposé par l'auteur** (crossref ∪ openalex `raw_orcid` ∪ hal TEI — cf. décision 5). À ajouter en tête.
   2. **Cross-source par publication × position auteur** (avec garde-fou méga-paper, état actuel).
   3. **Identifiants : IdRef, hal_person_id**. ORCID WoS retiré du matching (attribué algorithmiquement par WoS, régulièrement fautif).
   4. **Name matching**.
5. **ORCID fiable = ORCID déposé par l'auteur, pas ORCID résolu par la source.** Audit `data/raw_store` + crossref live (27 doublets OA∩crossref, 48 paires d'auteurs avec ORCID des deux côtés) : OpenAlex porte deux ORCID par authorship — `raw_orcid` (niveau authorship, recopié de la métadonnée brute de la source amont, = ORCID Crossref pour les articles à éditeur) et `author.orcid` (entité désambiguïsée par le clustering OA, régulièrement fautif). Le `raw_orcid` coïncide à 100 % avec l'ORCID Crossref sur le recouvrement ; aucun désaccord. Conséquence : on traite crossref, le `raw_orcid` OpenAlex et l'ORCID HAL (TEI `label_xml`) au même niveau de fiabilité, regroupés dans `ORCID_MATCH_SOURCES`. WoS (`PreferredORCID`) en est exclu. La provenance n'est **pas** tracée sur `person_identifiers` (la restriction s'applique au signal de matching, pas à l'enregistrement de l'identifiant).
3. **Seuil méga-paper conservé**. `MAX_AUTHORS_CROSS_SOURCE = 50` déjà implémenté dans `decide_cross_source_match`, cohérent avec `MAX_AUTHORS_CONFLICT = 50` côté admin.
4. **Statuts `pending`/`confirmed`/`rejected` inchangés**. Un identifier `rejected` n'est jamais utilisé pour le matching (`fetch_*_to_person_map` filtre déjà `status != 'rejected'`). `pending` et `confirmed` restent utilisés indistinctement ; restreindre aux `confirmed` est différé.

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

**Repenser la cascade par fiabilité de la source, pas par type d'identifiant.** Un même type d'identifiant peut avoir des fiabilités opposées selon sa provenance : un ORCID déposé par l'auteur (Crossref, `raw_orcid` OpenAlex, TEI HAL) est excellent, un ORCID résolu algorithmiquement par la source (`author.orcid` OpenAlex, `PreferredORCID` WoS) est peu fiable (cf. décision 5). Et le cross-source en tête est inopérant au bootstrap (n=0) puisqu'il suppose des matchings préexistants ; il devrait venir **après** les identifiers fiables, pas avant.

Hiérarchie cible par fiabilité de source :

1. **ORCID déposé par l'auteur** (`ORCID_MATCH_SOURCES` : crossref ∪ openalex `raw_orcid` ∪ hal).
2. **Identifiers HAL** (hal_person_id, idhal, idref — extraits de `label_xml`).
3. **IdRef ESR** (ScanR, theses.fr).
4. **Cross-source** par publication × position (avec garde-fou méga-paper).
5. **Name matching**.

#### Fiabilisation de l'ORCID (fait)

- [x] **Normaliseur OpenAlex → `raw_orcid`** au lieu de `author.orcid` (`_extract_openalex_orcid`).
- [x] **Suppression du garde-fou par nom** (`keep_orcid_if_name_matches` + `source_data.display_name` OA) : inutile sur `raw_orcid`, qui est déposé par l'auteur. Code mort supprimé.
- [x] **ORCID restreint aux sources à dépôt auteur** comme signal de matching (`ORCID_MATCH_SOURCES`, gate côté cascade). WoS exclu. L'enregistrement de l'identifiant reste agnostique.

> Effet sur le stock : ces changements modifient la normalisation OA (ORCID stocké) et la cascade. Le stock existant porte encore l'ancien `author.orcid` jusqu'au full rerun `raw_hash=null`.

#### Réordonnancement de la cascade (reste)

- [ ] **Mettre l'ORCID déposé auteur en tête** du décideur (avant cross-source).
- [ ] **Reculer le cross-source** après les identifiers fiables (sinon inopérant au bootstrap).
- [ ] **Ajout `hal_person_id`** au niveau des identifiants HAL. Sous-décision `decide_match_by_identifier(value, hal_account_map)` existe déjà — ajouter la map prefetch + l'argument au décideur.

## Questions ouvertes

- **Matching cross-source sur méga-papers** : le seuil `MAX_AUTHORS_CROSS_SOURCE = 50` court-circuite le cross-source au-delà. Suffit-il, ou faut-il restreindre davantage ? Mesure préalable du ratio matchings utiles / faux positifs sur les papers à 30-50 auteurs encore couverts par le matching. À examiner après Phase 1.

- **Statuts `pending` vs `confirmed`** : aujourd'hui les deux sont utilisés indistinctement pour le matching. Restreindre aux `confirmed` réduirait le bruit mais fragiliserait la cascade sur des identifiers récents non encore validés. À reconsidérer plus tard.

- **Invariants métier dans la cascade** : faut-il intégrer `check_can_merge_persons` (jamais de fusion auto entre deux persons avec `persons_rh` distincts) comme partie de la cascade, ou le garder en pré-check côté admin/scripts seulement ? À trancher si Phase 2 produit des cas où la cascade rattacherait deux personnes RH-distinctes par identifier.

## Liens

- Pattern de référence (décision pure déjà en domain) : [`resolve_doi_conflict`](../../domain/publication.py)
- Briques sous-décisions déjà migrées : [`domain/persons/matching.py`](../../domain/persons/matching.py)
- Phase 5 de `CODE_rich-domain-model.md` (refactor `create_persons_from_source_authorships` côté entités) — débloquée après Phase 1 de ce chantier.



## idées à intégrer
* signaux supplémentaires (affiliation notamment) pour trancher entre homonymes
