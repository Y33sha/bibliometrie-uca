import type { Action } from 'svelte/action';
import { dismissable } from '#lib/actions/dismissable.js';

const FACET_OPENED = 'facet-opened';

/**
 * État du panneau d'un filtre de liste (facette, filtre d'entité, filtre de présence).
 *
 * Un seul panneau est ouvert à la fois : ouvrir un panneau ferme les autres. Le panneau se ferme au clic hors du filtre et par Échap. L'action `root` se pose sur l'élément qui contient le bouton et le panneau.
 */
export function useFacetPanel() {
	let open = $state(false);
	const id = Symbol();

	function show() {
		window.dispatchEvent(new CustomEvent(FACET_OPENED, { detail: id }));
		open = true;
	}

	function toggle() {
		if (open) open = false;
		else show();
	}

	const root: Action<HTMLElement> = (node) => {
		const onOtherOpened = (e: Event) => {
			if ((e as CustomEvent).detail !== id) open = false;
		};
		window.addEventListener(FACET_OPENED, onOtherOpened);
		const dismiss = dismissable(node, () => {
			open = false;
		});
		return {
			destroy() {
				window.removeEventListener(FACET_OPENED, onOtherOpened);
				dismiss?.destroy?.();
			},
		};
	};

	return {
		get open() {
			return open;
		},
		set open(value: boolean) {
			open = value;
		},
		show,
		toggle,
		root,
	};
}
