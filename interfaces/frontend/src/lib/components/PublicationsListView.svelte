<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import SourceLinks from '#lib/components/SourceLinks.svelte';
	import AccessButton from '#lib/components/AccessButton.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import CorrespondingMark from '#lib/components/CorrespondingMark.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { withBase } from '#lib/paths.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import PivotControls from '#lib/components/stats/PivotControls.svelte';
	import PivotChart from '#lib/components/stats/PivotChart.svelte';
	import { PIVOT_URL_FILTERS, pivotSettingsFromUrl, usePivotChart } from '#lib/composables/usePivotChart.svelte.js';
	import PublicationDrawer from '#lib/components/publications/PublicationDrawer.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import { activeColumns } from '#lib/filterRegistry.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import LicenseBadge from '#lib/components/LicenseBadge.svelte';
	import { citationTopLabels, columnLabels, oaStatusDescriptions, oaStatusLabel } from '#lib/labels.js';
	import Tooltip from '#lib/components/Tooltip.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { PUBLICATION_FACETS_ENDPOINT, usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
	import { PUBLICATION_FILTER_GROUPS, publicationFilters } from '#lib/publicationFilters.js';
	import { useColumnVisibility } from '#lib/composables/useColumnVisibility.svelte.js';
	import ColumnMenu from '#lib/components/ColumnMenu.svelte';
	import { paramsToQuery } from '#lib/utils.js';
	import { nextSort, sortDirection, type SortDirection } from '#lib/sort.js';
	import IconButton from '#lib/components/IconButton.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import { contextEntityId, type PublicationListContext } from '#lib/publicationListContext.js';

	import type { components } from '#lib/api/schema.js';
	type Publication = components['schemas']['PublicationListItem'] & {
		// Champs présents quand l'API est appelée avec `person_id` (cf. routes /api/publications côté backend qui enrichit la réponse). Optionnels car non garantis hors contexte personne.
		contribution_id?: number | null;
	};

	function isCorresponding(p: Publication): boolean {
		return p.author_positions?.includes('corresponding') ?? false;
	}

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
		onchange,
	}: {
		apiKey?: string;
		context?: PublicationListContext;
		urlSync?: boolean;
		basePath?: string;
		/** Ajoute en tête de ligne une croix qui exclut la contribution. Le parent gère l'auth check et passe le callback. Si le callback retourne `true` (ou void), la ligne est retirée du tableau ; retourne `false` pour annuler (ex. l'utilisatrice a cliqué Annuler dans un confirm). */
		showAdminExclude?: boolean;
		/** Nombre d'éléments par page (50 pour les onglets, 100 pour /publications). */
		perPage?: number;
		onExcludeContribution?: (contributionId: number, publicationId: number) => void | boolean | Promise<void | boolean>;
		/** Appelé après une fusion de publications dans le volet. */
		onchange?: () => void;
	} = $props();

	// Volet d'une publication : ouvert tant que `?publication=<id>` figure dans l'URL. Une icône en tête de ligne ouvre le volet ; le titre mène toujours à la fiche.
	const drawer = useDrawerParam('publication');

	// Le laboratoire a la colonne et le filtre « Statut HAL ». La personne a la colonne « Auteur correspondant », et marque les APC des publications dont elle n'est pas l'auteur correspondant. Le filtre « Position auteur » vaut pour l'un et l'autre.
	// svelte-ignore state_referenced_locally
	const isLab = context.kind === 'lab';
	// svelte-ignore state_referenced_locally
	const isPerson = context.kind === 'person';

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
		{ key: 'citation_top', label: columnLabels.citationTop },
		...(isLab ? [{ key: 'hal_status', label: 'Statut HAL' }] : []),
		{ key: 'sources',    label: columnLabels.sources },
		{ key: 'access',     label: columnLabels.access, fixed: true },
	];
	const initialHidden = ['apc', 'oa_status', 'license', 'citation_top', 'publisher', 'sources'];
	if (isLab) initialHidden.push('hal_status');
	const cv = useColumnVisibility('publication-table-columns', columnDefs, initialHidden);
	const col = cv.col;

	// --- Vue ---
	// Notices : type et DOI, puis titre, puis année, revue, éditeur et laboratoires ; accès à droite. Tableau : une colonne par champ, colonnes au choix. Statistiques : graphique des publications filtrées.
	type View = 'notices' | 'table' | 'stats';
	const VIEWS: readonly View[] = ['notices', 'table', 'stats'];
	let view = $state<View>('notices');

	// Tris de la vue Notices, où les en-têtes de colonne manquent : année, des plus récentes aux plus anciennes, ou titre, de A à Z. Un bouton inverse le sens. Un tri choisi dans le tableau sur une autre colonne reste proposé.
	type SortField = { field: string; label: string; first: SortDirection };
	const NOTICE_SORTS: SortField[] = [
		{ field: 'year', label: columnLabels.year, first: 'desc' },
		{ field: 'title', label: columnLabels.title, first: 'asc' },
	];
	/** Colonnes triées par ordre alphabétique : leur sens s'affiche « A→Z ». Les autres (année, montant) s'affichent par une flèche. */
	const ALPHABETICAL_SORTS = new Set(['title', 'serial', 'publisher', 'labs']);

	// --- Filtres ---
	// svelte-ignore state_referenced_locally
	const FILTERS = publicationFilters(context);

	const list = useFilteredList<Publication, ReturnType<typeof usePublicationFacets>>({
		filters: FILTERS,
		baseParams() {
			const params = new URLSearchParams({ excluded_doc_type: 'ongoing_thesis' });
			const personId = contextEntityId(context, 'person');
			if (personId) params.set('person_id', personId);
			const monographId = contextEntityId(context, 'monograph');
			if (monographId) params.set('monograph_id', monographId);
			return params;
		},
		endpoint: '/api/publications',
		itemsKey: 'publications',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		defaultSort: 'year_desc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		facets: (buildParams) => usePublicationFacets({ filters: FILTERS, apiKey: () => `${apiKey}-facets`, buildParams }),
		// La vue et les réglages du graphique s'écrivent dans l'URL avec les filtres.
		extraUrl: {
			filters: { view: { type: 'single', urlKey: 'view', defaultValue: 'notices' }, ...PIVOT_URL_FILTERS },
			state: () => ({ view, ...pivot.settings }),
			restore(restored) {
				if (VIEWS.includes(restored.view as View)) view = restored.view as View;
				pivot.restore(pivotSettingsFromUrl(restored));
			},
		},
		onchange: () => {
			if (view === 'stats') pivot.load();
		},
	});
	const listing = list.listing;
	const facets = list.facets;
	const currentSort = $derived(list.sort);

	// Graphique de la vue Statistiques.
	const pivot = usePivotChart({
		buildParams: list.filterParams,
		// Libellés servis par la facette, y compris celui des publications sans licence.
		licenseLabel: (value) => facets.options.license?.find((o) => o.value === value)?.text,
		onsettingchange: () => list.syncUrl(),
	});

	// Charge le graphique, et d'abord son vocabulaire à la première ouverture de la vue.
	async function loadChart() {
		if (!pivot.schema) await pivot.loadSchema();
		await pivot.load();
	}

	// Sort display
	const yearSort = $derived(sortDirection(currentSort, 'year'));
	const titleSort = $derived(sortDirection(currentSort, 'title'));
	const apcSort = $derived(sortDirection(currentSort, 'apc'));
	const serialSort = $derived(sortDirection(currentSort, 'serial'));
	const publisherSort = $derived(sortDirection(currentSort, 'publisher'));
	const labsSort = $derived(sortDirection(currentSort, 'labs'));

	// Tri courant, décomposé pour la vue Notices.
	const sortField = $derived(currentSort.replace(/_(asc|desc)$/, ''));
	const sortDir = $derived<SortDirection>(currentSort.endsWith('_asc') ? 'asc' : 'desc');
	const noticeSorts = $derived(
		NOTICE_SORTS.some((s) => s.field === sortField)
			? NOTICE_SORTS
			: [...NOTICE_SORTS, { field: sortField, label: columnLabels[sortField as keyof typeof columnLabels] ?? sortField, first: sortDir }],
	);
	// Texte du sens d'un tri alphabétique ; les autres tris s'affichent par une flèche dessinée.
	const sortDirLabel = $derived(
		ALPHABETICAL_SORTS.has(sortField) ? (sortDir === 'asc' ? 'A→Z' : 'Z→A') : null,
	);
	const sortDirTitle = $derived(
		sortField === 'year'
			? sortDir === 'desc' ? "Plus récentes d'abord" : "Plus anciennes d'abord"
			: ALPHABETICAL_SORTS.has(sortField)
				? sortDir === 'asc' ? 'De A à Z' : 'De Z à A'
				: sortDir === 'desc' ? 'Décroissant' : 'Croissant',
	);

	function setSortField(field: string) {
		const first = noticeSorts.find((s) => s.field === field)?.first ?? 'asc';
		list.setSort(`${field}_${first}`);
	}

	function toggleSortDir() {
		list.setSort(`${sortField}_${sortDir === 'asc' ? 'desc' : 'asc'}`);
	}

	function setView(next: View) {
		view = next;
		list.syncUrl();
		if (view === 'stats') loadChart();
	}

	function toggleSort(column: 'year' | 'title' | 'serial' | 'publisher' | 'labs' | 'apc') {
		list.setSort(nextSort(currentSort, column, column === 'year' || column === 'apc' ? 'desc' : 'asc'));
	}

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', currentSort);
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
		await list.restore();
		// Colonnes des filtres actifs, affichées d'office.
		const needed = activeColumns(FILTERS, list.values);
		if (needed.length) cv.ensure(needed);
		if (view === 'stats') loadChart();
	});
</script>


<ListToolbar bind:search={list.search} placeholder="Rechercher par titre ou sujet" onsearch={list.onSearchInput} list={listing} one="publication" many="publications" exportUrl={view === 'stats' ? undefined : exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet exportAction()}
		{#if view === 'stats'}<button type="button" class="export-btn" onclick={pivot.exportPng}>Export PNG</button>{/if}
	{/snippet}
	{#snippet actions()}
		{#if view === 'notices'}
			<span class="sort-select">
				<label>Trier par
					<select value={sortField} onchange={(e) => setSortField(e.currentTarget.value)}>
						{#each noticeSorts as s (s.field)}<option value={s.field}>{s.label}</option>{/each}
					</select>
				</label>
				<button type="button" class="facet-btn sort-dir" title={sortDirTitle} aria-label="Sens du tri : {sortDirTitle}" onclick={toggleSortDir}>
					{#if sortDirLabel}{sortDirLabel}{:else}
						<svg class="sort-dir-icon" class:up={sortDir === 'asc'} width="10" height="18" viewBox="0 0 10 18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 1.5v15M1.5 13l3.5 3.5L8.5 13" /></svg>
					{/if}
				</button>
			</span>
		{/if}
		<div class="segmented" role="group" aria-label="Affichage">
			<button type="button" aria-pressed={view === 'notices'} onclick={() => setView('notices')}>Notices</button>
			<button type="button" aria-pressed={view === 'table'} onclick={() => setView('table')}>Tableau</button>
			<button type="button" aria-pressed={view === 'stats'} onclick={() => setView('stats')}>Statistiques</button>
		</div>
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
{#snippet panel()}
	<FilterPanel filters={FILTERS} groups={PUBLICATION_FILTER_GROUPS} bind:values={list.values} options={facets.options} presenceCounts={facets.sourceCounts} loaded={facets.loaded} expanded={['docTypes', 'years']} entityEndpoint={PUBLICATION_FACETS_ENDPOINT} buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
{/snippet}
{#if view === 'stats'}
<div class="stats-view">
	<div class="stats-controls"><PivotControls chart={pivot} /></div>
	<PivotChart chart={pivot} />
</div>
{:else if view === 'notices'}
<ListStatus list={listing} emptyText="Aucune publication trouvée">
	<ul class="notices">
		{#each listing.items as p (p.id)}
			<li class="notice" class:active-row={p.id === drawer.id}>
				<div class="notice-actions row-actions">
					<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(p.id)} />
					{#if showAdminExclude && p.contribution_id != null}
						<IconButton icon="reject" label="Exclure ce lien auteur–publication" onclick={() => onExcludeClick(p)} />
					{/if}
				</div>
				<div>
					{#if p.doc_type || p.doi}
						<div class="notice-head">
							{#if p.doc_type}<DocTypePill docType={p.doc_type} />{/if}
							{#if p.doi}<span class="notice-doi"><DoiLink doi={p.doi} text /></span>{/if}
						</div>
					{/if}
					<div class="notice-body">
					<a href={resolve(`publications/${p.id}`)} class="publication-title notice-title"><PublicationTitle titre={p.title} /></a>
					<div class="notice-meta">
						{#if p.publication_year}<span class="notice-year">{p.publication_year}</span>{/if}
						{#if p.serial}<span class="notice-serial">{#if p.serial_id}<a href={resolve(`journals/${p.serial_id}`)}>{p.serial}</a>{:else}{p.serial}{/if}</span>{/if}
						{#if p.publisher}<span>{#if p.publisher_id}<a href={resolve(`publishers/${p.publisher_id}`)}>{p.publisher}</a>{:else}{p.publisher}{/if}</span>{/if}
						{#if !isLab && p.lab_items?.length}
							<span class="notice-labs">{#each p.lab_items as lab, i (lab.id)}{#if i > 0}{', '}{/if}<a href={resolve(`structures/${lab.id}`)}>{lab.label}</a>{/each}</span>
						{/if}
					</div>
					</div>
				</div>
				<div class="notice-access"><AccessButton accessUrl={p.access_url} oaStatus={p.oa_status} docType={p.doc_type} compact /></div>
			</li>
		{/each}
	</ul>
</ListStatus>
{:else}
<TableScroll>
<table class="data-table publication-table">
	<thead>
		<tr>
			<th class="row-actions"></th>
			{#if col('type')}<th style="width:80px">{columnLabels.type}</th>{/if}
			{#if col('year')}<th style="width:40px" class="sortable" class:active={yearSort !== null} onclick={() => toggleSort('year')}>
				{columnLabels.year} <SortChevron direction={yearSort} />
			</th>{/if}
			{#if col('doi')}<th style="width:28px">{columnLabels.doi}</th>{/if}
			<th class="sortable publication-col-title" class:active={titleSort !== null} onclick={() => toggleSort('title')}>
				{columnLabels.title} <SortChevron direction={titleSort} />
			</th>
			{#if col('serial')}<th class="publication-col-journal sortable" class:active={serialSort !== null} onclick={() => toggleSort('serial')}>
				{columnLabels.serial} <SortChevron direction={serialSort} />
			</th>{/if}
			{#if col('publisher')}<th class="publication-col-journal sortable" class:active={publisherSort !== null} onclick={() => toggleSort('publisher')}>
				{columnLabels.publisher} <SortChevron direction={publisherSort} />
			</th>{/if}
			{#if !isLab && col('labs')}<th style="width:80px" class="sortable" class:active={labsSort !== null} onclick={() => toggleSort('labs')}>
				{columnLabels.labs} <SortChevron direction={labsSort} />
			</th>{/if}
			{#if isPerson && col('corr')}<th style="width:30px" title="Auteur correspondant">&#9993;</th>{/if}
			{#if col('apc')}<th style="width:60px" class="sortable" class:active={apcSort !== null} onclick={() => toggleSort('apc')}>
				{columnLabels.apc} <SortChevron direction={apcSort} />
			</th>{/if}
			{#if col('oa_status')}<th style="width:60px">{columnLabels.oaStatus}</th>{/if}
			{#if col('license')}<th style="width:90px">{columnLabels.license}</th>{/if}
			{#if col('citation_top')}<th style="width:80px">{columnLabels.citationTop}</th>{/if}
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
			<TableStatusRow loading={listing.loading} error={listing.error} colspan={cv.visibleColumns.length + 1} emptyText="Aucune publication trouvée" />
		{:else}
			{#each listing.items as p (p.id)}
				<tr class:active-row={p.id === drawer.id}>
					<!-- Cellule d'actions : volet, puis exclusion de la contribution. -->
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(p.id)} />
						{#if showAdminExclude && p.contribution_id != null}
							<IconButton icon="reject" label="Exclure ce lien auteur–publication" onclick={() => onExcludeClick(p)} />
						{/if}
					</td>
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
							<a href={resolve(`structures/${lab.id}`)} class="structure-link">{lab.label}</a>
						{/each}
					</td>{/if}
					{#if isPerson && col('corr')}<td class="corr-cell">
						{#if isCorresponding(p)}<CorrespondingMark />{/if}
					</td>{/if}
					{#if col('apc')}<td class="apc-cell">
						{#if p.apc}
							{@const ucaApc = p.apc.filter(a => a.in_perimeter)}
							{@const isPersonNonCorr = isPerson && !isCorresponding(p)}
							{#if ucaApc.length > 0}
								<span class="tag" class:tag-success={!isPersonNonCorr}
									title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || institution.name})`).join('\n') + (isPersonNonCorr ? '\nAuteur non correspondant' : '')}>
									{Math.round(ucaApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{:else}
								<span class="tag" title={p.apc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.institution || '?'})`).join('\n')}>
									{Math.round(p.apc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{/if}
						{/if}
					</td>{/if}
					{#if col('oa_status')}<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<Tooltip text={oaStatusDescriptions[p.oa_status] ?? ''}><span class="tag" style="--tag-color: var(--{p.oa_status})">{oaStatusLabel(p.oa_status)}</span></Tooltip>
						{/if}
					</td>{/if}
					{#if col('license')}<td class="license-cell">{#if p.license}<LicenseBadge license={p.license} />{/if}</td>{/if}
					{#if col('citation_top')}<td>
						{#if p.citation_top}<span class="tag tag-accent" class:tag-filled={p.citation_top === 'top_1_percent'}>{citationTopLabels[p.citation_top]}</span>{/if}
					</td>{/if}
					{#if isLab && col('hal_status')}
						<td>{#if p.hal_status}<span class="tag hal-{p.hal_status}">{halStatusLabel(p.hal_status)}</span>{/if}</td>
					{/if}
					{#if col('sources')}<td class="links-cell">
						<SourceLinks ids={[['hal', p.hal_id], ['openalex', p.openalex_id], ['scanr', p.scanr_id], ['wos', p.wos_id]]} urls={p.record_urls} />
					</td>{/if}
					<td class="access-cell"><AccessButton accessUrl={p.access_url} oaStatus={p.oa_status} docType={p.doc_type} compact /></td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</TableScroll>
{/if}

{#if view !== 'stats'}
<Pagination page={listing.page} pages={listing.pages} onchange={list.goToPage} />
{/if}
</FilterLayout>

{#if drawer.id !== null}
	<PublicationDrawer
		publicationId={drawer.id}
		onclose={() => drawer.open(null)}
		onopen={drawer.open}
		onchange={() => {
			listing.load();
			facets.load();
			onchange?.();
		}}
	/>
{/if}

<style>
	.license-cell {
		font-size: var(--fs-sm);
	}
	.publication-table { min-width: 760px; }
	.access-cell { white-space: nowrap; }

	/* Statut HAL (lab) */
	.hal-ok              { --tag-color: var(--success); }
	.hal-notice          { --tag-color: var(--warning); }
	.hal-hors_collection { --tag-color: var(--attention); }
	.hal-hors_hal        { --tag-color: var(--danger); }

	/* Auteur correspondant (person) */
	.corr-cell { text-align: center; }
	.corr-cell :global(.corresponding-mark) { margin-left: 0; }

	/* Vue Notices : actions, notice, accès ; l'accès passe sous la notice sur un écran étroit. */
	.sort-select {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		font-size: var(--fs-sm);
		color: var(--muted);
	}
	.sort-select label {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	/* Sens du tri : « A→Z » ou flèche, collé à la liste du tri. */
	/* Même largeur pour la flèche et pour « A→Z », contenu calé à gauche, près de la liste du tri. Au survol, seule la couleur change. */
	.sort-dir {
		width: 3em;
		justify-content: flex-start;
		padding: 0 4px;
		margin-left: 2px;
	}
	.sort-dir:hover {
		background: none;
		color: color-mix(in srgb, var(--accent), black 25%);
	}
	/* Flèche haute, vers le bas pour un ordre décroissant, retournée pour un ordre croissant. */
	.sort-dir-icon.up {
		transform: rotate(180deg);
	}
	/* Vue Statistiques : réglages, puis graphique dans une colonne flexible. Sa hauteur suit la fenêtre, moins le menu et la barre d'outils de la liste à sa place ; elle ignore le glissement de la barre au défilement, qui la ferait varier. */
	.stats-view {
		display: flex;
		flex-direction: column;
		height: max(480px, calc(100vh - var(--header-height) - 180px));
	}
	.stats-controls {
		margin-bottom: 12px;
	}
	.notices {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	/* La colonne de l'accès a la même largeur dans toutes les notices, lien présent ou non : les titres passent à la ligne au même endroit. Elle contient le lien le plus large, « Texte intégral ». */
	.notice {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) 7.5rem;
		gap: 0 12px;
		padding: 10px 8px;
		border-bottom: 1px solid var(--border-subtle);
	}
	.notice:hover {
		background: var(--surface-hover);
	}
	.notice.active-row {
		background: var(--accent-light);
	}
	.notice-actions {
		display: flex;
		gap: 2px;
		align-items: flex-start;
	}
	.notice-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 10px;
		margin-bottom: 6px;
		font-size: var(--fs-sm);
	}
	.notice-doi {
		min-width: 0;
	}
	/* Titre et ligne de métadonnées en léger retrait : le type de document ressort en tête de notice. */
	.notice-body {
		padding-left: 10px;
	}
	.notice-title {
		font-size: 1.1rem;
	}
	.notice-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		row-gap: 2px;
		margin-top: 3px;
		font-size: var(--fs-sm);
		color: var(--muted);
	}
	/* Le point séparateur précède l'élément suivant et passe à la ligne avec lui. */
	.notice-meta > * + *::before {
		content: '·';
		margin: 0 6px;
		color: var(--text-faint);
	}
	.notice-meta a {
		color: inherit;
		text-decoration: none;
	}
	.notice-meta a:hover {
		text-decoration: underline;
	}
	.notice-year,
	.notice-labs {
		font-weight: 600;
		color: var(--text-secondary);
	}
	.notice-serial {
		font-style: italic;
	}
	.notice-access {
		justify-self: end;
		padding-top: 2px;
	}
	@media (max-width: 640px) {
		.notice {
			grid-template-columns: auto minmax(0, 1fr);
		}
		.notice-access {
			grid-column: 2;
			justify-self: start;
			padding-top: 4px;
		}
	}
</style>
