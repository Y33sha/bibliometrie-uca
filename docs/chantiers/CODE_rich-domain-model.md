# Chantier — Domaine riche (entités métier)

Commencé le 2026-05-12

## Contexte

Le chantier `2026-05-12_CODE_purete-domain.md` a nettoyé la moitié du
diagnostic : `domain/` ne dépend plus de pydantic, les 10 `BaseModel`
sont exfiltrés vers `infrastructure/db/jsonb_models/`. Reste l'autre
moitié : **pas d'entités au sens DDD dans `domain/`**.

Inventaire actuel :

- **Value Objects** : `DOI`, `HALId`, `NNT` (`domain/publication.py`),
  `ORCID`, `IdHAL`, `IdRef` (`domain/persons/identifiers.py`).
- **Règles isolées** : `resolve_doi_conflict`, `best_oa_status`,
  `clean_publication_title` (`domain/publication.py`) ;
  `check_can_merge_persons` (`domain/persons/merge.py`) ;
  `decide_cross_source_match`, `decide_name_form_outcome`,
  `decide_match_by_identifier` (`domain/persons/matching.py`) ;
  `allow_person_creation` (`domain/persons/creation.py`) ;
  `names_compatible`, `compute_person_name_forms` (`domain/names.py`) ;
  `has_minimal_publication_metadata` (`domain/publications/dedup.py`).
- **Dataclasses de résultat de requête** : `PubByDoi`, `PubByNnt`,
  `PubByTitle`, `PubThesisCandidate` (`domain/publication.py`).
- **Zéro entité avec identité + comportement.** `domain/structure.py`
  est vide (commentaire d'amorce seulement).

Le schéma de base est bâti autour de **3 entités métier clairement
identifiables** (`publications`, `persons`, `structures`), mais aucune
classe ne les documente côté `domain/`. Architecture DDD bâtarde :
orientée métier dans la structure de dossiers, anaemic dans le
contenu — en deçà du standard "anaemic domain model = miroir de la
base" critiqué par Cosmic Python, qui aurait au moins ces classes
vides comme point d'appui.

**Conséquences observables :**

1. Le code applicatif manipule des `dict[str, Any]` et des `int`
   (cf. `application/pipeline/persons/create_persons_from_source_authorships.py`,
   `application/publications.py`).
2. Les invariants métier sont enforcés ponctuellement et de façon
   éparse (ex. `check_can_merge_persons` uniquement appelé avant la
   fusion ; `add_identifier` accepte silencieusement les doublons selon
   le statut, cf. `application/persons.py:125-141`).
3. Des effets de bord cachés vivent dans des fonctions applicatives
   (ex. `refresh_from_sources` qui fusionne des publications sur
   collision DOI sans le signaler dans son retour, cf.
   `application/publications.py:348-353`).
4. Plusieurs chantiers METIER_* à venir (`decide-person-match`,
   `dedup-fusion-publications`, `doc-types`, `crossref`,
   `doi-ra-datacite`) vont déposer de la logique métier — sans
   entités, elle atterrira dans `application/` ou comme fonctions
   libres dans `domain/`, perpétuant la dispersion.

## Décisions

1. **Cible architecturale — six aggregates roots** :
   - `Publication` (root) + `Authorship` (entité fille — schéma :
     `authorships.publication_id NOT NULL`)
   - `SourcePublication` (root) + `SourceAuthorship` (entité fille —
     schéma : `source_authorships.source_publication_id NOT NULL`)
   - `Person` (root) + `PersonRH` (entité fille pressentie, à
     confirmer)
   - `PersonIdentifier` (root)
   - `Structure` (root)
   - `AddressAffiliation` (root) + `StructureLink` (VO interne)

   Plus les VOs : `DOI`, `HALId`, `NNT`, `ORCID`, `IdHAL`, `IdRef`,
   `Address`, `PersonNameForm`, `StructureNameForm`. Les VOs
   s'utilisent en attributs/arguments des entités.
2. **`PersonIdentifier` est un aggregate à part, pas un VO sur
   `Person`.** Justification : (a) le statut `pending/confirmed/rejected`
   porte sur la *relation* identifier↔person, pas sur l'identifier nu,
   donc cette relation est un objet métier de premier rang ; (b)
   l'opération de réattribution (déplacer un identifier d'une Person à
   une autre quand l'ancien statut était `rejected`) charge et mute
   *l'identifier*, pas les deux Persons — le modèle aggregate-séparé
   collapse cette opération en un load + un save. Identité naturelle :
   `(id_type, id_value)`. `Person.identifiers: tuple[PersonIdentifier, ...]`
   reste possible comme **projection en lecture** hydratée par le
   `PersonRepository` à la demande, mais n'est pas la source de vérité
   des mutations.
3. **`SourcePublication` est un aggregate à part, pas une entité fille
   de `Publication`.** Justification : le lifecycle est autonome
   (schéma : `source_publications.publication_id` *nullable*) — une
   SourcePublication naît à l'extraction d'une source, peut vivre
   non-attachée pendant la dédup, puis s'attache. Attribut mutable
   `publication_id: int | None` ; méthodes `attach_to(pub_id)`,
   `reattach_to(new_pub_id)`. `Publication.source_publications` reste
   une projection lecture.
4. **`Authorship` et `SourceAuthorship` sont des entités filles**
   (sens DDD strict — lifecycle lié au root, accès via le root). Le
   schéma le tranche par les contraintes `NOT NULL` sur leurs FK
   parentales. Authorship vit dans `Publication`, SourceAuthorship
   vit dans `SourcePublication`.
5. **Address est décomposée en VO + aggregate.** `Address` (VO,
   défini par `normalized_text`) vit dans `domain/addresses/address.py`.
   `AddressAffiliation` (aggregate root, `domain/addresses/affiliation.py`)
   porte l'address VO + l'état de résolution (countries,
   suggested_countries, resolved_at, pub_count) + un
   `tuple[StructureLink, ...]`. `StructureLink` (VO interne, VO car
   pas de transition cross-aggregate, contrairement à
   `PersonIdentifier`) porte `(structure_id, matched_form_id,
   is_confirmed)`. Méthodes de `AddressAffiliation` :
   `confirm_structure`, `reject_structure`, `suggest_structure`,
   `mark_resolved`.
6. **`PersonNameForm` et `StructureNameForm` sont des VOs**, définis
   par contenu. Vivent dans `domain/persons/name_forms.py` et
   `domain/structures/name_forms.py`. *Nuance pour `PersonNameForm`* :
   la table `person_name_forms` (`name_form text + person_ids int[]`)
   est un index inverse dénormalisé pour le matching — pas un
   aggregate. Le domain VO est juste la string ; la mapping
   `form → persons` est une infrastructure de query.
7. **Approche progressive** : scaffolding minimal des entités (Phase 1), migration statique des règles vers leur module thématique (Phase 2), refactor des use-cases mono-aggregate (Phase 3), hydratation de Publication + orchestrations qui en dépendent (Phase 4), orchestrations Person (Phase 5), nettoyage des doublons (Phase 6), convention de transmission aux chantiers METIER_* (Phase 7), généralisation de l'hydratation aux autres entités (Phase 8, différée).
8. **Les dataclasses de résultat de requête ne sont pas des entités.**
   `PubByDoi`, `PubByNnt`, `PubByTitle`, `PubThesisCandidate` restent
   des projections de lecture (DTOs domain), distinctes des
   aggregates. Le caller charge une `Publication` quand il a besoin
   d'appeler du comportement métier ; il reçoit une `PubByDoi` quand
   il veut juste lire.
9. **Convention de transmission aux chantiers METIER_*** : ces
   chantiers documentent dans leur fiche la cible domain (méthode
   d'entité, VO, règle libre) avant de commencer à coder.
10. **Aggregates futurs hors scope** : `Publisher`, `Journal`,
    `Subject` (tables existantes mais peu de logique métier
    aujourd'hui — deviendront probablement des aggregates lors d'un
    chantier ultérieur dédié).

## Phasage

### Phase 1 — Scaffolding des entités (~1-2j)

**VOs (commencer par ici — plus simples, autonomes) :**

- [x] `domain/persons/name_forms.py` — VO `PersonNameForm` (frozen,
      identité = string normalisée). — `8675e10`
- [x] `domain/structures/name_forms.py` — VO `StructureNameForm`
      (frozen ; attributs : `form_text`, `is_word_boundary`,
      `is_excluding`, `requires_context_of: tuple[int, ...]`). — `8675e10`
- [x] `domain/addresses/address.py` — VO `Address` (frozen, identité
      = `normalized_text`). — `8675e10`
- [x] `domain/publications/identifiers.py` — migrer `DOI`, `HALId`,
      `NNT` depuis `domain/publication.py` (miroir de
      `domain/persons/identifiers.py`). `domain/publication.py` reste
      en place transitoirement comme façade ré-exportant ; suppression
      après refacto complet des callers.

**Aggregates roots :**

- [x] `domain/publications/publication.py` — classe `Publication`
      (identité `id`, identifiant naturel `doi` ; HALId/NNT vivent côté
      `source_publications.external_ids`, non portés par l'aggregate
      canonique. Métadonnées title/pub_year/doc_type/oa_status/…,
      composition d'`Authorship` en entités filles).
- [x] `domain/publications/authorship.py` — entité fille `Authorship`
      d'aggregate Publication. Identité `id`. Attributs : `person_id`,
      `author_position`, `in_perimeter`, `source_manual`, `excluded`,
      `is_corresponding`, `roles`, `structure_ids`, `notes`.
- [x] `domain/source_publications/source_publication.py` — aggregate
      root `SourcePublication`. Identité naturelle = `(source,
      source_id)`. Attribut mutable `publication_id: int | None`.
      Méthodes `attach_to(pub_id)`, `reattach_to(new_pub_id)`.
      Composition de `SourceAuthorship` en entités filles.
- [x] `domain/source_publications/source_authorship.py` — entité
      fille `SourceAuthorship`. Identité `id`. Attributs : `source`,
      `author_position`, `person_id`, `authorship_id`,
      `raw_author_name`, `author_name_normalized`,
      `person_identifiers` (jsonb), `source_structures`,
      `structure_ids`, `countries`, `in_perimeter`, `excluded`,
      `is_corresponding`, `roles`, `source_data`.
- [x] `domain/persons/person.py` — classe `Person` (identité `id`,
      `identifiers: tuple[PersonIdentifier, ...]` en projection lecture,
      `name_forms: tuple[PersonNameForm, ...]`). `hal_person_id` n'est
      pas attribut nu : c'est un `PersonIdentifier` d'`id_type` =
      `"hal_person_id"`.
- [x] `domain/persons/person_identifier.py` — aggregate root
      `PersonIdentifier` avec `id_type: str`, `id_value: str`,
      `person_id: int`, `status: AttributionStatus`, `source: str |
      None`. Méthodes `confirm()`, `reject()`, `reattribute_to(new_person_id,
      *, source)`. Exception `CannotReattributeError` (sous-classe
      `ConflictError`) si tentative depuis statut non-rejected.
- [x] `domain/structures/structure.py` — classe `Structure` (identité
      + `name_forms: tuple[StructureNameForm, ...]` + api_ids). Les
      relations hiérarchiques (`structure_relations`) ne sont pas
      portées par l'aggregate en Phase 1 (à scaffolder quand de la
      logique métier émergera dessus).
- [x] `domain/addresses/affiliation.py` — aggregate root
      `AddressAffiliation` + VO interne `StructureLink`. Attributs :
      `id`, `address: Address`, `raw_text`, `suggested_countries`,
      `countries`, `resolved_at`, `pub_count`, `structure_links:
      tuple[StructureLink, ...]`. Méthodes :
      `confirm_structure(structure_id)`,
      `reject_structure(structure_id)`,
      `suggest_structure(structure_id, matched_form_id)`,
      `mark_resolved(at: datetime)`. Le caller fournit le timestamp
      pour préserver la pureté.

**Invariants rapatriés :**

- [x] `Person.can_merge_with(other, *, has_distinct_rh)` (reprend
      `check_can_merge_persons` de `domain/persons/merge.py` ; doublon
      temporaire, suppression Phase 2). Signature avec `has_distinct_rh`
      kwarg en attendant le scaffolding `PersonRH`.
- [x] `Publication.has_minimal_metadata()` (reprend `has_minimal_publication_metadata` de `domain/publications/dedup.py`). Doublon temporaire en `dedup.py` ; suppression Phase 6.

**Convention + tests :**

- [x] En-tête de chaque fichier d'entité : phrase intemporelle du type
      « La logique métier touchant à <X> vit ici » (sans référence à
      des chantiers ou phases — règle générale docstrings).
- [x] Tests unitaires sur les constructeurs, les 2-3 invariants
      rapatriés, et les transitions de `PersonIdentifier`,
      `SourcePublication`, `AddressAffiliation` (confirm/reject/
      reattribute/attach + cas d'erreur).

### Phase 2 — Migration statique vers modules thématiques

Déplacement de règles isolées et de modules orphelins vers les subpackages d'aggregate. Pas de changement de comportement, juste l'emplacement du code.

#### Phase 2.1 — Règles isolées de `domain/publication.py` vers modules thématiques

Arbitrage par règle : méthode d'instance UNIQUEMENT pour les
comportements d'identité (entité agit sur elle-même). Les comparaisons
entre entités et les agrégations de valeurs sont des **domain
services** (free functions), à placer dans le module thématique
adéquat — pas à forcer en méthodes.

- [x] `domain/publication.py:resolve_doi_conflict` (+ `DoiConflictResolution`,
      `_CHAPTER_DOC_TYPES`, `_BOOK_DOC_TYPES`) → free function dans
      `domain/publications/dedup.py`. Justification : c'est une
      comparaison entre deux publications, pas une action d'identité ;
      les callers actuels passent des projections et des strings, pas
      des `Publication` (forcer en méthode obligerait à affaiblir les
      invariants de l'entité). — `6f231f5`
- [x] `domain/publication.py:best_oa_status` (+ `OA_RANK`,
      `OA_STATUS_UNKNOWN_DEFAULT`) + `domain/publication.py:clean_publication_title`
      (+ helpers `_decode_html_entities_once`, regex internes) →
      nouveau module `domain/publications/metadata.py` (catch-all
      pour les règles de métadonnées de publication sans meilleure
      cible). Justifications : agrégation de valeurs / utility string,
      sans état d'instance.
- [ ] `domain/persons/matching.py` (`decide_cross_source_match`,
      `decide_name_form_outcome`, `decide_match_by_identifier`) →
      déféré à `METIER_decide-person-match` qui refondra la cascade.

#### Phase 2.2 — Modules orphelins de `domain/` racine vers subpackages

Quelques modules historiques restaient à la racine de `domain/` alors qu'ils sont attachés à un aggregate. Déplacement vers la subpackage thématique, sur le même principe que la dispersion 2.1.

- [x] Supprimer `domain/structure.py` — placeholder vide, redondant
      avec `domain/structures/structure.py`, 0 caller.
- [x] `domain/names.py` → split :
  - `parse_raw_author_name`, `names_compatible`, `first_names_compatible`,
    `last_names_compatible` → `domain/persons/name_matching.py`
    (règles de comparaison de signatures).
  - `compute_person_name_forms` → ajout dans
    `domain/persons/name_forms.py` existant (factory de la VO
    `PersonNameForm` : les strings qu'elle produit sont les valeurs
    canoniques du VO).
- [x] `domain/doc_types.py` → `domain/publications/doc_types.py`
      (mapping des types de documents, attribut de Publication).
- [x] `domain/authorship_roles.py` → `domain/publications/authorship_roles.py`
      (rôles canoniques d'authorship, entité fille de Publication).
- [x] `domain/hal_domains.py` → `domain/sources/hal_domains.py`
      (référentiel HAL CCSD pour les sujets ; HAL est la seule source
      avec un référentiel en dur parce que ses codes sont opaques).
- [x] `domain/subject.py` → nouveau subpackage `domain/subjects/`
      (sujets sont un concept métier à part, méritent leur dossier
      sur le même modèle que `persons/`, `publications/`,
      `structures/`).

### Phase 3 — Use-cases mono-aggregate : pattern load → mutate → save

L'application charge un aggregate via le repository, appelle ses méthodes, sauvegarde. La logique métier vit dans l'aggregate ; le repository ne contient plus que la persistance.

- [x] `application/persons.py:add_identifier` (`PersonIdentifier`
      aggregate) — pilote du pattern : `repo.find_identifier(id_type,    id_value)`, dispatche (créer / idempotent / `reattribute_to` /
      `CannotAttributeConflict`), sauve. Ancien upsert SQL
      `repo.add_identifier` retiré du port + impl. Changement de
      comportement : cas pending/confirmed sur autre personne lève
      `CannotAttributeConflict` (sous-classe `ConflictError`, HTTP 409
      via handler existant) au lieu du silent no-op précédent. — `bd6f587`
- [x] `application/persons.py:add_identifiers_from_authorships` — itère désormais en déléguant chaque identifiant à `add_identifier` (qui charge / dispatche / sauvegarde via l'aggregate `PersonIdentifier`). Signature inchangée `(person_id, authorships: list[dict])` : le parsing dict→identifiant reste interne (path batch piloté par les dicts du pipeline). Tolérance au conflit : `CannotAttributeConflict` est loggé en warning et la promotion continue sur les autres identifiants — comportement adapté au batch pipeline, distinct du path strict de `add_identifier` utilisé par l'API admin.

### Phase 4 — Hydratation Publication et orchestrations larges autour de Publication

Les use-cases orchestrant Publication (fusion, find_or_create, refresh_from_sources) ne peuvent pas être refactorés tant que l'entité Publication ne sait pas se charger / se sauvegarder. Le premier item débloque les suivants en étendant l'entité, en ajoutant les méthodes de chargement / persistance au repo, et en rapatriant la règle d'enrichissement métadonnées depuis le SQL vers `Publication.absorb()`. Les autres entités (Person, Structure, SourcePublication) ne sont pas hydratées ici : ce chantier ne touche que Publication parce que c'est elle qui débloque la fin des orchestrations Publication. La généralisation est différée (Phase 8).

- [ ] **Hydratation de l'aggregate Publication** (préalable aux items suivants) : étendre l'entité Publication avec les attributs nécessaires aux opérations métier (`journal_id`, `language`, `container_title`, `countries` en plus du strict minimum scaffoldé en Phase 1), ajouter au repo une méthode de chargement `find_by_id(id) -> Publication | None` et une méthode de persistance `save(pub) -> None`, et déplacer la règle d'enrichissement métadonnées (pairwise OA, COALESCE des champs, union des countries) actuellement portée par le SQL de `repo.merge_into` vers une méthode `Publication.absorb(other)`.
- [ ] `application/publications.py:merge_publications` : load target + source via repo, `target.absorb(source)`, `repo.save(target)`, puis `repo.merge_into` réduit au plumbing FK + DELETE source.
- [ ] `application/publications.py:find_or_create` (l. 125-194) → refactor pour utiliser `Publication` en entrée/sortie. Coord avec `METIER_dedup-fusion-publications` (cascade dédup).
- [ ] `application/publications.py:refresh_from_sources` (fusion implicite l. 348-353 sur collision DOI) → rendre explicite : soit via `Publication.absorb()` une fois l'hydratation faite, soit via un retour `RefreshResult(absorbed_publication_id: int | None)` qui force le caller à gérer la collision.
- [ ] Helpers de `refresh_from_sources` (`_first_non_null`, `_merge_lists`, `_merge_jsonb`, `_first_doc_type`) — coord avec `METIER_dedup-fusion-publications` qui vise déjà à les exfiltrer vers `domain/publications/merge.py`.

### Phase 5 — Orchestrations Person

- [ ] `application/persons.py:merge_person` (orchestrateur l. 340-358) → autour de `Person.merge_with(other)`. Question à examiner : que deviennent les `PersonIdentifier` de la personne absorbée (`reattribute_to` pour chacun, conflits sur statuts `confirmed` à cadrer).
- [ ] `application/pipeline/persons/create_persons_from_source_authorships.py` — refactor de la cascade matching porté par `METIER_decide-person-match`. Ce chantier-ci s'arrête au point où la cascade manipule des `Person` et `PersonIdentifier` (au lieu de `int + dict`).

#### Structure (note)

Aucune logique métier identifiée actuellement au-delà du CRUD de `application/structures.py:35-212`. L'entité `Structure` reste un scaffold minimal. Si des règles émergent (validation `api_ids`, contraintes sur `structure_relations`, cycles interdits dans la hiérarchie, …), elles s'y déposent.

### Phase 6 — Cleanup des doublons

Une fois les callers de Phase 1 migrés vers les entités (Phases 3, 4, 5), les fonctions libres font doublon avec les méthodes d'aggregate. Suppression.

- [ ] `domain/publications/dedup.py:has_minimal_publication_metadata` — supprimer une fois les callers passés par `Publication.has_minimal_metadata()`.
- [ ] `domain/persons/merge.py:check_can_merge_persons` — supprimer une fois `application/persons.py:merge_person` migré vers `Person.can_merge_with(...)`. Le fichier `merge.py` devient vide et peut être supprimé.

### Phase 7 — Convention pour les chantiers METIER_*

- [ ] Documenter dans un fichier `docs/architecture.md` (ou compléter `CLAUDE.md`) que la logique métier touchant une entité doit y atterrir, et préciser le périmètre des aggregates.
- [ ] Mettre à jour `METIER_decide-person-match.md` : ajouter section « Cible domain » pointant `Person` + `domain/persons/matching.py`.
- [ ] Mettre à jour `METIER_dedup-fusion-publications.md` : idem, pointant `Publication` + `domain/publications/dedup.py` + `domain/publications/merge.py`.
- [ ] Mettre à jour `METIER_doc-types.md`, `METIER_crossref.md`, `METIER_doi-ra-datacite.md` quand ils démarreront — même principe.

### Phase 8 — Audit général des repositories (différé)

Généralisation de l'hydratation faite en Phase 4 pour Publication aux autres aggregates (Person, Structure, SourcePublication, AddressAffiliation). À instruire séparément quand on y arrivera. Hypothèse de travail (Laura) : les repositories sont majoritairement en écriture et ne renvoient rien ; à vérifier.

Audit préalable :

- [ ] Inventaire des méthodes de chaque repository (`infrastructure/repositories/`) : signature, type de retour, callers.
- [ ] Identifier les méthodes en lecture (renvoyant `dict`, dataclass, ou autre) — combien, où, vers quels callers.
- [ ] Décider du contrat : repos renvoient des entités par défaut OU ajout ciblé de méthodes `find_by_id(id) -> Entity` en complément des lectures projectives existantes (modèle retenu en Phase 4 pour Publication).
- [ ] Trancher la place de la conversion `row → entity` (au sein du repo, via un mapper dédié, via une classmethod d'entité ?).
- [ ] Coordonner avec les query services pour API (`application/ports/`) : ces derniers restent sur des DTOs de projection ; pas d'entités hydratées en lecture API.

Contenu détaillé à formaliser en phase d'instruction.

## Questions ouvertes

- **`PersonRH` : entité fille ou aggregate séparé ?** Tranché : 1:1
  avec Person, entité fille au sens DDD strict. Les dates start_date/
  end_date évoluent quand de nouvelles données SIHR arrivent. Non
  scaffoldée en Phase 1 (pas de logique métier identifiée) ; à ajouter
  quand `Person.can_merge_with` devient un self-check.
- **`authorships.person_id` nullable.** Aucune mutation prod ne pose
  cette colonne à NULL (cf. audit du `2026-05-12` : le build pipeline
  filtre `WHERE sa.person_id IS NOT NULL`, et les « orphan
  authorships » du code (`application/authorships/assign_orphans.py`)
  désignent en réalité des `source_authorships` orphelines — naming
  trompeur). Probablement un héritage mort. Mini-chantier de cohérence
  schéma `DATA_authorships_person_id_not_null` à instruire séparément
  (vérifier l'absence de rows NULL en prod, puis migration NOT NULL).
- **Coordination avec les chantiers METIER_*.** Démarrer Rich-Domain
  en entier d'abord garantit aux METIER_* une cible, mais Rich-Domain
  ne peut pas tester les invariants tant qu'on ne sait pas ce que les
  METIER_* y déposeront. Hypothèse de séquencement : terminer Phase 1
  + 2 de Rich-Domain, puis enchaîner avec un METIER_* en pilote
  (probablement `decide-person-match`), puis revenir compléter
  Rich-Domain au besoin.
- **`PubByDoi`, `PubByNnt`, … restent-elles dans `domain/`** ? Aujourd'hui oui. Si elles sont consommées par des query services qui sortent vers l'API frontend, peut-être plus naturel dans `application/ports/` ? À reconsidérer en Phase 8 quand on aura cartographié le rôle des repositories en lecture.
- **`clean_publication_title` et autres fonctions de canonicalisation** — tranché en Phase 2.1 : free function dans `domain/publications/metadata.py`. Utility string sans état d'instance, pas de gain à forcer en méthode.

## Liens

- Préalable : `2026-05-12_CODE_purete-domain.md` (pureté DDD,
  exfiltration pydantic).
- Chantier producteur de logique métier sur `Person` :
  `METIER_decide-person-match.md`.
- Chantier producteur de logique métier sur `Publication` :
  `METIER_dedup-fusion-publications.md`.
- Autres chantiers METIER_* qui enrichiront les entités :
  `METIER_doc-types.md`, `METIER_crossref.md`,
  `METIER_doi-ra-datacite.md`, `METIER_sujets-mots-cles.md`.
- Référence externe : Cosmic Python, ch. 1 (Domain Model) et ch. 5
  (TDD in the Domain Model).
