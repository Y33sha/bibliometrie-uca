# Chantier — Duplications du frontend

## Contexte

Inventaire du 2026-11-04 sur `interfaces/frontend/src` : la feuille partagée `lib/styles/shared.css` (1 778 lignes), les styles locaux de 94 composants, les composants, les fonctions et les libellés.

### Étiquettes

Une étiquette (tag, badge, pastille, chip) est un court texte sur fond clair, arrondi, en petite taille. `shared.css` en définit 18 classes, les composants 31 autres. Elles se rangent en quatre groupes.

| Groupe | Classes de `shared.css` | Classes locales |
|---|---|---|
| Accent : fond `--accent-light`, texte `--accent` | `lab-tag`, `structure-tag`, `entity-tag-accent`, `id-badge` | `lab-badge`, `publication-count-tag`, `struct-chip`, `ident-chip`, `tag` de `RelationsSection` |
| Neutre : fond `--surface` ou `--border-subtle` | `entity-tag`, `tutelle-tag`, `meta-badge`, `canonical-tag`, `apc-other`, `detail-tag` | `count-pill`, `stat-badge`, `hal-publications`, `tag` de la configuration et de `DetachNameFormModal` |
| Teinte d'état : succès, danger, attention, avertissement | `oa-tag`, `apc-tag`, `badge-doaj`, `structure-type`, `status-chip` | `struct-tag` (copié dans Affiliations et Qualité de la détection), `hal-badge`, `citation-top`, `status-tag`, `match-badge`, `ctx-tag`, `country-tag`, `status-badge`, `tag-excluded` |
| Icône ronde de 22 px | `id-icon`, `source-tag` : base, survol et image identiques ; `id-hal` égale `source-hal` | — |

- Dans un groupe, les classes diffèrent par la marge intérieure (de 1 px × 5 px à 3 px × 10 px), le rayon (`--radius` ou `--radius-pill`), l'affichage (inline, inline-block, inline-flex) et la formule de survol.
- Seule `status-chip` a des modificateurs de teinte. 24 règles locales recopient ces paires de couleurs.
- `type-pill` tire ses deux couleurs d'une seule propriété (`--type-color`).
- `lab-tag` sert seulement dans des tableaux, où `.data-table .lab-tag` retire fond, marges et survol. Sa forme d'étiquette reste invisible.

### Boutons et contrôles

- **Boutons sans bordure** (fond transparent, survol `--hover`) : `export-btn`, `facet-btn`, `toolbar select`, `btn-add`, `icon-btn`, `facet-clear`. Six hauteurs et couleurs.
- **Boutons pleins** : `toolbar-action` égale presque `btn btn-primary`. `btn-confirm`, `btn-danger` et `btn-primary` répètent deux règles en changeant la couleur. Même schéma pour `icon-btn-danger` et `icon-btn-success`.
- **Boutons à contour** : `btn-merge` égale presque `btn-create`. `btn-merge-inline` (pointillés) redéclare la base de `btn`.
- **État désactivé** : trois versions (`btn`, `btn-merge`, `icon-btn`).
- **Boutons locaux** : 34.
  - `btn-merge-modal` de `DetachNameFormModal`, le bouton de connexion et `tab-btn.active` de Qualité de la détection recopient `btn-primary`.
  - `AccessButton` recopie `toolbar-action`.
  - Six boutons de retrait « × », quatre boutons-liens textuels, trois boutons de nom semblables à `triage-person`, deux sélecteurs segmentés (Qualité de la détection, `PublicationsDashboard`).
- **Champs** : quatre règles de champ texte dans `shared.css`, cinq dans les composants. Deux styles de menu déroulant partagent la même flèche SVG ; un troisième, dans les modales, n'en a pas.
- **Panneaux flottants** : `facet-panel` recopié six fois (`ColumnMenu`, `Picker`, Qualité de la détection, Contributions orphelines). Lignes d'options recopiées six fois.

### Autres styles répétés

- **Texte secondaire** : `.muted { color: var(--muted) }` défini dans 11 composants, et la même règle sous 18 autres noms. La paire couleur atténuée et `--fs-sm` revient 13 fois dans 10 fichiers. `shared.css` n'a pas de classe utilitaire.
- **Chargement et liste vide** : `shared.css` regroupe `.loading`, `.empty`, `.no-results`. Neuf composants les redéfinissent, dont trois pages d'entité avec la même règle.
- **Grilles libellé / valeur** : six définitions. `rh-info` de `PersonDrawer` égale presque `drawer-fields`.
- **Petites capitales** : cinq variantes dans `shared.css`, dix dans les composants, 11 espacements de lettres distincts.
- **Encarts** : `info-box` couvre l'accent. Six encarts locaux pour l'avertissement, l'attention et le danger. L'aspect de `batch-bar` est défini de trois façons (Affiliations, Pays, Contributions orphelines).
- **Surcharges** : environ 45 règles locales reprennent le nom d'une classe partagée. 14 sélecteurs `:global` dans 6 fichiers, dont les styles de base (`html`, `body`, anneau de focus) dans `+layout.svelte`. Un `!important`.
- **Collisions de noms** : `.empty` désigne une étiquette dans `NameFormsList`, `.access-embargo` change de couleurs dans `AccessButton`, `.publication-title` sert à un `span` dans Contributions orphelines.

### Valeurs en dur

- **Couleurs** : 51 valeurs hexadécimales dans `shared.css` hors `:root`. Les étiquettes OA (`.oa-*`) ignorent les variables `--gold`, `--hybrid`, `--closed`. `#856404` égale `--warning-text`, `#d4a017` égale `--warning`. Huit couples de teintes de survol choisies à la main. Les composants n'ont aucune couleur hexadécimale.
- **Teintes calculées** : deux familles de `color-mix`, « couleur à 20 % sur blanc » (survol clair) et « couleur assombrie de 20 % » (survol plein), plus 29 formules dans 16 composants.
- **Sans variable** : 14 ombres (10 valeurs), deux fonds d'overlay, deux anneaux de focus, `color: white` 20 fois.

### Code mort

- **Classes** : `subtitle`, `dash-summary`, `id-badge.id-confirmed`, `wos-label`, `source-tag-label` et ses quatre variantes, `type-badge`, `access-tag` (`accessTag()` écrit son nom dans un attribut `data-access`), `status-chip.ambiguous`.
- **Déclarations redondantes** : survols répétant la base (`toolbar-action`, `export-btn`, `id-badge`, `structure-tag`), `color: white` des survols de `btn-confirm`, `btn-danger`, `btn-primary`, taille de police de `btn-sm`.
- **Composant** : `RelatedPublications.svelte`, importé nulle part.
- **Exports inutilisés** : `halCollectionUrl` (`structures/types.ts`), `getActiveTab` (`TabNav`), `identifierStatusClasses`, `issnSupportNames`, `issnStatusLabels` (`labels.ts`).

### Composants

- **Vues de liste** (six composants, plus les pages Labos et Sujets) : chacune écrit `buildFilterParams`, `exportCsvUrl`, la synchronisation de l'URL, sa restauration et la pagination. `filterRegistry` décrit filtres, paramètres et URL de façon déclarative ; seules les publications et les statistiques s'en servent. `ThesesListView` interroge les mêmes routes que les publications, mais recopie l'option « Aucun labo », l'encodage de présence et la liste des sources.
- **Volets** (cinq) : rechargement au changement d'identifiant (6 copies), en-tête avec lien public et renommage (3), fonction `update()` identique dans les volets revue et éditeur, section de fusion avec `Picker` (3) ; `PublicationMergeSection` fait la même chose sans `Picker`.
- **Modales** : boutons « Annuler » et action recopiés 7 fois. L'état de `StructureFormModal` est déclaré deux fois (page Labos, `StructureDrawer`). `DetachNameFormModal` et `PersonDrawer` affichent la même liste de personnes.
- **Listes de tri** : `LikelyProceedingsList` recopie `SerialGroupsList` ; `AmbiguousFormsList` et `SuspectMergesList` recopient `PersonPairsList`. Les quatre pages Problèmes HAL et quatre pages d'administration synchronisent leur URL à la main, à côté de `useUrlFilters`. Trois compteurs de file recopiés.
- **Pages d'entité** (sept) : titre, fil d'Ariane, « introuvable » et « Chargement… » recopiés 7 fois. Onglet actif recalculé 6 fois, alors que `TabNav` le calcule. Carte « Sujets principaux » et chargement des sujets recopiés 4 fois.
- **Balisages recopiés** :
  - pastille DOAJ (3), lien d'éditeur ou texte (7), lien de revue ou texte (4), nom de personne (10) ;
  - « N publications » avec un pluriel écrit à la main (12), à côté de `formatCount` ;
  - en-têtes triables (31 dans 9 fichiers), étiquettes retirables (6) ;
  - chargement et liste vide écrits à la main (10 blocs) ; « Chargement… » 23 fois hors `listStatus.ts`.

### Fonctions et libellés

- **Dates** : `formatDate` redéfini dans la page d'une revue, alors que `utils.ts` l'exporte ; format mois-année recodé dans `ThesesTable`.
- **Nombres** : `toLocaleString('fr-FR')` 55 fois dans 28 fichiers ; pourcentages calculés de 7 façons, sans fonction commune.
- **Chargements** : les types de revue, les modèles OA et les types d'éditeur sont chargés deux fois chacun. Les caches de `sources`, `licenses` et `docTypes` répètent le même mécanisme.
- **Divers** : six temporisations de saisie écrites à la main ; 26 signalements d'erreur avec 7 préfixes différents.
- **Icônes** : trois mécanismes (SVG de `IconButton`, SVG de `SectionLabel`, police Flaticon), neuf SVG en ligne, dix glyphes « × » à côté de `IconButton icon="reject"`.
- **Libellés** : types d'identifiant (5 copies), noms des sources (4), libellés OA (`labels.ts` et `pivotValues.ts`), « Top 1 % » (2), nature d'une monographie (3). `filterLabels` et `columnLabels` contournés par des libellés écrits en dur (6). Noms de section répétés dans la navigation, l'en-tête de page et le fil d'Ariane.

## Décisions

- Le code mort et les déclarations redondantes sont supprimés.
- Étiquettes : une seule classe, teintée par la propriété `--tag-color`. Le fond, le texte et le survol en dérivent en OKLCH relatif, à luminosité fixe. Les couleurs des graphiques restent inchangées.

## Phasage

### Phase 1 — Code mort

- [x] Classes mortes et déclarations redondantes de `shared.css` (d081f66ce)
- [x] `RelatedPublications.svelte` et exports inutilisés (d081f66ce)

### Phase 2 — Variables

- [x] Ombres, fond d'overlay, anneau de focus, texte sur accent, espacements de lettres (1daca0c32)
- [x] Teintes de survol en deux formules (373241bc7)

### Phase 3 — Étiquettes

- [x] Classe d'étiquette à variantes de teinte, de taille et de forme ; couleurs des étiquettes en variables (97b683111)
- [x] Étiquettes partagées et locales sur cette classe
- [ ] Icône ronde unique pour les identifiants et les sources

### Phase 4 — Boutons et contrôles

- [ ] Boutons sans bordure, pleins, à contour et en pointillés ; un seul état désactivé
- [ ] Boutons locaux sur les classes partagées, dont `AccessButton` et sa variante compacte ; retrait « × » sur `IconButton`
- [ ] Champs, menus déroulants, panneaux flottants et lignes d'options

### Phase 5 — Utilitaires

- [ ] Classe de texte secondaire
- [ ] Chargement et liste vide sur `ListStatus`
- [ ] Encarts d'information, d'avertissement et de danger
- [ ] Styles de base de `+layout.svelte` dans `shared.css` ; collisions de noms

### Phase 6 — Composants

- [ ] Vues de liste sur une base commune (question 1)
- [ ] Volets sur une base commune (question 2)
- [ ] Listes de tri sur leurs composants génériques ; pages Problèmes HAL et d'administration sur `useUrlFilters`
- [ ] Pages d'entité : en-tête, onglet actif, carte des sujets
- [ ] Balisages recopiés en composants : pastille DOAJ, liens d'éditeur et de revue, nom de personne, en-tête triable

### Phase 7 — Fonctions, libellés et icônes

- [ ] Dates, nombres, pourcentages et pluriels sur `utils.ts` et `plural.ts`
- [ ] Énumérations chargées une fois ; signalement d'erreur unique
- [ ] Libellés sur `labels.ts` ; un nom par section
- [ ] Un mécanisme d'icônes (question 3)

## Questions ouvertes

1. Vues de liste : toutes sur `filterRegistry`, ou un composable de liste qui l'englobe.
2. Volets : un composant de base (en-tête, renommage, fusion), ou des composables partagés.
3. Icônes : un composant `Icon` en SVG, ou la police Flaticon partout.
