/**
 * Résout un href de markdown vers une URL finale.
 *
 * - Liens externes (http(s), mailto:, protocol-relative) : inchangés
 * - Liens absolus (/...) : inchangés
 * - Ancres pures (#section) : inchangées (la page courante)
 * - Sinon : lien interne vers une page de doc, préfixé par `${base}/docs/`
 *   et `.md` final éventuellement strippé
 */
export function resolveDocLink(href: string, base: string): string {
	if (/^(https?:|mailto:|\/\/|\/|#)/.test(href)) return href;
	const stripped = href.replace(/\.md(?=$|#)/, '');
	return `${base}/docs/${stripped}`;
}
