# Fusion des publications — dénouer l'enchevêtrement

## Contexte

La fusion de deux publications en une passe par **trois chemins** aujourd'hui, dont deux accidentels :

1. la réconciliation (`reconcile_components.py`) : c'est elle qui **possède l'identité**. `plan_reconciliation` ancre chaque partition-DOI sur la publication qui porte déjà ce DOI (`_claim` / `external_carrier` via `existing_pub_by_doi`) et applique le cannot-link DOI (« deux DOI non-nuls distincts ne fusionnent jamais ») ; elle n'a donc jamais besoin de réécrire un DOI ni de créer une seconde publication au même DOI.
2. un **auto-merge caché dans `refresh_from_sources`** (`application/services/publications/core.py`) : recomputer le DOI d'une publication déclenche un `find_by_doi` + `merge_publications` si une autre publication le porte. C'est une **béquille redondante** — elle ne couvre que la fenêtre transitoire, pendant la réconciliation, où une publication dissoute porte encore son DOI avant suppression (que l'ordre « dissoudre d'abord » gère déjà). Hors pipeline, le DOI d'une SP ne change pas → l'auto-merge ne se déclenche jamais.
3. `merge_publications` en direct (`interfaces/api/routers/admin`, `interfaces/cli/maintenance`), pour une fusion manuelle.

Un nouveau venu ne peut pas dire quel est *le* chemin de fusion, ni pourquoi rafraîchir des métadonnées fusionne des publications.

Deuxième couche : `merge_publications` fusionne via `Publication.absorb(source)` — une règle *pairwise* (`absorb_oa_status` + COALESCE des scalaires nullable + union des countries) — au lieu de recomputer depuis les sources. Or après `merge_into`, la cible détient déjà toutes les `source_publications` de la source : `refresh_from_sources(target)` donnerait la valeur canonique. D'où deux règles OA qui **divergent** selon le chemin de fusion : réconciliation via `best_oa_status` (`["hybrid", "gold"]` → `gold`) vs `merge_publications` via `absorb_oa_status` (`("hybrid", "gold")` → `hybrid`). Le statut OA d'une publication dépend de par où elle a fusionné.

## Décisions

L'identité (quelles publications sont une seule œuvre) est du ressort exclusif de la réconciliation, qui l'assume déjà. `refresh_from_sources` doit redevenir un recompute pur, et la règle de fusion doit être unique : recompute depuis les sources.

## Phasage

- [x] `refresh_from_sources` → recompute pur : retirer le `find_by_doi` + l'auto-merge (`merge_publications`). Il ne connaît plus que les `source_publications` de sa propre publication. (`f1ee192a`)
- [x] `merge_publications` = `merge_into` puis recompute depuis les sources, au lieu de `Publication.absorb`. Supprime `Publication.absorb` (agrégation métadonnées) et `absorb_oa_status` (`domain/publications/metadata`), lève la divergence OA, et — l'auto-merge de `refresh` étant parti — sans circularité `merge → refresh → merge`. (`65ec1511`)
- [x] Reformuler le commentaire d'ordonnancement de `reconcile` (étape 2, dissolutions) : la raison devient « libérer le DOI avant que le survivant le reprenne », plus « éviter que l'auto-merge se déclenche ». (`65ec1511`)

## Questions ouvertes

Aucune. La réconciliation garantit qu'une seule publication porte un DOI donné à l'arrivée (toutes les SP d'un DOI dans la même composante → même ancre ; porteur hors voisinage ancré via `existing_pub_by_doi`) et supprime les publications dissoutes **avant** de rafraîchir les survivants qui reprennent leur DOI. Deux publications ne coexistent donc jamais sur le même DOI au moment d'un `save` : l'auto-merge ne se déclenche par construction jamais, ni en pipeline ni en standalone.
