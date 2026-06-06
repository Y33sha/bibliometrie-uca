# Chantier — Background jobs pour les endpoints longs

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

Endpoints candidats (à vérifier) : `review_structure_link`, `batch_review_structure_link`, puis les endpoints pays `batch_set_country_by_ids` / `batch_set_country_by_filter`.

## Audit endpoints long-running

Lister les endpoints POST/PUT/PATCH qui peuvent franchir le timeout
reverse-proxy (60s classique) selon le volume. Priorité :
user-triggered (pas les scripts CLI). Candidats pressentis :

- `review_structure_link` / `batch_review_structure_link` (périmètre d'adresses populaires)
- `batch_set_country_by_ids` / `batch_set_country_by_filter` (pays
  sur beaucoup d'adresses)
- Endpoints merge de `admin/duplicates` (publications / persons)
- `orphan-authorships/assign` (création de personne + rattachement)

Livrable audit : tableau par endpoint avec volume max observable,
temps moyen, temps P99, décision (sync / seuil + bg task / toujours
bg task).

## Refresh des matviews `source_authorship_structures` / `authorship_structures` sur action admin

Depuis le passage de `source_authorship_structures` (SAS) en matview (cf. `DATA_perimeter-materialise`), toute action admin qui touche une affiliation (`review_structure_link`, assign orphelin, etc.) déclenche un `REFRESH` **complet** de la chaîne `SAS → authorship_structures` : ~3-4 s pour SAS (SELECT ~2,3 s sur 8,3 M `source_authorship_addresses`) + ~2 s pour `authorship_structures`, soit ~5-8 s par action — alors que le changement peut être minuscule (une seule adresse modifiée, une seule publication liée, et tout se recalcule globalement). Le refresh full est massivement disproportionné au delta.

Candidat background-jobs / debounce : décorréler le refresh de la réponse admin (réactivité immédiate, matview rattrape en async). Fallback de repli déjà acté : si gênant, supprimer le refresh sur action admin et laisser **seul le pipeline** maintenir ces matviews (staleness bornée entre deux runs, acceptable pour ces dérivées).

## Idées à intégrer
Cleanup explicite des idle in transaction côté API (BG tasks notamment) : vérifier qu'aucune BackgroundTasks ne laisse une transaction ouverte si elle plante.
