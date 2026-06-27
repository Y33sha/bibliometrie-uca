<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { autofocus } from '$lib/actions/focus';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import { oaLabelsMap, docTypePlural, docTypeFamilies } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	Chart.register(...registerables, ChartDataLabels);

	// --- Types ---
	import type { components } from '$lib/api/schema';
	type PublisherRow = components['schemas']['PublisherStatsRow'];
	type JournalRow = components['schemas']['JournalStatsRow'];
	type LabRow = components['schemas']['LabStatsRow'];
	// Ligne partagée par les 3 onglets pour la ventilation OA (mêmes champs OaCounts).
	type OaRow = PublisherRow | JournalRow | LabRow;

	// --- State ---
	type View = 'top' | 'publisher_detail' | 'journal_detail';
	type Tab = 'oa' | 'publishers' | 'journals' | 'labs';

	let view: View = $state('top');
	let tab: Tab = $state('oa');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedDocTypes: string[] = $state([]); // défaut = famille « Publications » (cf. onMount)
	let search = $state('');
	let publisherId: number | null = $state(null);
	let publisherName = $state('');
	let journalId: number | null = $state(null);
	let journalName = $state('');
	let pubSort = $state('-pubs');
	let journalSort = $state('-pubs');
	let labSort = $state('-pubs');

	function toggleSort(current: string, field: string): string {
		if (current === field) return '-' + field;
		if (current === '-' + field) return field;
		return field;
	}

	let chartCanvas: HTMLCanvasElement | undefined = $state();
	let yearChart: Chart | null = null;
	let initialYearsApplied = false;

	// --- Pivot : axes de l'histogramme. Groupement primaire (abscisse) + comparaison empilée (facultative). ---
	let pivotSchema = $state<components['schemas']['PivotSchemaResponse'] | null>(null);
	let primaryBy = $state('oa_access'); // groupement primaire (abscisse) : une catégorie, jamais l'année
	let groupBy = $state('year'); // comparaison : série secondaire empilée (facultative), p. ex. l'année
	let chartMode = $state<'absolu' | 'part'>('absolu'); // part = empilement aplati à 100 %
	let legendItems: { label: string; color: string }[] = $state([]);
	// Le graphe par année est toujours le simple compte de publications (barres empilées). Le taux
	// d'accès ouvert n'est pas une mesure : il se lit via le découpage par accès. Pas de sélecteur de mesure.
	const measure = 'pub_count';

	// Dimensions graphables (groupables, faible cardinalité). Le groupement primaire est une catégorie
	// à analyser (accès, voie, type) ; un axe ordinal comme l'année ne se groupe pas, il se compare —
	// l'année est donc exclue du groupement et réservée à la comparaison.
	const graphableDims = $derived(
		pivotSchema ? pivotSchema.dimensions.filter((d) => d.groupable && d.cardinality === 'low') : []
	);
	const groupingDims = $derived(graphableDims.filter((d) => !d.ordinal));
	// Comparaison : toute dimension graphable (l'année comprise), moins celle prise comme primaire.
	const comparableDims = $derived(graphableDims.filter((d) => d.key !== primaryBy));

	// Barre de facettes dérivée du registre (cf. domain `applicable_facets`) : ensemble des dimensions
	// filtrables, moins un groupement catégoriel (l'année, ordinale, reste filtrable). Miroir TS de la règle G.
	const facetKeys = $derived.by(() => {
		if (!pivotSchema) return new Set(['year', 'lab', 'oa_voie', 'apc']);
		const grouped = new Set([primaryBy, groupBy].filter(Boolean));
		const out = new Set<string>();
		for (const d of pivotSchema.dimensions) {
			if (!d.filterable) continue;
			if (grouped.has(d.key) && !d.ordinal) continue;
			out.add(d.key);
		}
		return out;
	});

	// Couleurs / libellés / ordre par dimension de découpage. Les valeurs OA réutilisent les
	// variables CSS existantes ; les autres dimensions piochent dans une palette catégorielle.
	const OA_VOIE_ORDER = ['diamond', 'gold', 'hybrid', 'bronze', 'green', 'embargoed', 'closed', 'unknown'];
	const OA_ACCESS_ORDER = ['ouvert', 'embargo', 'ferme', 'indetermine'];
	const OA_ACCESS_LABELS: Record<string, string> = {
		ouvert: 'Ouvert', embargo: 'Sous embargo', ferme: 'Fermé', indetermine: 'Indéterminé',
	};
	const OA_ACCESS_VAR: Record<string, string> = {
		ouvert: '--green', embargo: '--embargoed', ferme: '--closed', indetermine: '--unknown',
	};
	const PALETTE = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#b07aa1', '#76b7b2', '#ff9da7', '#9c755f', '#bab0ac', '#edc948'];

	function dimLabel(dim: string, value: string): string {
		if (dim === 'oa_access') return OA_ACCESS_LABELS[value] ?? value;
		if (dim === 'oa_voie') return oaLabelsMap[value] ?? value;
		if (dim === 'doc_type_family')
			return docTypeFamilies.find((f) => f.key === value)?.label ?? value;
		return value;
	}
	function dimColor(dim: string, value: string, idx: number, cs: CSSStyleDeclaration): string {
		if (dim === 'oa_voie') return cs.getPropertyValue('--' + value).trim() || PALETTE[idx % PALETTE.length];
		if (dim === 'oa_access') return cs.getPropertyValue(OA_ACCESS_VAR[value] ?? '').trim() || PALETTE[idx % PALETTE.length];
		return PALETTE[idx % PALETTE.length];
	}
	function orderedValues(dim: string, rows: Record<string, unknown>[]): string[] {
		const present = rows.map((r) => String(r[dim]));
		if (dim === 'year') return [...new Set(present)].sort((a, b) => Number(a) - Number(b));
		if (dim === 'oa_access') return OA_ACCESS_ORDER.filter((v) => present.includes(v));
		if (dim === 'oa_voie') return OA_VOIE_ORDER.filter((v) => present.includes(v));
		if (dim === 'doc_type_family')
			return docTypeFamilies.map((f) => f.key).filter((k) => present.includes(k));
		// Sinon : valeurs distinctes triées par total décroissant.
		const totals = new Map<string, number>();
		for (const r of rows) {
			const v = String(r[dim]);
			totals.set(v, (totals.get(v) ?? 0) + Number(r.value ?? 0));
		}
		return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([v]) => v);
	}

	function onPrimaryChange() {
		// Le groupement primaire ne peut pas être aussi la comparaison.
		if (groupBy === primaryBy) groupBy = '';
		onAxisChange(primaryBy);
	}
	function onGroupByChange() {
		onAxisChange(groupBy);
	}
	function onAxisChange(dim: string) {
		// Grouper par une dimension filtrable efface son filtre actif (sinon il resterait, caché).
		const cleared = dim === 'oa_voie' && selectedOa.length > 0;
		if (cleared) selectedOa = [];
		syncUrl();
		if (cleared) refresh();
		else loadChart();
	}

	// --- Filter params (shared by all loaders) ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		if (publisherId) p.set('publisher_id', String(publisherId));
		if (journalId) p.set('journal_id', String(journalId));
		return p;
	}

	// --- Composables: paginated tables ---
	const pubFetch = usePaginatedFetch<PublisherRow>({
		endpoint: '/api/stats/publishers',
		itemsKey: 'publishers',
		perPage: 50,
		apiKey: 'stats-publishers',
		buildParams: () => {
			const p = chartParams();
			if (search.trim()) p.set('search', search.trim());
			p.set('sort', pubSort);
			return p;
		},
	});

	const journalFetch = usePaginatedFetch<JournalRow>({
		endpoint: '/api/stats/journals',
		itemsKey: 'journals',
		perPage: 50,
		apiKey: 'stats-journals',
		buildParams: () => {
			const p = chartParams();
			if (search.trim()) p.set('search', search.trim());
			p.set('sort', journalSort);
			return p;
		},
	});

	const labFetch = usePaginatedFetch<LabRow>({
		endpoint: '/api/stats/labs',
		itemsKey: 'labs',
		perPage: 50,
		apiKey: 'stats-labs',
		buildParams: () => {
			const p = chartParams();
			p.set('sort', labSort);
			return p;
		},
	});

	// --- Composable: facets ---
	const facets = useFacets<'years' | 'labs' | 'oa' | 'apc' | 'docTypes'>({
		endpoint: '/api/stats/facets',
		apiKey: 'stats-facets',
		buildParams: chartParams,
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			labs: { type: 'labeled', apiKey: 'labs' },
			oa: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			apc: { type: 'passthrough', apiKey: 'apc' },
			docTypes: { type: 'label_map', apiKey: 'doc_types', labels: docTypePlural },
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
			selectedDocTypes: { type: 'string_array', urlKey: 'doc_type' },
			publisherId: { type: 'single', urlKey: 'publisher_id' },
				journalId: { type: 'single', urlKey: 'journal_id' },
				search: { type: 'single', urlKey: 'search' },
			primaryBy: { type: 'single', urlKey: 'axis', defaultValue: 'oa_access' },
				groupBy: { type: 'single', urlKey: 'group_by', defaultValue: 'year' },
				chartMode: { type: 'single', urlKey: 'mode', defaultValue: 'absolu' },
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
			selectedDocTypes,
			publisherId: publisherId ? String(publisherId) : '',
			journalId: journalId ? String(journalId) : '',
			search,
			primaryBy,
			groupBy,
			chartMode,
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
		if (publisherId) { p.set('publisher_id', String(publisherId)); }
		if (journalId) { p.set('journal_id', String(journalId)); }
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
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
		await Promise.all([loadTabContent(), facets.load()]);
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
		const p = chartParams();
		p.set('measure', measure);
		p.set('group', primaryBy);
		const comparison = groupBy && groupBy !== primaryBy ? groupBy : '';
		if (comparison) p.set('group2', comparison);
		const res = await api<{ rows: Record<string, unknown>[] }>('/api/stats/pivot?' + p);
		await tick();
		if (yearChart) yearChart.destroy();
		const rows = res.rows;
		if (!rows.length || !chartCanvas) { yearChart = null; legendItems = []; return; }

		// La comparaison occupe l'abscisse (on compare le long de l'axe des x ; l'année y va
		// naturellement) ; le groupement est l'empilement (la catégorie lue dans chaque barre). Sans
		// comparaison, le groupement passe en abscisse, en barres simples.
		const xDim = comparison || primaryBy;
		const stackDim = comparison ? primaryBy : '';
		const cs = getComputedStyle(document.documentElement);
		const cats = orderedValues(xDim, rows); // valeurs en abscisse
		const labels = cats.map((c) => dimLabel(xDim, c));
		const series = stackDim ? orderedValues(stackDim, rows) : ['__all__'];
		const datasets = series.map((sv, i) => ({
			label: stackDim ? dimLabel(stackDim, sv) : 'Publications',
			data: cats.map((cv) => {
				const row = rows.find(
					(r) => String(r[xDim]) === cv && (!stackDim || String(r[stackDim]) === sv)
				);
				return row ? Number(row.value) : 0;
			}),
			backgroundColor: stackDim ? dimColor(stackDim, sv, i, cs) : cs.getPropertyValue('--accent').trim(),
			barPercentage: 0.5,
			categoryPercentage: 0.7
		}));
		legendItems = datasets.map((d) => ({ label: d.label, color: d.backgroundColor }));

		// Mode « part » : aplatir chaque colonne (abscisse) à 100 % en remplaçant les comptes par leur
		// proportion. N'a de sens qu'avec un empilement ; sans comparaison, on reste en absolu.
		const part = chartMode === 'part' && !!stackDim;
		if (part) {
			const totals = cats.map((_, ci) => datasets.reduce((s, d) => s + ((d.data[ci] as number) || 0), 0));
			for (const d of datasets) d.data = d.data.map((c, ci) => (totals[ci] ? ((c as number) / totals[ci]) * 100 : 0));
		}

		yearChart = new Chart(chartCanvas, {
			type: 'bar',
			plugins: [whiteBgPlugin],
			data: {
				labels,
				datasets
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
										return part
											? `${ctx.dataset.label} : ${pct}%`
											: `${ctx.dataset.label} : ${val} (${pct}%)`;
									},
									afterBody: (items) => {
										const total = items[0].chart.data.datasets.reduce((s, ds) => s + ((ds.data[items[0].dataIndex] as number) || 0), 0);
										return part ? [] : `Total : ${total}`;
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
					y: part
						? { stacked: true, min: 0, max: 100, ticks: { font: { size: 13 }, callback: (v: string | number) => v + ' %' } }
						: { stacked: true, beginAtZero: true, ticks: { font: { size: 13 }, precision: 0 } }
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
		if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
		if (restored.publisherId) {
			publisherId = parseInt(restored.publisherId as string);
			try {
				const pub = await api<{id: number, name: string}>(`/api/publishers/${publisherId}`);
				publisherName = pub.name;
			} catch { publisherName = `#${publisherId}`; }
		}
		if (restored.journalId) {
			journalId = parseInt(restored.journalId as string);
			try {
				const j = await api<{id: number, title: string}>(`/api/journals/${journalId}`);
				journalName = j.title;
			} catch { journalName = `#${journalId}`; }
		}
		if (restored.search) search = restored.search as string;
		if (restored.primaryBy !== undefined) primaryBy = restored.primaryBy as string;
		if (restored.groupBy !== undefined) groupBy = restored.groupBy as string;
		if (restored.chartMode !== undefined) chartMode = restored.chartMode as 'absolu' | 'part';
		if (restored.page) pubFetch.page = restored.page as number;
		if (restored.labPage) labFetch.page = restored.labPage as number;

		// Vocabulaire du pivot : dimensions graphables (faible cardinalité, hors l'axe année)
		// proposées au sélecteur de découpage. Ajouter une dimension au registre l'y fait apparaître.
		try {
			pivotSchema = await api<components['schemas']['PivotSchemaResponse']>('/api/stats/pivot/schema');
		} catch { pivotSchema = null; }

		// Défaut du type de document : la famille « Publications » (même base que la liste des
		// publications), sauf si l'URL en a restauré une sélection.
		if (selectedDocTypes.length === 0) {
			selectedDocTypes = [...(docTypeFamilies.find((f) => f.key === 'publications')?.types ?? [])];
		}

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

<!-- Cellule de ventilation OA (barre de répartition), partagée par les onglets éditeurs/revues/labos.
     Le détail chiffré par voie relève du pivot (onglet Open Access) / du drill-down, pas des tables. -->
{#snippet oaBreakdownCells(r: OaRow)}
	<td>
		<div class="oa-bar">
			<span class="diamond" style="width:{oaPercent(r.diamond, r.pub_count)}"></span>
			<span class="gold" style="width:{oaPercent(r.gold, r.pub_count)}"></span>
			<span class="hybrid" style="width:{oaPercent(r.hybrid, r.pub_count)}"></span>
			<span class="bronze" style="width:{oaPercent(r.bronze, r.pub_count)}"></span>
			<span class="green" style="width:{oaPercent(r.green, r.pub_count)}"></span>
			<span class="embargoed" style="width:{oaPercent(r.embargoed, r.pub_count)}"></span><span class="closed" style="width:{oaPercent(r.closed, r.pub_count)}"></span>
			<span class="unknown" style="width:{oaPercent(r.unknown, r.pub_count)}"></span>
		</div>
	</td>
{/snippet}

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

<!-- Ligne 1 : contrôles du pivot + onglets -->
<div class="toolbar controls-row">
	{#if tab === 'oa' && pivotSchema}
		<label class="groupby">
			Grouper par&nbsp;:
			<select bind:value={primaryBy} onchange={onPrimaryChange}>
				{#each groupingDims as d (d.key)}
					<option value={d.key}>{d.label}</option>
				{/each}
			</select>
		</label>
		<label class="groupby">
			Comparer par&nbsp;:
			<select bind:value={groupBy} onchange={onGroupByChange}>
				<option value="">Aucun</option>
				{#each comparableDims as d (d.key)}
					<option value={d.key}>{d.label}</option>
				{/each}
			</select>
		</label>
	{/if}
	{#if tab === 'oa' && groupBy && groupBy !== primaryBy}
		<label class="groupby">
			<input type="checkbox" checked={chartMode === 'part'} onchange={(e) => { chartMode = e.currentTarget.checked ? 'part' : 'absolu'; syncUrl(); loadChart(); }} />
			Part&nbsp;(%)
		</label>
	{/if}
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
	{#if tab === 'publishers' || tab === 'journals'}
		<input type="search" placeholder="Rechercher..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
	{/if}
	{#if tab !== 'oa'}
		<span class="count">
			{#if tab === 'publishers'}{pubFetch.total} éditeur{pubFetch.total > 1 ? 's' : ''}
			{:else if tab === 'journals'}{journalFetch.total} revue{journalFetch.total > 1 ? 's' : ''}
			{:else if tab === 'labs'}{labFetch.total} laboratoire{labFetch.total > 1 ? 's' : ''}
			{/if}
		</span>
	{/if}
	<a class="pub-link" href={pubsUrl}>Voir les publications &rarr;</a>
</div>
<!-- Ligne 2 : filtres à facettes (dérivés du registre sur l'onglet OA ; inchangés sur les
     onglets-tables tant qu'ils ne sont pas migrés au pivot) -->
<div class="toolbar facets-row">
	{#if tab !== 'oa' || facetKeys.has('year')}
		<FacetDropdown label="Années" allLabel="Toutes" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
	{/if}
	{#if tab !== 'oa' || facetKeys.has('lab')}
		<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onFilterChange} />
	{/if}
	{#if tab !== 'oa' || facetKeys.has('oa_voie')}
		<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />
	{/if}
	{#if tab !== 'oa' || facetKeys.has('doc_type')}
		<FacetDropdown label="Types" options={facets.options.docTypes} groups={docTypeFamilies.map((f) => ({ label: f.label, values: f.types }))} bind:selected={selectedDocTypes} onchange={onFilterChange} />
	{/if}
	{#if tab !== 'oa' || facetKeys.has('apc')}
		<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
	{/if}
</div>

<!-- Tab: Open Access (chart) -->
{#if tab === 'oa'}
	{#if legendItems.length > 1}
		<div class="legend">
			{#each legendItems as item (item.label)}
				<span><span class="legend-dot" style="background:{item.color}"></span>{item.label}</span>
			{/each}
		</div>
	{/if}
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
				<th class="sortable" class:active={pubSort === 'name' || pubSort === '-name'} onclick={() => { pubSort = toggleSort(pubSort, 'name'); pubFetch.page = 1; pubFetch.load(); }}>Éditeur {pubSort === 'name' ? '▲' : pubSort === '-name' ? '▼' : ''}</th>
				<th class="num">Revues</th>
				<th class="num sortable" class:active={pubSort === 'pubs' || pubSort === '-pubs'} onclick={() => { pubSort = toggleSort(pubSort, 'pubs'); pubFetch.page = 1; pubFetch.load(); }}>Articles {pubSort === 'pubs' ? '▲' : pubSort === '-pubs' ? '▼' : ''}</th>
				<th class="num sortable" class:active={pubSort === 'apc' || pubSort === '-apc'} onclick={() => { pubSort = toggleSort(pubSort, 'apc'); pubFetch.page = 1; pubFetch.load(); }}>APC UCA {pubSort === 'apc' ? '▲' : pubSort === '-apc' ? '▼' : ''}</th>
				<th style="min-width:100px">OA</th>
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
					{@render oaBreakdownCells(r)}
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
				<th class="sortable" class:active={journalSort === 'name' || journalSort === '-name'} onclick={() => { journalSort = toggleSort(journalSort, 'name'); journalFetch.page = 1; journalFetch.load(); }}>Revue {journalSort === 'name' ? '▲' : journalSort === '-name' ? '▼' : ''}</th>
				{#if !publisherId}<th>Éditeur</th>{/if}
				<th class="num sortable" class:active={journalSort === 'pubs' || journalSort === '-pubs'} onclick={() => { journalSort = toggleSort(journalSort, 'pubs'); journalFetch.page = 1; journalFetch.load(); }}>Articles {journalSort === 'pubs' ? '▲' : journalSort === '-pubs' ? '▼' : ''}</th>
				<th class="num sortable" class:active={journalSort === 'apc' || journalSort === '-apc'} onclick={() => { journalSort = toggleSort(journalSort, 'apc'); journalFetch.page = 1; journalFetch.load(); }}>APC UCA {journalSort === 'apc' ? '▲' : journalSort === '-apc' ? '▼' : ''}</th>
				<th style="min-width:100px">OA</th>
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
					{@render oaBreakdownCells(r)}
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
					<th class="sortable" class:active={labSort === 'name' || labSort === '-name'} onclick={() => { labSort = toggleSort(labSort, 'name'); labFetch.page = 1; labFetch.load(); }}>Laboratoire {labSort === 'name' ? '▲' : labSort === '-name' ? '▼' : ''}</th>
					<th class="num sortable" class:active={labSort === 'pubs' || labSort === '-pubs'} onclick={() => { labSort = toggleSort(labSort, 'pubs'); labFetch.page = 1; labFetch.load(); }}>Articles {labSort === 'pubs' ? '▲' : labSort === '-pubs' ? '▼' : ''}</th>
					<th class="num sortable" class:active={labSort === 'apc' || labSort === '-apc'} onclick={() => { labSort = toggleSort(labSort, 'apc'); labFetch.page = 1; labFetch.load(); }}>APC UCA {labSort === 'apc' ? '▲' : labSort === '-apc' ? '▼' : ''}</th>
					<th style="min-width:100px">OA</th>
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
						{@render oaBreakdownCells(r)}
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
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}
	.facets-row { margin-bottom: 16px; }
	.toolbar input[type='search'] { width: 220px; }
	.groupby {
		font-size: 0.9rem;
		color: var(--muted);
		white-space: nowrap;
	}
	.groupby select {
		font-family: inherit;
		font-size: 0.9rem;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: white;
	}
	.tab-group { display: flex; gap: 0; }
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
	th.sortable { cursor: pointer; user-select: none; }
	th.sortable:hover { color: var(--accent); }
	th.sortable.active { color: var(--accent); }

	.name-cell {
		font-size: 0.9em;
		word-break: break-word;
	}
	.name-cell a { color: var(--accent); text-decoration: none; cursor: pointer; }
	.name-cell a:hover { text-decoration: underline; }
	.num-small { font-size: 0.85rem; color: var(--muted); }
	.apc-cell { font-size: 0.85rem; color: var(--success); white-space: nowrap; }

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
	.oa-bar .embargoed { background: var(--embargoed); }
	.oa-bar .closed { background: var(--closed); }
	.oa-bar .unknown { background: var(--unknown); }

</style>
