# Règles métier retenues dans les routers HTTP

## Contexte

`app.py` déclare que ses handlers d'exception sont le seul endroit où une erreur métier devient un code HTTP : les services lèvent les erreurs de `domain/errors.py`, et `NotFoundError`, `ValidationError`, `ConflictError` et leurs sœurs y trouvent leur statut. Les routers lèvent pourtant `HTTPException` en une trentaine d'endroits.

Ces trente occurrences ne relèvent pas d'un même cas.

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

Une seconde famille de contrôles vit dans les routers sans exister ailleurs : le nom obligatoire à la création d'une personne, écrit deux fois (`admin/persons.py` et `admin/authorships.py`) ; la valeur d'enum `journal_type` validée contre `JOURNAL_TYPES_SET` ; l'existence d'un code pays ; la présence d'un `country_code` non vide, que le modèle Pydantic déclare `str` et qui accepte donc la chaîne vide.

Enfin, `admin/publication_duplicates.py` enveloppe la fusion dans un `try` qui remballe l'exception en `HTTPException(500, f"Échec de la fusion : {e}")`. `app.py` porte déjà un handler `Exception` qui répond 500 sans divulguer l'interne ; le wrapper est redondant et rend au client le message de l'exception.

## Décisions

Les deux règles de fusion descendent dans les services, pour les quatre agrégats. Un service qui refuse de fusionner une revue avec elle-même et un service qui refuse de fusionner une personne avec elle-même sont le même geste : rien ne justifie que l'un le sache et l'autre l'ignore. Les routers cessent de pré-vérifier et laissent remonter.

Les treize traductions d'une lecture vide restent des `HTTPException`. C'est le seul endroit du router où HTTP est le sujet.

Le wrapper 500 de `admin/publication_duplicates.py` disparaît : le handler global fait ce qu'il prétend faire, et ne divulgue rien.

Les contrôles de forme du corps de requête — nom non vide, `country_code` non vide — reviennent aux modèles Pydantic, qui sont faits pour ça et qui rendent un 422 documenté dans le contrat. Les contrôles référentiels — le code pays existe, la valeur d'enum est connue — descendent dans les services avec les règles de fusion.

Hors périmètre : la politique d'interface de `admin/persons.py`, qui restreint les types d'identifiant à ceux que l'interface expose. Elle porte sur ce que l'interface accepte, non sur ce que le domaine permet, et sa place est bien le router.

## Phasage

### Phase 1 — les fusions

- [ ] `merge_person` et `merge_publications` refusent la fusion d'une entité avec elle-même.
- [ ] `merge_journals` et `merge_publishers` lèvent `NotFoundError` sur une entité absente.
- [ ] Les quatre routers de fusion retirent leurs pré-vérifications d'existence et leurs contrôles d'auto-fusion.
- [ ] Tests : les quatre agrégats rendent le même statut sur la même règle, et un appel direct au service est tenu par les mêmes gardes.

### Phase 2 — la validation des corps de requête

- [ ] Nom non vide et `country_code` non vide portés par les modèles Pydantic, en un seul endroit.
- [ ] Existence d'un code pays et validité d'une valeur d'enum descendues dans les services.
- [ ] Les routers concernés retirent les contrôles correspondants.

### Phase 3 — le wrapper 500

- [ ] `admin/publication_duplicates.py` laisse remonter jusqu'au handler global.
- [ ] Vérifier qu'aucune réponse d'erreur ne rend le message d'une exception au client.

## Questions ouvertes

- Le statut de l'auto-fusion. Les revues et les éditeurs rendent 409 (`ConflictError`), les personnes et les publications 400. Deux identifiants identiques dans une requête relèvent de la requête malformée plutôt que du conflit avec l'état courant, ce qui plaide pour `ValidationError` et 400 ; mais le 409 est en place et le frontend le traite peut-être. Trancher avant d'uniformiser.
- Le passage du nom obligatoire à Pydantic change le statut de 400 à 422. À vérifier côté frontend, qui distingue peut-être les deux.
- `admin/authorships.py` exige « `person_id` ou `create_person` », invariant qui porte sur le corps entier plutôt que sur un champ. Un validateur de modèle l'exprimerait ; reste à voir si le gain vaut l'indirection.
