<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import { oaLabelsMap, docTypePlural, docTypeFamilies } from '$lib/labels';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	Chart.register(...registerables, ChartDataLabels);

	// --- Types ---
	import type { components } from '$lib/api/schema';
	// --- State ---
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedDocTypes: string[] = $state([]); // défaut = famille « Publications » (cf. onMount)

	let chartCanvas: HTMLCanvasElement | undefined = $state();
	let yearChart: Chart | null = null;
	let initialYearsApplied = false;

	// --- Pivot : axes de l'histogramme. Groupement primaire (abscisse) + comparaison empilée (facultative). ---
	let pivotSchema = $state<components['schemas']['PivotSchemaResponse'] | null>(null);
	let primaryBy = $state('oa_access'); // groupement primaire (abscisse) : une catégorie, jamais l'année
	let groupBy = $state('year'); // comparaison : série secondaire empilée (facultative), p. ex. l'année
	let chartMode = $state<'absolu' | 'part'>('absolu'); // part = empilement aplati à 100 %
	let chartPage = $state(1); // page de l'axe de comparaison à forte cardinalité (laboratoires)
	let chartCatTotal = $state(0); // total des valeurs sur cet axe (0 si faible cardinalité)
	const CHART_PAGE_SIZE = 10;
	let legendItems: { label: string; color: string }[] = $state([]);
	// Le graphe par année est toujours le simple compte de publications (barres empilées). Le taux
	// d'accès ouvert n'est pas une mesure : il se lit via le découpage par accès. Pas de sélecteur de mesure.
	const measure = 'pub_count';

	// Groupement primaire : catégories à analyser, faible cardinalité, non ordinales (accès, voie,
	// type). L'année ne se groupe pas (elle se compare) ; le laboratoire non plus (forte cardinalité).
	const groupingDims = $derived(
		pivotSchema
			? pivotSchema.dimensions.filter((d) => d.groupable && d.cardinality === 'low' && !d.ordinal)
			: []
	);
	// Comparaison : toute dimension groupable (l'année, les catégories, le laboratoire à forte
	// cardinalité), moins celle déjà prise comme groupement primaire.
	const comparableDims = $derived(
		pivotSchema ? pivotSchema.dimensions.filter((d) => d.groupable && d.key !== primaryBy) : []
	);

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

	function dimCard(dim: string): string {
		return pivotSchema?.dimensions.find((d) => d.key === dim)?.cardinality ?? 'low';
	}
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
		chartPage = 1; // changer d'axe repart de la première page
		// Comparer/grouper par une dimension filtrable efface son filtre actif (sinon il resterait, caché).
		let cleared = false;
		if (dim === 'oa_voie' && selectedOa.length > 0) { selectedOa = []; cleared = true; }
		if (dim === 'lab' && selectedLabs.length > 0) { selectedLabs = []; cleared = true; }
		syncUrl();
		if (cleared) refresh();
		else loadChart();
	}

	// --- Filter params (partagés par le graphe et les facettes) ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		return p;
	}

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
			selectedYears: { type: 'string_array', urlKey: 'year' },
			selectedLabs: { type: 'string_array', urlKey: 'lab_id' },
			selectedOa: { type: 'string_array', urlKey: 'oa_status' },
			selectedApc: { type: 'string_array', urlKey: 'has_apc' },
			selectedDocTypes: { type: 'string_array', urlKey: 'doc_type' },
			primaryBy: { type: 'single', urlKey: 'axis', defaultValue: 'oa_access' },
				groupBy: { type: 'single', urlKey: 'group_by', defaultValue: 'year' },
				chartMode: { type: 'single', urlKey: 'mode', defaultValue: 'absolu' },
				chartPage: { type: 'page', urlKey: 'chart_page' },
		},
	});

	function syncUrl() {
		urlFilters.syncUrl(() => ({
			selectedYears,
			selectedLabs,
			selectedOa,
			selectedApc,
			selectedDocTypes,
			primaryBy,
			groupBy,
			chartMode,
			chartPage,
		}));
	}

	// --- Derived: publications link ---
	const pubsUrl = $derived.by(() => {
		const p = new URLSearchParams();
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		return base + '/publications?' + p.toString();
	});

	// --- Data loading ---
	async function refresh() {
		await Promise.all([loadChart(), facets.load()]);
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

		// Abscisse : à forte cardinalité (laboratoire), on pagine les valeurs (triées par total
		// décroissant) au lieu de les tronquer — l'axe reste lisible, le détail reste atteignable.
		const highCard = dimCard(xDim) === 'high';
		const allCats = orderedValues(xDim, rows);
		chartCatTotal = highCard ? allCats.length : 0;
		if (highCard && (chartPage - 1) * CHART_PAGE_SIZE >= allCats.length) chartPage = 1;
		const cats = highCard
			? allCats.slice((chartPage - 1) * CHART_PAGE_SIZE, chartPage * CHART_PAGE_SIZE)
			: allCats;
		const labels = cats.map((c) => dimLabel(xDim, c));

		const cell = (cv: string, sv: string) => {
			const row = rows.find((r) => String(r[xDim]) === cv && (!stackDim || String(r[stackDim]) === sv));
			return row ? Number(row.value) : 0;
		};
		const series = stackDim ? orderedValues(stackDim, rows) : ['__all__'];
		const datasets = series.map((sv, i) => ({
			label: stackDim ? dimLabel(stackDim, sv) : 'Publications',
			data: cats.map((cv) => cell(cv, sv)),
			backgroundColor: stackDim ? dimColor(stackDim, sv, i, cs) : cs.getPropertyValue('--accent').trim(),
			barPercentage: 0.85,
			categoryPercentage: 0.7
		}));
		legendItems = datasets.map((d) => ({ label: d.label, color: d.backgroundColor }));

		// Mode « part » : aplatir chaque colonne (abscisse) à 100 % en remplaçant les comptes par leur
		// proportion. N'a de sens qu'avec un empilement ; sans comparaison, on reste en absolu.
		const part = chartMode === 'part' && !!stackDim;
		if (part) {
			const totals = labels.map((_, ci) => datasets.reduce((s, d) => s + ((d.data[ci] as number) || 0), 0));
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
					indexAxis: highCard ? 'y' : 'x',
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
					[highCard ? 'y' : 'x']: { stacked: true, grid: { display: false }, ticks: { font: { size: highCard ? 12 : 14 } } },
					[highCard ? 'x' : 'y']: part
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
		syncUrl();
		refresh();
	}

	onMount(async () => {
		// Restore state from URL params
		const u = new URLSearchParams(window.location.search);
		const restored = urlFilters.restoreFromUrl(u);
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
		if (restored.primaryBy !== undefined) primaryBy = restored.primaryBy as string;
		if (restored.groupBy !== undefined) groupBy = restored.groupBy as string;
		if (restored.chartMode !== undefined) chartMode = restored.chartMode as 'absolu' | 'part';
		if (restored.chartPage) chartPage = restored.chartPage as number;

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

<!-- Ligne 1 : contrôles du pivot + onglets -->
<div class="toolbar controls-row">
	{#if pivotSchema}
		<label class="groupby">
			Grouper par&nbsp;:
			<select bind:value={primaryBy} onchange={onPrimaryChange}>
				{#each groupingDims as d (d.key)}
					<option value={d.key}>{d.label}</option>
				{/each}
			</select>
		</label>
		<!-- {#key primaryBy} : recrée le select quand le groupement change, pour que sa valeur
		     affichée reste synchronisée avec `groupBy` malgré le recalcul des options. -->
		{#key primaryBy}
			<label class="groupby">
				Comparer par&nbsp;:
				<select bind:value={groupBy} onchange={onGroupByChange}>
					<option value="">Aucun</option>
					{#each comparableDims as d (d.key)}
						<option value={d.key}>{d.label}</option>
					{/each}
				</select>
			</label>
		{/key}
	{/if}
	{#if groupBy && groupBy !== primaryBy}
		<label class="groupby">
			<input type="checkbox" checked={chartMode === 'part'} onchange={(e) => { chartMode = e.currentTarget.checked ? 'part' : 'absolu'; syncUrl(); loadChart(); }} />
			Part&nbsp;(%)
		</label>
	{/if}
	<a class="pub-link" href={pubsUrl}>Voir les publications &rarr;</a>
</div>
<!-- Ligne 2 : filtres à facettes, dérivés du registre (cf. domain `applicable_facets`, règle G). -->
<div class="toolbar facets-row">
	{#if facetKeys.has('year')}
		<FacetDropdown label="Années" allLabel="Toutes" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('lab')}
		<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('oa_voie')}
		<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('doc_type')}
		<FacetDropdown label="Types" options={facets.options.docTypes} groups={docTypeFamilies.map((f) => ({ label: f.label, values: f.types }))} bind:selected={selectedDocTypes} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('apc')}
		<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
	{/if}
</div>

<!-- Histogramme du pivot -->
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
{#if chartCatTotal > CHART_PAGE_SIZE}
	<Pagination
		page={chartPage}
		pages={Math.ceil(chartCatTotal / CHART_PAGE_SIZE)}
		onchange={(p) => { chartPage = p; syncUrl(); loadChart(); }}
	/>
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

</style>
