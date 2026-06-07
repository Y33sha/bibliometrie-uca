<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';

	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import type { components } from '$lib/api/schema';

	type Journal = components['schemas']['JournalOut'];

	// Composant de liste de revues réutilisable. Utilisé par :
	// - `/journals` (mode autonome avec sync URL)
	// - `/admin/journals` (snippet `actionCell` pour Modifier/Fusionner)
	// - `/publishers/[id]?tab=journals` (filtre `publisherId` fixe, colonne Éditeur masquée)
	interface ExternalFilters {
		publisherId?: number;
	}

	let {
		apiKey = 'journals-list',
		externalFilters,
		urlSync = false,
		basePath = '/journals',
		perPage = 50,
		withPubs = false,
		hidePublisherColumn = false,
		actionCell,
		actionColumnHeader = '',
		onTotalChange,
	}: {
		apiKey?: string;
		externalFilters?: ExternalFilters;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Si true, n'expose que les revues avec ≥ 1 publication rattachée
		 *  (mode page publique, masque les orphelines). Défaut false = admin. */
		withPubs?: boolean;
		/** Masque la colonne Éditeur (utile sur `publishers/[id]?tab=journals`
		 *  où toutes les lignes ont le même éditeur). */
		hidePublisherColumn?: boolean;
		/** Snippet rendu dans la colonne actions (1 row → 1 cell). Si fourni,
		 *  une colonne Actions est ajoutée à droite du tableau. */
		actionCell?: Snippet<[Journal]>;
		/** En-tête de la colonne actions (vide par défaut, comme admin). */
		actionColumnHeader?: string;
		onTotalChange?: (total: number) => void;
	} = $props();

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('-pubs');
	let selectedJournalTypes: string[] = $state([]);
	let selectedOaModels: string[] = $state([]);
	let selectedDoaj: string[] = $state([]); // 'true' / 'false'

	$effect(() => {
		if (onTotalChange) onTotalChange(journals.total);
	});

	// --- Params builder partagé entre liste + facettes ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (externalFilters?.publisherId != null) {
			params.set('publisher_id', String(externalFilters.publisherId));
		}
		if (selectedJournalTypes.length) params.set('journal_type', selectedJournalTypes.join(','));
		if (selectedOaModels.length) params.set('oa_model', selectedOaModels.join(','));
		// DOAJ : un seul ['true'] / ['false'] est interprétable côté API
		// (bool unique). Les autres cas (vide, ou les 2) = pas de filtre.
		if (selectedDoaj.length === 1) params.set('is_in_doaj', selectedDoaj[0]);
		if (withPubs) params.set('with_pubs', 'true');
		return params;
	}

	const journals = usePaginatedFetch<Journal>({
		endpoint: '/api/journals',
		itemsKey: 'journals',
		perPage,
		apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/journals/facets',
		apiKey: `${apiKey}-facets`,
		buildParams: buildFilterParams,
		facets: {
			journalTypes: { type: 'labeled', apiKey: 'journal_types' },
			oaModels: { type: 'labeled', apiKey: 'oa_models' },
			doaj: { type: 'labeled', apiKey: 'doaj' },
		},
	});

	const url = useUrlFilters({
		basePath,
		filters: {
			selectedJournalTypes: { type: 'string_array', urlKey: 'journal_type' },
			selectedOaModels: { type: 'string_array', urlKey: 'oa_model' },
			selectedDoaj: { type: 'string_array', urlKey: 'is_in_doaj' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: '-pubs' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedJournalTypes,
			selectedOaModels,
			selectedDoaj,
			search,
			currentSort,
			currentPage: journals.page,
		}));
	}

	function onFilterChange() {
		journals.page = 1;
		syncUrl();
		journals.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		journals.page = 1;
		syncUrl();
		journals.load();
	});

	function setSort(s: string) {
		currentSort = currentSort === s ? oppositeSort(s) : s;
		journals.page = 1;
		syncUrl();
		journals.load();
	}

	function oppositeSort(s: string): string {
		return s.startsWith('-') ? s.slice(1) : '-' + s;
	}

	function sortArrow(col: 'title' | 'publisher' | 'pubs'): string {
		if (currentSort === col) return '▲';
		if (currentSort === '-' + col) return '▼';
		return '';
	}

	function formatIssns(j: Journal): string {
		const parts: string[] = [];
		if (j.issn) parts.push(j.issn);
		if (j.eissn) parts.push(j.eissn);
		return parts.join(' / ');
	}

	function journalTypeLabel(value: string | null): string {
		if (!value) return '';
		const opt = facets.options.journalTypes.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedJournalTypes) selectedJournalTypes = restored.selectedJournalTypes as string[];
			if (restored.selectedOaModels) selectedOaModels = restored.selectedOaModels as string[];
			if (restored.selectedDoaj) selectedDoaj = restored.selectedDoaj as string[];
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) journals.page = restored.currentPage as number;
		}
		await facets.load();
		journals.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="text"
		placeholder="Rechercher dans les titres…"
		bind:value={search}
		oninput={onSearchInput}
	/>
	<FacetDropdown
		label="Types"
		options={facets.options.journalTypes}
		bind:selected={selectedJournalTypes}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="DOAJ"
		options={facets.options.doaj}
		bind:selected={selectedDoaj}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="Modèle OA"
		options={facets.options.oaModels}
		bind:selected={selectedOaModels}
		onchange={onFilterChange}
	/>
	<span class="count">{journals.total.toLocaleString('fr-FR')} revue{journals.total > 1 ? 's' : ''}</span>
</div>

<table class="journals-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort('title')}>
				Titre {sortArrow('title')}
			</th>
			<th>ISSN</th>
			{#if !hidePublisherColumn}
				<th class="sortable" onclick={() => setSort('publisher')}>
					Éditeur {sortArrow('publisher')}
				</th>
			{/if}
			<th>Type</th>
			<th class="num sortable" onclick={() => setSort('pubs')}>
				Publis {sortArrow('pubs')}
			</th>
			{#if actionCell}<th>{actionColumnHeader}</th>{/if}
		</tr>
	</thead>
	<tbody>
		{#each journals.items as j (j.id)}
			<tr>
				<td>
					<a href="{base}/journals/{j.id}" class="journal-link">{j.title}</a>
					{#if j.is_in_doaj}
						{#if j.doaj_url}
							<a class="badge-doaj" href={j.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
						{:else}
							<span class="badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
						{/if}
					{/if}
					{#if j.is_predatory}<span class="badge-pred">prédatrice</span>{/if}
				</td>
				<td class="issn-cell">{formatIssns(j)}</td>
				{#if !hidePublisherColumn}
					<td class="muted">
						{#if j.pub_name}
							{#if j.publisher_id}
								<a href="{base}/publishers/{j.publisher_id}" class="publisher-link">{j.pub_name}</a>
							{:else}
								{j.pub_name}
							{/if}
						{/if}
					</td>
				{/if}
				<td class="muted">{journalTypeLabel(j.journal_type)}</td>
				<td class="num">{j.pub_count.toLocaleString('fr-FR')}</td>
				{#if actionCell}<td class="actions">{@render actionCell(j)}</td>{/if}
			</tr>
		{/each}
		{#if journals.items.length === 0}
			<tr><td colspan={hidePublisherColumn ? 4 : 5} class="no-results">Aucune revue ne correspond aux filtres.</td></tr>
		{/if}
	</tbody>
</table>

<Pagination
	page={journals.page}
	pages={journals.pages}
	onchange={(p) => {
		journals.page = p;
		syncUrl();
		journals.load();
	}}
/>

<style>
	.journals-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.journals-table thead th {
		background: #f5f4f1;
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.journals-table thead th.num { text-align: right; }
	.journals-table thead th.sortable { cursor: pointer; user-select: none; }
	.journals-table thead th.sortable:hover { color: var(--accent); }
	.journals-table tbody tr { border-bottom: 1px solid #f0efec; }
	.journals-table tbody tr:last-child { border-bottom: none; }
	.journals-table tbody tr:hover { background: #fafaf8; }
	.journals-table td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }
	.journals-table td.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: var(--muted);
	}
	.issn-cell {
		color: var(--muted);
		font-size: 0.85rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.muted { color: var(--muted); }
	.no-results { text-align: center; color: var(--muted); padding: 30px; }

	.journal-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.journal-link:hover { text-decoration: underline; }
	.publisher-link { color: var(--muted); text-decoration: none; }
	:global(a.publisher-link:hover) { text-decoration: underline; }

	.badge-doaj {
		font-size: 0.7rem;
		padding: 1px 5px;
		background: #2e7d32;
		color: white;
		border-radius: 8px;
		margin-left: 6px;
		vertical-align: middle;
		font-weight: 600;
		text-decoration: none;
	}
	:global(a.badge-doaj:hover) { background: #256528; }
	.badge-pred {
		font-size: 0.7rem;
		padding: 1px 5px;
		background: #c0392b;
		color: white;
		border-radius: 8px;
		margin-left: 4px;
		vertical-align: middle;
		font-weight: 600;
	}
	.actions { white-space: nowrap; position: relative; }
</style>
