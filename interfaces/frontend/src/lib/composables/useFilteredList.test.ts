// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { runInEffectRoot } from './effectRoot.svelte';

// Mocks SvelteKit et API : la réponse de l'API est modifiable, chaque appel est capturé.
let apiResponse: Record<string, unknown> = {};
const apiSpy = vi.fn(async (..._args: unknown[]) => apiResponse);
vi.mock('#lib/api/index.js', async () => ({
	api: (...args: unknown[]) => apiSpy(...args),
	cancel: () => {},
	errorMessage: (await import('../api/client')).errorMessage,
}));
vi.mock('$app/navigation', () => ({ goto: async () => {} }));
vi.mock('$app/paths', () => ({ resolve: (path: string) => '/' + path }));
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/publications') } }));

// Import APRÈS les mocks pour qu'ils s'appliquent.
const { useFilteredList } = await import('./useFilteredList.svelte');

const cleanups: Array<() => void> = [];
afterEach(() => {
	for (const c of cleanups) c();
	cleanups.length = 0;
	apiSpy.mockClear();
});

function mount() {
	const facetsLoad = vi.fn(async () => {});
	const { value, cleanup } = runInEffectRoot(() =>
		useFilteredList<number, { load: () => Promise<void> }>({
			filters: [],
			endpoint: '/api/x',
			itemsKey: 'items',
			perPage: 2,
			apiKey: () => 'k',
			defaultSort: 'year',
			urlSync: () => false,
			basePath: () => '/x',
			facets: () => ({ load: facetsLoad }),
		}),
	);
	cleanups.push(cleanup);
	return { list: value, facetsLoad };
}

const requestedPage = () => new URL(String(apiSpy.mock.lastCall![0]), 'http://localhost').searchParams.get('page');

describe('useFilteredList', () => {
	it('reload recharge la liste et les décomptes sur la page courante', async () => {
		const { list, facetsLoad } = mount();
		apiResponse = { items: [5, 6], total: 6, page: 3, pages: 3 };
		list.goToPage(3);
		await vi.waitFor(() => expect(list.listing.total).toBe(6));

		// Une ligne de la page 3 disparaît de la liste côté serveur.
		apiResponse = { items: [5], total: 5, page: 3, pages: 3 };
		list.reload();
		await vi.waitFor(() => expect(list.listing.total).toBe(5));
		expect(requestedPage()).toBe('3');
		expect(list.listing.items).toEqual([5]);
		expect(facetsLoad).toHaveBeenCalledOnce();
	});
});
