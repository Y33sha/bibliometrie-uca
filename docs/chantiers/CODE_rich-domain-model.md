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
7. **Approche progressive** : scaffolding minimal en Phase 1, puis
   rapatriement de la logique mûre en Phase 2, puis enrichissement
   délégué aux chantiers METIER_* en Phase 3, puis arbitrage sur les
   repositories en Phase 4.
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

- [ ] `domain/publications/publication.py` — classe `Publication`
      (identité `id`, identifiants naturels DOI/HALId/NNT, métadonnées
      title/pub_year/doc_type/oa_status/…, composition d'`Authorship`
      en entités filles).
- [ ] `domain/publications/authorship.py` — entité fille `Authorship`
      d'aggregate Publication. Identité `id`. Attributs : `person_id`,
      `author_position`, `in_perimeter`, `source_manual`, `excluded`,
      `is_corresponding`, `roles`, `structure_ids`, `notes`.
- [ ] `domain/source_publications/source_publication.py` — aggregate
      root `SourcePublication`. Identité naturelle = `(source,
      source_id)`. Attribut mutable `publication_id: int | None`.
      Méthodes `attach_to(pub_id)`, `reattach_to(new_pub_id)`.
      Composition de `SourceAuthorship` en entités filles.
- [ ] `domain/source_publications/source_authorship.py` — entité
      fille `SourceAuthorship`. Identité `id`. Attributs : `source`,
      `author_position`, `person_id`, `authorship_id`,
      `raw_author_name`, `author_name_normalized`,
      `person_identifiers` (jsonb), `source_structures`,
      `structure_ids`, `countries`, `in_perimeter`, `excluded`,
      `is_corresponding`, `roles`, `source_data`.
- [ ] `domain/persons/person.py` — classe `Person` (identité `id`,
      `hal_person_id`, `identifiers: tuple[PersonIdentifier, ...]` en
      projection lecture, `name_forms: tuple[PersonNameForm, ...]`).
- [ ] `domain/persons/person_identifier.py` — aggregate root
      `PersonIdentifier` avec `identifier: ORCID | IdHAL | IdRef`,
      `person_id: int`, `status: AttributionStatus`, `source: str`.
      Méthodes `confirm()`, `reject()`, `reattribute_to(new_person_id,
      *, source)`. Exception `CannotReattributeError` si tentative
      depuis statut non-rejected.
- [ ] `domain/structures/structure.py` — classe `Structure` (identité
      + `name_forms: tuple[StructureNameForm, ...]` + api_ids +
      relations).
- [ ] `domain/addresses/affiliation.py` — aggregate root
      `AddressAffiliation` + VO interne `StructureLink`. Attributs :
      `id`, `address: Address`, `suggested_countries`, `countries`,
      `resolved_at`, `pub_count`, `structure_links: tuple[StructureLink,
      ...]`. Méthodes : `confirm_structure(structure_id)`,
      `reject_structure(structure_id)`,
      `suggest_structure(structure_id, matched_form_id)`,
      `mark_resolved()`.

**Invariants rapatriés :**

- [ ] `Person.can_merge_with(other)` (reprend `check_can_merge_persons`
      de `domain/persons/merge.py`).
- [ ] `Publication.has_minimal_metadata()` (reprend
      `has_minimal_publication_metadata` de
      `domain/publications/dedup.py`).

**Convention + tests :**

- [ ] Documenter en en-tête de chaque fichier d'entité la convention
      « la logique métier touchant à <X> atterrit ici ; les chantiers
      METIER_* la déposent au fil de l'eau ».
- [ ] Tests unitaires sur les constructeurs, les 2-3 invariants
      rapatriés, et les transitions de `PersonIdentifier`,
      `SourcePublication`, `AddressAffiliation` (confirm/reject/
      reattribute/attach + cas d'erreur).

### Phase 2 — Rapatrier la logique éparpillée (~3-5j)

Chaque item est à examiner le moment venu : certains seront retenus,
d'autres déférés ou supprimés du scope. La liste est exhaustive sur
ce que l'audit a identifié comme candidat.

**Publication :**

- [ ] `domain/publications/dedup.py:has_minimal_publication_metadata`
      → méthode `Publication.has_minimal_metadata()` (déjà en Phase 1).
- [ ] `domain/publication.py:resolve_doi_conflict` → méthode
      `Publication.resolve_doi_conflict_with(other) -> DoiConflictResolution`.
- [ ] `domain/publication.py:best_oa_status` → méthode
      `Publication.compute_best_oa_status(source_statuses)` OU reste
      fonction pure (à arbitrer : agrégation de valeurs, pas
      comportement d'identité).
- [ ] `application/publications.py:refresh_from_sources` (fusion
      implicite l. 348-353 sur collision DOI) → rendre explicite : soit
      méthode `Publication.absorb(other)` qui retourne l'absorbé, soit
      retour `RefreshResult(merged_into: int | None)` qui force le
      caller à gérer la collision.
- [ ] Helpers de `refresh_from_sources` (`_first_non_null` l. 220-225,
      `_merge_lists` l. 228-237, `_merge_jsonb` l. 240-249,
      `_first_doc_type` l. 262-294) → à arbitrer : helpers neutres
      conservés OU regroupés dans `Publication.merge_source_rows(rows)`.
      **Coordination avec `METIER_dedup-fusion-publications`** : ce
      chantier vise déjà à exfiltrer ces helpers vers
      `domain/publications/merge.py`.
- [ ] `domain/publication.py:clean_publication_title` et helpers de
      décodage HTML (`_decode_html_entities_once`) → méthode
      `Publication.canonical_title()` OU règle libre maintenue.
      Question laissée ouverte par `2026-05-12_CODE_purete-domain.md`.
- [ ] `application/publications.py:find_or_create` (l. 125-194) →
      refactor pour utiliser `Publication` en entrée/sortie. NB :
      cascade de dédup elle-même visée par
      `METIER_dedup-fusion-publications` — coordonner.
- [ ] `application/publications.py:merge_publications` (l. 403-425) →
      réorganiser autour de `Publication.absorb(other)` ;
      l'orchestration SQL reste côté repository.

**Person :**

- [ ] `domain/persons/merge.py:check_can_merge_persons` → méthode
      `Person.can_merge_with(other)` (déjà en Phase 1).
- [ ] `application/persons.py:add_identifier` (l. 125-141, doublon
      silencieux selon le statut pending/confirmed/rejected) →
      orchestration applicative qui charge le `PersonIdentifier`
      existant via `PersonIdentifierRepository.find(identifier)` et
      dispatche : créer si absent, idempotent si déjà sur cette
      personne, `reattribute_to()` si rejected, lever
      `CannotAttributeConflict` sinon. La logique métier (transitions,
      invariants) est entièrement portée par l'aggregate
      `PersonIdentifier`.
- [ ] `application/persons.py:merge_person` (orchestrateur l. 340-358)
      → réorganiser autour de `Person.merge_with(other)` ;
      l'orchestration SQL des 7 étapes (cf.
      `infrastructure/repositories/person_repository/_core.py:68-144`)
      reste côté repository. À examiner : que deviennent les
      `PersonIdentifier` de la personne absorbée ? Probablement
      `reattribute_to(target_person_id)` pour chacun, mais les statuts
      `confirmed` posent question (conflit potentiel avec un identifier
      déjà sur la cible).
- [ ] `domain/persons/creation.py:allow_person_creation` → méthode
      d'entité ? Plutôt une décision liée à un contexte d'authorship
      qu'à une `Person` existante. À arbitrer : reste règle libre OU
      `Person.is_creatable_from(authorship_context)` classmethod.
- [ ] `domain/persons/matching.py` (`decide_cross_source_match`,
      `decide_name_form_outcome`, `decide_match_by_identifier`) → la
      cascade complète est portée par `METIER_decide-person-match` qui
      créera `decide_person_match`. La question ici : ces sous-décisions
      appartiennent-elles à `Person` ou restent-elles pures à côté ? À
      coordonner avec ce chantier.
- [ ] `domain/names.py` (`names_compatible`, `first_names_compatible`,
      `last_names_compatible`, `compute_person_name_forms`,
      `parse_raw_author_name`) → fonctions de comparaison/normalisation
      de noms. Restent libres (pas liées à l'identité d'une personne
      donnée) ; éventuellement, certaines deviennent des méthodes ou
      `classmethod` de `PersonNameForm` (ex.
      `PersonNameForm.is_compatible_with(other)`). À arbitrer item par
      item.
- [ ] `application/persons.py:add_identifiers_from_authorships`
      (l. 209-241) → refactor pour itérer sur des `PersonIdentifier`
      (création / réattribution via le repository d'aggregate) au lieu
      de `(int, list[dict])`.
- [ ] `application/pipeline/persons/create_persons_from_source_authorships.py`
      → le refactor de la cascade matching elle-même est porté par
      `METIER_decide-person-match`. Ce chantier-ci s'arrête au point où
      la cascade manipule des `Person` et `PersonIdentifier` (au lieu
      de `int + dict`).

**Structure :**

- [ ] Aucune logique métier identifiée actuellement au-delà du CRUD
      de `application/structures.py:35-212`. L'entité `Structure`
      reste un scaffold minimal. Si des règles émergent (validation
      `api_ids`, contraintes sur `structure_relations`,
      cycles interdits dans la hiérarchie, …), elles s'y déposent.

### Phase 3 — Convention pour les chantiers METIER_* (~0,5j, documentation)

- [ ] Documenter dans un fichier `docs/architecture.md` (ou compléter
      `CLAUDE.md`) que la logique métier touchant une entité doit y
      atterrir, et préciser le périmètre des aggregates.
- [ ] Mettre à jour `METIER_decide-person-match.md` : ajouter section
      « Cible domain » pointant `Person` + `domain/persons/matching.py`.
- [ ] Mettre à jour `METIER_dedup-fusion-publications.md` : idem,
      pointant `Publication` + `domain/publications/dedup.py` +
      `domain/publications/merge.py`.
- [ ] Mettre à jour `METIER_doc-types.md`, `METIER_crossref.md`,
      `METIER_doi-ra-datacite.md` quand ils démarreront — même
      principe.

### Phase 4 — Repositories et entités (à instruire le moment venu)

Phase à creuser quand on y arrivera. Hypothèse de travail (Laura) :
les repositories sont majoritairement en écriture et ne renvoient
rien ; à vérifier.

Audit préalable :

- [ ] Inventaire des méthodes de chaque repository
      (`infrastructure/repositories/`) : signature, type de retour,
      callers.
- [ ] Identifier les méthodes en lecture (renvoyant `dict`,
      dataclass, ou autre) — combien, où, vers quels callers.
- [ ] Décider du contrat : repos renvoient des entités par défaut OU
      ajout ciblé de méthodes `load_<entity>(id) -> Entity` en
      complément des lectures projectives existantes.
- [ ] Trancher la place de la conversion `row → entity` (au sein du
      repo, via un mapper dédié, via une classmethod d'entité ?).
- [ ] Coordonner avec les query services pour API
      (`application/ports/`) : ces derniers restent sur des DTOs de
      projection ; pas d'entités hydratées en lecture API.

Contenu détaillé à formaliser en phase d'instruction.

## Questions ouvertes

- **`PersonRH` : entité fille ou aggregate séparé ?** 1:1 avec Person,
  données SIHR sans lifecycle propre apparent — penche pour entité
  fille (sens DDD strict). À confirmer en lisant le schéma précis et
  les usages au démarrage de Phase 1.
- **Conflits de `PersonIdentifier` à la fusion de Persons.** Quand on
  fusionne A → B, les `PersonIdentifier` de A doivent être déplacés.
  Cas simples : confirmed sur A, absent sur B → réattribuer à B. Cas
  conflictuels : confirmed sur A ET sur B pour la même valeur
  (devrait être impossible par contrainte SQL, mais en théorie) ;
  rejected sur A et confirmed sur B (l'historique de rejet de A
  disparaît) ; etc. À cadrer en Phase 2 lors du refacto de
  `merge_person`.
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
- **`PubByDoi`, `PubByNnt`, … restent-elles dans `domain/`** ?
  Aujourd'hui oui. Si elles sont consommées par des query services
  qui sortent vers l'API frontend, peut-être plus naturel dans
  `application/ports/` ? À reconsidérer en Phase 4 quand on aura
  cartographié le rôle des repositories en lecture.
- **`clean_publication_title` et autres fonctions de canonicalisation**
  — méthode d'entité ou règle libre ? Laissée ouverte par
  `2026-05-12_CODE_purete-domain.md`, à trancher en Phase 2.

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
