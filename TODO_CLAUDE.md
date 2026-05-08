# TODO Claude

## Backoff `not_found_at` sur DOI

Pour limiter la croissance du pool de DOI retentés à chaque run de
`fetch_missing_doi`, stocker un `not_found_at TIMESTAMP` sur les DOI
qu'une source n'a pas pu résoudre, et ne les réessayer qu'après N jours
(30 ?). Chantier séparé.

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
