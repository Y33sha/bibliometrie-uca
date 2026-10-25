/**
 * Valeur d'une variable CSS de `shared.css`, pour les bibliothèques de graphiques qui attendent une couleur résolue (un canvas ne sait pas interpréter `var(...)`). Renvoie une chaîne vide si la variable est absente.
 */
export function cssColor(name: string): string {
	return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

/**
 * Couleur d'un statut open access, lue dans la variable CSS de même nom : une valeur de `oa_status` (`diamond`, `gold`, `hybrid`, `bronze`, `green`, `embargoed`, `closed`, `unknown`) ou la catégorie agrégée `open`. Renvoie `undefined` si la variable est absente : le graphique retombe alors sur sa palette.
 */
export function oaStatusColor(status: string | null | undefined): string | undefined {
	return cssColor(status || 'unknown') || undefined;
}
