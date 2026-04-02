<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import { oaLabelsMap } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	Chart.register(...registerables, ChartDataLabels);

	// --- Types ---
	interface Summary { total_pubs: number; publisher_count: number; journal_count: number; }
	interface YearData { pub_year: number; gold: number; diamond: number; hybrid: number; bronze: number; green: number; closed: number; unknown: number; }
	interface OaRow { pub_count: number; apc_uca: number; gold: number; diamond: number; hybrid: number; bronze: number; green: number; closed: number; unknown: number; }
	interface PublisherRow extends OaRow { publisher_id: number; publisher_name: string; journal_count: number; }
	interface JournalRow extends OaRow { journal_id: number; journal_title: string; publisher_name: string | null; }
	interface LabRow extends OaRow { lab_id: number; lab_name: string; lab_acronym: string | null; }

	// --- State ---
	type View = 'top' | 'publisher_detail' | 'journal_detail';
	type Tab = 'oa' | 'publishers' | 'journals' | 'labs';

	let view: View = $state('top');
	let tab: Tab = $state('oa');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let search = $state('');
	let publisherId: number | null = $state(null);
	let publisherName = $state('');
	let journalId: number | null = $state(null);
	let journalName = $state('');

	let summary: Summary = $state({ total_pubs: 0, publisher_count: 0, journal_count: 0 });

	let chartCanvas: HTMLCanvasElement;
	let yearChart: Chart | null = null;
	let initialYearsApplied = false;

	// --- Filter params (shared by all loaders) ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (publisherId) p.set('publisher_id', String(publisherId));
		if (journalId) p.set('journal_id', String(journalId));
		return p;
	}

	// --- Composables: paginated tables ---
	const pubFetch = usePaginatedFetch<PublisherRow>({
		endpoint: '/api/pub-stats/publishers',
		itemsKey: 'publishers',
		perPage: 50,
		apiKey: 'pub-stats-publishers',
		buildParams: () => {
			const p = chartParams();
			if (search.trim()) p.set('search', search.trim());
			return p;
		},
	});

	const journalFetch = usePaginatedFetch<JournalRow>({
		endpoint: '/api/pub-stats/journals',
		itemsKey: 'journals',
		perPage: 50,
		apiKey: 'pub-stats-journals',
		buildParams: () => {
			const p = chartParams();
			if (search.trim()) p.set('search', search.trim());
			return p;
		},
	});

	const labFetch = usePaginatedFetch<LabRow>({
		endpoint: '/api/pub-stats/labs',
		itemsKey: 'labs',
		perPage: 50,
		apiKey: 'pub-stats-labs',
		buildParams: chartParams,
	});

	// --- Composable: facets ---
	const facets = useFacets<'years' | 'labs' | 'oa' | 'apc'>({
		endpoint: '/api/pub-stats/facets',
		apiKey: 'pub-stats-facets',
		buildParams: chartParams,
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			labs: { type: 'labeled', apiKey: 'labs' },
			oa: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			apc: { type: 'passthrough', apiKey: 'apc' },
		},
	});

	// --- Composable: URL filters ---
	const urlFilters = useUrlFilters({
		basePath: '/stats',
		filters: {
			view: { type: 'single', urlKey: 'view', defaultValue: 'top' },
			tab: { type: 'single', urlKey: 'tab', defaultValue: 'oa' },
			selectedYears: { type: 'string_array', urlKey: 'year' },
			selectedLabs: { type: 'string_array', urlKey: 'lab_id' },
			selectedOa: { type: 'string_array', urlKey: 'oa_status' },
			selectedApc: { type: 'string_array', urlKey: 'has_apc' },
			publisherId: { type: 'single', urlKey: 'publisher_id' },
			publisherName: { type: 'single', urlKey: 'publisher_name' },
			journalId: { type: 'single', urlKey: 'journal_id' },
			journalName: { type: 'single', urlKey: 'journal_name' },
			search: { type: 'single', urlKey: 'search' },
			page: { type: 'page', urlKey: 'page' },
			labPage: { type: 'page', urlKey: 'lab_page' },
		},
	});

	function syncUrl() {
		urlFilters.syncUrl(() => ({
			view,
			tab,
			selectedYears,
			selectedLabs,
			selectedOa,
			selectedApc,
			publisherId: publisherId ? String(publisherId) : '',
			publisherName,
			journalId: journalId ? String(journalId) : '',
			journalName,
			search,
			page: pubFetch.page,
			labPage: labFetch.page,
		}));
	}

	// --- Derived: publications link ---
	const pubsUrl = $derived.by(() => {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (publisherId) { p.set('publisher_id', String(publisherId)); p.set('publisher_name', publisherName); }
		if (journalId) { p.set('journal_id', String(journalId)); p.set('journal_name', journalName); }
		p.set('doc_type', 'article,review');
		return base + '/publications?' + p.toString();
	});

	// --- Navigation ---
	function goTo(newView: View, opts?: { id?: number; name?: string }) {
		const wasPublisherDetail = view === 'publisher_detail';
		if (yearChart) { yearChart.destroy(); yearChart = null; }
		view = newView;
		tab = 'oa';
		pubFetch.page = 1; labFetch.page = 1;
		search = '';
		if (newView === 'top') {
			publisherId = null; publisherName = '';
			journalId = null; journalName = '';
		} else if (newView === 'publisher_detail') {
			publisherId = opts?.id ?? null;
			publisherName = opts?.name ?? '';
			journalId = null; journalName = '';
		} else if (newView === 'journal_detail') {
			journalId = opts?.id ?? null;
			journalName = opts?.name ?? '';
			if (!wasPublisherDetail) {
				publisherId = null; publisherName = '';
			}
		}
		syncUrl();
		refresh();
	}

	function goToTop(defaultTab: Tab) {
		if (yearChart) { yearChart.destroy(); yearChart = null; }
		view = 'top';
		tab = defaultTab;
		publisherId = null; publisherName = '';
		journalId = null; journalName = '';
		pubFetch.page = 1; labFetch.page = 1;
		search = '';
		syncUrl();
		refresh();
	}

	async function switchTab(newTab: Tab) {
		if (tab === 'oa' && yearChart) {
			yearChart.destroy();
			yearChart = null;
		}
		tab = newTab;
		pubFetch.page = 1; labFetch.page = 1;
		search = '';
		syncUrl();
		await loadTabContent();
	}

	// --- Data loading ---
	async function refresh() {
		await Promise.all([loadSummary(), loadTabContent(), facets.load()]);
	}

	async function loadSummary() {
		summary = await api<Summary>('/api/pub-stats/summary?' + chartParams());
	}

	async function loadTabContent() {
		if (tab === 'oa') {
			await tick();
			await loadChart();
		} else if (tab === 'publishers') {
			await pubFetch.load();
		} else if (tab === 'journals') {
			await journalFetch.load();
		} else if (tab === 'labs') {
			await labFetch.load();
		}
	}

	async function loadChart() {
		const data = await api<YearData[]>('/api/pub-stats/by-year?' + chartParams());
		await tick();
		if (yearChart) yearChart.destroy();
		if (!data.length || !chartCanvas) { yearChart = null; return; }

		const cs = getComputedStyle(document.documentElement);
		yearChart = new Chart(chartCanvas, {
			type: 'bar',
			plugins: [whiteBgPlugin],
			data: {
				labels: data.map((d) => d.pub_year),
				datasets: [
					{ label: 'Diamond', data: data.map((d) => d.diamond), backgroundColor: cs.getPropertyValue('--diamond').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Gold', data: data.map((d) => d.gold), backgroundColor: cs.getPropertyValue('--gold').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Hybrid', data: data.map((d) => d.hybrid), backgroundColor: cs.getPropertyValue('--hybrid').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Bronze', data: data.map((d) => d.bronze), backgroundColor: cs.getPropertyValue('--bronze').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Green', data: data.map((d) => d.green), backgroundColor: cs.getPropertyValue('--green').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Closed', data: data.map((d) => d.closed), backgroundColor: cs.getPropertyValue('--closed').trim(), barPercentage: 0.5, categoryPercentage: 0.7 },
					{ label: 'Indéterminé', data: data.map((d) => d.unknown), backgroundColor: cs.getPropertyValue('--unknown').trim(), barPercentage: 0.5, categoryPercentage: 0.7 }
				]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { display: false },
					tooltip: {
						bodyFont: { size: 14 },
						callbacks: {
							label: (ctx) => {
								const val = ctx.raw as number;
								const total = ctx.chart.data.datasets.reduce((s, ds) => s + ((ds.data[ctx.dataIndex] as number) || 0), 0);
								const pct = total ? ((val / total) * 100).toFixed(1) : '0.0';
								return `${ctx.dataset.label} : ${val} (${pct}%)`;
							},
							afterBody: (items) => {
								const total = items[0].chart.data.datasets.reduce((s, ds) => s + ((ds.data[items[0].dataIndex] as number) || 0), 0);
								return `Total : ${total}`;
							}
						}
					},
					datalabels: {
						color: '#fff',
						font: { size: 13, weight: 'bold' },
						formatter: (val: number, ctx) => {
							const total = ctx.chart.data.datasets.reduce((s, ds) => s + ((ds.data[ctx.dataIndex] as number) || 0), 0);
							const pct = total ? (val / total) * 100 : 0;
							return pct >= 10 ? Math.round(pct) + '%' : '';
						},
						anchor: 'center' as const,
						align: 'center' as const,
						listeners: {}
					}
				},
				interaction: {
					mode: 'point' as const,
					intersect: true
				},
				hover: {
					mode: 'point' as const,
					intersect: true
				},
				scales: {
					x: { stacked: true, grid: { display: false }, ticks: { font: { size: 14 } } },
					y: { stacked: true, beginAtZero: true, ticks: { font: { size: 13 }, precision: 0 } }
				}
			}
		});
	}

	let chartWhiteBg = $state(false);

	function exportChartPng() {
		if (!yearChart) return;
		chartWhiteBg = true;
		yearChart.options.plugins!.legend = { display: true, position: 'bottom' as const };
		yearChart.update('none');
		const a = document.createElement('a');
		a.href = yearChart.toBase64Image('image/png', 1);
		a.download = 'chart.png';
		a.click();
		chartWhiteBg = false;
		yearChart.options.plugins!.legend = { display: false };
		yearChart.update('none');
	}

	const whiteBgPlugin = {
		id: 'whiteBg',
		beforeDraw(chart: Chart) {
			if (!chartWhiteBg) return;
			const { ctx, width, height } = chart;
			ctx.save();
			ctx.fillStyle = '#ffffff';
			ctx.fillRect(0, 0, width, height);
			ctx.restore();
		}
	};

	function onFilterChange() {
		pubFetch.page = 1; labFetch.page = 1;
		syncUrl();
		refresh();
	}

	const onSearchInput = urlFilters.debouncedSearch(() => {
		pubFetch.page = 1;
		syncUrl();
		loadTabContent();
	});

	function oaPercent(val: number, total: number): string {
		return total ? (val / total * 100).toFixed(1) + '%' : '0%';
	}

	function labDisplayName(row: LabRow): string {
		if (row.lab_acronym && row.lab_acronym !== row.lab_name) {
			return row.lab_acronym + ' — ' + row.lab_name;
		}
		return row.lab_acronym || row.lab_name;
	}

	onMount(async () => {
		// Restore state from URL params
		const u = new URLSearchParams(window.location.search);
		const restored = urlFilters.restoreFromUrl(u);
		if (restored.view) {
			const v = restored.view as string;
			if (v === 'publisher_detail' || v === 'journal_detail') view = v;
		}
		if (restored.tab) {
			const t = restored.tab as string;
			if (t === 'oa' || t === 'publishers' || t === 'journals' || t === 'labs') tab = t;
		}
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.publisherId) { publisherId = parseInt(restored.publisherId as string); publisherName = (restored.publisherName as string) || ''; }
		if (restored.journalId) { journalId = parseInt(restored.journalId as string); journalName = (restored.journalName as string) || ''; }
		if (restored.search) search = restored.search as string;
		if (restored.page) pubFetch.page = restored.page as number;
		if (restored.labPage) labFetch.page = restored.labPage as number;

		// Load facets first, then apply default years if needed, then full refresh
		await facets.load();
		if (!initialYearsApplied && selectedYears.length === 0 && facets.options.years.length > 0) {
			const sorted = facets.options.years.map((o) => o.value).sort().reverse();
			selectedYears = sorted.slice(0, 5);
			syncUrl();
		}
		initialYearsApplied = true;
		refresh();
	});
</script>

<svelte:head>
	<title>Statistiques — Bibliométrie UCA</title>
</svelte:head>

<!-- Summary row -->
<div class="summary-row">
	<div class="summary-card">
		<div class="value">{summary.total_pubs}</div>
		<div class="label">Articles</div>
	</div>
	{#if !journalId}
		{#if !publisherId}
			<div class="summary-card">
				<div class="value">{summary.publisher_count}</div>
				<div class="label">Éditeurs</div>
			</div>
		{/if}
		<div class="summary-card">
			<div class="value">{summary.journal_count}</div>
			<div class="label">Revues</div>
		</div>
	{/if}
	<a class="pub-link" href={pubsUrl}>Voir les publications &rarr;</a>
</div>

<!-- Breadcrumb for detail views -->
{#if view !== 'top'}
	<div class="breadcrumb">
		{#if publisherId}
			<!-- svelte-ignore a11y_missing_attribute -->
			<a onclick={() => goToTop('publishers')}>Éditeurs</a>
			<span class="sep">›</span>
			{#if view === 'publisher_detail'}
				{publisherName}
			{:else}
				<!-- svelte-ignore a11y_missing_attribute -->
				<a onclick={() => goTo('publisher_detail', { id: publisherId ?? undefined, name: publisherName })}>{publisherName}</a>
				<span class="sep">›</span>
				{journalName}
			{/if}
		{:else if journalId}
			<!-- svelte-ignore a11y_missing_attribute -->
			<a onclick={() => goToTop('journals')}>Revues</a>
			<span class="sep">›</span>
			{journalName}
		{/if}
	</div>
{/if}

<!-- Toolbar: tabs + filters -->
<div class="toolbar">
	<div class="tab-group">
		<button class="tab-btn" class:active={tab === 'oa'} onclick={() => switchTab('oa')}>Open Access</button>
		{#if view === 'top'}
			<button class="tab-btn" class:active={tab === 'publishers'} onclick={() => switchTab('publishers')}>Éditeurs</button>
		{/if}
		{#if view === 'top' || view === 'publisher_detail'}
			<button class="tab-btn" class:active={tab === 'journals'} onclick={() => switchTab('journals')}>Revues</button>
		{/if}
		<button class="tab-btn" class:active={tab === 'labs'} onclick={() => switchTab('labs')}>Laboratoires</button>
	</div>
	<FacetDropdown label="Années" allLabel="Toutes" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
	<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onFilterChange} />
	<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />
	<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
	{#if tab === 'publishers' || tab === 'journals'}
		<input type="text" placeholder="Rechercher..." bind:value={search} oninput={onSearchInput} />
	{/if}
	{#if tab !== 'oa'}
		<span class="count">
			{#if tab === 'publishers'}{pubFetch.total} éditeur{pubFetch.total > 1 ? 's' : ''}
			{:else if tab === 'journals'}{journalFetch.total} revue{journalFetch.total > 1 ? 's' : ''}
			{:else if tab === 'labs'}{labFetch.total} laboratoire{labFetch.total > 1 ? 's' : ''}
			{/if}
		</span>
	{/if}
</div>

<!-- Tab: Open Access (chart) -->
{#if tab === 'oa'}
	<div class="legend">
		<span><span class="legend-dot" style="background:var(--diamond)"></span>Diamond</span>
		<span><span class="legend-dot" style="background:var(--gold)"></span>Gold</span>
		<span><span class="legend-dot" style="background:var(--hybrid)"></span>Hybrid</span>
		<span><span class="legend-dot" style="background:var(--bronze)"></span>Bronze</span>
		<span><span class="legend-dot" style="background:var(--green)"></span>Green</span>
		<span><span class="legend-dot" style="background:var(--closed)"></span>Closed</span>
		<span><span class="legend-dot" style="background:var(--unknown)"></span>Indéterminé</span>
	</div>
	<div class="chart-area">
		<canvas bind:this={chartCanvas}></canvas>
		<button type="button" class="chart-export" onclick={exportChartPng}>Export PNG</button>
	</div>
{/if}

<!-- Tab: Publishers -->
{#if tab === 'publishers'}
	<table class="data-table">
		<thead>
			<tr>
				<th>Éditeur</th>
				<th class="num">Revues</th>
				<th class="num">Articles</th>
				<th class="num">APC UCA</th>
				<th style="min-width:100px">OA</th>
				<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
				<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
			</tr>
		</thead>
		<tbody>
			{#each pubFetch.items as r (r.publisher_id)}
				<tr>
					<td class="name-cell">
						<!-- svelte-ignore a11y_missing_attribute -->
						<a onclick={() => goTo('publisher_detail', { id: r.publisher_id, name: r.publisher_name })}>{r.publisher_name}</a>
					</td>
					<td class="num num-small">{r.journal_count}</td>
					<td class="num">{r.pub_count}</td>
					<td class="num apc-cell">{r.apc_uca > 0 ? Math.round(r.apc_uca).toLocaleString('fr-FR') + ' €' : ''}</td>
					<td>
						<div class="oa-bar">
							<span class="diamond" style="width:{oaPercent(r.diamond, r.pub_count)}"></span>
							<span class="gold" style="width:{oaPercent(r.gold, r.pub_count)}"></span>
							<span class="hybrid" style="width:{oaPercent(r.hybrid, r.pub_count)}"></span>
							<span class="bronze" style="width:{oaPercent(r.bronze, r.pub_count)}"></span>
							<span class="green" style="width:{oaPercent(r.green, r.pub_count)}"></span>
							<span class="closed" style="width:{oaPercent(r.closed, r.pub_count)}"></span>
							<span class="unknown" style="width:{oaPercent(r.unknown, r.pub_count)}"></span>
						</div>
					</td>
					<td class="num num-small">{r.diamond}</td>
					<td class="num num-small">{r.gold}</td>
					<td class="num num-small">{r.hybrid}</td>
					<td class="num num-small">{r.bronze}</td>
					<td class="num num-small">{r.green}</td>
					<td class="num num-small">{r.closed}</td>
					<td class="num num-small">{r.unknown}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	<Pagination page={pubFetch.page} pages={pubFetch.pages} onchange={(p) => { pubFetch.goToPage(p); syncUrl(); }} />
{/if}

<!-- Tab: Journals -->
{#if tab === 'journals'}
	<table class="data-table">
		<thead>
			<tr>
				<th>Revue</th>
				{#if !publisherId}<th>Éditeur</th>{/if}
				<th class="num">Articles</th>
				<th class="num">APC UCA</th>
				<th style="min-width:100px">OA</th>
				<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
				<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
			</tr>
		</thead>
		<tbody>
			{#each journalFetch.items as r (r.journal_id)}
				<tr>
					<td class="name-cell">
						<!-- svelte-ignore a11y_missing_attribute -->
						<a onclick={() => goTo('journal_detail', { id: r.journal_id, name: r.journal_title })}>{r.journal_title}</a>
					</td>
					{#if !publisherId}
						<td class="name-cell num-small">{r.publisher_name || ''}</td>
					{/if}
					<td class="num">{r.pub_count}</td>
					<td class="num apc-cell">{r.apc_uca > 0 ? Math.round(r.apc_uca).toLocaleString('fr-FR') + ' €' : ''}</td>
					<td>
						<div class="oa-bar">
							<span class="diamond" style="width:{oaPercent(r.diamond, r.pub_count)}"></span>
							<span class="gold" style="width:{oaPercent(r.gold, r.pub_count)}"></span>
							<span class="hybrid" style="width:{oaPercent(r.hybrid, r.pub_count)}"></span>
							<span class="bronze" style="width:{oaPercent(r.bronze, r.pub_count)}"></span>
							<span class="green" style="width:{oaPercent(r.green, r.pub_count)}"></span>
							<span class="closed" style="width:{oaPercent(r.closed, r.pub_count)}"></span>
							<span class="unknown" style="width:{oaPercent(r.unknown, r.pub_count)}"></span>
						</div>
					</td>
					<td class="num num-small">{r.diamond}</td>
					<td class="num num-small">{r.gold}</td>
					<td class="num num-small">{r.hybrid}</td>
					<td class="num num-small">{r.bronze}</td>
					<td class="num num-small">{r.green}</td>
					<td class="num num-small">{r.closed}</td>
					<td class="num num-small">{r.unknown}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	<Pagination page={journalFetch.page} pages={journalFetch.pages} onchange={(p) => { journalFetch.goToPage(p); syncUrl(); }} />
{/if}

<!-- Tab: Labs -->
{#if tab === 'labs'}
	{#if labFetch.items.length > 0}
		<table class="data-table">
			<thead>
				<tr>
					<th>Laboratoire</th>
					<th class="num">Articles</th>
					<th class="num">APC UCA</th>
					<th style="min-width:100px">OA</th>
					<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
					<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
				</tr>
			</thead>
			<tbody>
				{#each labFetch.items as r (r.lab_id)}
					<tr>
						<td class="name-cell" title={r.lab_name}>
							<a href="{base}/laboratories/{r.lab_id}">{labDisplayName(r)}</a>
						</td>
						<td class="num">{r.pub_count}</td>
						<td class="num apc-cell">{r.apc_uca > 0 ? Math.round(r.apc_uca).toLocaleString('fr-FR') + ' €' : ''}</td>
						<td>
							<div class="oa-bar">
								<span class="diamond" style="width:{oaPercent(r.diamond, r.pub_count)}"></span>
								<span class="gold" style="width:{oaPercent(r.gold, r.pub_count)}"></span>
								<span class="hybrid" style="width:{oaPercent(r.hybrid, r.pub_count)}"></span>
								<span class="bronze" style="width:{oaPercent(r.bronze, r.pub_count)}"></span>
								<span class="green" style="width:{oaPercent(r.green, r.pub_count)}"></span>
								<span class="closed" style="width:{oaPercent(r.closed, r.pub_count)}"></span>
								<span class="unknown" style="width:{oaPercent(r.unknown, r.pub_count)}"></span>
							</div>
						</td>
						<td class="num num-small">{r.diamond}</td>
						<td class="num num-small">{r.gold}</td>
						<td class="num num-small">{r.hybrid}</td>
						<td class="num num-small">{r.bronze}</td>
						<td class="num num-small">{r.green}</td>
						<td class="num num-small">{r.closed}</td>
						<td class="num num-small">{r.unknown}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<Pagination page={labFetch.page} pages={labFetch.pages} onchange={(p) => { labFetch.goToPage(p); syncUrl(); }} />
	{:else}
		<div class="empty">Aucun laboratoire associé</div>
	{/if}
{/if}

<style>
	.summary-row {
		display: flex;
		gap: 10px;
		margin-bottom: 16px;
		align-items: center;
		flex-wrap: wrap;
	}
	.summary-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 16px;
		text-align: center;
	}
	.summary-card .value { font-size: 1.45rem; font-weight: 700; line-height: 1.2; }
	.summary-card .label {
		font-size: 0.8rem;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
	.pub-link {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 8px 14px;
		background: var(--accent);
		color: white;
		text-decoration: none;
		border-radius: 5px;
		font-size: 0.95rem;
		font-weight: 500;
	}
	.pub-link:hover { opacity: 0.9; }

	.toolbar { margin-bottom: 16px; }
	.toolbar input[type='text'] { width: 220px; background: white; }
	.tab-group { display: flex; gap: 0; margin-right: 12px; }
	.tab-btn {
		padding: 6px 14px;
		border: 1px solid var(--border);
		background: white;
		font-size: 0.95rem;
		cursor: pointer;
		font-family: inherit;
	}
	.tab-btn:first-child { border-radius: 4px 0 0 4px; }
	.tab-btn:last-child { border-radius: 0 4px 4px 0; }
	.tab-btn:not(:first-child) { border-left: none; }
	.tab-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

	.breadcrumb { font-size: 0.95rem; color: var(--muted); margin-bottom: 12px; }
	.breadcrumb a { color: var(--accent); text-decoration: none; cursor: pointer; }
	.breadcrumb a:hover { text-decoration: underline; }
	.breadcrumb .sep { margin: 0 6px; color: #ccc; }

	.legend {
		display: flex;
		gap: 12px;
		justify-content: center;
		margin-bottom: 8px;
		font-size: 0.8rem;
		color: var(--muted);
	}
	.legend-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 2px;
		margin-right: 3px;
		vertical-align: middle;
	}

	.chart-area {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
		margin-bottom: 16px;
		position: relative;
		height: 550px;
	}
	.chart-export {
		position: absolute;
		top: 8px;
		right: 8px;
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 0.85rem;
		color: var(--muted);
		cursor: pointer;
		font-family: inherit;
		opacity: 0;
		transition: opacity 0.15s;
	}
	.chart-area:hover .chart-export {
		opacity: 1;
	}
	.chart-export:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	.data-table { margin-bottom: 4px; }

	.name-cell {
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.name-cell a { color: var(--accent); text-decoration: none; cursor: pointer; }
	.name-cell a:hover { text-decoration: underline; }
	.num-small { font-size: 0.85rem; color: var(--muted); }
	.apc-cell { font-size: 0.85rem; color: #2e7d32; white-space: nowrap; }

	.oa-bar {
		display: flex;
		height: 6px;
		border-radius: 3px;
		overflow: hidden;
		min-width: 80px;
	}
	.oa-bar span { height: 100%; }
	.oa-bar .diamond { background: var(--diamond); }
	.oa-bar .gold { background: var(--gold); }
	.oa-bar .hybrid { background: var(--hybrid); }
	.oa-bar .bronze { background: var(--bronze); }
	.oa-bar .green { background: var(--green); }
	.oa-bar .closed { background: var(--closed); }
	.oa-bar .unknown { background: var(--unknown); }

</style>
