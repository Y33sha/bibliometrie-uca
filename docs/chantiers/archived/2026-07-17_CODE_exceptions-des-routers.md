# Exceptions : démêler les `HTTPException` des routers

## Contexte

Les handlers d'exception d'`app.py` mappent une erreur métier vers un statut HTTP et un corps : les services lèvent les erreurs de `domain/errors.py`, et `NotFoundError`, `ValidationError`, `ConflictError` et leurs sœurs y trouvent leur statut. Les routers lèvent pourtant `HTTPException` en une trentaine d'endroits.

Ces trente occurrences ne relèvent pas d'un même cas — c'est leur tri qui fait ce chantier. Les unes traduisent une lecture vide et sont à leur place ; les autres portent des règles métier, des validations de corps de requête, ou masquent le handler global.

Treize traduisent une lecture qui n'a rien rendu. Le port déclare `get_journal_detail(id) -> JournalDetail | None`, le router reçoit `None` et répond 404. Aucune règle n'est violée : la requête n'a pas trouvé. Le contrat du port porte l'absence, et la traduire en statut est le travail de l'adaptateur HTTP.

Les autres portent des règles métier, et leur placement diverge selon l'entité. Deux règles gouvernent les fusions — refuser de fusionner une entité avec elle-même, refuser d'opérer sur une entité absente — et chacune vit dans une couche différente selon l'agrégat concerné.

| Entité | « pas avec soi-même » | « existe » |
| --- | --- | --- |
| Revues | `journals/core.py` → `ConflictError` → 409 | router → 404 |
| Éditeurs | `publishers/core.py` → `ConflictError` → 409 | router → 404 |
| Personnes | router → 400 | `persons/core.py` → `NotFoundError`, **et** router → 404 |
| Publications | router → 400 | `publications/core.py` → `NotFoundError`, **et** router → 404 |

Trois conséquences se constatent.

La même règle rend deux statuts. Fusionner une revue avec elle-même donne 409, une personne avec elle-même donne 400.

Un appelant qui n'est pas HTTP n'est pas tenu par les mêmes règles. Un script qui appelle `merge_person` directement fusionne une personne avec elle-même sans que rien ne l'arrête, là où `merge_journals` le lui refuse. Symétriquement, `merge_journals` sur un identifiant inexistant ne rencontre aucune garde applicative.

Là où le service valide déjà, le router valide une seconde fois. `persons/core.py` lève `NotFoundError` sur une personne absente, et sa docstring l'annonce ; le router interroge néanmoins `person_exists` deux fois avant de l'appeler. Ces deux allers-retours SQL produisent le 404 que le handler global produirait de toute façon.

Une seconde famille de contrôles vit dans les routers sans exister ailleurs : le nom obligatoire à la création d'une personne, écrit deux fois (`admin/persons.py` et `admin/authorships.py`) ; la valeur d'enum `journal_type` validée contre `JOURNAL_TYPES_SET` ; l'existence d'un code pays ; la présence d'un `country_code` non vide, que le modèle Pydantic déclare `str` et qui accepte donc la chaîne vide ; la restriction des types d'identifiant à ceux que l'interface expose.

Enfin, `admin/publication_duplicates.py` enveloppe la fusion dans un `try` qui remballe l'exception en `HTTPException(500, f"Échec de la fusion : {e}")`. `app.py` porte déjà un handler `Exception` qui répond 500 sans divulguer l'interne ; le wrapper est redondant et rend au client le message de l'exception.

Une seconde question, distincte du tri des exceptions, tient au contrat. Traduire une erreur en HTTP a deux moitiés : le mapping vers un statut et un corps à l'exécution, et la déclaration de ce couple sur la route, qui le fait entrer dans l'OpenAPI. Les handlers tiennent la première ; aucune route ne porte la seconde. Pour les erreurs à corps trivial (`{detail}`), elle ne manque à personne. Mais deux erreurs portent un corps structuré — `PublisherMergeBlockedError` (`blocking_journals`) et `RejectedPairError` (`rejected_pairs`) — que le frontend recopie à la main, faute de le trouver dans le contrat généré. La docstring de la fusion d'éditeurs entretient l'angle mort : elle annonce que deux revues homonymes fusionnent et tait le refus en bloc qui les concerne.

## Décisions

Les deux règles de fusion descendent dans les services, pour les quatre agrégats. Un service qui refuse de fusionner une revue avec elle-même et un service qui refuse de fusionner une personne avec elle-même sont le même geste : rien ne justifie que l'un le sache et l'autre l'ignore. Les routers cessent de pré-vérifier et laissent remonter.

L'auto-fusion rend 400 partout (`ValidationError`) : deux identifiants identiques dans une requête décrivent une requête malformée, non un conflit avec l'état courant.

Les treize traductions d'une lecture vide restent des `HTTPException`. C'est le seul endroit du router où HTTP est le sujet.

Le wrapper 500 de `admin/publication_duplicates.py` disparaît : le handler global fait ce qu'il prétend faire, et ne divulgue rien.

Les deux corps d'erreur structurés se déclarent. Un modèle Pydantic par corps (`interfaces/api/models/errors.py`), que le handler produit et que la route publie via `responses={409: ...}` : la forme s'écrit une fois, tenue à l'exécution comme au contrat. Les erreurs à corps trivial restent sans modèle, leur forme étant universelle. Le frontend lit les types générés.

Les contrôles descendent tous dans les services, y compris ceux que leur forme ferait passer pour de la validation de corps de requête. Le nom obligatoire est une règle métier — une personne sans patronyme n'existe pas, quel que soit l'appelant — et vaut aussi bien au renommage qu'à la création : il reste un 400. La restriction des types d'identifiant tient à la provenance et non à l'interface : `hal_person_id` est la référence d'un compte HAL, que l'extraction observe dans le TEI et que personne n'attribue à la main ; la garde porte donc sur `source="manual"`, dans le service.

Une vérification d'existence a sa place quand l'écriture référence l'entité sans la lire : une clé étrangère traduirait autrement son absence en erreur d'intégrité. Elle n'en a pas quand l'écriture est une mise à jour : le `rowcount` de l'`UPDATE` dit l'absence sans lecture préalable, et l'ignorer produisait des 200 silencieux sur une entité inexistante. Sur le chemin chaud de la phase `persons`, `add_identifier` boucle avec `source="auto"` sur une personne que la cascade vient de créer : la garde n'y court pas.

## Phasage

### Phase 1 — les fusions

- [x] `merge_person` et `merge_publications` refusent la fusion d'une entité avec elle-même.
- [x] `merge_journals` et `merge_publishers` lèvent `NotFoundError` sur une entité absente.
- [x] Les quatre routers de fusion retirent leurs pré-vérifications d'existence et leurs contrôles d'auto-fusion.
- [x] Tests : les quatre agrégats rendent le même statut sur la même règle, et un appel direct au service est tenu par les mêmes gardes.

### Phase 2 — les contrôles des routers

- [x] Nom obligatoire porté par `persons/core.py`, en un seul endroit, à la création comme au renommage.
- [x] Existence d'un code pays et validité de `journal_type` descendues dans les services.
- [x] Restriction des types d'identifiant portée par `add_identifier`, conditionnée à `source="manual"`.
- [x] `set_countries` et `update_name` lèvent `NotFoundError` sur un `rowcount` nul.
- [x] Les vérifications d'existence des cibles de `reassign_identifier` et des assignations de signatures orphelines descendent dans les services.
- [x] Les routers concernés retirent les contrôles correspondants ; les ports `person_exists` et `address_exists` disparaissent faute d'appelant.

### Phase 3 — le wrapper 500

- [x] `admin/publication_duplicates.py` laisse remonter jusqu'au handler global.
- [x] Vérifier qu'aucune réponse d'erreur ne rend le message d'une exception au client.

### Phase 4 — le contrat des erreurs structurées

- [x] `PublisherMergeBlockedResponse` et `RejectedPairsResponse` dans `interfaces/api/models/errors.py`, produits par les handlers d'`app.py`.
- [x] Les trois routes concernées — fusion d'éditeurs, attribution et attribution en lot de signatures orphelines — déclarent leur 409 via `responses={}`.
- [x] Le frontend (pages éditeurs et signatures orphelines) lit les types générés, plutôt que de réécrire `BlockingJournal` et `RejectedPair`.
- [x] La docstring de la fusion d'éditeurs décrit le refus en bloc et son 409 ; le commentaire d'`app.py` distingue le mapping runtime du contrat (`5a8cfc99`).

## Questions ouvertes

- `admin/authorships.py` exige « `person_id` ou `create_person` », invariant qui porte sur le corps entier plutôt que sur un champ. La règle vit dans le command handler, qui compose les deux agrégats ; un validateur de modèle Pydantic l'exprimerait aussi.
