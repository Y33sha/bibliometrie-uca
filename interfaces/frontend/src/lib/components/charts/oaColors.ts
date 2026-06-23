/**
 * Couleur sémantique d'un statut Open Access, reprise des variables CSS
 * globales de la page statistiques (`--diamond`, `--gold`, `--hybrid`,
 * `--bronze`, `--green`, `--embargoed`, `--closed`, `--unknown`, définies sur
 * `:root` dans le layout racine). Le nom de variable correspond exactement à la
 * valeur de `oa_status`.
 *
 * Résolue au runtime côté client (le canvas ne sait pas interpréter `var(...)`).
 * Renvoie `undefined` côté serveur ou si la variable est absente : le composant
 * graphique retombe alors sur sa palette neutre.
 */
export function oaStatusColor(status: string | null | undefined): string | undefined {
	if (typeof document === 'undefined') return undefined;
	const key = status || 'unknown';
	const value = getComputedStyle(document.documentElement).getPropertyValue(`--${key}`).trim();
	return value || undefined;
}
