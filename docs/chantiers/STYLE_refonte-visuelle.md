# Refonte visuelle du frontend

## Contexte

L'apparence du frontend est datée et hétérogène : cartes imbriquées, plusieurs couleurs d'accent (teal du menu, bleu `#3b6b9e` de `--accent`, bleus en dur), palettes open access divergentes entre le dashboard de structure et la page Statistiques, titres de section de styles différents selon les pages.

État du CSS :

- Les variables CSS sont réparties entre deux blocs `:root`, dans `routes/+layout.svelte` et dans `lib/styles/shared.css`.
- 85 composants sur 100 ont leur propre bloc `<style>`. Les couleurs en dur y sont fréquentes (`#888` ×33, `#c0392b` ×12, `#2563eb` ×10…), et 39 appels `var(--x, #valeur)` contiennent une couleur de repli.
- Certaines variables sont utilisées sans être définies : `--fg`, `--mono`, `--bg-muted`.
- Les variables en doublon : `--text-muted` (`#777`) et `--muted` (`#6b7280`), `--section-heading` et le teal du menu.
- Les polices à chasse fixe se répartissent en cinq déclarations différentes.
- Les graphiques (Chart.js) lisent leurs couleurs en JavaScript : `oaStatusColor()` lit les variables CSS, mais le dashboard de structure, `DoughnutChart`, `BarChart` et `SubjectsCloud` codent leurs palettes en dur.
- Deux composants d'onglets coexistent : `TabNav` (onglets synchronisés avec l'URL, pages publiques) et `HubTabs` (onglets à compteur, référentiels d'administration).
- La CSP limite les polices à `font-src 'self'`. La police Ubuntu est servie depuis `static/fonts/`.

Le texte blanc sur le teal de la barre publique (`#5b9ea0`) a un contraste d'environ 3:1, sous le seuil de 4,5:1.

Le modèle visuel de départ est la page d'administration « Configuration du pipeline » : titres de section en petites capitales teal soulignés d'un filet.

## Décisions

- **Un seul niveau de contenant au maximum.** Les zones se séparent par l'espacement et les titres de section. Les cartes et bordures autour des zones de contenu disparaissent.
- **Une seule couleur d'accent : le teal**, en trois nuances (foncée, moyenne, claire). Les valeurs sont plus foncées que le teal actuel, pour le contraste.
- **Toutes les variables dans un seul `:root`**, dans `shared.css`. Les noms existants sont conservés quand la notion existe déjà (`--accent`, `--muted`, `--text`, `--border`…).
- **Les couleurs de rôle passent par les variables** : texte, surfaces, bordures, accent, états. Une palette de catégories (sources, types de structure, voies open access, niveaux de relation) est définie une seule fois, dans une classe de `shared.css` ou un module TypeScript commun. Les teintes de survol se calculent depuis la variable avec `color-mix()`.
- **Un style dupliqué entre composants est factorisé** dans `shared.css`, ou dans un module TypeScript commun pour les palettes de graphiques.
- **Les graphiques lisent leurs couleurs dans les variables CSS**, par `cssVar()`.
- **Palette open access agrégée** (ouvert, sous embargo, fermé, indéterminé) commune à toute l'application. Ouvert en vert, embargo en ambre, fermé en gris foncé, indéterminé en gris clair. Pas de rouge. Les voies (diamond, gold, hybrid, bronze, green) gardent leurs couleurs propres.
- **Police auto-hébergée** dans `static/fonts/` comme Ubuntu, désignée par `--font`. Chiffres tabulaires (`font-variant-numeric: tabular-nums`) sur toute la page.
- **Filtres de liste sur deux niveaux** : le bouton de filtre affiche le nombre de valeurs choisies, la barre « Filtres actifs » détaille ces valeurs avec une croix par filtre. On ajoute ou retire une valeur depuis le bouton sans supprimer le filtre.
- **Un seul style de titre de section** : petites capitales par CSS (`text-transform: uppercase`), texte source en casse normale.
- **Un seul rayon d'arrondi** (`--radius`), 999 px pour les pastilles.
- **Un seul style d'onglets** pour `TabNav` et `HubTabs`.

## Phasage

Chaque étape fait l'objet d'un test visuel par l'utilisatrice avant la suivante.

### Étape 0 — Variables CSS, sans changement visible

- [x] Rassembler les deux blocs `:root` dans `shared.css` (719aad2d3)
- [x] Remplacer les variables non définies par leur équivalent (`--fg` → `--text`, `--bg-muted` → `--surface-hover`) ; définir `--mono` et l'appliquer à toutes les polices à chasse fixe (719aad2d3)
- [x] Fusionner `--text-muted` dans `--muted` (719aad2d3)
- [x] Déclarer en variables les teals de la barre de navigation (`--nav-public`, `--nav-admin` et leurs sous-menus) (719aad2d3)
- [x] Supprimer les couleurs de repli des appels `var()` (719aad2d3)
- [x] Factoriser les styles dupliqués : pastilles de type de structure, bandeau des fiches structure, encart d'information, lien HAL des pages Problèmes HAL, pastille DOAJ, pastille de structure, files de triage (composant `PersonPairsList` pour les paires de personnes), infobulle de `FacetDropdown` (composant `Tooltip`) (181901773)
- [x] Factoriser les dashboards et leurs palettes : grille et cartes `.dash-*`, anneau open access des dashboards de structure et de personne (composant `OaDoughnut`, couleurs lues dans `--open`, `--embargoed`, `--closed`, `--unknown`), palette des sujets (`subjectColor`) (ea2657f5c)
- [x] Remplacer les couleurs de rôle en dur par la variable de même rôle (écarts de teinte faibles acceptés) ; variables ajoutées : `--text-faint`, `--warning-text`, `--attention`, `--attention-light`, `--tooltip-bg` (59ee06448)
- [x] Teintes de survol des couleurs de rôle calculées par `color-mix()` (59ee06448)
- [x] Faire lire aux graphiques et aux statuts du pipeline leurs couleurs de rôle dans les variables (`cssVar()`) (59ee06448)

### Étape 1 — Fondations globales

- [x] Héberger Inter et Source Sans 3 dans `static/fonts/` ; Source Sans 3 appliquée au `body` (`--font`)
- [x] Chiffres tabulaires sur toute la page
- [x] Passer `--accent` au teal foncé ; ajouter les nuances moyenne (`--accent-mid`) et claire ; fusionner `--section-heading` dans `--accent`
- [x] Supprimer le bleu restant (boutons pleins, barres de graphiques, pagination active, liens)
- [x] Trois niveaux de gris de texte : `--text` (principal), `--text-secondary`, `--muted` (discret)
- [x] Fond de page blanc cassé très léger ; surfaces et bordures en gris froids
- [x] Palette open access agrégée : nouvelles valeurs de `--open`, `--embargoed`, `--closed`, `--unknown`
- [x] Style unique de titre de section (`.section-title`, titres des cartes de dashboard, libellés de la fiche publication) ; suppression des bandeaux teal de la fiche structure admin
- [x] `--radius` unique, appliqué partout ; `--radius-pill` pour les pastilles

### Étape 2 — En-tête d'entité et onglets

- [x] En-tête hors carte (classes `entity-*` partagées par les pages structure, personne, revue, éditeur, monographie, sujet) : titre 28–32 px posé sur le fond, sigle en gris à côté
- [x] Identifiants (ROR, HAL, tutelles) en pastilles à fond clair, libellé en petites capitales grises
- [x] Un seul style d'onglets pour `TabNav` et `HubTabs` : alignés à gauche, sans fond ni bordures latérales, onglet actif en texte foncé semi-gras souligné d'un trait de 2–3 px, filet fin sous l'ensemble
- [x] Contenu de l'onglet directement sous les onglets, sans carte

- [x] Fil d'Ariane fondé sur l'arborescence du site (`Breadcrumb`) à la place des liens de retour, sur les pages de détail publiques, la fiche structure admin et la page de qualité de la détection

### Étape 3 — Recherche, filtres et menus

- [x] Zone recherche et filtres sans carte
- [x] Champ de recherche avec icône loupe, bordure fine, focus en couleur d'accent
- [x] Nombre de résultats en texte secondaire, sans encadré
- [x] Action principale en bouton plein couleur d'accent, actions secondaires (« Export CSV », « Export PNG ») en boutons discrets
- [x] Boutons de filtre sans bordure, fond au survol
- [x] Menus déroulants natifs (page Statistiques) au style des boutons de filtre
- [x] Pagination sans bordure, page active en couleur d'accent

### Étape 4 — Tableaux

- [x] Factoriser : tableaux de liste sur `.data-table`, files de triage des revues sur `.triage-table`, colonnes triables et numériques dans `shared.css`, lien de titre `.publication-title` ; restent à part les tableaux de mise en page propre (run du pipeline, comparaison des sources, ISSN, blocages d'éditeurs)
- [x] En-têtes de colonnes sans fond, 11–12 px, gris, petites capitales
- [x] Tableaux sans cadre ; séparateurs de lignes très pâles, fond au survol de la ligne
- [x] Liens des tableaux en couleur d'accent, soulignés au survol ; titre ou nom principal en semi-gras (`.entity-link`, `.publication-title`)
- [x] Colonnes numériques alignées à droite
- [x] Pastilles réservées aux valeurs à code couleur : type de document, statut open access, statut HAL ; structures et fonctions en texte simple
- [x] Boutons d'action secondaires par ligne (modifier, supprimer, exclure) visibles au survol de la ligne ou au focus, sur les écrans à pointeur (`.row-actions`)
- [x] Publications : type de document en pastille, teinte du type dans la page Statistiques (`docTypeColor()`), aussi dans les pages Problèmes HAL
- [x] Personnes : coche de présence dans l'extraction du SI RH allégée (sans pastille pleine)
- [x] Personnes : fonction en texte simple, sans troncature

### Étape 5 — Dashboards

- [x] Rangée de chiffres clés en tête des dashboards de structure et de personne : publications, part en open access, thèses (`KeyFigures`)
- [x] Sujets principaux en barres horizontales, 15 premiers (`SubjectBars`, à la place du nuage de mots) ; dépendance `d3-cloud` retirée
- [x] Publications par année : barres teal, axe vertical à partir de 0, année en cours en teinte claire avec la mention « en cours » (`PublicationsByYearChart`) ; valeurs au bout des barres
- [x] Open access des dashboards de structure et de personne en barre empilée horizontale, part d'ouvert en grand (`OaBar`) ; les dashboards de revue et d'éditeur gardent l'anneau des voies
- [x] Graphiques sans carte ni bordure, sous un titre de section
- [x] Police `--font` dans les graphiques : Chart.js initialisé une fois (`chart.ts`), graphe des sujets ; `cssColor()` généralisé en `cssVar()`

### Étape 6 — Page Statistiques

- [x] Réglages du graphique (indicateur, mesure, comparer par, part, tri) sur une ligne, filtres sur une autre
- [x] Graphique sans cadre ; « Export PNG » discret en haut à droite, toujours visible
- [x] Légende alignée à gauche au-dessus du graphique
- [x] Libellés tronqués à 45 caractères au lieu de 30, libellé complet au survol
- [x] Carte des collaborations : dégradé teal au lieu de bleu

### Étape 7 — Pages d'administration

- [x] Boutons Modifier et Supprimer de l'administration en icônes sans bordure, crayon et corbeille, libellé en infobulle (`IconButton`) (0398a8dbd)
- [x] Configuration du pipeline : une liste par section, lignes séparées par des filets ; encart d'information en teal clair
- [x] Fiche structure : hors carte ; en-tête avec type en pastille, sigle en gras, nom complet, actions à droite
- [x] Fiche structure : tutelles et « est tutelle de » en grille libellé / valeurs, sans titre en double
- [x] Fiche structure : croix des pastilles de tutelles grises, rouges au survol ; bouton « + Ajouter » discret
- [x] Fiche structure : formes de noms avec compteur en pastille, actions visibles au survol, formulaire d'ajout sur fond léger

### Étape 8 — Barre de navigation publique

- [x] Rubriques en pastilles arrondies, rubrique active sur fond plus clair ; contraste des liens relevé ; hauteurs liées à `--header-height`
- [x] Barre teal retenue ; variante blanche écartée

### Étape 9 — Vérifications

- [ ] Contraste des gris de texte (au moins 4,5:1 pour le texte courant)
- [ ] Couleurs des graphiques distinguables par la luminosité
- [ ] Affichage à largeur réduite
- [ ] Pages restantes : référentiels, problèmes HAL, adresses, pages d'erreur

## Questions ouvertes

- Police : Source Sans 3 ou Inter, à trancher après essai sur d'autres écrans. La police écartée sera supprimée de `static/fonts/` et de `app.html`.
- Compteurs dans les onglets d'entité (« Publications 1 849 »). Sans objet pour le dashboard, sans intérêt pour les adresses et les collaborations. Pour les autres onglets, reste à choisir entre le total de l'entité et le total filtré. `TabNav` accepte déjà un compteur.
- Mode sombre, une fois toutes les couleurs en variables.

## Annexe — valeurs de départ

Valeurs à ajuster à l'écran.

```css
:root {
	/* Accent */
	--accent: #1f5f5f;        /* texte, bouton plein */
	--accent-mid: #2f8a8a;    /* trait d'onglet actif, focus */
	--accent-light: #e6f2f2;  /* fond de pastille, encart */

	/* Navigation */
	--nav-public: #2f7f7f;
	--nav-admin: #1f5f5f;

	/* Texte */
	--text: #1d2433;
	--text-secondary: #5b6474;
	--muted: #6b7280;

	/* Surfaces et lignes */
	--bg: #fbfbfa;
	--card: #ffffff;
	--border: #ebedf0;
	--hover: #f4f6f7;

	/* Open access agrégé */
	--open: #2e9b4f;
	--embargoed: #d29a1e;
	--closed: #4b5260;
	--unknown: #c9ced6;

	/* Action destructive */
	--danger: #b42318;

	/* Forme */
	--radius: 8px;
	--font: "Inter", system-ui, sans-serif;
}
```
