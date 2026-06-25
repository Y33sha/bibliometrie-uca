# Chantier — Écritures API : frontière transactionnelle (commit avant réponse)

Commencé le 2026-06-24

## Contexte

FastAPI exécute la phase de nettoyage (« teardown » : le code après le `yield`) des dépendances `yield` **après** l'envoi de la réponse. Vérifié dans la source installée (`fastapi 0.136.3`, `starlette 1.3.1`) : `await response(...)` — qui envoie le corps puis exécute les `BackgroundTasks` — a lieu à l'intérieur de l'`AsyncExitStack` portant les dépendances `yield` ; cette pile ne se ferme (ne déclenche les teardowns) qu'ensuite. L'ordre effectif d'une écriture est donc :

```
écriture (non commitée) → réponse envoyée → BackgroundTasks → commit
```

[`db_conn_sync`](../../interfaces/api/deps.py) ouvrait `engine.begin()` : le commit avait lieu au teardown, donc après l'envoi de la réponse. Conséquences (isolation PostgreSQL « read committed », chaque requête/tâche ouvre sa propre connexion) : un GET déclenché par le client juste après le POST lit l'état **pré-commit** (« mise à jour à retardement ») ; une `BackgroundTask` (propagation des pays) s'exécute **avant** le commit, sur sa propre connexion, et lit aussi du pré-commit.

**La racine n'est pas le timing, c'est une frontière transactionnelle manquante.** La doc d'architecture ([discipline transactionnelle](../architecture/04-infrastructure.md)) pose la règle Cosmic Python : les repositories ne committent jamais ; **le commit est la prérogative du use case** qui possède l'unité de travail. La règle est appliquée pour le pipeline (chaque orchestrateur de phase commit) mais **muette pour les écritures API** : aucun propriétaire d'unité de travail côté application, c'est la dépendance DI (`engine.begin`) qui commit par défaut — au mauvais moment. C'est ce trou qui produit le symptôme.

On ne peut pas faire committer les fonctions d'écriture fines (`application/persons.py`, `structures.py`, `addresses/countries.py`, `publishers.py`…) : elles prennent un `repo`, sont **transaction-agnostiques par conception** et **réutilisées** depuis l'API, le pipeline et les CLI (vérifié). Les faire committer casserait le batching pipeline/CLI. Ce sont des briques, pas des frontières.

Surface : ~36 endpoints d'écriture (POST/PUT/PATCH/DELETE) sur 11 routers (publishers, journals, structures, persons, perimeters, authorships, publication_duplicates, person_duplicates, addresses, pipeline_config, auth). Symptôme d'origine : page `admin/countries`, mises à jour à retardement sur les chemins qui rechargent après écriture.

`auth` n'a pas besoin d'audit manuel : le garde-fou de la Décision 5 répond à sa place. `logout` ne pose qu'un cookie (aucune écriture base) → muet. Si `login` écrit une session / un refresh-token, ou s'il existe un changement de mot de passe, ces chemins **émettent du DML** → le garde-fou les signale et ils entrent dans la liste de migration. On observe ce qu'écrit `auth` au lieu de le présumer.

## Décisions

1. **Frontière transactionnelle = un command handler par écriture API**, dans la couche application. Une écriture API est une *commande* (intention d'un acteur, courte) — distincte de l'orchestrateur de phase pipeline (longue, batchée). Le command handler reçoit la connexion de la requête + les ports (repos/queries), compose les fonctions d'écriture fines, et `conn.commit()` au succès. Les briques partagées restent agnostiques (composition pipeline/CLI préservée). Aucune décision de persistance ne descend dans `interfaces/api`.

2. **Unit of Work en forme fonction**, pas en objet. Le command handler *est* l'unité de travail (comme les orchestrateurs pipeline le sont déjà sous forme de fonction). On ne réifie pas (`class UnitOfWork`, registry de repos `uow.persons`/`uow.addresses`, fakes) ; l'upgrade fonction→objet est mécanique le jour venu — aucune porte fermée. Le **vrai déclencheur** de réification n'est pas la verbosité du câblage mais la **composition transactionnelle** de command handlers : tant qu'une écriture = un command handler = un commit, l'invariant tient ; le jour où un handler en appelle un autre qui commit, ou qu'un endpoint doit composer deux intentions en une seule transaction, la fonction ne sait plus répondre « suis-je le propriétaire externe ? ». C'est ce que l'objet UoW passé en paramètre résout. À réifier à ce moment-là, pas avant (cf. Questions ouvertes).

3. **Le routeur redevient mince** : parse → appelle le command handler → enregistre les `BackgroundTasks` (concern transport, légitime ici) → `return`. Le command handler ayant commité avant de rendre la main, le commit précède le `return`, donc l'envoi de la réponse **et** les `BackgroundTasks`.

4. **Découpage transaction vs tâche de fond, décidé par écriture.** Ce qui est une conséquence atomique de l'écriture vit dans le command handler (même transaction) ; ce qui tolère une fenêtre reste `BackgroundTask`. Pour la propagation des pays / `in_perimeter` : **reste en tâche de fond** — elle est décorrélée de la réponse par décision de performance (recompute lourd, des dizaines de milliers de `source_authorships`), et c'est de la donnée dérivée. Le correctif suffit à la rendre correcte : la BG task s'exécutant après le commit du command handler, elle lit désormais l'état commité. Le périmé en tâche de fond se dissout sans rien déplacer.

5. **`db_conn_sync` : `engine.connect()` en commit-as-you-go** (Phase 0, faite). Pour une écriture, c'est la connexion que le command handler commit ; pour un GET, la connexion de lecture, sans écriture à committer. Pendant la migration, le commit de fin reste un garde-fou (un endpoint non migré persiste quand même).

   **Garde-fou bruyant, bascule pilotée par la donnée.** Le risque de la bascule finale en rollback est caché : elle retire le filet, donc toute écriture qui (a) n'a jamais reçu de command handler et (b) touche réellement la base perd ses données **silencieusement, au moment du flip**. « Une fois toutes les écritures migrées » serait une croyance, pas une vérification. On rend donc le garde-fou **observable** — mais le bon signal est l'**émission de DML**, pas la méthode HTTP ni l'état de transaction. Sous SQLAlchemy une simple lecture ouvre déjà une transaction : un endpoint en méthode d'écriture qui ne fait que valider puis renvoyer 404 (un DELETE sur un id inexistant : un SELECT, aucune écriture) aurait une transaction ouverte au teardown → faux positif qui retarderait la bascule sur du bruit. Le garde-fou s'appuie donc sur un listener `after_execute` qui marque la connexion « dirty » dès qu'un INSERT/UPDATE/DELETE passe ; au teardown, dirty-et-non-committé → **warning** (chemin de l'endpoint). Précis et méthode-agnostique : il ne fire que sur des écritures réelles non committées, reste muet sur les GET, sur `logout` (aucun DML) et sur les méthodes d'écriture qui n'ont fait que lire. La bascule n'est déclenchée que lorsque ce warning s'est tu sur tout le trafic (tests **et** prod). L'incomplétude devient observable au lieu de claquer des mois plus tard ; et une écriture parasite faite dans un routeur hors command handler (risque de la Décision 1) devient un signal, pas une fuite silencieuse.

   Le flag est **conscient des savepoints** : un endpoint qui écrit dans un `SAVEPOINT` puis le rollback (preview honnête — calculer l'impact d'un changement en l'appliquant réellement puis en l'annulant) ne doit pas laisser un flag fantôme. Le garde-fou empile l'état du flag à l'ouverture d'un savepoint et le restaure au rollback (le DML émis depuis est annulé), de sorte qu'un preview reste muet tandis qu'un DML émis **hors** savepoint et non committé reste signalé.

6. **Le command handler opère sur la connexion de la requête** (celle de `db_conn_sync`, partagée avec les repos/queries du routeur via le cache de dépendances FastAPI), il n'en ouvre pas une à lui. Son bénéfice est le lifecycle simple (un seul checkout du pool, pas de seconde connexion à gérer), pas une garantie d'isolation : sous read committed, partager la connexion ne fige **pas** le snapshot (chaque statement prend le sien à son propre début). Ce qui rend la validation 404/400 au routeur sûre n'est donc pas l'absence de TOCTOU mais l'**atomicité du statement d'écriture** — entre le « la ressource existe ? » et l'écriture, la course résiduelle existe, mais un UPDATE/DELETE qui ne touche aucune ligne est un no-op bénin, pas une corruption (et un check du rowcount la neutralise le jour où ça compte).

## Phasage

### Phase 0 — `db_conn_sync` en commit-as-you-go

- [x] `db_conn_sync` : `engine.connect()` + commit de fin au succès (garde-fou) / rollback sur exception, autorisant un commit anticipé dans le caller. Docstring corrigé. Test de régression « écriture lisible au GET suivant ». (commit `3d27bd83`)

### Phase 1 — Mécanique du command handler + routeur pilote (addresses)

- [x] Forme de passage : command handlers dans `application/addresses/commands.py`, recevant la connexion de la requête (`Depends(db_conn_sync)`) et les ports séparément. Ils composent les briques agnostiques de `structures.py` / `countries.py` et `conn.commit()` ; la réification objet (Décision 2) reste reportée.
- [x] Garde-fou instrumenté (Décision 5) dans `infrastructure/db/dml_guard.py`. En codant, le signal retenu n'est ni le type de statement compilé ni le grep du SQL mais le **command tag PostgreSQL** (psycopg `statusmessage` : `UPDATE n` / `INSERT 0 n` / `DELETE n`) : les écritures `addresses` mêlent constructs Core (liens structure) et SQL brut (cascade pays), et un `WITH … UPDATE` n'est pas reconnaissable par le type compilé — le tag, lui, est la classification de la base, robuste pour tous les cas et muet sur les lectures. Le flag est réarmé par `commit`/`rollback` (donc « dirty **et** rien committé depuis le dernier DML »), et `auth` s'auto-instrumente.
- [x] Migration des écritures `addresses` (review, batch-review, country, batch-country — le symptôme d'origine) vers leurs command handlers ; routeur aminci (validations 404/400 et lectures de réponse conservées) ; propagation des pays laissée en `BackgroundTask` (Décision 4).
- [x] Tests du garde-fou (`tests/integration/infrastructure/db/test_dml_guard.py`) : le flag se pose sur INSERT/UPDATE/DELETE — SQL brut comme DML enveloppé dans un CTE —, reste muet sur les lectures (cas du DELETE-404), se réarme après commit ; `db_conn_sync` warne quand son commit de fin rattrape du DML échappé, et reste silencieux quand le handler a commité ou que la requête n'a fait que lire. La transition warn→muet est ainsi figée : un DML non committé warne (et ne survivrait pas à la bascule finale), un handler qui commit ne warne pas. La lisibilité immédiate de l'écriture migrée est couverte de bout en bout par `test_set_country_visible_immediately`.

### Phases 2..N — Router par router

- [x] publishers, journals (update, merge). Command handlers dans `application/publishers_commands.py` et `application/journals_commands.py` — convention : module de commands adjacent au domaine, dans le package quand le domaine en est un (`addresses/commands.py`), en module-frère `<domaine>_commands.py` quand il est plat. Le preview `journals/type-change-impact` (GET, écriture en savepoint rollbacké) a motivé la conscience des savepoints dans le garde-fou (Décision 5).
- [ ] structures (structures, relations, name-forms)
- [ ] persons (identifiers, status, reject, name, merge, name-forms)
- [ ] perimeters
- [ ] authorships (exclude, orphan assign / batch-assign)
- [ ] publication_duplicates, person_duplicates
- [ ] pipeline_config

### Phase finale — `db_conn_sync` en lecture seule

- [ ] **Quand le warning du garde-fou s'est tu sur tout le trafic** (tests + prod, `auth` compris) — donc plus aucune écriture ne passe hors command handler : remplacer le commit de fin de `db_conn_sync` par un rollback. Petit changement en un point ; la complétude est alors vérifiée par la donnée, pas crue.

## Questions ouvertes

- **Placement de la validation HTTP** (404/400 : ressource inexistante, code pays inconnu). Reste-t-elle dans le routeur (garde-fou transport) ou descend-elle dans le command handler via des erreurs domaine mappées en HTTP ? Le minimum est que le **commit** descende ; la validation peut rester au routeur — sûr grâce à l'atomicité du statement d'écriture (Décision 6), pas à une absence de TOCTOU.
- **Découpage transaction vs tâche de fond pour les autres écritures** que la propagation des pays (tranchée : BG). À décider au cas par cas en migrant chaque router.
- **Quand réifier le UoW en objet** (Décision 2) : au premier besoin de **composition transactionnelle** (un command handler qui en compose un autre, ou deux intentions en une transaction), pas sur un critère de verbosité du câblage.
