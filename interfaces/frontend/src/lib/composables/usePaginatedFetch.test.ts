// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { runInEffectRoot } from './effectRoot.svelte';
import type { PaginatedFetchOptions } from './usePaginatedFetch.svelte';

let apiResponse: Record<string, unknown> = {};
// `(..._args: unknown[])` plutôt que `()` : permet à TS de typer
// `apiSpy.mock.calls[0][0]` lors des assertions.
const apiSpy = vi.fn(async (..._args: unknown[]) => apiResponse);
vi.mock('$lib/api', () => ({ api: (...args: unknown[]) => apiSpy(...args) }));

const { usePaginatedFetch } = await import('./usePaginatedFetch.svelte');

// `usePaginatedFetch` utilise `$effect` (rechargement réactif sur changement de
// clé) : il doit être instancié dans un scope d'effet, sinon `effect_orphan`.
// `mount` enveloppe la création ; les scopes sont disposés après chaque test.
const cleanups: Array<() => void> = [];
afterEach(() => {
	for (const c of cleanups) c();
	cleanups.length = 0;
});

function mount<T>(opts: PaginatedFetchOptions) {
	const { value, cleanup } = runInEffectRoot(() => usePaginatedFetch<T>(opts));
	cleanups.push(cleanup);
	return value;
}

describe('usePaginatedFetch', () => {
	beforeEach(() => {
		apiSpy.mockClear();
		apiResponse = {};
	});

	it('démarre avec items=[], total=0, page=1, loaded=false', () => {
		const f = mount<number>({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		expect(f.items).toEqual([]);
		expect(f.total).toBe(0);
		expect(f.page).toBe(1);
		expect(f.pages).toBe(1);
		expect(f.loaded).toBe(false);
	});

	it('loading vaut true à la création, false après load()', async () => {
		apiResponse = { items: [], total: 0, page: 1, pages: 1 };
		const f = mount<number>({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		expect(f.loading).toBe(true);
		await f.load();
		expect(f.loading).toBe(false);
	});

	it('load() injecte page et per_page dans les params', async () => {
		apiResponse = { items: [], total: 0, page: 1, pages: 1 };
		const f = mount<number>({
			endpoint: '/api/x',
			itemsKey: 'items',
			perPage: 25,
			apiKey: 'k',
			buildParams: () => new URLSearchParams('foo=bar'),
		});
		await f.load();
		const url = apiSpy.mock.calls[0][0] as string;
		expect(url).toContain('foo=bar');
		expect(url).toContain('page=1');
		expect(url).toContain('per_page=25');
	});

	it('par défaut, perPage = 50', async () => {
		apiResponse = { items: [], total: 0, page: 1, pages: 1 };
		const f = mount({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		await f.load();
		expect(apiSpy.mock.calls[0][0]).toContain('per_page=50');
	});

	it('peuple items, total, page, pages, loaded depuis la réponse', async () => {
		apiResponse = { items: [10, 20, 30], total: 100, page: 2, pages: 4 };
		const f = mount<number>({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		await f.load();
		expect(f.items).toEqual([10, 20, 30]);
		expect(f.total).toBe(100);
		expect(f.page).toBe(2);
		expect(f.pages).toBe(4);
		expect(f.loaded).toBe(true);
	});

	it('utilise itemsKey custom (e.g. "publications")', async () => {
		apiResponse = { publications: ['a', 'b'], total: 2, page: 1, pages: 1 };
		const f = mount<string>({
			endpoint: '/api/publications',
			itemsKey: 'publications',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		await f.load();
		expect(f.items).toEqual(['a', 'b']);
	});

	it('goToPage met à jour page, recharge et scroll en haut', async () => {
		apiResponse = { items: [], total: 0, page: 3, pages: 5 };
		const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
		const f = mount({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		f.goToPage(3);
		// goToPage est synchrone, mais load() est async — on l'attend.
		await Promise.resolve(); // micro-task pour laisser load() partir
		expect(f.page).toBe(3);
		expect(apiSpy).toHaveBeenCalled();
		expect(scrollSpy).toHaveBeenCalledWith(0, 0);
		scrollSpy.mockRestore();
	});

	it('items est mutable (set externe possible)', () => {
		const f = mount<number>({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		f.items = [1, 2, 3];
		expect(f.items).toEqual([1, 2, 3]);
	});

	it('page est mutable (set externe possible avant load)', async () => {
		apiResponse = { items: [], total: 0, page: 5, pages: 10 };
		const f = mount({
			endpoint: '/api/x',
			itemsKey: 'items',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
		});
		f.page = 5;
		await f.load();
		expect(apiSpy.mock.calls[0][0]).toContain('page=5');
	});
});
