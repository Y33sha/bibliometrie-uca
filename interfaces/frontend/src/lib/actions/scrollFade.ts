import type { Action } from 'svelte/action';

/**
 * Estompe les bords d'un conteneur à défilement horizontal du côté où le contenu continue : classes `fade-start` et `fade-end`, mises en forme par `shared.css`.
 *
 * Les classes suivent le défilement, la taille du conteneur et celle de son contenu.
 */
export const scrollFade: Action<HTMLElement> = (node) => {
	const update = () => {
		const max = node.scrollWidth - node.clientWidth;
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
