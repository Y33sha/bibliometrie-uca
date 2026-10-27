// @vitest-environment jsdom
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { horizontalOverflow } from './horizontalOverflow';

beforeAll(() => {
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			disconnect() {}
		},
	);
});

/** Conteneur de 300 px de large dont le contenu mesure `contentWidth` px. */
function setup(contentWidth: number) {
	const node = document.createElement('div');
	document.body.appendChild(node);
	Object.defineProperty(node, 'clientWidth', { value: 300 });
	Object.defineProperty(node, 'scrollWidth', { value: contentWidth });
	return node;
}

function scrollTo(node: HTMLElement, left: number) {
	node.scrollLeft = left;
	node.dispatchEvent(new Event('scroll'));
}

describe('horizontalOverflow', () => {
	it('laisse les bords nets quand le contenu tient dans le conteneur', () => {
		const node = setup(300);
		const action = horizontalOverflow(node);
		expect(node.classList.contains('overflowing')).toBe(false);
		expect(node.classList.contains('fade-start')).toBe(false);
		expect(node.classList.contains('fade-end')).toBe(false);
		action?.destroy?.();
	});

	it('signale un contenu plus large que le conteneur', () => {
		const node = setup(800);
		const action = horizontalOverflow(node);
		expect(node.classList.contains('overflowing')).toBe(true);
		action?.destroy?.();
	});

	it('estompe le bord du côté où le contenu continue', () => {
		const node = setup(800);
		const action = horizontalOverflow(node);
		expect(node.classList.contains('fade-start')).toBe(false);
		expect(node.classList.contains('fade-end')).toBe(true);

		scrollTo(node, 200);
		expect(node.classList.contains('fade-start')).toBe(true);
		expect(node.classList.contains('fade-end')).toBe(true);

		scrollTo(node, 500);
		expect(node.classList.contains('fade-start')).toBe(true);
		expect(node.classList.contains('fade-end')).toBe(false);
		action?.destroy?.();
	});
});
