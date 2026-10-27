import type { Action } from 'svelte/action';

/**
 * Publie la hauteur du nœud dans la variable CSS `--list-sticky-height` de la racine du document, et la tient à jour quand le nœud change de taille.
 *
 * Le nœud est la bande collante posée au-dessus d'un tableau de liste : l'en-tête du tableau se colle sous elle.
 */
export const stickyHeight: Action<HTMLElement> = (node) => {
	const root = document.documentElement;
	const publish = () => root.style.setProperty('--list-sticky-height', `${node.offsetHeight}px`);
	const observer = new ResizeObserver(publish);
	observer.observe(node);
	publish();
	return {
		destroy() {
			observer.disconnect();
			root.style.removeProperty('--list-sticky-height');
		},
	};
};
