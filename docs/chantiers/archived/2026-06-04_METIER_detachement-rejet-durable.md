# Chantier — Rejet durable d'une paire (publication, personne) : garde matching, détachement, réassignation

## Contexte

Il existe deux façons de casser un lien personne ↔ publication, et elles ne se comportent pas de la même manière face aux rebuilds du pipeline.

**Rejet canonique** — le bouton de suppression (croix) sur la fiche personne (`PATCH /api/authorships/{id}/exclude` → `exclude_authorship`). Il écrit la paire `(publication_id, person_id)` dans `rejected_authorships` puis supprime la row `authorships`. Les sites qui insèrent dans `authorships` anti-joignent ce store, donc le rejet survit aux rebuilds (mécanique posée par le chantier `archived/2026-06-01_DATA_rejected-authorships-sidecar`).

**Détachement source** — « Détacher *n* authorships » depuis `admin/persons` (`POST /api/persons/{id}/detach-authorships` → `detach_authorships`). Il nulle `person_id` sur les `source_authorships` sélectionnées et supprime les `authorships` canoniques devenues orphelines. **Il n'écrit pas dans `rejected_authorships`.**

Conséquence : au run suivant, la cascade de matching personnes (`decide_person_match`) ré-attache `person_id` à la `source_authorship` (même ORCID / idHAL / forme de nom), puis `build_authorships` recrée la paire. **Le détachement saute.** C'est le comportement indésirable visé.

Cause racine, plus profonde que le seul détachement : `rejected_authorships` n'est anti-joint qu'au **moment de l'INSERT dans `authorships`**. La canonique est protégée, mais rien n'empêche la phase `persons` de re-poser `person_id` sur la `source_authorship`. Tant que le matching ignore le store, tout rejet laisse un lien source ressuscité (forme de nom ré-attribuée, zombie) que seul l'anti-join final intercepte. La durabilité doit être garantie **en amont, dans le matching**.

Second problème, découvert au passage : sur les chemins de réassignation (`admin/orphan-authorships`), si la paire est dans `rejected_authorships`, on pose bien `person_id` sur la source mais l'authorship canonique n'est **pas** recréée, et sans le signaler.

## Phasage

### Phase 1 — Garde de rejet dans le matching personnes (pièce maîtresse)

C'est la garde qui rend tout rejet durable. `decide_person_match` (décideur pur) reçoit l'ensemble des `person_id` déjà rejetés pour la publication de l'authorship traitée. Le caller (`create_persons_from_source_authorships`) préfetche une map `publication_id -> frozenset[person_id]` depuis `rejected_authorships`, en même temps que les autres lookups.

La garde s'applique à deux endroits :

1. **Tout match** (ORCID, `hal_person_id`, IdRef, cross-source, name form univoque) vers un `person_id` rejeté pour cette publication est annulé : la cascade retombe au signal suivant, et faute de mieux laisse l'authorship orpheline plutôt que de recréer le lien rejeté.
2. **Cas du name form ambigu** (≥ 2 personnes, aujourd'hui `skip(ambiguous_name_form)`) : les candidats rejetés sont **éliminés de la liste** avant `decide_name_form_outcome`. Conséquence recherchée : si 2 personnes partagent la forme de nom mais qu'une est rejetée pour cette publication, il ne reste qu'une candidate → la décision passe de `skip` à `match`. Le rejet devient un signal de désambiguïsation par élimination.

Effet : `person_id` n'est jamais re-posé sur une `source_authorship` d'une paire rejetée. La durabilité ne repose plus sur le seul anti-join final ; elle est garantie en amont.

- [x] Filtre de rejet dans `decide_person_match` : annuler tout match (ORCID / hal / idref / cross-source) vers un `person_id` rejeté pour la publication.
- [x] Élimination des candidats rejetés dans le cas du name form (ambigu comme univoque), via `decide_name_form_outcome` (désambiguïsation par élimination).
- [x] Prefetch de la map `publication_id -> frozenset[person_id]` (`fetch_rejected_person_ids_by_pub`) dans `create_persons_from_source_authorships`, et passage aux deux décideurs dans la boucle.
- [x] Tests unitaires : match annulé par la garde ; désambiguïsation par élimination (2 candidats dont 1 rejeté → match univoque).
- [x] Test d'intégration : paire rejetée non re-rattachée à la `source_authorship` ; élimination désambiguïsant une forme de nom.
- [x] Doc `pipeline/07-persons` : garde de rejet dans la cascade + désambiguïsation par élimination.

### Phase 2 — Rejeter = opération unifiée (croix canonique ∪ détachement)

La garde en place, rejeter une paire `(publication_id, person_id)` est une seule opération (`reject_pair`), quel que soit le point d'entrée :

1. `reject_authorship` (INSERT sidecar `ON CONFLICT DO NOTHING`).
2. Nuller `person_id` sur **toutes** les `source_authorships` de cette personne pour cette publication (op repo `unlink_all_source_authorships_for_pair`).
3. Supprimer la canonique (`delete_orphan_authorships_for_person`, devenue orpheline — invariant du sidecar préservé).
4. Événement d'audit.

Nettoyage des formes de nom (décidé en cours de chantier) : après le rejet, on supprime **toutes** les formes de nom de la personne que plus aucune source n'atteste (`delete_orphan_name_forms_for_person`), pas seulement celle d'entrée. Les formes calculées depuis le nom de la personne (source `persons`) sont préservées. Appelé par `detach_authorships` (une fois après la boucle) et par `exclude_authorship` (quand `person_repo` est fourni). L'ancien `count_authorships_with_name_form` devient mort et est supprimé. Le paramètre `name_form` disparaît du contrat de détachement, et la réponse expose `cleaned_forms: int`.

Deux points d'entrée convergent sur ce cœur :

- **Détachement** (`detach_authorships`) : résout l'ensemble distinct des `publication_id` des authorships sélectionnées et applique `reject_pair` à chaque paire. Le rejet porte sur la publication entière — les sources référencent la même publi, donc « cette personne n'est pas l'auteur de cette publication » vaut pour toutes ses sources.
- **Croix canonique** (`exclude_authorship`) : aujourd'hui écrit le store + supprime la canonique mais **laisse** `person_id` sur les sources (le chantier sidecar avait abandonné le détachement source, jugé non durable et inutile vu l'anti-join). La garde (phase 1) renverse cette prémisse : le détachement source devient durable et utile (supprime le zombie, stoppe l'attribution erronée de forme de nom). La croix gagne donc l'étape 2 — elle applique le même `reject_pair`.

- [x] Op repo `unlink_all_source_authorships_for_pair(publication_id, person_id)` (port + impl) : nulle `person_id` sur toutes les sa dont `source_publication.publication_id = pub` et `person_id = pid`.
- [x] Cœur `reject_pair(publication_id, person_id)` : store + détacher toutes les sources + supprimer la canonique + audit.
- [x] `detach_authorships` réécrit : résoudre les `publication_id` distincts, appliquer `reject_pair` par paire ; nettoyage en masse des formes de nom orphelines (drop du paramètre `name_form`).
- [x] `exclude_authorship` : appliquer le détachement source (étape 2) via `reject_pair` + nettoyage des formes de nom orphelines.
- [x] Op repo `delete_orphan_name_forms_for_person` (port + impl) ; suppression du mort `count_authorships_with_name_form`.
- [x] Tests d'intégration : store peuplé, toutes les sources de la paire détachées, canonique supprimée, non recréée au rerun ; nettoyage des formes orphelines (forme source orpheline supprimée, forme calculée préservée, forme encore attestée conservée).
- [x] Frontend : modale de détachement regroupée par publication (une ligne par publi, sources en tags), envoi d'une référence de source par publi, `name_form` retiré du body. Schéma OpenAPI régénéré.
- [x] Doc `guide-utilisateur/03-workflow-admin`, `donnees/05-authorships-et-sources`, `pipeline/08-authorships`.

### Phase 3 — Réassigner une paire rejetée : recréation garantie + modale + un-reject

**Couvrir tous les chemins de réassignation existants** (`admin/orphan-authorships` : assignation unitaire et batch, création de personne incluse). Comportement UI inchangé hors la nouvelle modale.

**(a) La canonique doit toujours être recréée.** Toute pose de `person_id` sur une `source_authorship` recompose la canonique et la crée si `authorship_id` est null. Déjà le cas des chemins UI (`assign_orphan_authorship` → `_refresh_authorship_from_sources` ; `batch_assign_orphan_authorships` → `create_authorships_from_sources` + `link_source_authorships_to_authorships`) **sauf** quand la paire est rejetée (l'anti-join sidecar skippe l'INSERT). Une fois la paire dé-rejetée (point b), la recréation reprend.

**(b) Pré-check + modale + un-reject.** Avant d'assigner : résoudre `publication_id`, interroger le store ; si la paire est rejetée et la requête non forcée, renvoyer un signal « bloqué » avec la `created_at` ; sur confirmation (`force=true`), un-reject puis assignation normale (la garde laisse passer, la canonique se recrée).

- [x] Vérifier (test) qu'aucun chemin de pose de `person_id` ne laisse la canonique non recomposée (assign forcé → canonique recréée).
- [x] Ops repo `find_rejected_authorship(publication_id, person_id) -> created_at | None` et `delete_rejected_authorship(publication_id, person_id)` (port + impl) ; `find_publication_ids_for_source_authorships` pour le pré-contrôle batch.
- [x] `force: bool = False` sur `AssignOrphanAuthorship` / `BatchAssignOrphanAuthorships` + endpoints (injection `authorship_repo` + `audit`).
- [x] Réponse « bloqué » : domaine `RejectedPairError` (sous-classe `ConflictError`) + handler 409 `{detail, rejected_pairs:[{publication_id, person_id, rejected_at}]}` (unitaire + batch).
- [x] un-reject sur `force=true` (helper `_resolve_rejection`) + événement d'audit `authorship.unrejected`.
- [x] Frontend : modale de confirmation (orphan-authorships, unitaire + batch) interceptant le 409 et rejouant en `force=true` (helper `withRejectGuard`).
- [x] Tests d'intégration : assign/batch bloqués sur paire rejetée ; assign/batch forcés → un-reject + canonique recréée (application + API).

## Questions ouvertes

- **Grain de la modale de détachement.** _Résolu :_ regroupement par publication (une ligne par publi, sources en tags), plus nettoyage en masse des formes de nom orphelines. L'entrée reste par forme de nom ; une même publi peut apparaître sous plusieurs tags de forme de nom, c'est assumé (le détachement opère de toute façon sur la publication entière).
- **Forme de la réponse « bloqué ».** _Résolu :_ 409 avec payload structuré (`created_at` de la paire rejetée).
- **Modale batch.** _Résolu :_ même modale que l'unitaire, listant chaque paire rejetée (publication + date) ; le payload 409 `rejected_pairs` couvre les deux cas.
- **Stock existant.** La garde ne joue qu'aux runs futurs ; une paire rejetée avant la garde peut porter un `person_id` source ressuscité. Un full rerun `raw_hash=null` ré-applique la cascade gardée et nettoie — pas de backfill dédié.
