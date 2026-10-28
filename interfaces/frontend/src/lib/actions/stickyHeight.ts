import type { Action } from 'svelte/action';

/**
 * Publie dans une variable CSS de la racine du document la hauteur visible du nœud : sa hauteur moins la part `hidden`, en pixels. La variable suit les changements de taille du nœud.
 *
 * Le nœud est une barre collante posée au-dessus d'un tableau de liste, et `hidden` la part de la barre glissée sous le menu supérieur. L'en-tête du tableau se colle sous la part visible des barres.
 */
export const stickyHeight: Action<HTMLElement, { variable: string; hidden?: number }> = (node, params) => {
	const root = document.documentElement;
	let { variable, hidden = 0 } = params;
	const publish = () => root.style.setProperty(variable, `${Math.max(0, node.offsetHeight - hidden)}px`);
	const observer = new ResizeObserver(publish);
	observer.observe(node);
	publish();
	return {
		update(next) {
			root.style.removeProperty(variable);
			({ variable, hidden = 0 } = next);
			publish();
		},
		destroy() {
			observer.disconnect();
			root.style.removeProperty(variable);
		},
	};
};
