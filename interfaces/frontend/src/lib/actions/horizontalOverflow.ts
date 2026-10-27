import type { Action } from 'svelte/action';

/**
 * Signale par des classes le débordement horizontal d'un conteneur, mises en forme par `shared.css` :
 * - `overflowing` quand le contenu est plus large que le conteneur ;
 * - `fade-start` et `fade-end` du côté où le contenu continue, pour en estomper le bord.
 *
 * Les classes suivent le défilement, la taille du conteneur et celle de son contenu.
 */
export const horizontalOverflow: Action<HTMLElement> = (node) => {
	const update = () => {
		const max = node.scrollWidth - node.clientWidth;
		node.classList.toggle('overflowing', max > 1);
		node.classList.toggle('fade-start', node.scrollLeft > 1);
		node.classList.toggle('fade-end', node.scrollLeft < max - 1);
	};
	const observer = new ResizeObserver(update);
	const observeChildren = () => {
		observer.disconnect();
		observer.observe(node);
		for (const child of node.children) observer.observe(child);
	};
	const mutations = new MutationObserver(observeChildren);
	mutations.observe(node, { childList: true });
	observeChildren();
	node.addEventListener('scroll', update, { passive: true });
	update();
	return {
		destroy() {
			observer.disconnect();
			mutations.disconnect();
			node.removeEventListener('scroll', update);
		},
	};
};
