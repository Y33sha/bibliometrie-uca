# Brancher le domaine riche orphelin

Commencé le 2026-06-29

## Contexte

Un audit du code non appelé (vulture + vérification manuelle de chaque candidat) révèle que la quasi-totalité des symboles « morts » ne sont pas inutiles : ce sont des constructions de domaine riche (value objects, aggregate, invariants métier) et des mappings canoniques qui encodent une intention de modélisation mais qu'aucune couche applicative ni infrastructure n'appelle.

La distinction structurante est entre le code mort *par obsolescence* (à supprimer) et le code factuellement mort *qui gagnerait à être ressuscité* (à brancher). Le seul cas d'obsolescence — `get_last_report_date`, supplanté par `get_last_extract_date` sur `pipeline_phase_executions` — est déjà retiré. Tout le reste relève du branchement.

Le motif de fond : la couche domaine offre des contrats stricts (VOs auto-validés au contrat `X("...")` strict / `X.try_parse(...)` tolérant), un vocabulaire canonique et des transitions d'état explicites, pendant que le pipeline et l'infrastructure font le même travail en SQL ou en validation ad hoc. Brancher le domaine supprime cette divergence et fait du domaine la source de vérité.

## Décisions

- Ne pas supprimer le domaine riche orphelin : le brancher, ou — au cas par cas — acter explicitement qu'une logique reste en SQL/infra et retirer alors le pendant domaine devenu redondant (avec ses tests).
- Chaque item ci-dessous est un choix binaire « brancher » vs « acter le retrait », à trancher à l'examen du site d'appel pertinent.
- Validation des rôles d'authorship : applicative seule (garde-fou au chargement contre `AUTHORSHIP_ROLES`), sans contrainte ni enum en base. `roles` n'a pas de writer libre — seul le pipeline l'écrit via les mappings gardés — donc une contrainte en base ne protégerait d'aucun écrivain réel, au prix d'une duplication SQL du vocabulaire ou d'une migration array-of-enum.

## Phasage

### Value objects des identifiants personne

`ORCID`, `IdHAL`, `IdRef` (`domain/persons/identifiers.py`) sont auto-validés mais jamais instanciés ; seules les fonctions `normalize_*` du même module servent (pipeline).

- [x] VO `HalPersonId` ajouté : les quatre `PERSON_IDENTIFIER_TYPES` ont un value object, le dispatch est total (plus de type sans validation).
- [x] Dispatch `normalized_identifier_value(id_type, raw)` branché dans l'entonnoir d'écriture unique `add_identifier`, qui valide et normalise avant lookup et insertion. Couvre l'ajout manuel (API admin) et la promotion canonique (pipeline) sans duplication.
- [x] Validation ad hoc du router supprimée (regex ORCID locale, strip d'URL partiel) ; `ValidationError → 400`.
- [x] Politique par appelant : strict côté API (4xx) ; tolérant côté pipeline (`add_identifiers_from_authorships` loggue « identifiant mal formé » et poursuit).
- [x] Réduire la duplication résiduelle : `add_identifier` porte l'issue de sa cascade (`AddIdentifierResult`) ; le router traduit l'issue en réponse sans refaire ni lookup ni décision. Le SQL brut disparaît entièrement du router (la route de fusion passe aussi par `person_exists`).

### Vocabulaire canonique des rôles d'authorship

`AUTHORSHIP_ROLES` (`domain/publications/authorship_roles.py`) est le vocabulaire canonique, mais rien ne garantit que les mappings par source (`_HAL_MAP`, `_WOS_MAP`, `_SCANR_MAP`, `THESES_FIELD_ROLES`) ne produisent que des valeurs de cet ensemble.

- [x] Garde-fou : assertion au chargement du module vérifiant que tout rôle produit par les mappings (`_SOURCE_MAPS`, `THESES_FIELD_ROLES`) appartient à `AUTHORSHIP_ROLES`. Une faute de frappe dans un mapping fait échouer l'import.

### Type de document canonique HAL

`derive_hal_doc_type` (`domain/sources/hal.py`) doublait le mapping canonique ; le normalizer HAL stocke délibérément le `doc_type` brut et ne l'appelait pas.

- [x] Retiré : supplanté par le résolveur générique `map_doc_type`, branché dans la phase `metadata_correction` pour toutes les sources. Le brancher aurait ré-introduit un cas particulier HAL dans une résolution volontairement source-agnostique.

### Transitions d'état d'une attribution d'identifiant

`PersonIdentifier.confirm` / `reject` (`domain/persons/person_identifier.py`) doublaient les transitions de `AttributionStatus`, faites par `update_identifier_status`.

- [x] Acté : la transition de statut reste portée par `update_identifier_status` (UPDATE ciblé, validé par l'enum Postgres, retournant la ligne d'audit). `confirm`/`reject` étaient des setters sans garde — retirés avec leurs tests. `reattribute_to` (garde `REJECTED → PENDING`) reste.

### Aggregate de résolution d'adresse

`AddressAffiliation` + `StructureLink` et ses méthodes (`confirm_structure`, `reject_structure`, `suggest_structure`) formaient un aggregate jamais hydraté ; la résolution adresse → structure se fait en SQL/infra.

- [x] Retiré (aggregate, VO interne, tests). La résolution reste en SQL/infra : le pipeline `affiliations` la fait en masse, et les attributions manuelles admin passent par `review_structure_link` / `batch_review_structure_link` — upserts ciblés/batch `(address_id, structure_id)` retournant le delta de contribution à `in_perimeter`, que l'aggregate ne modélise pas. Aucun use-case, dans le pipeline ni dans l'interface, ne justifie l'hydratation.

### Invariants, projections et helpers orphelins

- [x] `Publication.has_minimal_metadata` : retiré. L'aggregate n'est hydraté qu'en lecture ; titre et année sont déjà garantis en amont (les normalizers refusent un record sans année ou sans titre, `pub_year` est `NOT NULL`). Une contrainte `NOT NULL` sur le titre s'ajoutera si le besoin se concrétise.
- [x] `CorrectedFields.is_empty` : retiré. Annoncé comme « fast-path des callers », mais aucun caller ne l'utilise ni n'a de fast-path nette (ils inspectent des champs précis et font du travail spécifique même sans correction).
- [x] `parse_locations` retiré : seul orphelin du module. Le balayage multi-locations utile (hal-id, related_dois) est déjà câblé via `extract_hal_id_from_url` sur toutes les locations (`normalize` → `external_ids`, puis cross-import). Les prédicats `is_hal_location` / `is_repository_location` restent : ils servent `should_skip_publisher_journal`, branché dans `normalize`.
- [x] `applicable_facets` retiré : règle de présentation, pas du domaine. Le registre des dimensions (la vraie source de vérité) est déjà exposé via `pivotSchema` ; le frontend dérive la barre de facettes côté vue, là où l'état de groupement est connu. Calculer cette soustraction triviale côté serveur imposerait un aller-retour par interaction.
- [x] `hal_domain_path` retiré (aucun cas d'usage ; les sujets HAL s'affichent via le libellé feuille `hal_domain_label`). Retiré aussi des gabarits `HEADER`/`FOOTER` du générateur `refresh_hal_domain_labels.py` pour qu'une régénération ne le réintroduise pas.
- [x] `AuthorshipRepository.find_by_publication_id` retiré (port, impl, helpers de projection, tests) : aucune opération de domaine ne manipule des aggregates `Authorship` par publication (affichage par projections SQL, construction set-based).
- [x] `PublicationRepository.are_distinct` retiré (port, impl). Il portait sur des publications canoniques — entités *dérivées* et instables. La vraie intention (« ces deux `source_publications` réfèrent à des objets différents, ne pas créer d'arête ») se situe au niveau `source_publications`, pas ici, et l'exclusion des paires déjà marquées distinctes se fait en SQL ensembliste côté liste. La refonte à venir de la gestion admin des publications (disparition probable de `admin/duplicates`, comme `person-duplicates`) confirme le sens du retrait.

### Complétude de convention

- [x] `DOI_SEARCHABLE_SOURCES_SET` retiré : aucun consommateur (les usages de la liste sont des sets de travail mutables et de l'itération ordonnée, pas des tests d'appartenance). Pas d'abstraction spéculative ; une constante `*_SEARCHABLE_SOURCES_SET` par famille d'identifiants se rétablira si le cross-import se généralise (arXiv, PMID…).
