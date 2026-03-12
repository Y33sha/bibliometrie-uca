<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import { oaLabelsMap } from '$lib/labels';

	Chart.register(...registerables, ChartDataLabels);

	// --- Types ---
	interface Summary { total_pubs: number; publisher_count: number; journal_count: number; }
	interface YearData { pub_year: number; gold: number; diamond: number; hybrid: number; bronze: number; green: number; closed: number; unknown: number; }
	interface OaRow { pub_count: number; gold: number; diamond: number; hybrid: number; bronze: number; green: number; closed: number; unknown: number; }
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
	let search = $state('');
	let publisherId: number | null = $state(null);
	let publisherName = $state('');
	let journalId: number | null = $state(null);
	let journalName = $state('');
	let page = $state(1);
	let labPage = $state(1);

	// Facet options
	let yearOptions: FacetOption[] = $state([]);
	let labOptions: FacetOption[] = $state([]);
	let oaOptions: FacetOption[] = $state([]);

	let summary: Summary = $state({ total_pubs: 0, publisher_count: 0, journal_count: 0 });

	let publishers: PublisherRow[] = $state([]);
	let pubTotal = $state(0);
	let pubPages = $state(1);

	let journals: JournalRow[] = $state([]);
	let journalTotal = $state(0);
	let journalPages = $state(1);

	let labRows: LabRow[] = $state([]);
	let labTotal = $state(0);
	let labPages = $state(1);

	let chartCanvas: HTMLCanvasElement;
	let yearChart: Chart | null = null;
	let debounceTimer: ReturnType<typeof setTimeout>;
	let initialYearsApplied = false;

	const pubsUrl = $derived.by(() => {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (publisherId) { p.set('publisher_id', String(publisherId)); p.set('publisher_name', publisherName); }
		if (journalId) { p.set('journal_id', String(journalId)); p.set('journal_name', journalName); }
		p.set('doc_type', 'article,review');
		return base + '/publications?' + p.toString();
	});

	// --- Filter params ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (publisherId) p.set('publisher_id', String(publisherId));
		if (journalId) p.set('journal_id', String(journalId));
		return p;
	}

	// --- URL sync (preserve state across navigation) ---
	function syncUrl() {
		const p = new URLSearchParams();
		if (view !== 'top') p.set('view', view);
		if (tab !== 'oa') p.set('tab', tab);
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (publisherId) { p.set('publisher_id', String(publisherId)); p.set('publisher_name', publisherName); }
		if (journalId) { p.set('journal_id', String(journalId)); p.set('journal_name', journalName); }
		if (search) p.set('search', search);
		if (page > 1) p.set('page', String(page));
		if (labPage > 1) p.set('lab_page', String(labPage));
		const qs = p.toString();
		history.replaceState(history.state, '', base + '/stats' + (qs ? '?' + qs : ''));
	}

	// --- Navigation ---
	function goTo(newView: View, opts?: { id?: number; name?: string }) {
		const wasPublisherDetail = view === 'publisher_detail';
		if (yearChart) { yearChart.destroy(); yearChart = null; }
		view = newView;
		tab = 'oa';
		page = 1; labPage = 1;
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
		page = 1; labPage = 1;
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
		page = 1; labPage = 1;
		search = '';
		syncUrl();
		await loadTabContent();
	}

	// --- Data loading ---
	async function refresh() {
		await Promise.all([loadSummary(), loadTabContent(), loadFacets()]);
	}

	async function loadFacets() {
		const p = chartParams();
		const data = await api<{
			years: { value: number; count: number }[];
			labs: { value: number; label: string; count: number }[];
			oa_statuses: { value: string; count: number }[];
		}>('/api/pub-stats/facets?' + p);
		yearOptions = data.years.map((y) => ({
			value: String(y.value), text: String(y.value), count: y.count
		}));
		labOptions = data.labs.map((l) => ({
			value: String(l.value), text: l.label, count: l.count
		}));
		oaOptions = data.oa_statuses.map((o) => ({
			value: o.value, text: oaLabelsMap[o.value] || o.value, count: o.count
		}));
	}

	async function loadSummary() {
		summary = await api<Summary>('/api/pub-stats/summary?' + chartParams());
	}

	async function loadTabContent() {
		if (tab === 'oa') {
			await tick();
			await loadChart();
		} else if (tab === 'publishers') {
			await loadPublishers();
		} else if (tab === 'journals') {
			await loadJournals();
		} else if (tab === 'labs') {
			await loadLabsTable();
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
		// Temporarily enable white background + legend, re-render, export, then restore
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

	async function loadPublishers() {
		const p = chartParams();
		if (search.trim()) p.set('search', search.trim());
		p.set('page', String(page));
		p.set('per_page', '50');
		const data = await api<{ total: number; page: number; pages: number; publishers: PublisherRow[] }>('/api/pub-stats/publishers?' + p);
		publishers = data.publishers;
		pubTotal = data.total;
		pubPages = data.pages;
	}

	async function loadJournals() {
		const p = chartParams();
		if (search.trim()) p.set('search', search.trim());
		p.set('page', String(page));
		p.set('per_page', '50');
		const data = await api<{ total: number; page: number; pages: number; journals: JournalRow[] }>('/api/pub-stats/journals?' + p);
		journals = data.journals;
		journalTotal = data.total;
		journalPages = data.pages;
	}

	async function loadLabsTable() {
		const p = chartParams();
		p.set('page', String(labPage));
		p.set('per_page', '50');
		const data = await api<{ total: number; page: number; pages: number; labs: LabRow[] }>('/api/pub-stats/labs?' + p);
		labRows = data.labs;
		labTotal = data.total;
		labPages = data.pages;
	}

	function onFilterChange() {
		page = 1; labPage = 1;
		syncUrl();
		refresh();
	}

	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			page = 1;
			syncUrl();
			loadTabContent();
		}, 400);
	}

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
		const uView = u.get('view');
		if (uView === 'publisher_detail' || uView === 'journal_detail') view = uView;
		const uTab = u.get('tab');
		if (uTab === 'oa' || uTab === 'publishers' || uTab === 'journals' || uTab === 'labs') tab = uTab;
		if (u.get('year')) selectedYears = u.get('year')!.split(',');
		if (u.get('lab_id')) selectedLabs = u.get('lab_id')!.split(',');
		if (u.get('oa_status')) selectedOa = u.get('oa_status')!.split(',');
		const pid = u.get('publisher_id');
		if (pid) { publisherId = parseInt(pid); publisherName = u.get('publisher_name') || ''; }
		const jid = u.get('journal_id');
		if (jid) { journalId = parseInt(jid); journalName = u.get('journal_name') || ''; }
		if (u.get('search')) search = u.get('search')!;
		if (u.get('page')) page = parseInt(u.get('page')!);
		if (u.get('lab_page')) labPage = parseInt(u.get('lab_page')!);

		// Load facets first, then apply default years if needed, then full refresh
		await loadFacets();
		if (!initialYearsApplied && selectedYears.length === 0 && yearOptions.length > 0) {
			// Pré-sélectionner les 5 dernières années
			const sorted = yearOptions.map((o) => o.value).sort().reverse();
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
	<FacetDropdown label="Années" allLabel="Toutes" options={yearOptions} bind:selected={selectedYears} onchange={onFilterChange} />
	<FacetDropdown label="Laboratoires" options={labOptions} searchable bind:selected={selectedLabs} onchange={onFilterChange} />
	<FacetDropdown label="Voies OA" options={oaOptions} bind:selected={selectedOa} onchange={onFilterChange} />
	{#if tab === 'publishers' || tab === 'journals'}
		<input type="text" placeholder="Rechercher..." bind:value={search} oninput={onSearchInput} />
	{/if}
	{#if tab !== 'oa'}
		<span class="count">
			{#if tab === 'publishers'}{pubTotal} éditeur{pubTotal > 1 ? 's' : ''}
			{:else if tab === 'journals'}{journalTotal} revue{journalTotal > 1 ? 's' : ''}
			{:else if tab === 'labs'}{labTotal} laboratoire{labTotal > 1 ? 's' : ''}
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
				<th class="num">Articles</th>
				<th class="num">Revues</th>
				<th style="min-width:100px">OA</th>
				<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
				<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
			</tr>
		</thead>
		<tbody>
			{#each publishers as r (r.publisher_id)}
				<tr>
					<td class="name-cell">
						<!-- svelte-ignore a11y_missing_attribute -->
						<a onclick={() => goTo('publisher_detail', { id: r.publisher_id, name: r.publisher_name })}>{r.publisher_name}</a>
					</td>
					<td class="num">{r.pub_count}</td>
					<td class="num num-small">{r.journal_count}</td>
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
	<Pagination page={page} pages={pubPages} onchange={(p) => { page = p; syncUrl(); loadPublishers(); window.scrollTo(0, 0); }} />
{/if}

<!-- Tab: Journals -->
{#if tab === 'journals'}
	<table class="data-table">
		<thead>
			<tr>
				<th>Revue</th>
				{#if !publisherId}<th>Éditeur</th>{/if}
				<th class="num">Articles</th>
				<th style="min-width:100px">OA</th>
				<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
				<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
			</tr>
		</thead>
		<tbody>
			{#each journals as r (r.journal_id)}
				<tr>
					<td class="name-cell">
						<!-- svelte-ignore a11y_missing_attribute -->
						<a onclick={() => goTo('journal_detail', { id: r.journal_id, name: r.journal_title })}>{r.journal_title}</a>
					</td>
					{#if !publisherId}
						<td class="name-cell num-small">{r.publisher_name || ''}</td>
					{/if}
					<td class="num">{r.pub_count}</td>
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
	<Pagination page={page} pages={journalPages} onchange={(p) => { page = p; syncUrl(); loadJournals(); window.scrollTo(0, 0); }} />
{/if}

<!-- Tab: Labs -->
{#if tab === 'labs'}
	{#if labRows.length > 0}
		<table class="data-table">
			<thead>
				<tr>
					<th>Laboratoire</th>
					<th class="num">Articles</th>
					<th style="min-width:100px">OA</th>
					<th class="num">Dia.</th><th class="num">Gold</th><th class="num">Hybrid</th><th class="num">Bronze</th>
					<th class="num">Green</th><th class="num">Closed</th><th class="num">Ind.</th>
				</tr>
			</thead>
			<tbody>
				{#each labRows as r (r.lab_id)}
					<tr>
						<td class="name-cell" title={r.lab_name}>
							<a href="{base}/laboratories/{r.lab_id}">{labDisplayName(r)}</a>
						</td>
						<td class="num">{r.pub_count}</td>
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
		<Pagination page={labPage} pages={labPages} onchange={(p) => { labPage = p; syncUrl(); loadLabsTable(); }} />
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

	.toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 16px;
		align-items: center;
		flex-wrap: wrap;
	}
	.toolbar input[type='text'] {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		background: white;
		width: 220px;
	}
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
	.count { margin-left: auto; color: var(--muted); font-size: 0.85rem; }

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

	.data-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
		margin-bottom: 4px;
	}
	.data-table th {
		text-align: left;
		padding: 8px 10px;
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		background: #fafaf8;
	}
	.data-table td {
		padding: 7px 10px;
		font-size: 0.95rem;
		border-bottom: 1px solid #f0efec;
	}
	.data-table tr:last-child td { border-bottom: none; }
	.data-table tr:hover td { background: #fafaf8; }

	.name-cell {
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.name-cell a { color: var(--accent); text-decoration: none; cursor: pointer; }
	.name-cell a:hover { text-decoration: underline; }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.num-small { font-size: 0.85rem; color: var(--muted); }

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

	.empty { text-align: center; padding: 40px; color: var(--muted); }
</style>
