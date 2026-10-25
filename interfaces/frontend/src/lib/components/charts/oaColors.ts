/**
 * Couleur d'un statut open access, lue dans la variable CSS de même nom (`shared.css`) : une valeur de `oa_status` (`diamond`, `gold`, `hybrid`, `bronze`, `green`, `embargoed`, `closed`, `unknown`) ou la catégorie agrégée `open`.
 *
 * Résolue au runtime côté client (le canvas ne sait pas interpréter `var(...)`). Renvoie `undefined` côté serveur ou si la variable est absente : le composant graphique retombe alors sur sa palette neutre.
 */
export function oaStatusColor(status: string | null | undefined): string | undefined {
	if (typeof document === 'undefined') return undefined;
	const key = status || 'unknown';
	const value = getComputedStyle(document.documentElement).getPropertyValue(`--${key}`).trim();
	return value || undefined;
}
