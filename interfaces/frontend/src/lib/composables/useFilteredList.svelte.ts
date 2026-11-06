/**
 * Liste filtrée par un registre de filtres : valeurs des filtres, recherche, tri, page, chargement paginé, décomptes, panneau des filtres, et synchronisation avec l'URL.
 *
 * Chaque vue de liste déclare ses filtres (`ListFilter[]`) et ses particularités (paramètres imposés par la page, décomptes, réglages propres) ; le composable enchaîne le reste. `restore` relit l'URL et charge la liste, au montage de la vue.
 */
import { page as appPage } from '$app/state';
import { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';
import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
import { useUrlFilters, type FilterDef as UrlFilterDef } from '#lib/composables/useUrlFilters.svelte.js';
import {
	activeCount,
	appendFilterParams,
	initialValues,
	restoreValues,
	urlFilterDefs,
	urlState,
	type ListFilter,
} from '#lib/filterRegistry.js';

/** Ce que le composable attend des décomptes : un rechargement. */
interface Facets {
	load(): Promise<void>;
}

/** Réglages propres à la page, écrits dans l'URL avec les filtres (vue, réglages d'un graphique…). */
interface ExtraUrlState {
	filters: Record<string, UrlFilterDef>;
	/** Valeurs à écrire, par clé de `filters`. */
	state: () => Record<string, unknown>;
	/** Reporte les valeurs lues dans l'URL. */
	restore: (restored: Record<string, unknown>) => void;
}

export function useFilteredList<T, F extends Facets>(config: {
	filters: ListFilter[];
	/** Paramètres imposés par la page, posés avant les filtres (contexte, valeurs par défaut de l'API). Un filtre actif remplace un paramètre de même nom. */
	baseParams?: () => URLSearchParams;
	endpoint: string;
	itemsKey: string;
	perPage: number;
	/** Clé de cache de la liste ; les décomptes reçoivent la leur. */
	apiKey: () => string;
	defaultSort: string;
	urlSync: () => boolean;
	basePath: () => string;
	debounceMs?: number;
	/** Crée les décomptes, à partir des paramètres des filtres et de la recherche. */
	facets: (buildParams: () => URLSearchParams) => F;
	extraUrl?: ExtraUrlState;
	/** Appelé après chaque changement de filtre ou de recherche, une fois la liste et les décomptes relancés. */
	onchange?: () => void;
}) {
	let values = $state(initialValues(config.filters));
	let search = $state('');
	let sort = $state(config.defaultSort);
	const panel = useFilterPanel();

	/** Paramètres des filtres et de la recherche, sans le tri ni la page. */
	function filterParams(): URLSearchParams {
		const params = config.baseParams?.() ?? new URLSearchParams();
		appendFilterParams(config.filters, values, params);
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	const listing = usePaginatedFetch<T>({
		endpoint: config.endpoint,
		itemsKey: config.itemsKey,
		perPage: config.perPage,
		apiKey: config.apiKey,
		buildParams() {
			const params = filterParams();
			params.set('sort', sort);
			return params;
		},
	});

	const facets = config.facets(filterParams);

	const url = useUrlFilters({
		basePath: config.basePath,
		debounceMs: config.debounceMs,
		filters: {
			...urlFilterDefs(config.filters),
			...config.extraUrl?.filters,
			search: { type: 'single', urlKey: 'search' },
			sort: { type: 'single', urlKey: 'sort', defaultValue: config.defaultSort },
			page: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		if (!config.urlSync()) return;
		url.syncUrl(() => ({
			...urlState(config.filters, values),
			...config.extraUrl?.state(),
			search,
			sort,
			page: listing.page,
		}));
	}

	/** Après un changement de filtre ou de recherche : première page, URL, liste et décomptes rechargés. */
	function onFilterChange() {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
		config.onchange?.();
	}

	/** Change le tri : première page, URL et liste rechargée ; les décomptes ne dépendent pas du tri. */
	function setSort(next: string) {
		sort = next;
		listing.page = 1;
		syncUrl();
		listing.load();
	}

	/** Change de page. */
	function goToPage(p: number) {
		listing.goToPage(p);
		syncUrl();
	}

	/** Relit l'URL, puis charge les décomptes et la liste. À appeler au montage de la vue. */
	async function restore() {
		if (config.urlSync()) {
			const restored = url.restoreFromUrl(appPage.url.searchParams);
			restoreValues(config.filters, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.sort) sort = restored.sort as string;
			if (restored.page) listing.page = restored.page as number;
			config.extraUrl?.restore(restored);
		}
		await facets.load();
		listing.load();
	}

	return {
		get values() {
			return values;
		},
		set values(v) {
			values = v;
		},
		get search() {
			return search;
		},
		set search(v: string) {
			search = v;
		},
		get sort() {
			return sort;
		},
		/** Nombre de filtres actifs proposés dans la page. */
		get activeCount() {
			return activeCount(config.filters, values);
		},
		listing,
		facets,
		panel,
		filterParams,
		syncUrl,
		onFilterChange,
		/** Recherche saisie : `onFilterChange` après une pause de frappe. */
		onSearchInput: url.debouncedSearch(onFilterChange),
		setSort,
		goToPage,
		restore,
	};
}
