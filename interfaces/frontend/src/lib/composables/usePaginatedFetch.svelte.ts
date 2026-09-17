import { api } from '$lib/api';
import { dropPageParam, isPageOutOfRange } from '$lib/pagination';

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
 *
 * `data` expose la dernière réponse entière, pour les champs portés à côté de la liste (facettes, drapeaux).
 */

export interface PaginatedFetchOptions {
	/** Chemin de l'API. Passer un getter `() => ...` quand il dépend d'un état (identifiant d'entité, onglet) : il est relu à chaque chargement. */
	endpoint: string | (() => string);
	itemsKey: string;
	perPage?: number;
	/** Clé de cache `api()`. Passer un getter `() => ...` pour qu'un changement (ex. invalidation après édition admin) déclenche un rechargement. */
	apiKey: string | (() => string);
	buildParams: () => URLSearchParams;
	/** Clé du numéro de page dans l'URL, retirée quand la page demandée dépasse la dernière. Défaut `page` ; `null` pour une liste dont la page reste hors de l'URL. */
	pageParam?: string | null;
}

export function usePaginatedFetch<T, R = Record<string, unknown>>(opts: PaginatedFetchOptions) {
	let items: T[] = $state([]);
	let data: R | null = $state.raw(null);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loaded = $state(false);
	// `true` dès la création : tant que le premier `load()` n'a pas abouti, on n'a pas de données — les tableaux affichent « Chargement… », pas « vide ».
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

			const endpoint = typeof opts.endpoint === 'function' ? opts.endpoint() : opts.endpoint;
			const response = await api<Record<string, unknown>>(endpoint + '?' + params, { key: lastKey });
			const range = { page: response.page as number, pages: response.pages as number };
			if (isPageOutOfRange(range)) {
				// La liste a rétréci sous la page demandée : retour à la première page.
				page = 1;
				if (opts.pageParam !== null) dropPageParam(opts.pageParam);
				return await load();
			}
			data = response as R;
			items = response[opts.itemsKey] as T[];
			total = response.total as number;
			pages = range.pages;
			page = range.page;
			loaded = true;
		} finally {
			loading = false;
		}
	}

	// Recharge quand la clé d'API change (ex. après une édition/fusion admin qui incrémente une version pour invalider le cache). Nécessite que `apiKey` soit passé en getter `() => ...` pour être suivi réactivement. La garde `lastKey` évite un double-chargement au montage.
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
		set total(v: number) { total = v; },
		get data() { return data; },
		get page() { return page; },
		set page(v: number) { page = v; },
		get pages() { return pages; },
		get loaded() { return loaded; },
		get loading() { return loading; },
		load,
		goToPage,
	};
}
