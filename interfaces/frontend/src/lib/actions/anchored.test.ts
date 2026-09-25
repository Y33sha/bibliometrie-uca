// @vitest-environment jsdom
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { anchored } from './anchored';

beforeAll(() => {
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			disconnect() {}
		},
	);
});

/** Ancre de 100 × 20 px dont le haut est à `top`, et panneau de 150 px de haut. */
function setup(top: number) {
	const anchor = document.createElement('div');
	const panel = document.createElement('div');
	anchor.appendChild(panel);
	document.body.appendChild(anchor);
	anchor.getBoundingClientRect = () => ({ left: 50, right: 150, top, bottom: top + 20, width: 100, height: 20 }) as DOMRect;
	Object.defineProperty(panel, 'offsetHeight', { value: 150 });
	return panel;
}

describe('anchored', () => {
	it('place le panneau en position fixe sous son ancre', () => {
		const panel = setup(100);
		const action = anchored(panel);
		expect(panel.style.position).toBe('fixed');
		expect(panel.style.top).toBe('124px');
		expect(panel.style.left).toBe('50px');
		action.destroy();
	});

	it('passe au-dessus de l\'ancre quand la place manque en bas de la fenêtre', () => {
		const panel = setup(window.innerHeight - 40);
		const action = anchored(panel);
		expect(panel.style.top).toBe(`${window.innerHeight - 40 - 4 - 150}px`);
		action.destroy();
	});

	it('suit l\'ancre quand un conteneur défile', () => {
		const panel = setup(100);
		const action = anchored(panel);
		panel.parentElement!.getBoundingClientRect = () => ({ left: 50, right: 150, top: 60, bottom: 80, width: 100, height: 20 }) as DOMRect;
		window.dispatchEvent(new Event('scroll'));
		expect(panel.style.top).toBe('84px');
		action.destroy();
	});
});
