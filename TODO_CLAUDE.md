# TODO Claude

## Suite de la refonte `domain/pipeline_modes.py`

- **Docs à mettre à jour** (`monthly` → `full`, 3 modes au lieu de 4) :
  - `README.md` (exemples `--mode`)
  - `docs/exploitation.md` (tableau de planification cron, ligne "monthly")
  - `docs/pipeline.md` (description des modes)
  - `docs/guide-utilisateur.md` (mention "modes weekly et monthly")
- **Crons server-side** : vérifier que les tâches planifiées n'appellent plus
  `--mode monthly` (remplacer par `--mode full`).
- **Harmonisation `extract_theses.py`** : accepter `--mode` et `--year` comme
  les autres extracteurs, pour uniformiser le traitement et permettre un
  éventuel `weekly` theses si besoin un jour (absence actuelle non justifiée
  par la source).

## Suite du split `cross_imports` → `fetch_missing_hal_id` + `fetch_missing_doi`

La phase `cross_imports` a été éclatée en deux phases distinctes, et les 4
scripts `cross_import_<source>.py` ont été fusionnés en un dispatcher unique
`interfaces/cli/pipeline/fetch_missing_doi.py` + un adapter par source dans
`infrastructure/sources/<source>/fetch_missing_doi.py`.

- **Docs à mettre à jour** :
  - `docs/pipeline.md` (section "Phase 2 — cross_imports" à scinder en 2a et 2b,
    références aux 4 scripts `cross_import_<source>.py` qui n'existent plus).
  - `CONTRIBUTING.md` (section "cross_imports" et "Script autonome
    `infrastructure/sources/<source>/cross_import_<source>.py`" — obsolètes).
  - `ROADMAP.md` ligne 194-195 (liste des scripts de cross-import).
- **Backoff `not_found_at` sur DOI** : pour limiter la croissance du pool de
  DOI retentés à chaque run, stocker un `not_found_at TIMESTAMP` sur les DOI
  qu'une source n'a pas pu résoudre, et ne les réessayer qu'après N jours
  (30 ?). Chantier séparé.

## Suite de la suppression de `harvest_hal_identifiers`

ORCID/IdRef des auteurs HAL sont désormais extraits depuis le TEI
(`label_xml`) pendant la normalisation — la phase dédiée qui interrogeait
l'API `ref/author` n'existe plus. La clé `hal_ref_author` a été retirée
de `api_base_urls` (migration 007, `infrastructure/app_config.py`,
`infrastructure/db/seed.sql`). À vérifier côté docs :

- Références à l'API `ref/author` HAL ou à `harvest_hal_identifiers` à
  retirer de `docs/pipeline.md`, `docs/sources.md` et `README.md` si
  présentes.

## Background jobs pour les endpoints de propagation massive

Le fix no-op sur `review_structure_link` (commit 9376bbd) règle le cas
fréquent (confirmer une auto-détection = no-op sans propagation). Reste
le cas d'un **vrai changement** massif : rejeter l'UCA sur une adresse
à 67k source_authorships, ou batch sur plusieurs adresses populaires →
CTE longue + UPDATE massif → 504 timeout reverse-proxy.

Plan :
- Seuil (ex: `PROPAGATION_SYNC_THRESHOLD = 5000` authorships) : en
  dessous, propagation synchrone comme aujourd'hui.
- Au-dessus : `fastapi.BackgroundTasks` pour décorréler la réponse de
  la propagation. Le client reçoit 202 avec `{propagation_pending:
  True, authorship_count: N}`, la propagation tourne en arrière-plan
  avec sa propre connexion DB (ne pas réutiliser celle de la requête).
- Frontend : gérer le 202 → afficher "propagation en cours, ça peut
  prendre quelques minutes" + rafraîchir après un délai / polling.
- Limites de `fastapi.BackgroundTasks` : même process, pas persistant
  aux restarts. Si le risque est acceptable pour une utilisation admin
  (l'utilisatrice relance la mutation si besoin), on reste simple. Sinon,
  introduire un job queue (pg-boss like) — plus gros chantier.

Endpoints candidats (à vérifier) : `review_structure_link`,
`batch_review_structure_link`, `unassign_manual_structure`, puis les
endpoints pays `batch_set_country_by_ids` / `batch_set_country_by_filter`.

## Audit endpoints long-running

Lister les endpoints POST/PUT/PATCH qui peuvent franchir le timeout
reverse-proxy (60s classique) selon le volume. Priorité :
user-triggered (pas les scripts CLI). Candidats pressentis :

- `review_structure_link` / `batch_review_structure_link` /
  `unassign_manual_structure` (périmètre d'adresses populaires)
- `batch_set_country_by_ids` / `batch_set_country_by_filter` (pays
  sur beaucoup d'adresses)
- Endpoints merge de `admin/duplicates` (publications / persons)
- `orphan-authorships/assign` (création de personne + rattachement)

Livrable audit : tableau par endpoint avec volume max observable,
temps moyen, temps P99, décision (sync / seuil + bg task / toujours
bg task).

## Audit "sync I/O dans les coroutines"

Distinct du précédent. Chercher les endpoints `async def` qui
appellent des fonctions faisant du `requests.get(...)` ou des
opérations psycopg2/psycopg en mode blocking sans `await` — ça
bloque l'event loop et ruine la concurrence de **tous les clients**.

Heuristique de recherche :
- Rechercher `def ` (pas `async def`) dans les routers/services qui
  font des appels HTTP ou DB
- Vérifier les imports `requests` et `psycopg` non-async dans le flow
  d'un endpoint
- Potentiellement instrumenter avec un handler qui trace les
  coroutines dépassant un seuil de temps entre deux `await`.

## Normalisation du schéma `person_name_forms`

Schéma actuel : `person_name_forms(name_form, person_ids[], sources[])`
— deux arrays parallèles non-corrélés. Conséquence : pour une forme
liée à plusieurs personnes via plusieurs sources, on ne sait pas
quel `(person_id, source)` est responsable de quoi.

Exemple problématique : forme `"j dupont"` reliée à person 1 (Jérôme
Dupont) via `persons` et à person 2 (Jeanne Dupont-Martin) via
`openalex` — finit avec `person_ids=[1,2], sources=['persons','openalex']`,
zéro moyen de tracer 1↔persons et 2↔openalex sans recalculer.

C'est cette faiblesse qui justifie la **recalculation systématique
batch** dans `populate_person_name_forms` : on ne peut pas faire
d'update vraiment incrémental (delete d'authorship → suppression de
sa contribution) parce qu'on ne sait pas quelles contributions
viennent de qui.

Schéma cible : `person_name_form_sources(name_form, person_id, source)`
en row-per-triple, drop des arrays. Permet update vraiment incrémental
(delete authorship → DELETE row(s) correspondante(s)) + traçabilité
complète.

Coût : migration SQL non-triviale + adaptation des consommateurs (il
y en a peu : matching cascade + queries admin). Bénéfice : suppression
de la phase de recalculation batch + traçabilité.

## Seuil d'auteurs pour le matching cross-source

`domain.persons.matching.decide_cross_source_match` (étape 1 du
pipeline persons) rattache une authorship à la `person_id` connue
d'une autre source à la même `(publication_id, author_position)`,
avec garde-fou `names_compatible`. Sur les méga-papers (consortiums
>50 auteurs), les positions divergent souvent entre HAL/OpenAlex/WoS
→ faux conflits ou faux matchings.

À ajouter : court-circuit si le `source_publication` a plus de N
auteurs (constante `MAX_AUTHORS_CROSS_SOURCE`, à harmoniser avec
`MAX_AUTHORS_CONFLICT` côté `TODO_LAURA.md`). Renvoie `None` direct
(pas de cross-source) au-delà du seuil.

Coût : ajout d'un argument `total_author_count` à
`decide_cross_source_match` + compute du count côté caller (depuis
le prefetch ou une query supplémentaire).

## Unifier la règle de choix de cible de fusion

Trois fusions de publications coexistent dans le pipeline avec **trois
règles ad hoc** pour décider laquelle des deux publis survit :

- `merge_pubs_by_hal_id` : « HAL gagne » (ordre des arguments fixé
  dans `_merge_pub(cur, hal_pub_id, src_pub_id, ...)`).
- `merge_pubs_by_nnt` : ranking SQL via
  `queries.rank_publications_by_merge_priority` (priorité sources +
  ancienneté + complétude).
- `try_merge_by_doi` (`application/publications.py`) : sa propre
  cascade.

Sans impact métier réel (les métadonnées canoniques sont triangulées
par `refresh_from_sources` selon `SOURCE_PRIORITY` après la fusion)
mais incohérence de code. La règle « HAL gagne » est en plus
discutable sur le fond : une publi avec hal_id peut venir d'OA/ScanR
qui moissonnent HAL (HAL canonique) ou d'un article CrossRef avec
métadonnées éditeur déposé en parallèle sur HAL (HAL non canonique).

À unifier : un seul `rank_publications_by_merge_priority` (porté en
`domain/publications/merge.py` lors du chantier
`identification des doublons par hal_id` (b)) appelé par les trois
sites de fusion.

**Sous-point** : `merge_pubs_by_nnt` ne gère pas les redirections en
chaîne (contrairement à `merge_pubs_by_hal_id` qui a un `resolve()`
local pour suivre les redirections accumulées dans le batch). Si dans
un même run une fusion produit `pub_A → pub_B` puis qu'une autre
demande `pub_X → pub_A`, on tente de fusionner vers `pub_A` déjà
disparu → erreur capturée par le savepoint, fusion perdue. Bug
potentiel ou cas qui ne se produit jamais — à mesurer. Le résolveur
serait à porter dans le helper unifié des 3 sites de fusion.

## Crossref absent de `build_authorships.all_sources`

[`build_authorships.py:20-26`](application/pipeline/authorships/build_authorships.py#L20)
hardcode 5 sources (HAL, OpenAlex, WoS, ScanR, theses.fr) — Crossref
manque. La liste sert à plusieurs étapes :

- **Étape 2** (link FK `source_authorships.authorship_id` →
  `authorships.id` via `link_source_authorships_to_authorship_for`) :
  Crossref insère bien des `source_authorships`, donc devrait y figurer
  pour que ses authorships soient reliées à la table de vérité. **Bug
  potentiel** ou décision non documentée.
- **Étape 4** (propagation `in_perimeter` + `structure_ids`) :
  Crossref n'a pas de `structure_ids` (affiliations brutes texte uniquement)
  → exclusion légitime à ce niveau.

À investiguer : vérifier si les `source_authorships` Crossref sont
correctement reliées à `authorships` aujourd'hui. Si non → ajouter
Crossref à la liste mais avec gestion différenciée selon l'étape, ou
scinder en deux constantes (`AUTHORSHIPS_LINK_SOURCES` vs
`STRUCTURE_PROPAGATION_SOURCES`).
