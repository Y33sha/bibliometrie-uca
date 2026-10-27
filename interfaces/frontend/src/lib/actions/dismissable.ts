import type { Action } from 'svelte/action';

/**
 * Appelle `onDismiss` à l'appui du pointeur hors du nœud et à la touche Échap.
 *
 * L'appui précède le clic et tout nouveau rendu : l'appui qui ouvre un panneau est passé avant que le panneau ne pose cette action, et un élément du nœud retiré ensuite par le rendu compte bien comme intérieur.
 */
export const dismissable: Action<HTMLElement, () => void> = (node, onDismiss) => {
	let dismiss = onDismiss;
	const onPointerdown = (e: PointerEvent) => {
		if (!node.contains(e.target as Node)) dismiss();
	};
	const onKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Escape') dismiss();
	};
	window.addEventListener('pointerdown', onPointerdown);
	window.addEventListener('keydown', onKeydown);
	return {
		update(next) {
			dismiss = next;
		},
		destroy() {
			window.removeEventListener('pointerdown', onPointerdown);
			window.removeEventListener('keydown', onKeydown);
		},
	};
};
