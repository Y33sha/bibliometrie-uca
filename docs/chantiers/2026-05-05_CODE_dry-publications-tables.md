# Chantier — DRY publications tables
Commencé et terminé le 2026-05-05

## État : terminé ✅

Migration de `/laboratories/[id]` et `/persons/[id]` vers
`<PublicationsListView>` réalisée. Les quatre points d'usage du tableau
de publications partagent désormais le même composant :

- `/publications` (mode autonome, sync URL complète)
- `/subjects/[id]?tab=publications` (filtre `subject_id` fixe)
- `/laboratories/[id]?tab=publications` (filtre `lab_id` + Statut HAL)
- `/persons/[id]?tab=publications` (filtre `person_id` + Corresp./UCA)

Bilan code : ~570 lignes de duplication retirées (lab + person), tableau,
toolbar, facets, composables et handlers tous mutualisés.

## Contexte initial

Le tableau de publications avec ses filtres facets (années, labos, types,
accès, OA, APC, pays, sources) et son tri (titre, année, APC) était répété
à plusieurs endroits du frontend, chaque implémentation re-déclarant le
markup, les composables et les handlers avec des variations mineures.

## Travail réalisé

### Phase 1 — `useUrlFilters` additif (commit 8291720)

`syncUrl` préserve désormais les keys URL non gérées par l'instance.
Pré-requis pour faire cohabiter plusieurs `useUrlFilters` sur une même
page (ex : la page parent gère `?tab=`, le composant gère ses filtres).

### Phase 2 — Extension du composant (commit 4580afe)

Nouveaux props sur `<PublicationsListView>` :

- `externalFilters` étendu : `labId, labLabel, halCollection, personId,
  personLabel`.
- `showHalStatusColumn` (lab) : ajoute la colonne et la facet « Statut
  HAL », avec calcul client-side basé sur `halCollection`.
- `showCorrespondingColumn` (person) : colonne ✉ et facet « Corresp. ».
- `showPerimeterFacet` (person) : facet « UCA » (`in_perimeter`).
- `showAdminExclude` + `onExcludeAuthorship` (person, admin) : 1ère
  colonne avec bouton ✕, callback async (parent gère confirm + API,
  retourne `false` pour annuler).
- `apcMode: 'uca' | 'lab' | 'person-uca'` : mode de rendu du tag APC.
- `perPage` : 50 pour les onglets, 100 pour `/publications`.

### Phase 3 — Migration `/laboratories/[id]` (commit 6282560)

-267 lignes net. La page utilise `<PublicationsListView>` configuré avec
`labId, halCollection, showHalStatusColumn, apcMode='lab'`. Son
`useUrlFilters` ne gère plus que les keys cross-onglets (`tab`,
`persons`, `addresses`).

### Phase 4 — Migration `/persons/[id]` (commit 3ec23cc)

-257 lignes net. Configure `personId, showCorrespondingColumn,
showPerimeterFacet, showAdminExclude, apcMode='person-uca'`. La page
fournit `excludeAuthorship` (avec confirm + API) au composant.

### Bonus — Pre-commit svelte-check (commit 1b0680f)

Ajout de `svelte-check` au pre-commit, déclenché uniquement quand des
fichiers frontend sont staged. Bloque sur les vraies erreurs (pas les
warnings).

## Idées pour plus tard

- `ExternalFilters` est devenu une grosse interface plate. Si on a la
  certitude qu'aucun appelant ne combine jamais plusieurs catégories
  (subject + lab + person), on pourrait le passer en union discriminée
  (`{ kind: 'subject' | 'lab' | 'person', ... }`) plus typée. Pas urgent.
- Si on extrait demain l'onglet « Personnes » de `/laboratories/[id]`
  en composant réutilisable, l'additivité de `useUrlFilters` (phase 1)
  permettra une migration symétrique sans douleur.
