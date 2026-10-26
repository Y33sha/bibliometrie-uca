# Chantier — Simplification des services applicatifs et de leurs ports

## Contexte

Une écriture de l'API est une fonction de `application/services/`, sans commit : la requête commite à son terme, avec ses événements d'audit (`db_conn`). Une relecture de `application/` relève les sources de complexité suivantes.

### Services

- Les ports de recalcul du pipeline (`PerimeterStructures`, `SerialRecompute`, `PublicationPerimeterRecompute`, `PublicationCountRecompute`, `CountryRecompute`) sont des instances uniques, qui reçoivent `conn` à chaque appel. Les services prennent donc `conn` pour le seul transmettre. Les repositories, eux, sont construits sur la connexion de la requête.
- Chaque route d'écriture déclare de 3 à 6 dépendances pour fournir au service ses repositories et ses ports.
- `structures._to_row` compose la ligne de réponse de l'API : `structure_type` sous le nom `type`, identifiants en chaînes.
- `create_structure` reçoit 8 paramètres séparés, `create_name_form` 5. Leurs mises à jour reçoivent le modèle typé (`StructureUpdate`, `NameFormUpdate`). Un champ ajouté touche le modèle, le routeur, le service et le domaine.
- `load_merge_pair` charge les deux agrégats d'une fusion pour en vérifier l'existence. Ses trois appelants ignorent le couple chargé. Pour une personne, l'agrégat contient ses identifiants et ses formes de nom.
- Détails :
  - `persons.py` définit un `logger` qu'il n'utilise pas ;
  - `update_identifier_status` et `update_name_form_status` typent le statut en `str`, et le comparent l'un à `AttributionStatus.REJECTED.value`, l'autre à `"rejected"`. Le routeur transmet un `AttributionStatus` ;
  - `create_tutelle` recalcule la clôture des périmètres quand la tutelle existait déjà ;
  - `set_country` rend `[address_id]` ;
  - les deux propagations qui suivent une écriture d'adresse vivent dans deux paquets : celle des pays dans `addresses/countries.py`, celle d'`in_perimeter` dans `contributions/core.py`.
- Docstrings : plaidoyers (module `publishers`, `_merge`), renvoi au module voisin (module `serials`), description périmée de l'aperçu dans `requalify_publications_for_serial`, retours à la ligne non sémantiques dans `_resolve_rejection`.

### Ports

- Aucun port n'a de seconde implémentation, doublure de test comprise : les tests passent par la base.
- Les 18 ports de lecture (`application/ports/read_models/`) sont lus, pour 14 d'entre eux, par un seul routeur. Seul `ConfigQueries` sert aussi à un service. Une lecture est déclarée trois fois : méthode du `Protocol`, le plus souvent sans docstring ; méthode de la classe `Pg…` ; fonction du module de l'adaptateur. 29 des 96 méthodes `Pg…` des lectures, et 17 des 65 des repositories, délèguent en une ligne à une fonction, à laquelle elles passent la connexion.
- Les modèles Pydantic des ports de lecture sont les réponses de l'API (`PersonProfileResponse`, `PersonOut`…), construites par l'infrastructure et rendues par les routeurs.
- Les docstrings des ports de repositories décrivent l'implémentation (tables, `ILIKE`, `pinned_groups_sql`) et nomment des modèles de réponse de l'API (`StructureOut`, `NameFormStatusResponse`).
- Docstrings fausses : `ports/repositories/__init__.py` cite des repositories `Publication` et `DoiPrefix`, absents des ports ; `PublisherRepository` annonce un enrichissement des pays, sous un intertitre vide.
- Les docstrings de module des ports de lecture nomment leur unique consommateur (« consommé par le router … ») ; celle de `_common.py` plaide son emplacement.
- `ports/pipeline/phase_executions.py` ne déclare aucun port. Il contient les structures d'une exécution de phase, que l'orchestrateur du pipeline, l'observabilité et la lecture des exécutions par l'API partagent. Le pipeline importe `application` pour elles.

## Décisions

- Les ports de recalcul sont construits sur la connexion de la requête par les fabriques de `interfaces/api/deps.py`, comme les repositories. Leurs méthodes perdent le paramètre `conn`.
- Le service rend l'agrégat ; le routeur compose la réponse.
- Les créations de structure et de forme de nom reçoivent un modèle typé, déclaré dans le port comme `StructureUpdate`.
- Les mises à jour des éditeurs et des périmètres gardent leur forme : un `edit` de l'agrégat, sur le modèle de `Serial.edit`, coûterait plus qu'il ne simplifie.
- La vérification d'existence des fusions rend `None`.
- Hexagone pour les écritures, lectures directes (séparation lecture/écriture). Une lecture de l'API est un adaptateur de `infrastructure/read_models/`, qui déclare ses modèles de réponse ; le router le reçoit sans port.
- Chaque agrégat a un objet de service, qui reçoit ses repositories et ses recalculs à la construction. Une fabrique de `deps.py` le construit sur une connexion ; une route d'écriture reçoit seulement le service.
- La docstring d'un port décrit le contrat : ce que la méthode rend et lève, sans tables ni requêtes, sans modèle de réponse de l'API.
- Le statut, les signaux et les métriques d'une exécution de phase vont dans `domain/pipeline_runs.py`, que le pipeline, l'infrastructure et `application/` importent tous trois. `PhaseExecution` va dans `infrastructure/observability/phase_executions.py`, son seul utilisateur. Le pipeline importe alors `domain/` et l'infrastructure, sans exception pour `application/`.

## Phasage

### Phase 1 — Ports de recalcul liés à la connexion

- [x] Ports de `application/ports/pipeline/` sans paramètre `conn` (`2ec48058f`)
- [x] Adaptateurs exposés par `pipeline/public.py` construits sur une connexion. Seuls l'API et les scripts les instancient ; le pipeline appelle les fonctions qu'ils enveloppent
- [x] Fabriques de `deps.py` sur `DbConn` ; tâches de fond sur leur propre connexion
- [x] `conn` retiré des services et des routes, sauf l'aperçu du changement de type de revue (savepoint)

### Phase 2 — Retouches sans décision de fond

- [x] `load_merge_pair` en vérification d'existence, sans retour (`977c4bb60`)
- [x] Statuts typés `AttributionStatus` dans `persons.py` ; `logger` inutilisé retiré
- [x] `create_tutelle` : recalcul de la clôture seulement pour une tutelle créée
- [x] `set_country` sans liste artificielle en retour
- [x] Propagations consécutives à une écriture d'adresse réunies

### Phase 3 — Frontière entre service et interface

- [x] `_to_row` remplacé par la composition de `StructureOut` dans le routeur (`bb68f4aea`)
- [x] `StructureCreate` et `NameFormCreate` dans le port, reçus par `create_structure` et `create_name_form`

### Phase 4 — Docstrings

- [x] Docstrings fausses des ports corrigées
- [x] Docstrings des ports de repositories réduites au contrat
- [x] Relecture de style de `application/`

### Phase 5 — Compte rendu d'exécution des phases

- [x] Vocabulaire d'une exécution de phase dans `domain/pipeline_runs.py`, `PhaseExecution` dans l'infrastructure ; exception `pipeline.** -> application.ports.**` retirée du contrat d'import
- [x] `PhaseStatus` en `StrEnum` ; statut d'un run calculé par `worst_status` (domaine), seule déclaration de la règle

### Phase 6 — Un objet de service par agrégat

- [x] `PersonService` (`c4cedae14`)
- [x] `ContributionService` : rejet et attribution des contributions orphelines réunis dans un module (`bf0fe23b2`)
- [x] `SerialService` et `PublisherService` ; les scripts ponctuels construisent leurs services par les fabriques de `deps.py` (`73e0c5acd`)
- [x] `StructureService` et `PerimeterService` (`b2785cb87`)
- [x] `AddressService`, tâches de fond comprises, et `ConfigService` ; `deps.py` sépare lectures et écritures (`280e5be75`)
- [x] Documentation d'architecture

### Phase 7 — Lectures directes, sans ports

- [x] `PerimeterService` consulte la configuration par `ConfigRepository` (`63c68ec43`)
- [x] Une lecture par paquet de `infrastructure/read_models/`, modèles de réponse dans `models.py` ; `Protocol` de lecture supprimés, classes `Pg…` renommées ; contrats d'import et documentation d'architecture
- [ ] Une seule déclaration par lecture : la requête dans la méthode de la classe, sans fonction relayée

## Questions ouvertes

(aucune)
