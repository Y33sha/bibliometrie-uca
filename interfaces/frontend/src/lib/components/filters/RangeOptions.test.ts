// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import RangeOptions from './RangeOptions.svelte';

// Plage principale 2010–2015 ; 1990, 2000 et 2030 en sont écartées et forment les barres « avant » et « après ».
const options = [
	{ value: '1990', text: '1990', count: 1 },
	{ value: '2000', text: '2000', count: 1 },
	...[2010, 2011, 2012, 2013, 2014, 2015].map((y) => ({ value: String(y), text: String(y), count: 100 })),
	{ value: '2030', text: '2030', count: 1 },
];
const years = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => String(from + i));

function render(selected: string[] = [], onchange?: (selected: string[]) => void) {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const component = mount(RangeOptions, { target, props: { options, selected, onchange } });
	flushSync();
	const [start, end] = target.querySelectorAll<HTMLInputElement>('input[type=range]');
	return {
		target,
		start,
		end,
		summary: () => target.querySelector('.range-value')!.textContent,
		destroy() {
			unmount(component);
			target.remove();
		},
	};
}

describe('RangeOptions', () => {
	it('montre toutes les barres dans la sélection quand aucune année n’est filtrée', () => {
		const r = render();
		expect(r.target.querySelectorAll('.bar').length).toBe(8);
		expect(r.target.querySelectorAll('.bar.in-range').length).toBe(8);
		expect(r.summary()).toBe('Toutes les années');
		r.destroy();
	});

	it('place la poignée droite sur la barre « avant » quand la sélection s’arrête avant la plage', () => {
		const r = render(years(1990, 2009));
		expect(r.end.value).toBe('1');
		expect(r.summary()).toBe("Jusqu'à 2009");
		r.destroy();
	});

	it('place la poignée gauche sur la barre « après » quand la sélection commence après la plage', () => {
		const r = render(years(2016, 2030));
		expect(r.start.value).toBe('7');
		expect(r.summary()).toBe('Depuis 2016');
		r.destroy();
	});

	it('borne la sélection à la première année de la plage quand la poignée gauche quitte la barre « avant »', () => {
		const onchange = vi.fn();
		const r = render([], onchange);
		r.start.value = '1';
		// Svelte écoute ces événements à la racine : ils doivent remonter.
		r.start.dispatchEvent(new Event('input', { bubbles: true }));
		r.start.dispatchEvent(new Event('change', { bubbles: true }));
		flushSync();
		expect(onchange).toHaveBeenCalledWith(years(2010, 2030));
		expect(r.summary()).toBe('Depuis 2010');
		r.destroy();
	});
});
