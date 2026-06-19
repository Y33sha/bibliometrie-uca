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
	/** Clé de cache `api()`. Passer un getter `() => ...` pour qu'un changement
	 *  (ex. invalidation après édition admin) déclenche un rechargement. */
	apiKey: string | (() => string);
	buildParams: () => URLSearchParams;
}

export function usePaginatedFetch<T>(opts: PaginatedFetchOptions) {
	let items: T[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loaded = $state(false);
	// `true` dès la création : tant que le premier `load()` n'a pas abouti, on
	// n'a pas de données — les tableaux affichent « Chargement… », pas « vide ».
	let loading = $state(true);

	const perPage = opts.perPage ?? 50;
	const currentKey = (): string =>
		typeof opts.apiKey === 'function' ? opts.apiKey() : opts.apiKey;
	let lastKey: string | undefined;

	async function load() {
		loading = true;
		try {
			lastKey = currentKey();
			const params = opts.buildParams();
			params.set('page', String(page));
			params.set('per_page', String(perPage));

			const data = await api<Record<string, unknown>>(
				opts.endpoint + '?' + params,
				{ key: lastKey },
			);
			items = data[opts.itemsKey] as T[];
			total = data.total as number;
			pages = data.pages as number;
			page = data.page as number;
			loaded = true;
		} finally {
			loading = false;
		}
	}

	// Recharge quand la clé d'API change (ex. après une édition/fusion admin qui
	// incrémente une version pour invalider le cache). Nécessite que `apiKey`
	// soit passé en getter `() => ...` pour être suivi réactivement. La garde
	// `lastKey` évite un double-chargement au montage.
	$effect(() => {
		const key = currentKey();
		if (loaded && key !== lastKey) load();
	});

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
		get loading() { return loading; },
		load,
		goToPage,
	};
}
