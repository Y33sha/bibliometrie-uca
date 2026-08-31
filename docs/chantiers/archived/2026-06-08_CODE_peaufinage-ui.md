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

- [x] Composant `Modal` (titre, slot, actions, échap/clic-fond, focus à l'ouverture) + store `dialogs` (`confirmDialog()` promesse, `toast()`) + `DialogHost` global monté dans `+layout` (`d325a4ab`)
- [x] `confirm()`/`alert()` → `confirmDialog()`/`toast()` sur les 9 pages (addresses, config, feedback, journals, persons admin+public, publishers, structures, structures/[id]) ; confirmations destructives en `danger:true` (`88154f6d`)

### Phase 2 — Harmonisation styles + tokens

- [x] **Pas de composant `Button`** : on a aligné les pages divergentes sur le système global `.btn*` existant + ajouté une règle « bouton de toolbar = gabarit des champs voisins » dans `shared.css`. Fait sur countries, duplicates, person-duplicates ; selects d'addresses au look doux des autres pages (`75d35962`). (Validé visuellement par Laura page par page.)
- [x] **Tokens hex → variables** (méthode usage-first, par fonction) :
  - exacts → token, valeurs identiques (`25a99741`) ; fallback `--accent` divergent collapsé (`1db26a5c`).
  - rouges d'erreur/rejet → `--danger`/`--danger-light` (`025f42b7`, inclut suppression de l'override `--danger:#c44` d'addresses).
  - verts succès/validé → `--success`/`--success-light`, `.oa-green` → `--green` (`7c606905`).
  - 3 neutres clairs dominants → `--surface`/`--surface-hover`/`--border-subtle`, valeurs identiques (`9d9b788b`).
  - cohérence bouton inter-modales : « Enregistrer » de EditNameModal en bleu (`57c565e8`).
  - logos de source (au lieu de badges colorés) dans les pages *duplicates via composant `SourceTag` ; icônes en local pour fonctionner hors ligne ; `.source-oa*` renommé `.source-openalex*` (`ecc5a4a8`).
- [ ] **Couleurs restantes = décisions de palette, pas de la dérive** (différé) :
  - *catégoriel* (légitime, à tokeniser ou laisser) : couleurs de **sources** (HAL vert *et* bleu selon les pages — incohérence à trancher, OA, theses, WoS), **statut OA** (les tokens `--gold/--green/--bronze/...` existent mais pas leurs variantes claires type `#fef3e0`), **types de structure**, **statuts de thèse**, **badges de sujets**.
  - *bespoke récurrent sans token* : teal du header/section `#5b9ea0`, bordure info/help `#c4d8ed`.
  - *neutres froids* (`#f5f5f5`, `#fafafa`, `#f0f0f0`, `#eee`) et *échelle de gris texte* (`#666`/`#888`/`#999`/`#ccc`…) : convergence = léger changement visuel → au cas par cas.
  - *textes ambre foncé* (`#856404`…) : pas de token lisible (`--warning` trop clair en texte) → nécessiterait un `--warning-dark`.

### Phase 3 — Responsivité

- [x] Menu de navigation : hamburger + menu vertical sous 860px ; dropdowns desktop passés en CSS pur (`b5e12b33`).
- [x] Grilles dashboard en 1 colonne sous breakpoint + graphiques adaptatifs (`.dash-card` min-width:0, viewBox du nuage de sujets) (`5876e6d2`). Barres à facettes déjà repliables (`.toolbar` flex-wrap).
- [x] Tableaux larges : wrapper `.table-scroll` (scroll horizontal + min-width) ; hauteur bornée + en-têtes figés sous 760px (`c84ef3cb`). Cibles tactiles écartées (usage admin souris, validé).

### Phase 4 — A11y quick-wins (léger)

- [x] **Toutes les modales sur le composant `Modal`** (8 modales custom migrées, 2 systèmes CSS fusionnés) ; `Modal` gère Entrée (valider) + Escape (annuler) ; CSS mort `.modal-bg`/`.modal` supprimé ; −13 warnings a11y (`5c1e2da9`).
- [x] Quick-wins a11y/propreté (portée resserrée, validée) : CSS mort retiré (`css_unused_selector` 28→0, `1aaf82f6`) ; refs canvas en `$state` (`non_reactive_update` 5→0, pas de vrais bugs, `13f14f59`) ; labels associés aux champs dans les modales (`a11y_label_has_associated_control` 23→0, `06acb00c`). **Total warnings svelte-check 113 → 44.** Laissés intentionnellement : `<div>` cliquables (invasif, faible valeur admin) et `state_referenced_locally` (lectures one-shot de props, voulu).

### Phase 5 — Cohérence des états (au fil)

- [x] Chargement / vide / erreur / succès : déjà stylés via classes partagées (`.loading`/`.empty`/`.no-results`) ; erreur/succès via Toast (phase 1) ; texte de chargement uniformisé sur l'ellipse « Chargement… » (`26371c9f`).
- [x] Tableaux : flèches de tri homogènes (↑↓ → ▲▼) + en-têtes de colonnes homogènes (`26371c9f`). `ColumnMenu` **laissé aux publications** (YAGNI — seule table avec assez de colonnes pour justifier le masquage).

## Questions ouvertes

- **Ampleur du noyau de composants.** S'arrêter à `Modal`/`Toast`/`Button` (ma reco) ou aller jusqu'à `Select`/`Tag`/`Badge`/`Card` partagés ? À trancher selon ce que la phase 2 révèle de duplication réelle.
- **Mode sombre / rethème.** Hors scope ici, mais les tokens (décision 3) en sont le prérequis : faut-il viser un thème dès maintenant ou seulement assainir les tokens ?
- **Périmètre tableaux responsives.** Scroll horizontal (simple) vs colonnes masquables/empilées (plus de code) — choisir par type de tableau.
- **Curseur a11y.** Confirmer qu'on se limite aux quick-wins (usage admin) et qu'on ne traite pas le contraste / la navigation clavier complète.
