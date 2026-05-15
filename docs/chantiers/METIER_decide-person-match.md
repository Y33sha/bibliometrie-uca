# Chantier — Cascade unifiée de matching personnes (`decide_person_match`)

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
   1. **ORCID dans authorship Crossref** (un ORCID Crossref vient de l'éditeur, directement de l'auteur lors de la soumission ; le plus fiable). À ajouter en tête.
   2. **Cross-source par publication × position auteur** (avec garde-fou méga-paper, état actuel).
   3. **Identifiants : IdRef, hal_person_id**. ORCID hors Crossref retiré (les ORCID OA/WoS viennent souvent d'un matching par nom côté éditeur, régulièrement fautifs).
   4. **Name matching**.
3. **Seuil méga-paper conservé**. `MAX_AUTHORS_CROSS_SOURCE = 50` déjà implémenté dans `decide_cross_source_match`, cohérent avec `MAX_AUTHORS_CONFLICT = 50` côté admin.
4. **Statuts `pending`/`confirmed`/`rejected` inchangés**. Un identifier `rejected` n'est jamais utilisé pour le matching (`fetch_*_to_person_map` filtre déjà `status != 'rejected'`). `pending` et `confirmed` restent utilisés indistinctement ; restreindre aux `confirmed` est différé.

## Phasage

### Phase 1 — Refactor structurel pur (logique préservée)

- [ ] **Implémenter `decide_person_match`** dans `domain/persons/matching.py`. Signature :

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

- [ ] **Tests unitaires sur toutes les branches** de la cascade : match cross-source, match idref, match orcid, name_form single match, name_form ambiguous, name_form create, name_form skip (create interdit).
- [ ] **Refactor `create_persons_from_source_authorships.py`** : passer de 4 boucles à 1 boucle.
  - Prefetch des 4 lookups en début de `run` (déjà partiellement présent : `linked_index`, `idref_map`, `orcid_map`, `name_form_map`).
  - Une seule boucle sur `all_authorships`. Pour chaque authorship : calculer les 4 candidats, appeler `decide_person_match`, appliquer l'effet (`link_to_person` / `create_person` / `add_identifiers` / `add_name_form`).
  - Suppression des fonctions `step1_cross_source`, `step1b_idref`, `step2_orcid`, `step3_name_forms`.
- [ ] **Nettoyage** :
  - Docstring du module : retirer l'« Étape 4 : Personnes liées aux thèses » fantôme (jamais appelée par `run()`, cf. trou de couverture).
  - Lever au passage les 5 `Any` résiduels signalés par `CODE_chasse-aux-any` (les `all_authorships: Any` deviennent typés).
- [ ] **Tests d'intégration** adaptés à la nouvelle structure (1 boucle au lieu de 4 steps). Vérifier que les compteurs de fin de run restent comparables.

### Phase 2 — Peaufinage hiérarchie (post-refactor)

- [ ] **Ajout source dédiée ORCID Crossref** en tête. Soit nouveau paramètre dédié dans `decide_person_match` (`orcid_crossref_match`), soit map ORCID restreinte à `source = 'crossref'`.
- [ ] **Ajout `hal_person_id`** au niveau des identifiants (à côté d'IdRef). Sous-décision `decide_match_by_identifier(value, hal_account_map)` existe déjà — il suffit d'ajouter une map prefetch + un argument au décideur.
- [ ] **Retirer le matching ORCID hors Crossref**. Filtre côté `fetch_orcid_to_person_map` ou côté décideur.

## Questions ouvertes

- **Trou de couverture theses** : `BIBLIO_SOURCES = ("hal", "openalex", "wos", "scanr", "crossref")` exclut délibérément theses. Conséquence : aucune `source_authorship` theses n'a `in_perimeter = TRUE` (le mécanisme `set_in_perimeter_from_addresses` n'est appelé que pour `BIBLIO_SOURCES` dans `populate_affiliations.run_populate`). `fetch_unlinked_authorships` filtre `WHERE in_perimeter = TRUE`, donc les authorships theses ne passent jamais dans la cascade. Les rattachements visibles aujourd'hui (ex. personne 2557 liée à 8 thèses comme non-auteur) sont vestiges d'un état antérieur du code (commentaire trompeur `populate_affiliations.py:60` « in_perimeter est déjà à TRUE (posé par normalize_theses) »). À réexaminer après refactor : (a) pourquoi `BIBLIO_SOURCES` exclut-il theses initialement ? (b) conséquences d'inclure theses dans le périmètre standard sur les autres consommateurs (`application/authorships/core.py:VALID_SOURCES`, `domain/pipeline_modes.py`) ? (c) ajout à `BIBLIO_SOURCES` ou solution alternative (boucle dédiée theses dans `populate_affiliations`) ?

- **Matching cross-source sur méga-papers** : le seuil `MAX_AUTHORS_CROSS_SOURCE = 50` court-circuite le cross-source au-delà. Suffit-il, ou faut-il restreindre davantage ? Mesure préalable du ratio matchings utiles / faux positifs sur les papers à 30-50 auteurs encore couverts par le matching. À examiner après Phase 1.

- **Statuts `pending` vs `confirmed`** : aujourd'hui les deux sont utilisés indistinctement pour le matching. Restreindre aux `confirmed` réduirait le bruit mais fragiliserait la cascade sur des identifiers récents non encore validés. À reconsidérer plus tard.

- **Invariants métier dans la cascade** : faut-il intégrer `check_can_merge_persons` (jamais de fusion auto entre deux persons avec `persons_rh` distincts) comme partie de la cascade, ou le garder en pré-check côté admin/scripts seulement ? À trancher si Phase 2 produit des cas où la cascade rattacherait deux personnes RH-distinctes par identifier.

## Liens

- Pattern de référence (décision pure déjà en domain) : [`resolve_doi_conflict`](../../domain/publication.py)
- Briques sous-décisions déjà migrées : [`domain/persons/matching.py`](../../domain/persons/matching.py)
- Phase 5 de `CODE_rich-domain-model.md` (refactor `create_persons_from_source_authorships` côté entités) — débloquée après Phase 1 de ce chantier.
