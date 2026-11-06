import type { Action } from 'svelte/action';

/**
 * Affiche en entier un libellé tronqué par des points de suspension, dès que le pointeur entre dans la ligne qui le contient.
 *
 * Le libellé complet se pose par-dessus le libellé tronqué, dans la même police, sur un fond de carte (`.truncated-reveal`, dans `shared.css`). Il recouvre ce qui suit dans la ligne, par exemple un décompte, et peut déborder du conteneur. Il ne capte pas le pointeur et disparaît quand le pointeur quitte la ligne ou que la page défile. Un libellé entier n'est pas repris.
 */
export const revealTruncated: Action<HTMLElement> = (node) => {
	const row = node.parentElement ?? node;
	let overlay: HTMLElement | null = null;

	function hide() {
		overlay?.remove();
		overlay = null;
		window.removeEventListener('scroll', hide, true);
	}

	function show() {
		if (node.scrollWidth <= node.clientWidth) return;
		hide();
		const rect = node.getBoundingClientRect();
		const style = getComputedStyle(node);
		overlay = document.createElement('div');
		overlay.className = 'truncated-reveal';
		overlay.textContent = node.textContent;
		overlay.style.font = style.font;
		overlay.style.color = style.color;
		overlay.style.left = `${rect.left}px`;
		overlay.style.top = `${rect.top}px`;
		overlay.style.minHeight = `${rect.height}px`;
		overlay.style.maxWidth = `${window.innerWidth - rect.left - 8}px`;
		document.body.appendChild(overlay);
		window.addEventListener('scroll', hide, true);
	}

	row.addEventListener('pointerenter', show);
	row.addEventListener('pointerleave', hide);
	return {
		destroy() {
			hide();
			row.removeEventListener('pointerenter', show);
			row.removeEventListener('pointerleave', hide);
		},
	};
};
