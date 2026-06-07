# Chantier — Peaufinage UI (cohérence, responsivité, ergonomie)

Issu d'un item TODO_LAURA (« responsivité minimale de l'interface », « remplacer les confirm() par de vrais composants modals », styles divergents) + audit UI 2026-06-07.

## Contexte

L'interface (SvelteKit / Svelte 5) est pensée grand écran, à usage majoritairement **admin avec une poignée d'utilisateurs**. Plusieurs aspérités de finition se sont accumulées :

- **Styles réinventés par page.** Chaque page redéfinit ses boutons/tags/dropdowns en `<style>` local (`.btn-primary`/`.btn-secondary`/`.btn-suggest` réécrits, badges/tags avec couleurs **hex en dur** type `#c44`, `#2a7d4f`, `#fef3e0` à côté des `var(--accent)`/`var(--border)`). Résultat : pages visuellement divergentes — boutons de `admin/duplicates` et `admin/person-duplicates`, dropdowns de `admin/addresses` et `admin/countries`.
- **Dialogues natifs bruts.** `confirm()` / `alert()` dispersés dans ~9 pages admin (journals, structures/[id], config, feedback, publishers, structures, addresses, persons…) — pas de modale ni de toast réutilisables.
- **Responsivité clunky.** Le menu de navigation ([`+layout.svelte`](../../interfaces/frontend/src/routes/+layout.svelte)) ne se compacte pas proprement en petit écran (pas de hamburger) ; grilles dashboard en colonnes fixes (`laboratories/[id]` : `.dash-grid { grid-template-columns: 1fr 1fr }` sans media query) ; tableaux larges sans stratégie de débordement ; cibles tactiles minuscules (`.add-country { width: 32px }`, `×` de suppression de tag).
- **A11y** : `svelte-check` remonte ~100 warnings (div cliquables sans clavier, selects sans label…). Vu l'usage admin restreint, on ne vise **pas** une conformité WCAG complète — seulement des quick-wins peu coûteux.
- **États incohérents** : feedback d'erreur (`alert` brut vs rien), de chargement (« Chargement… » par endroits), de vide (« Aucune… » par endroits), de succès (le `batchResult` éphémère d'admin/countries).

Objectif : peaufinage cohérence + ergonomie, **sans sur-ingénierie ni code trop intensif**.

## Décisions

*(Proposées, questionnables. La fiche documente l'état et les écarts ; elle ne préjuge pas de qui implémente.)*

1. **Levier principal : un petit noyau de composants partagés**, pas un design system complet. Cibler les plus rentables d'abord — `Modal`, `Toast`, `Button` — qui résorbent à eux seuls la majorité des divergences. Les `Select`/`Tag`/`Badge` partagés viennent ensuite si le besoin se confirme (cf. questions).
2. **`confirm()`/`alert()` → `Modal`/`Toast` réutilisables.** Une modale de confirmation (titre, message, actions, focus-trap, échap/clic-fond pour fermer) + un toast pour succès/erreur. Remplace les dialogues natifs au fil des pages.
3. **Tokens couleur.** Remplacer les hex en dur par des variables CSS (`--success`, `--danger`, `--warning`…) — prérequis d'un rethème cohérent, et ça uniformise badges/tags.
4. **Responsivité gracieuse** : menu hamburger + repli du nav en petit écran ; grilles dashboard et barres à facettes en media queries ; conteneur de scroll pour les tableaux larges ; agrandir les cibles tactiles.
5. **A11y : quick-wins scopés seulement.** Gestion clavier sur les `<div>` cliquables déjà signalés par `svelte-check`, `<label>` manquants, focus-trap dans la nouvelle `Modal`. Pas de chasse exhaustive aux warnings.
6. **Cohérence des états.** Patterns uniformes chargement / vide / erreur / succès, portés par les composants partagés (Toast pour erreur/succès).

## Phasage

### Phase 1 — Modale + toast réutilisables

- [x] Composant `Modal` (titre, slot, actions, échap/clic-fond, focus à l'ouverture) + store `dialogs` (`confirmDialog()` promesse, `toast()`) + `DialogHost` global monté dans `+layout` (`5ac03d5f`)
- [x] `confirm()`/`alert()` → `confirmDialog()`/`toast()` sur les 9 pages (addresses, config, feedback, journals, persons admin+public, publishers, structures, structures/[id]) ; confirmations destructives en `danger:true` (`804268e6`)

### Phase 2 — Harmonisation styles + tokens

- [ ] Composant `Button` (variantes primary/secondary/danger/ghost) ; brancher les pages aux boutons divergents (`admin/duplicates`, `admin/person-duplicates`, `admin/addresses`, `admin/countries`).
- [ ] Remplacer les couleurs hex en dur par des tokens CSS (`--success`/`--danger`/`--warning`…) dans les `<style>` des pages/composants.

### Phase 3 — Responsivité

- [ ] Menu de navigation : hamburger + repli propre en petit écran (`+layout.svelte`).
- [ ] Grilles dashboard + barres à facettes : media queries (1 colonne en petit écran).
- [ ] Tableaux larges : conteneur de scroll horizontal ou colonnes masquables ; cibles tactiles agrandies.

### Phase 4 — A11y quick-wins (léger)

- [ ] Résorber les warnings `svelte-check` triviaux (clavier sur div cliquables, labels de selects) ; focus-trap déjà couvert par `Modal` (phase 1).

### Phase 5 — Cohérence des états (au fil)

- [ ] Uniformiser chargement / vide / erreur / succès via les composants partagés.
- [ ] Tableaux : indicateurs de tri homogènes ; généraliser le menu de colonnes (`ColumnMenu`) au-delà de publications si pertinent.

## Questions ouvertes

- **Ampleur du noyau de composants.** S'arrêter à `Modal`/`Toast`/`Button` (ma reco) ou aller jusqu'à `Select`/`Tag`/`Badge`/`Card` partagés ? À trancher selon ce que la phase 2 révèle de duplication réelle.
- **Mode sombre / rethème.** Hors scope ici, mais les tokens (décision 3) en sont le prérequis : faut-il viser un thème dès maintenant ou seulement assainir les tokens ?
- **Périmètre tableaux responsives.** Scroll horizontal (simple) vs colonnes masquables/empilées (plus de code) — choisir par type de tableau.
- **Curseur a11y.** Confirmer qu'on se limite aux quick-wins (usage admin) et qu'on ne traite pas le contraste / la navigation clavier complète.
