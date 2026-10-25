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
- **Les graphiques lisent leurs couleurs dans les variables CSS**, sur le modèle d'`oaStatusColor()`.
- **Palette open access agrégée** (ouvert, sous embargo, fermé, indéterminé) commune à toute l'application. Ouvert en vert, embargo en ambre, fermé en gris foncé, indéterminé en gris clair. Pas de rouge. Les voies (diamond, gold, hybrid, bronze, green) gardent leurs couleurs propres.
- **Police Inter**, hébergée dans `static/fonts/` comme Ubuntu. Chiffres tabulaires (`font-variant-numeric: tabular-nums`) dans les tableaux et les chiffres clés.
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
- [x] Factoriser les styles dupliqués : pastilles de type de structure, bandeau des fiches structure, encart d'information, lien HAL des pages Problèmes HAL, pastille DOAJ, pastille de structure, files de triage (composant `PersonPairsList` pour les paires de personnes), infobulle de `FacetDropdown` (composant `Tooltip`)
- [ ] Factoriser les palettes de graphiques : open access agrégé des dashboards de structure et de personne, nuage de sujets (`SubjectsCloud`, `SubjectGraph`)
- [ ] Remplacer les couleurs de rôle en dur par la variable de même rôle (écarts de teinte faibles acceptés) ; créer une variable pour un rôle qui n'en a pas
- [ ] Teintes de survol calculées par `color-mix()`
- [ ] Faire lire aux graphiques (`BarChart`, `DoughnutChart`, `SubjectsCloud`, dashboards) leurs couleurs dans les variables, valeurs actuelles inchangées

### Étape 1 — Fondations globales

- [ ] Héberger Inter dans `static/fonts/` et l'appliquer au `body`
- [ ] Chiffres tabulaires sur les tableaux et les chiffres clés
- [ ] Passer `--accent` au teal foncé ; ajouter les nuances moyenne et claire ; fusionner `--section-heading` dans `--accent`
- [ ] Supprimer le bleu restant (boutons pleins, barres de graphiques, pagination active, liens)
- [ ] Trois niveaux de gris de texte : `--text` (principal), `--text-secondary`, `--muted` (discret)
- [ ] Fond de page blanc cassé très léger
- [ ] Palette open access agrégée : nouvelles valeurs de `--open`, `--embargoed`, `--closed`, `--unknown` ; dashboard de structure branché sur ces variables
- [ ] Style unique de titre de section ; suppression des bandeaux teal pleine largeur (fiche structure admin) et des titres gras dans des cartes (dashboard)
- [ ] `--radius` unique, appliqué partout ; 999 px pour les pastilles

### Étape 2 — En-tête d'entité et onglets

- [ ] En-tête hors carte : titre 28–32 px posé sur le fond, sigle en gris à côté
- [ ] Identifiants (ROR, HAL, tutelles) en pastilles à fond clair, libellé en petites capitales grises
- [ ] Un seul style d'onglets pour `TabNav` et `HubTabs` : alignés à gauche, sans fond ni bordures latérales, onglet actif en texte foncé semi-gras souligné d'un trait de 2–3 px, filet fin sous l'ensemble
- [ ] Compteur discret dans les onglets d'entité (« Publications 1 849 »)
- [ ] Contenu de l'onglet directement sous les onglets, sans carte

### Étape 3 — Recherche, filtres et menus

- [ ] Zone recherche et filtres sans carte
- [ ] Champ de recherche avec icône loupe, bordure fine, focus en couleur d'accent
- [ ] Nombre de résultats en texte secondaire, sans encadré
- [ ] Action principale en bouton plein couleur d'accent, actions secondaires (« Export CSV », « Export PNG ») en boutons discrets
- [ ] Boutons de filtre sans bordure, fond au survol
- [ ] Filtre actif en pastille couleur d'accent avec la valeur et une croix (« Années : 2020–2026 × », « Types : 6 sélectionnés × »), à la place des badges numérotés
- [ ] Menus déroulants natifs (page Statistiques) au style des boutons de filtre
- [ ] Pagination sans bordure, page active en couleur d'accent

### Étape 4 — Tableaux

- [ ] En-têtes de colonnes sans fond, 11–12 px, gris, petites capitales
- [ ] Séparateurs de lignes très pâles, fond au survol de la ligne
- [ ] Liens des tableaux en couleur de texte principale, couleur d'accent au survol
- [ ] Colonnes numériques alignées à droite
- [ ] Pastilles réservées aux valeurs à code couleur (type de document, mode de correspondance)
- [ ] Boutons d'action par ligne en icônes sans bordure, visibles au survol de la ligne
- [ ] Publications : type de document en pastille, une teinte par type ; icônes de la colonne « Liens » de taille et d'espacement homogènes
- [ ] Personnes : marque discrète sur les personnes non vérifiées, à la place de la coche sur chaque ligne
- [ ] Personnes : un emplacement fixe par identifiant (ORCID, IdRef, HAL…), toujours dans le même ordre, rond vide pâle pour un identifiant absent
- [ ] Personnes : fonction en texte simple, sans troncature

### Étape 5 — Dashboards

- [ ] Rangée de chiffres clés en tête d'onglet : publications, part en open access, personnes, thèses
- [ ] Sujets principaux en barres horizontales (15 premiers)
- [ ] Publications par année : barres teal, axe vertical à partir de 0, année en cours distinguée (barre claire et mention « en cours »)
- [ ] Open access en barre empilée horizontale, pourcentage d'ouvert en grand
- [ ] Graphiques sans carte ni bordure, sous un titre de section

### Étape 6 — Page Statistiques

- [ ] Réglages du graphique (indicateur, mesure, comparer par, part, tri) sur une ligne, filtres sur une autre
- [ ] Graphique sans cadre ; « Export PNG » discret en haut à droite
- [ ] Légende alignée à gauche au-dessus du graphique
- [ ] Colonne de libellés plus large, libellé complet au survol

### Étape 7 — Pages d'administration

- [ ] Configuration du pipeline : une liste par section, lignes séparées par des filets ; boutons « Modifier » sans bordure ; encart d'information en teal clair
- [ ] Fiche structure : en-tête avec type en pastille, sigle en gras, nom complet, actions à droite ; « Éditer » en bouton discret, « Supprimer » en texte rouge sans fond
- [ ] Fiche structure : suppression du titre « Tutelles » en double
- [ ] Fiche structure : croix des pastilles de tutelles grises, rouges au survol
- [ ] Fiche structure : formes de noms avec boutons crayon et croix sans bordure, visibles au survol ; formulaire d'ajout aligné sur les colonnes du tableau

### Étape 8 — Barre de navigation publique

- [ ] Choisir entre la barre teal plus basse (rubrique active sur fond plus clair) et une barre blanche (logo en couleur, rubrique active soulignée en teal)

### Étape 9 — Vérifications

- [ ] Contraste des gris de texte (au moins 4,5:1 pour le texte courant)
- [ ] Couleurs des graphiques distinguables par la luminosité
- [ ] Affichage à largeur réduite
- [ ] Pages restantes : référentiels, problèmes HAL, adresses, pages d'erreur

## Questions ouvertes

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
