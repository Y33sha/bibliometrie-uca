/**
 * Infobulle d'un élément, affichée au survol et au focus par l'unique `<TooltipHost>` de la mise en page.
 *
 * Usage : `<td use:tooltip={texte}>`. Un texte vide n'affiche rien. Le texte sert aussi de description accessible (`aria-description`), ou de nom accessible pour un élément sans texte.
 */

type Anchor = { text: string; rect: DOMRect };

/** Infobulle affichée, lue par `<TooltipHost>`. */
export const tooltipState = $state<{ anchor: Anchor | null }>({ anchor: null });

let owner: Element | null = null;

function show(node: Element, text: string | null | undefined) {
	if (!text) return;
	owner = node;
	tooltipState.anchor = { text, rect: node.getBoundingClientRect() };
}

function hide(node: Element) {
	if (owner !== node) return;
	owner = null;
	tooltipState.anchor = null;
}

export function tooltip(node: HTMLElement | SVGElement, text: string | null | undefined) {
	let current = text;
	// Sans texte ni `aria-label` (icône seule), le texte de l'infobulle nomme l'élément.
	const named = Boolean(node.getAttribute('aria-label') || node.textContent?.trim());
	const describe = () => {
		const attribute = named ? 'aria-description' : 'aria-label';
		if (current && current !== node.getAttribute('aria-label')) node.setAttribute(attribute, current);
		else if (!current) node.removeAttribute(attribute);
	};
	const onEnter = () => show(node, current);
	const onLeave = () => hide(node);
	describe();
	node.addEventListener('mouseenter', onEnter);
	node.addEventListener('mouseleave', onLeave);
	node.addEventListener('focusin', onEnter);
	node.addEventListener('focusout', onLeave);
	return {
		update(next: string | null | undefined) {
			current = next;
			describe();
			if (owner === node) {
				if (current) show(node, current);
				else hide(node);
			}
		},
		destroy() {
			node.removeEventListener('mouseenter', onEnter);
			node.removeEventListener('mouseleave', onLeave);
			node.removeEventListener('focusin', onEnter);
			node.removeEventListener('focusout', onLeave);
			hide(node);
		},
	};
}
