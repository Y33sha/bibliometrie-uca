// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { tooltip, tooltipState } from './tooltip.svelte';

function element(text = ''): HTMLElement {
	const node = document.createElement('span');
	node.textContent = text;
	document.body.appendChild(node);
	return node;
}

describe('tooltip', () => {
	it('affiche le texte au survol et le retire à la sortie', () => {
		const node = element('DOI');
		tooltip(node, '10.1000/xyz');
		node.dispatchEvent(new MouseEvent('mouseenter'));
		expect(tooltipState.anchor?.text).toBe('10.1000/xyz');
		node.dispatchEvent(new MouseEvent('mouseleave'));
		expect(tooltipState.anchor).toBeNull();
	});

	it('n’affiche rien pour un texte vide', () => {
		const node = element('Laboratoire');
		tooltip(node, undefined);
		node.dispatchEvent(new MouseEvent('mouseenter'));
		expect(tooltipState.anchor).toBeNull();
	});

	it('décrit un élément nommé par son texte', () => {
		const node = element('LIMOS');
		tooltip(node, 'Dernier laboratoire');
		expect(node.getAttribute('aria-description')).toBe('Dernier laboratoire');
		expect(node.hasAttribute('aria-label')).toBe(false);
	});

	it('nomme un élément sans texte', () => {
		const node = element();
		tooltip(node, 'Voir la fiche publique');
		expect(node.getAttribute('aria-label')).toBe('Voir la fiche publique');
	});

	it('suit le nouveau texte et retire l’infobulle à la destruction', () => {
		const node = element('Tri');
		const action = tooltip(node, 'Ordre croissant');
		node.dispatchEvent(new MouseEvent('mouseenter'));
		action.update('Ordre décroissant');
		expect(tooltipState.anchor?.text).toBe('Ordre décroissant');
		action.destroy();
		expect(tooltipState.anchor).toBeNull();
	});
});
