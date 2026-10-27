import type { Action } from 'svelte/action';

/**
 * Publie dans la variable CSS `--list-sticky-height` de la racine du document la hauteur visible du nœud : sa hauteur moins le paramètre, en pixels. La variable suit les changements de taille du nœud.
 *
 * Le nœud est la barre collante posée au-dessus d'un tableau de liste, et le paramètre la part de la barre glissée sous le menu supérieur. L'en-tête du tableau se colle sous la part visible.
 */
export const stickyHeight: Action<HTMLElement, number | undefined> = (node, hiddenPart = 0) => {
	const root = document.documentElement;
	let hidden = hiddenPart;
	const publish = () =>
		root.style.setProperty('--list-sticky-height', `${Math.max(0, node.offsetHeight - hidden)}px`);
	const observer = new ResizeObserver(publish);
	observer.observe(node);
	publish();
	return {
		update(next = 0) {
			hidden = next;
			publish();
		},
		destroy() {
			observer.disconnect();
			root.style.removeProperty('--list-sticky-height');
		},
	};
};
