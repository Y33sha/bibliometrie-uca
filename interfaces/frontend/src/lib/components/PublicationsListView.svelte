<script lang="ts">
	import AccessButton from '#lib/components/AccessButton.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { asset, resolve } from '$app/paths';
	import { withBase } from '#lib/paths.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import PublicationFilterBar from '#lib/components/PublicationFilterBar.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import {
		activeColumns,
		appendFilterParams,
		initialValues,
		restoreValues,
		transferParams,
		urlFilterDefs,
		urlState,
	} from '#lib/filterRegistry.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import { licenseLabels } from '#lib/licenses.js';
	import { columnLabels, oaStatusLabel, publicationsDocTypes } from '#lib/labels.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
	import { publicationFilters } from '#lib/publicationFilters.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { useColumnVisibility } from '#lib/composables/useColumnVisibility.svelte.js';
	import ColumnMenu from '#lib/components/ColumnMenu.svelte';
	import { paramsToQuery } from '#lib/utils.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import IconButton from '#lib/components/IconButton.svelte';
	import { contextEntityId, type PublicationListContext } from '#lib/publicationListContext.js';

	import type { components } from '#lib/api/schema.js';
	type Publication = components['schemas']['PublicationListItem'] & {
		// Champs présents quand l'API est appelée avec `person_id` (cf. routes /api/publications côté backend qui enrichit la réponse). Optionnels car non garantis hors contexte personne.
		is_corresponding?: boolean | null;
		contribution_id?: number | null;
	};

	// --- Props ---
	// Composant de liste de publications réutilisable : la liste générale `/publications`, et l'onglet des publications d'un sujet, d'un laboratoire, d'une personne, d'une revue, d'un éditeur ou d'une monographie.
	let {
		apiKey = 'publication-list',
		context = { kind: 'all' },
		urlSync = true,
		basePath = '/publications',
		showAdminExclude = false,
		perPage = 100,
		onExcludeContribution,
		onopenPublication,
		activePublicationId = null,
	}: {
		apiKey?: string;
		context?: PublicationListContext;
		urlSync?: boolean;
		basePath?: string;
		/** Affiche la 1ère colonne avec un bouton ✕ pour exclure la contribution. Le parent gère l'auth check et passe le callback. Si le callback retourne `true` (ou void), la ligne est retirée du tableau ; retourne `false` pour annuler (ex. l'utilisatrice a cliqué Annuler dans un confirm). */
		showAdminExclude?: boolean;
		/** Nombre d'éléments par page (50 pour les onglets, 100 pour /publications). */
		perPage?: number;
		onExcludeContribution?: (contributionId: number, publicationId: number) => void | boolean | Promise<void | boolean>;
		/** Ouvre le volet de la publication dans la page hôte. Fourni, il ajoute en tête de ligne une icône qui l'appelle ; le titre mène toujours à la fiche. */
		onopenPublication?: (publicationId: number) => void;
		/** Publication ouverte par la page hôte, dont la ligne est mise en évidence. */
		activePublicationId?: number | null;
	} = $props();

	// Le laboratoire a la colonne et le filtre « Statut HAL ». La personne a la colonne et le filtre « Auteur correspondant », le filtre du périmètre, et marque les APC des publications dont elle n'est pas l'auteur correspondant.
	// svelte-ignore state_referenced_locally
	const isLab = context.kind === 'lab';
	// svelte-ignore state_referenced_locally
	const isPerson = context.kind === 'person';
	// La liste générale présélectionne la famille « Publications » tant que l'URL ne fixe pas les types.
	// svelte-ignore state_referenced_locally
	const restrictToPublications = context.kind === 'all';

	// Libellé d'un statut de dépôt HAL, servi par l'API avec les options du filtre « Statuts HAL ».
	function halStatusLabel(status: string): string {
		return facets.options.halStatus?.find((o) => o.value === status)?.text ?? status;
	}

	// --- Column visibility ---
	// Ordre des colonnes = ordre dans le tableau. Les colonnes propres au contexte (hal_status, corr) figurent dans le menu de visibilité seulement dans leur contexte.
	const columnDefs = [
		{ key: 'type',       label: columnLabels.type },
		{ key: 'year',       label: columnLabels.year },
		{ key: 'doi',        label: columnLabels.doi },
		{ key: 'title',      label: columnLabels.title, fixed: true },
		{ key: 'serial',     label: columnLabels.serial },
		{ key: 'publisher',  label: columnLabels.publisher },
		...(isLab ? [] : [{ key: 'labs', label: columnLabels.labs }]),
		...(isPerson ? [{ key: 'corr', label: 'Auteur correspondant' }] : []),
		{ key: 'apc',        label: columnLabels.apc },
		{ key: 'oa_status',  label: columnLabels.oaStatus },
		{ key: 'license',    label: columnLabels.license },
		...(isLab ? [{ key: 'hal_status', label: 'Statut HAL' }] : []),
		{ key: 'sources',    label: columnLabels.sources },
		{ key: 'access',     label: columnLabels.access, fixed: true },
	];
	const initialHidden = ['apc', 'oa_status', 'license', 'publisher', 'sources'];
	// Libellés de la colonne Licence, servis par l'API.
	let licenseNames = $state<Record<string, string>>({});
	if (isLab) initialHidden.push('hal_status');
	const cv = useColumnVisibility(columnDefs, initialHidden);
	const col = cv.col;

	// --- Filtres ---
	let search = $state('');
	let currentSort = $state('year_desc');

	// svelte-ignore state_referenced_locally
	const FILTERS = publicationFilters(context);
	let values = $state(initialValues(FILTERS));

	// Lien vers les statistiques, pendant inverse du bouton « Voir les publications » : il transmet les filtres et la recherche. Masqué quand le contexte est une personne ou une monographie, que la page Statistiques ne représente pas.
	const showStatsLink = $derived(!['person', 'monograph'].includes(context.kind));
	const statsUrl = $derived.by(() => {
		const p = transferParams(FILTERS, values);
		const q = search.trim();
		if (q) p.set('search', q);
		return resolve('stats') + '?' + paramsToQuery(p);
	});

	// Sort display
	const yearSort = $derived(sortDirection(currentSort, 'year'));
	const titleSort = $derived(sortDirection(currentSort, 'title'));
	const apcSort = $derived(sortDirection(currentSort, 'apc'));

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('excluded_doc_type', 'ongoing_thesis');
		const personId = contextEntityId(context, 'person');
		if (personId) params.set('person_id', personId);
		const monographId = contextEntityId(context, 'monograph');
		if (monographId) params.set('monograph_id', monographId);
		appendFilterParams(FILTERS, values, params);
		return params;
	}

	// --- Composables ---
	const listing = usePaginatedFetch<Publication>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const facets = usePublicationFacets({
		filters: FILTERS,
		apiKey: () => `${apiKey}-facets`,
		// Inclut le terme de recherche pour que les comptes de facettes suivent le champ de recherche (comme la liste), pas seulement les autres filtres.
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			...urlFilterDefs(FILTERS),
			search:      { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage: { type: 'page',   urlKey: 'page' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			...urlState(FILTERS, values),
			search,
			currentSort,
			currentPage: listing.page,
		}));
	}

	function onFilterChange() {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
	});

	function toggleSort(column: 'year' | 'title' | 'apc') {
		currentSort = nextSort(currentSort, column, column === 'title' ? 'asc' : 'desc');
		onFilterChange();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);
		// Colonnes visibles → le CSV reflète le tableau affiché.
		params.set('columns', cv.visibleColumns.join(','));
		return withBase(`/api/publications/export.csv?${paramsToQuery(params)}`);
	}

	async function onExcludeClick(p: Publication) {
		if (!onExcludeContribution || p.contribution_id == null) return;
		const result = await onExcludeContribution(p.contribution_id, p.id);
		// `false` = annulé par le parent (ex. l'utilisatrice a cliqué Annuler) ; `true` ou `undefined` = succès → on retire la ligne du tableau.
		if (result === false) return;
		listing.items = listing.items.filter((item) => item.id !== p.id);
	}

	onMount(async () => {
		licenseLabels()
			.then((labels) => (licenseNames = labels))
			.catch(() => {});
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			restoreValues(FILTERS, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) listing.page = restored.currentPage as number;
		}

		// Défaut « Publications » (liste générale uniquement) : sans filtre de type explicite dans l'URL, on pré-sélectionne la famille Publications. La sélection est réelle (et non un filtre caché), donc la facet « Types » la reflète ; cocher d'autres types ou « Tous » l'élargit. Le token `all` dans l'URL (« Tous » explicite) laisse la sélection vide.
		if (restrictToPublications && !(urlSync && page.url.searchParams.has('doc_type'))) {
			values.checkbox.docTypes = [...publicationsDocTypes];
		}

		// Forcer l'affichage des colonnes liées aux filtres actifs
		const needed = activeColumns(FILTERS, values);
		if (needed.length) cv.ensure(needed);

		await facets.load();
		listing.load();
	});
</script>


<ListToolbar bind:search placeholder="Rechercher par titre ou sujet" onsearch={onSearchInput} list={listing} one="publication" many="publications" exportUrl={exportCsvUrl()}>
	{#snippet actions()}
		{#if showStatsLink}<a href={statsUrl} class="toolbar-action">Statistiques &rarr;</a>{/if}
	{/snippet}
	<PublicationFilterBar filters={FILTERS} bind:values options={facets.options} sourceCounts={facets.sourceCounts} buildParams={buildFilterParams} onchange={onFilterChange} />
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values options={facets.options} onchange={onFilterChange} />
	{/snippet}
</ListToolbar>

<div class="table-scroll">
<table class="data-table publication-table">
	<thead>
		<tr>
			{#if onopenPublication}<th style="width:28px"></th>{/if}
			{#if showAdminExclude}<th style="width:28px"></th>{/if}
			{#if col('type')}<th style="width:80px">{columnLabels.type}</th>{/if}
			{#if col('year')}<th style="width:40px" class="sortable" class:active={yearSort !== null} onclick={() => toggleSort('year')}>
				{columnLabels.year} <SortChevron direction={yearSort} />
			</th>{/if}
			{#if col('doi')}<th style="width:28px">{columnLabels.doi}</th>{/if}
			<th class="sortable publication-col-title" class:active={titleSort !== null} onclick={() => toggleSort('title')}>
				{columnLabels.title} <SortChevron direction={titleSort} />
			</th>
			{#if col('serial')}<th class="publication-col-journal">{columnLabels.serial}</th>{/if}
			{#if col('publisher')}<th class="publication-col-journal">{columnLabels.publisher}</th>{/if}
			{#if !isLab && col('labs')}<th style="width:80px">{columnLabels.labs}</th>{/if}
			{#if isPerson && col('corr')}<th style="width:30px" title="Auteur correspondant">&#9993;</th>{/if}
			{#if col('apc')}<th style="width:60px" class="sortable" class:active={apcSort !== null} onclick={() => toggleSort('apc')}>
				{columnLabels.apc} <SortChevron direction={apcSort} />
			</th>{/if}
			{#if col('oa_status')}<th style="width:60px">{columnLabels.oaStatus}</th>{/if}
			{#if col('license')}<th style="width:90px">{columnLabels.license}</th>{/if}
			{#if isLab && col('hal_status')}<th style="width:100px">Statut HAL</th>{/if}
			{#if col('sources')}<th style="width:100px">{columnLabels.sources}</th>{/if}
			<th style="width:120px" class="col-menu-th">
				<ColumnMenu label={columnLabels.access} columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if listing.items.length === 0}
			<TableStatusRow loading={listing.loading} error={listing.error} colspan={cv.visibleColumns.length + (showAdminExclude ? 1 : 0) + (onopenPublication ? 1 : 0)} emptyText="Aucune publication trouvée" />
		{:else}
			{#each listing.items as p (p.id)}
				<tr class:active-row={p.id === activePublicationId}>
					{#if onopenPublication}
						<td class="row-actions">
							<IconButton icon="panel" label="Ouvrir le volet" onclick={() => onopenPublication(p.id)} />
						</td>
					{/if}
					{#if showAdminExclude}
						<td class="exclude-cell row-actions">
							{#if p.contribution_id != null}
								<button class="exclude-btn" title="Exclure ce lien auteur–publication"
									onclick={() => onExcludeClick(p)}>✕</button>
							{/if}
						</td>
					{/if}
					{#if col('type')}<td>
						{#if p.doc_type}<DocTypePill docType={p.doc_type} />{/if}
					</td>{/if}
					{#if col('year')}<td>{p.publication_year || ''}</td>{/if}
					{#if col('doi')}<td class="doi-cell">
						{#if p.doi}<DoiLink doi={p.doi} />{/if}
					</td>{/if}
					<td><a href={resolve(`publications/${p.id}`)} class="publication-title"><PublicationTitle titre={p.title} /></a></td>
					{#if col('serial')}<td class="journal-cell publication-col-journal">
						{#if p.serial_id}
							<a href={resolve(`journals/${p.serial_id}`)}>{p.serial}</a>
						{:else}
							{p.serial || ''}
						{/if}
					</td>{/if}
					{#if col('publisher')}<td class="journal-cell publication-col-journal">
						{#if p.publisher_id}
							<a href={resolve(`publishers/${p.publisher_id}`)}>{p.publisher}</a>
						{:else}
							{p.publisher || ''}
						{/if}
					</td>{/if}
					{#if !isLab && col('labs')}<td>
						{#each p.lab_items || [] as lab}
							<a href={resolve(`structures/${lab.id}`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>{/if}
					{#if isPerson && col('corr')}<td class="corr-cell">
						{#if p.is_corresponding}<span title="Auteur correspondant">&#10003;</span>{/if}
					</td>{/if}
					{#if col('apc')}<td class="apc-cell">
						{#if p.apc}
							{@const ucaApc = p.apc.filter(a => a.in_perimeter)}
							{@const isPersonNonCorr = isPerson && !p.is_corresponding}
							{#if ucaApc.length > 0}
								<span class="apc-tag" class:apc-other={isPersonNonCorr}
									title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || institution.name})`).join('\n') + (isPersonNonCorr ? '\nAuteur non correspondant' : '')}>
									{Math.round(ucaApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{:else}
								<span class="apc-tag apc-other" title={p.apc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.institution || '?'})`).join('\n')}>
									{Math.round(p.apc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{/if}
						{/if}
					</td>{/if}
					{#if col('oa_status')}<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<span class="oa-tag oa-{p.oa_status}">{oaStatusLabel(p.oa_status)}</span>
						{/if}
					</td>{/if}
					{#if col('license')}<td class="license-cell">{p.license ? (licenseNames[p.license] ?? p.license) : ''}</td>{/if}
					{#if isLab && col('hal_status')}
						<td>{#if p.hal_status}<span class="hal-badge hal-{p.hal_status}">{halStatusLabel(p.hal_status)}</span>{/if}</td>
					{/if}
					{#if col('sources')}<td class="links-cell">
						{#if p.hal_id}
							<a href={p.record_urls.hal} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
								<img src={asset('icons/hal.ico')} alt="HAL" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.openalex_id}
							<a href={p.record_urls.openalex} target="_blank" rel="noopener" class="source-tag source-openalex" title="OpenAlex: {p.openalex_id}">
								<img src={asset('icons/openalex.png')} alt="OA" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.scanr_id}
							<a href={p.record_urls.scanr} target="_blank" rel="noopener" class="source-tag source-scanr" title="ScanR: {p.scanr_id}">
								<img src={asset('scanr-icon.svg')} alt="ScanR" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.wos_id}
							<a href={p.record_urls.wos} target="_blank" rel="noopener" class="source-tag source-wos" title="WoS: {p.wos_id}">
								<img src={asset('icons/wos.ico')} alt="WoS" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
					</td>{/if}
					<td class="access-cell"><AccessButton accessUrl={p.access_url} oaStatus={p.oa_status} compact /></td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</div>

<Pagination page={listing.page} pages={listing.pages} onchange={(p) => { listing.goToPage(p); syncUrl(); }} />

<style>
	.license-cell {
		font-size: 0.8rem;
	}	.publication-table { min-width: 760px; }
	.publication-table tr.active-row td { background: var(--accent-light); }
	.access-cell { white-space: nowrap; }

	/* Statut HAL (lab) */
	.hal-badge {
		display: inline-block;
		padding: 2px 7px;
		border-radius: var(--radius);
		font-size: 0.8rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.hal-ok              { background: var(--success-light); color: var(--success); }
	.hal-notice          { background: #fff3e0; color: #c77c00; }
	.hal-hors_collection { background: #ffe8d6; color: #d35400; }
	.hal-hors_hal        { background: var(--danger-light); color: var(--danger); }

	/* Auteur correspondant (person) */
	.corr-cell { text-align: center; color: var(--accent); font-size: 0.85rem; }

	/* Bouton exclure (admin, person) */
	.exclude-cell { padding: 0 2px !important; text-align: center; vertical-align: middle; }
	.exclude-btn {
		background: none; border: none; cursor: pointer;
		color: var(--text-faint); font-size: 0.85rem; padding: 2px 4px;
		border-radius: var(--radius); line-height: 1; transition: color 0.15s, background 0.15s;
	}
	.exclude-btn:hover { color: var(--danger); background: var(--danger-light); }
</style>
