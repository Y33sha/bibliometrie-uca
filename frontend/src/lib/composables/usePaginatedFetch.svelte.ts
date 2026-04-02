import { api } from '$lib/api';

/**
 * Composable pour le chargement paginé de données.
 *
 * Usage :
 *   const pubs = usePaginatedFetch<Publication>({
 *     endpoint: '/api/publications',
 *     itemsKey: 'publications',
 *     perPage: 100,
 *     apiKey: 'pub-list',
 *     buildParams: () => buildFilterParams(),
 *   });
 *   await pubs.load();          // charge la page courante
 *   pubs.goToPage(3);           // change de page + recharge + scroll top
 */

interface PaginatedFetchOptions {
	endpoint: string;
	itemsKey: string;
	perPage?: number;
	apiKey: string;
	buildParams: () => URLSearchParams;
}

export function usePaginatedFetch<T>(opts: PaginatedFetchOptions) {
	let items: T[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loaded = $state(false);

	const perPage = opts.perPage ?? 50;

	async function load() {
		const params = opts.buildParams();
		params.set('page', String(page));
		params.set('per_page', String(perPage));

		const data = await api<Record<string, unknown>>(
			opts.endpoint + '?' + params,
			{ key: opts.apiKey },
		);
		items = data[opts.itemsKey] as T[];
		total = data.total as number;
		pages = data.pages as number;
		page = data.page as number;
		loaded = true;
	}

	function goToPage(p: number) {
		page = p;
		load();
		window.scrollTo(0, 0);
	}

	return {
		get items() { return items; },
		set items(v: T[]) { items = v; },
		get total() { return total; },
		get page() { return page; },
		set page(v: number) { page = v; },
		get pages() { return pages; },
		get loaded() { return loaded; },
		load,
		goToPage,
	};
}
