import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useDebouncedSearch } from './useDebouncedSearch.svelte';

describe('useDebouncedSearch', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('démarre avec un état vide', () => {
		const search = vi.fn(async () => []);
		const s = useDebouncedSearch({ search });
		expect(s.query).toBe('');
		expect(s.results).toEqual([]);
		expect(s.loading).toBe(false);
		expect(search).not.toHaveBeenCalled();
	});

	it('ne déclenche pas de fetch si la query fait moins que minLength', () => {
		const search = vi.fn(async () => ['a']);
		const s = useDebouncedSearch({ search, minLength: 3 });
		s.setQuery('ab');
		vi.runAllTimers();
		expect(search).not.toHaveBeenCalled();
		expect(s.loading).toBe(false);
		expect(s.results).toEqual([]);
	});

	it('debounce avant de fetch', async () => {
		const search = vi.fn(async () => ['result']);
		const s = useDebouncedSearch({ search, minLength: 2, delay: 300 });
		s.setQuery('foo');
		expect(s.loading).toBe(true);
		expect(search).not.toHaveBeenCalled();

		await vi.advanceTimersByTimeAsync(299);
		expect(search).not.toHaveBeenCalled();

		await vi.advanceTimersByTimeAsync(1);
		expect(search).toHaveBeenCalledOnce();
		expect(search).toHaveBeenCalledWith('foo');
		expect(s.results).toEqual(['result']);
		expect(s.loading).toBe(false);
	});

	it('annule la query précédente quand une nouvelle arrive', async () => {
		const search = vi.fn(async (q: string) => [q]);
		const s = useDebouncedSearch({ search, minLength: 2, delay: 300 });
		s.setQuery('first');
		await vi.advanceTimersByTimeAsync(200);
		s.setQuery('second');
		// Le premier timer est annulé : seul `second` doit déclencher un fetch.
		await vi.advanceTimersByTimeAsync(300);
		expect(search).toHaveBeenCalledOnce();
		expect(search).toHaveBeenCalledWith('second');
		expect(s.results).toEqual(['second']);
	});

	it('ignore une réponse obsolète si une nouvelle query est partie', async () => {
		// Les deux fetchs partent (debounce dépassé pour les deux), mais le 1er
		// est plus lent. Le 2e arrive avant et doit être conservé ; le 1er est
		// ignoré quand il finit.
		const responses: Record<string, Promise<string[]>> = {};
		const search = vi.fn((q: string) => responses[q]);

		let resolveFirst: (v: string[]) => void = () => {};
		responses['first'] = new Promise((r) => (resolveFirst = r));
		responses['second'] = Promise.resolve(['second-result']);

		const s = useDebouncedSearch({ search, minLength: 2, delay: 100 });
		s.setQuery('first');
		await vi.advanceTimersByTimeAsync(100);
		// `first` est en vol, pas encore résolu.
		s.setQuery('second');
		await vi.advanceTimersByTimeAsync(100);
		// `second` est résolu (Promise déjà settled).
		await vi.runAllTimersAsync();
		expect(s.results).toEqual(['second-result']);

		// On résout `first` après — il doit être ignoré.
		resolveFirst(['first-result']);
		await vi.runAllTimersAsync();
		expect(s.results).toEqual(['second-result']);
	});

	it('applique le transform sur les résultats', async () => {
		const search = vi.fn(async () => [1, 2, 3]);
		const s = useDebouncedSearch<number>({
			search,
			minLength: 2,
			delay: 0,
			transform: (rs) => rs.filter((n) => n > 1),
		});
		s.setQuery('xx');
		await vi.runAllTimersAsync();
		expect(s.results).toEqual([2, 3]);
	});

	it('clear() remet à zéro et annule le fetch en cours', async () => {
		const search = vi.fn(async () => ['result']);
		const s = useDebouncedSearch({ search, minLength: 2, delay: 300 });
		s.setQuery('foo');
		expect(s.loading).toBe(true);

		s.clear();
		expect(s.query).toBe('');
		expect(s.results).toEqual([]);
		expect(s.loading).toBe(false);

		await vi.runAllTimersAsync();
		expect(search).not.toHaveBeenCalled();
	});

	it('clear() ignore une réponse en vol', async () => {
		let resolveSearch: (v: string[]) => void = () => {};
		const search = vi.fn(() => new Promise<string[]>((r) => (resolveSearch = r)));
		const s = useDebouncedSearch({ search, minLength: 2, delay: 100 });

		s.setQuery('foo');
		await vi.advanceTimersByTimeAsync(100);
		// Le fetch est parti, on clear pendant qu'il est en vol.
		s.clear();
		resolveSearch(['stale-result']);
		await vi.runAllTimersAsync();
		expect(s.results).toEqual([]);
	});
});
