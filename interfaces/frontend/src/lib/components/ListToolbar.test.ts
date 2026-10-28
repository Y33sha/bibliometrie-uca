// @vitest-environment jsdom
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ListToolbar from './ListToolbar.svelte';

beforeAll(() => {
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			disconnect() {}
		},
	);
});

describe('ListToolbar', () => {
	// Une transformation sur la barre ferait d'elle le repère des panneaux en position fixe qu'elle contient : les facettes ouvertes sauteraient au défilement.
	it('glisse sous le menu sans transformation', () => {
		const target = document.createElement('div');
		document.body.appendChild(target);
		const component = mount(ListToolbar, {
			target,
			props: { list: { loaded: true, error: null, total: 0 }, one: 'résultat', many: 'résultats' },
		});
		flushSync();
		const anchor =target.querySelector<HTMLElement>('.list-toolbar-anchor')!;
		const bar = target.querySelector<HTMLElement>('.list-toolbar')!;
		Object.defineProperty(bar, 'offsetHeight', { value: 100 });
		anchor.getBoundingClientRect = () => ({ top: -30 }) as DOMRect;

		window.dispatchEvent(new Event('scroll'));
		flushSync();

		expect(document.documentElement.style.getPropertyValue('--list-toolbar-height')).toBe('70px');
		expect(bar.style.transform).toBe('');
		unmount(component);
		target.remove();
	});
});
