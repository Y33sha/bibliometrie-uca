/**
 * Ancre un panneau flottant (menu, liste de résultats, infobulle) sous son déclencheur, en position fixe.
 *
 * Un panneau en position absolue est rogné par tout ancêtre dont le débordement est masqué ou défilant. C'est le cas de `.table-scroll` : son `overflow-x: auto` rend aussi son `overflow-y` calculé `auto`. En position fixe, le panneau échappe à ces ancêtres. Sa position suit l'ancre au défilement de n'importe quel conteneur et au redimensionnement de la fenêtre.
 *
 * L'ancre est le parent du panneau, sauf mention contraire. Le panneau passe au-dessus de l'ancre quand la place manque en bas de la fenêtre.
 */
export interface AnchoredOptions {
	/** Bord de l'ancre sur lequel s'aligne le panneau : gauche, droit, ou centre. */
	align?: 'start' | 'end' | 'center';
	/** Écart en pixels entre l'ancre et le panneau. */
	offset?: number;
	anchor?: HTMLElement | null;
}

export function anchored(node: HTMLElement, options: AnchoredOptions = {}) {
	let opts = options;

	function place() {
		const anchor = opts.anchor ?? node.parentElement;
		if (!anchor) return;
		const align = opts.align ?? 'start';
		const offset = opts.offset ?? 4;
		const r = anchor.getBoundingClientRect();
		node.style.position = 'fixed';
		node.style.bottom = 'auto';

		node.style.transform = align === 'center' ? 'translateX(-50%)' : 'none';
		if (align === 'end') {
			node.style.left = 'auto';
			node.style.right = `${document.documentElement.clientWidth - r.right}px`;
		} else {
			node.style.left = `${align === 'center' ? r.left + r.width / 2 : r.left}px`;
			node.style.right = 'auto';
		}

		const height = node.offsetHeight;
		const spaceBelow = window.innerHeight - r.bottom - offset;
		const spaceAbove = r.top - offset;
		const above = height > spaceBelow && spaceAbove > spaceBelow;
		node.style.top = above ? `${r.top - offset - height}px` : `${r.bottom + offset}px`;
	}

	place();
	// Le contenu du panneau (résultats d'une recherche) change sa hauteur : on recalcule, pour le cas où il passe au-dessus.
	const resize = new ResizeObserver(place);
	resize.observe(node);
	window.addEventListener('scroll', place, { capture: true, passive: true });
	window.addEventListener('resize', place, { passive: true });

	return {
		update(next: AnchoredOptions = {}) {
			opts = next;
			place();
		},
		destroy() {
			resize.disconnect();
			window.removeEventListener('scroll', place, { capture: true });
			window.removeEventListener('resize', place);
		},
	};
}
