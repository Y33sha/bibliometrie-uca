import type { Action } from 'svelte/action';

/**
 * Publie la hauteur du nœud dans la variable CSS `--list-sticky-height` de la racine du document, et la tient à jour quand le nœud change de taille. Avec le paramètre `false`, la variable vaut zéro.
 *
 * Le nœud est la barre collante posée au-dessus d'un tableau de liste : l'en-tête du tableau se colle sous elle, ou sous le menu supérieur quand elle est masquée.
 */
export const stickyHeight: Action<HTMLElement, boolean | undefined> = (node, shown = true) => {
	const root = document.documentElement;
	let visible = shown;
	const publish = () =>
		root.style.setProperty('--list-sticky-height', `${visible ? node.offsetHeight : 0}px`);
	const observer = new ResizeObserver(publish);
	observer.observe(node);
	publish();
	return {
		update(next = true) {
			visible = next;
			publish();
		},
		destroy() {
			observer.disconnect();
			root.style.removeProperty('--list-sticky-height');
		},
	};
};
