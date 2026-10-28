<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { onMount, tick } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, latestRequest } from '#lib/api/index.js';
	import { Chart } from '#lib/components/charts/chart.js';
	import { cssColor, fontSize } from '#lib/components/charts/cssVar.js';
	import { readableOn } from '#lib/components/charts/contrast.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationFilterBar from '#lib/components/PublicationFilterBar.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import CollaborationMap from './CollaborationMap.svelte';
	import { defaultYears } from '#lib/defaultYears.js';
	import { orderedPivotValues, pivotValueColor, pivotValueLabel } from '#lib/pivotValues.js';
	import { paramsToQuery } from '#lib/utils.js';
	import { publicationsDocTypes } from '#lib/labels.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import {
		appendFilterParams,
		clearValue,
		ignoredFilters,
		initialValues,
		restoreValues,
		transferParams,
		urlFilterDefs,
		urlState,
	} from '#lib/filterRegistry.js';
	import { publicationFilters } from '#lib/publicationFilters.js';
	import { usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';

	// Chaque changement de filtre relance le graphe : la requête précédente, encore en vol, est annulée.
	const pivotRequest = latestRequest();

	// --- Types ---
	import type { components } from '#lib/api/schema.js';
	// --- State ---
	// Filtres de la liste des publications, hors contexte. La famille « Publications » est présélectionnée (cf. onMount).
	const FILTERS = publicationFilters({ kind: 'all' });
	let values = $state(initialValues(FILTERS));

	let chartCanvas: HTMLCanvasElement | undefined = $state();
	let yearChart: Chart | null = null;
	// Dernières lignes du pivot renvoyées par l'API : source du tracé, réutilisée par les contrôles d'affichage (mode, tri, page) qui re-tracent sans re-solliciter le serveur.
	let pivotRows: Record<string, unknown>[] = [];

	// --- Pivot : un indicateur (mesure et ventilation) + un axe de comparaison facultatif. ---
	let pivotSchema = $state<components['schemas']['PivotSchemaResponse'] | null>(null);
	let indicator = $state('doc_type_grouped');
	let groupBy = $state('year'); // comparaison : série secondaire empilée (facultative), p. ex. l'année
	let chartMode = $state<'absolu' | 'part'>('absolu'); // part = empilement aplati à 100 %
	let chartPage = $state(1); // page de l'axe de comparaison à forte cardinalité (laboratoires)
	let chartCatTotal = $state(0); // total des valeurs sur cet axe (0 si faible cardinalité)
	// Tri de l'axe de comparaison. '' = ordre par défaut (total décroissant) ; sinon la valeur d'une série empilée (p. ex. 'ouvert') : les catégories sont classées par la part de cette série.
	let chartSort = $state('');
	let chartSortDir = $state<'desc' | 'asc'>('desc');
	// Séries proposées au sélecteur de tri, dérivées de l'empilement courant (mises à jour au tracé).
	let sortableSeries = $state<{ value: string; label: string }[]>([]);
	const CHART_PAGE_SIZE = 10;
	let legendItems: { label: string; color: string }[] = $state([]);
	// Données du graphique pour les lecteurs d'écran : une ligne par catégorie de l'abscisse, une colonne par série, en valeurs absolues.
	let chartTable = $state<{ columns: string[]; rows: { label: string; values: string[] }[] } | null>(null);
	const indicatorDef = $derived(pivotSchema?.indicators.find((i) => i.key === indicator));
	// Dimension empilée dans chaque barre, imposée par l'indicateur.
	const breakdown = $derived(indicatorDef?.breakdown ?? '');
	// Valeur affichée d'une barre ou d'un total : entier pour un nombre de publications, montant arrondi à l'euro suivi de l'unité pour une somme.
	function formatValue(value: number): string {
		const unit = indicatorDef?.unit;
		const text = Math.round(value).toLocaleString('fr-FR');
		return unit ? `${text} ${unit}` : text;
	}

	// Entrée spéciale du sélecteur d'indicateur : remplace l'histogramme par la carte des collaborations internationales. Ce n'est pas une dimension du pivot, d'où les gardes dédiées.
	const COLLAB_VIEW = 'collaborations';
	const isCollab = $derived(indicator === COLLAB_VIEW);

	// Comparaison : les dimensions déclarées `comparable` (l'année et les entités à forte cardinalité : laboratoire, éditeur, revue, organisation partenaire).
	const comparableDims = $derived(
		pivotSchema ? pivotSchema.dimensions.filter((d) => d.comparable) : []
	);

	function dimCard(dim: string): string {
		return pivotSchema?.dimensions.find((d) => d.key === dim)?.cardinality ?? 'low';
	}
	// Libellés servis par la facette, y compris celui des publications sans licence.
	const licenseLabel = (value: string) => facets.options.license?.find((o) => o.value === value)?.text;
	const dimLabel = (dim: string, value: string) => pivotValueLabel(dim, value, licenseLabel);

	// Ordonne les catégories de l'axe `dim` par la part de la série `seriesValue` (lue sur `stackDim`) dans chaque catégorie : numérateur = valeur de cette série, dénominateur = total de la catégorie. Trier sur la part (et non la valeur brute) donne le classement « du plus au moins <série> » indépendamment de la taille de la catégorie, cohérent avec la vue en pourcentage.
	function orderBySeriesShare(
		dim: string,
		stackDim: string,
		seriesValue: string,
		dir: 'desc' | 'asc',
		rows: Record<string, unknown>[],
	): string[] {
		const num = new Map<string, number>();
		const den = new Map<string, number>();
		for (const r of rows) {
			const cat = String(r[dim]);
			const val = Number(r.value ?? 0);
			den.set(cat, (den.get(cat) ?? 0) + val);
			if (String(r[stackDim]) === seriesValue) num.set(cat, (num.get(cat) ?? 0) + val);
		}
		const share = (cat: string) => {
			const d = den.get(cat) ?? 0;
			return d ? (num.get(cat) ?? 0) / d : 0;
		};
		const sign = dir === 'desc' ? -1 : 1;
		return [...den.keys()].sort((a, b) => sign * (share(a) - share(b)));
	}

	function onAxisChange() {
		chartPage = 1; // changer d'axe repart de la première page
		syncUrl();
		loadChart();
	}

	// --- Filter params (partagés par le graphe et les facettes) ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		appendFilterParams(FILTERS, values, p);
		return p;
	}

	// --- Composable: facets ---
	const facets = usePublicationFacets({
		filters: FILTERS,
		apiKey: () => 'stats-facets',
		buildParams: chartParams,
	});

	// --- Composable: URL filters ---
	const urlFilters = useUrlFilters({
		basePath: '/stats',
		filters: {
			...urlFilterDefs(FILTERS),
			// La page a ses années par défaut : « toutes les années » s'écrit donc dans l'URL.
			years: { type: 'single', urlKey: 'year', defaultValue: '' },
			indicator: { type: 'single', urlKey: 'indicator', defaultValue: 'doc_type_grouped' },
				groupBy: { type: 'single', urlKey: 'group_by', defaultValue: 'year' },
				chartMode: { type: 'single', urlKey: 'mode', defaultValue: 'absolu' },
				chartPage: { type: 'page', urlKey: 'chart_page' },
				chartSort: { type: 'single', urlKey: 'sort', defaultValue: '' },
				chartSortDir: { type: 'single', urlKey: 'sort_dir', defaultValue: 'desc' },
		},
	});

	function syncUrl() {
		urlFilters.syncUrl(() => ({
			...urlState(FILTERS, values),
			indicator,
			groupBy,
			chartMode,
			chartPage,
			chartSort,
			chartSortDir,
		}));
	}

	// --- Derived: publications link ---
	// Les filtres passent tels quels : les deux pages partagent le registre des filtres.
	const pubsUrl = $derived(resolve('publications') + '?' + paramsToQuery(transferParams(FILTERS, values)));

	// Filtres courants sérialisés : pilotent la carte des collaborations, qui suit les mêmes filtres que le graphe mais ignore l'axe, le mode et la pagination.
	const collabParams = $derived(chartParams().toString());

	// --- Data loading ---
	async function refresh() {
		await Promise.all([loadChart(), facets.load()]);
	}

	// Récupère les lignes du pivot depuis l'API, puis délègue le tracé. La requête dépend seulement des filtres, de l'indicateur et de la comparaison ; les contrôles d'affichage (mode, tri, page) re-tracent depuis ce cache sans nouvel appel réseau (voir `renderChart`).
	async function loadChart() {
		// Vue Collaborations : la carte se dessine seule (composant dédié). On détruit l'histogramme éventuel et on n'interroge pas le pivot (`collaborations` n'est pas une dimension valide).
		if (isCollab) {
			if (yearChart) {
				yearChart.destroy();
				yearChart = null;
			}
			legendItems = [];
			return;
		}
		const p = chartParams();
		p.set('indicator', indicator);
		if (groupBy) p.set('compare', groupBy);
		const res = await pivotRequest<{ rows: Record<string, unknown>[] }>('/api/stats/pivot?' + p);
		pivotRows = res.rows;
		await tick();
		renderChart();
	}

	// Trace le graphe à partir des dernières lignes récupérées (`pivotRows`). Purement client : appelé
	// après chaque récupération, mais aussi seul quand seul l'affichage change (mode, tri, sens, page).
	function renderChart() {
		if (yearChart) yearChart.destroy();
		const rows = pivotRows;
		if (!rows.length || !chartCanvas) { yearChart = null; legendItems = []; chartTable = null; return; }
		const comparison = groupBy;

		// La comparaison occupe l'abscisse (on compare le long de l'axe des x ; l'année y va naturellement) ; la ventilation de l'indicateur est l'empilement (la catégorie lue dans chaque barre). Sans comparaison, la ventilation passe en abscisse, en barres simples.
		const xDim = comparison || breakdown;
		const stackDim = comparison ? breakdown : '';

		const stackValues = stackDim ? orderedPivotValues(stackDim, rows) : [];

		// Tri par part d'une série : n'a de sens que sur un axe entité à forte cardinalité (labo, éditeur, revue) avec un empilement. L'axe année reste chronologique, les axes à faible cardinalité gardent leur ordre métier. Le sélecteur n'apparaît que dans ce cas, et une clé devenue caduque (changement d'empilement ou d'axe) est réinitialisée.
		const highCard = dimCard(xDim) === 'high';
		const canSort = highCard && !!stackDim;
		sortableSeries = canSort ? stackValues.map((sv) => ({ value: sv, label: dimLabel(stackDim, sv) })) : [];
		if (chartSort && (!canSort || !stackValues.includes(chartSort))) chartSort = '';

		// Abscisse : à forte cardinalité, on pagine les valeurs plutôt que de les tronquer — l'axe reste lisible, le détail reste atteignable. Ordre par défaut : total décroissant ; si une clé de tri est choisie, on classe par la part de la série correspondante.
		const allCats =
			chartSort && canSort
				? orderBySeriesShare(xDim, stackDim, chartSort, chartSortDir, rows)
				: orderedPivotValues(xDim, rows);
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
		const series = stackDim ? stackValues : ['__all__'];

		// Échelle partagée entre pages : le maximum de l'axe des valeurs couvre toutes les catégories (pas seulement la page affichée), afin que l'échelle reste stable d'une page à l'autre et que les exports PNG soient comparables. `suggestedMax` laisse Chart.js arrondir les graduations ; comme ce maximum domine celui de chaque page, l'arrondi est identique partout.
		const catTotal = (cv: string) => series.reduce((s, sv) => s + cell(cv, sv), 0);
		const valueMax = Math.max(0, ...allCats.map(catTotal));

		const datasets = series.map((sv, i) => ({
			label: stackDim ? dimLabel(stackDim, sv) : (indicatorDef?.label ?? ''),
			data: cats.map((cv) => cell(cv, sv)),
			backgroundColor: stackDim ? pivotValueColor(stackDim, sv, i) : cssColor('accent'),
			barPercentage: 0.85,
			categoryPercentage: 0.7
		}));
		legendItems = datasets.map((d) => ({ label: d.label, color: d.backgroundColor }));
		chartTable = {
			columns: datasets.map((d) => d.label),
			rows: labels.map((label, ci) => ({ label, values: datasets.map((d) => formatValue(d.data[ci] as number)) })),
		};

		// Mode « part » sans comparaison : un camembert des parts de chaque catégorie du groupement primaire (l'empilement à 100 % d'une barre unique, déroulé en secteurs lisibles).
		if (chartMode === 'part' && !stackDim) {
			const values = datasets[0].data as number[];
			const colors = cats.map((cv, i) => pivotValueColor(xDim, cv, i));
			legendItems = cats.map((cv, i) => ({ label: dimLabel(xDim, cv), color: colors[i] }));
			const sliceTotal = (ctx: { dataset: { data: unknown[] } }) =>
				(ctx.dataset.data as number[]).reduce((s, v) => s + (v || 0), 0);
			yearChart = new Chart(chartCanvas, {
				type: 'pie',
				plugins: [whiteBgPlugin],
				data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: cssColor('card'), borderWidth: 1 }] },
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						tooltip: {
							bodyFont: { size: fontSize('md') },
							callbacks: {
								label: (ctx) => {
									const val = ctx.raw as number;
									const total = sliceTotal(ctx);
									const pct = total ? ((val / total) * 100).toFixed(1) : '0.0';
									return `${ctx.label} : ${formatValue(val)} (${pct}%)`;
								}
							}
						},
						datalabels: {
							color: (ctx) => readableOn(colors[ctx.dataIndex], cssColor('text')),
							font: { weight: 'bold' },
							formatter: (val: number, ctx) => {
								const total = sliceTotal(ctx);
								const pct = total ? (val / total) * 100 : 0;
								return pct >= 5 ? Math.round(pct) + '%' : '';
							},
							anchor: 'center' as const,
							align: 'center' as const,
							listeners: {}
						}
					}
				}
			});
			return;
		}

		// Mode « part » avec comparaison : aplatir chaque colonne (abscisse) à 100 % en remplaçant les comptes par leur proportion.
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
						bodyFont: { size: fontSize('md') },
						callbacks: {
									label: (ctx) => {
										const val = ctx.raw as number;
										const total = ctx.chart.data.datasets.reduce((s, ds) => s + ((ds.data[ctx.dataIndex] as number) || 0), 0);
										const pct = total ? ((val / total) * 100).toFixed(1) : '0.0';
										return part
											? `${ctx.dataset.label} : ${pct}%`
											: `${ctx.dataset.label} : ${formatValue(val)} (${pct}%)`;
									},
									afterBody: (items) => {
										const total = items[0].chart.data.datasets.reduce((s, ds) => s + ((ds.data[items[0].dataIndex] as number) || 0), 0);
										return part ? [] : `Total : ${formatValue(total)}`;
									}
								}
					},
					datalabels: {
								color: (ctx) => readableOn(String(ctx.dataset.backgroundColor), cssColor('text')),
								font: { weight: 'bold' },
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
					[highCard ? 'y' : 'x']: { stacked: true, grid: { display: false }, ticks: { font: { size: highCard ? 12 : 14 }, callback: (_v: string | number, i: number) => { const l = labels[i] ?? ''; return l.length > 45 ? l.slice(0, 45) + '…' : l; } } },
					[highCard ? 'x' : 'y']: part
						? { stacked: true, min: 0, max: 100, ticks: { callback: (v: string | number) => v + ' %' } }
						: { stacked: true, beginAtZero: true, suggestedMax: valueMax, ticks: { precision: 0, callback: (v: string | number) => Number(v).toLocaleString('fr-FR') } }
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
			ctx.fillStyle = cssColor('card');
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
		restoreValues(FILTERS, restored, values);
		if (restored.indicator !== undefined) indicator = restored.indicator as string;
		if (restored.groupBy !== undefined) groupBy = restored.groupBy as string;
		if (restored.chartMode !== undefined) chartMode = restored.chartMode as 'absolu' | 'part';
		if (restored.chartPage) chartPage = restored.chartPage as number;
		if (restored.chartSort !== undefined) chartSort = restored.chartSort as string;
		if (restored.chartSortDir !== undefined) chartSortDir = restored.chartSortDir as 'desc' | 'asc';

		// Un lien venu de la liste peut contenir une recherche, ou un filtre propre à un laboratoire ou à une personne : ils sont annoncés, puis retirés.
		const ignored = ignoredFilters(FILTERS, values);
		const term = u.get('search')?.trim();
		const lost = [
			...ignored.map((f) => `filtre « ${f.label} »`),
			...(term ? [`recherche « ${term} »`] : []),
		];
		if (lost.length) {
			toast(`Non pris en compte dans les statistiques : ${lost.join(', ')}`, 'warning', 6000);
			for (const f of ignored) clearValue(f, values);
			syncUrl();
		}

		// Vocabulaire du pivot : dimensions graphables (faible cardinalité, hors l'axe année) proposées au sélecteur de découpage. Ajouter une dimension au registre l'y fait apparaître.
		try {
			pivotSchema = await api<components['schemas']['PivotSchemaResponse']>('/api/stats/pivot/schema');
		} catch { pivotSchema = null; }

		// Défaut du type de document : la famille « Publications ». Appliqué uniquement quand l'URL ne porte pas de filtre de types ; le jeton `all` (sélection vide explicite) le laisse vide.
		if (!u.has('doc_type')) {
			values.checkbox.docTypes = [...publicationsDocTypes];
		}

		await facets.load();
		// Années par défaut : les années récentes, seulement quand l'URL ne fixe pas les années. Le jeton `all` (toutes les années, par exemple depuis la liste) les laisse vides.
		const yearOptions = facets.options.years ?? [];
		if (!u.has('year') && yearOptions.length > 0) {
			values.checkbox.years = defaultYears(yearOptions.map((o) => o.value), new Date().getFullYear());
			syncUrl();
		}
		refresh();
	});
</script>

<PageHeader title="Statistiques" hidden />

<div class="stats-page">
<!-- Ligne 1 : contrôles du pivot + onglets -->
<div class="toolbar controls-row">
	{#if pivotSchema}
		<label class="groupby">
			Indicateur&nbsp;:
			<select bind:value={indicator} onchange={onAxisChange}>
				{#each pivotSchema.indicators as i (i.key)}
					<option value={i.key}>{i.unit ? `${i.label} (${i.unit})` : i.label}</option>
				{/each}
				<option value={COLLAB_VIEW}>Collaborations internationales</option>
			</select>
		</label>
		{#if !isCollab}
		<span class="sep" aria-hidden="true"></span>
		<label class="groupby">
			Comparer par&nbsp;:
			<select bind:value={groupBy} onchange={onAxisChange}>
				<option value="">Aucun</option>
				{#each comparableDims as d (d.key)}
					<option value={d.key}>{d.label}</option>
				{/each}
			</select>
		</label>
			<span class="sep" aria-hidden="true"></span>
			{/if}
		{/if}
	{#if pivotSchema && !isCollab}
		<label class="groupby">
			<input type="checkbox" checked={chartMode === 'part'} onchange={(e) => { chartMode = e.currentTarget.checked ? 'part' : 'absolu'; syncUrl(); renderChart(); }} />
			Part&nbsp;(%)
		</label>
	{/if}
	{#if !isCollab && sortableSeries.length}
		<span class="sep" aria-hidden="true"></span>
		<label class="groupby">
			Trier&nbsp;:
			<select bind:value={chartSort} onchange={() => { chartPage = 1; syncUrl(); renderChart(); }}>
				<option value="">Total</option>
				{#each sortableSeries as s (s.value)}
					<option value={s.value}>% {s.label}</option>
				{/each}
			</select>
		</label>
		{#if chartSort}
			<button type="button" class="sort-dir" title="Sens du tri" onclick={() => { chartSortDir = chartSortDir === 'desc' ? 'asc' : 'desc'; chartPage = 1; syncUrl(); renderChart(); }}>
				{chartSortDir === 'desc' ? '↓' : '↑'}
			</button>
		{/if}
	{/if}
	<a class="toolbar-action pubs-link" href={pubsUrl}>Voir les publications &rarr;</a>
</div>
<!-- Ligne 2 : filtres, ceux de la liste des publications. -->
<div class="stats-filters">
	<PublicationFilterBar filters={FILTERS} bind:values options={facets.options} sourceCounts={facets.sourceCounts} buildParams={chartParams} onchange={onFilterChange} />
	<ActiveFilterBar filters={FILTERS} bind:values options={facets.options} onchange={onFilterChange} />
</div>

{#if isCollab}
<!-- Carte des collaborations internationales -->
<section class="collab-section">
	<CollaborationMap params={collabParams} />
</section>
{:else}
<!-- Histogramme du pivot -->
{#if legendItems.length > 1}
	<div class="legend">
		{#each legendItems as item (item.label)}
			<span><span class="legend-dot" style="background:{item.color}"></span>{item.label}</span>
		{/each}
	</div>
{/if}
<div class="chart-area">
	<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
	<canvas bind:this={chartCanvas} aria-hidden="true"></canvas>
	{#if chartTable}
		<div class="visually-hidden">
			<table>
				<thead>
					<tr><td></td>{#each chartTable.columns as c, i (i)}<th scope="col">{c}</th>{/each}</tr>
				</thead>
				<tbody>
					{#each chartTable.rows as row, i (i)}
						<tr><th scope="row">{row.label}</th>{#each row.values as v, j (j)}<td>{v}</td>{/each}</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
	<button type="button" class="export-btn chart-export" onclick={exportChartPng}>Export PNG</button>
</div>
{#if chartCatTotal > CHART_PAGE_SIZE}
	<Pagination
		page={chartPage}
		pages={Math.ceil(chartCatTotal / CHART_PAGE_SIZE)}
		onchange={(p) => { chartPage = p; syncUrl(); renderChart(); }}
	/>
{/if}
{/if}
</div>


<style>
	.collab-section {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.pubs-link { margin-left: auto; }

	.stats-filters {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 16px;
	}
	.groupby {
		font-size: var(--fs-md);
		color: var(--muted);
		white-space: nowrap;
	}
	/* Séparateur vertical léger entre les groupes de contrôles du pivot. */
	.sep {
		width: 1px;
		align-self: stretch;
		min-height: 20px;
		background: var(--border);
	}
	/* Écran étroit : les contrôles passent à la ligne, un séparateur resterait seul en bout de ligne. */
	@media (max-width: 820px) {
		.sep {
			display: none;
		}
	}
	.sort-dir {
		font-family: inherit;
		font-size: var(--fs-base);
		line-height: 1;
		height: 34px;
		padding: 0 10px;
		border: none;
		border-radius: var(--radius);
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
	}
	.sort-dir:hover {
		background: var(--hover);
	}
	/* Légende au-dessus du graphique, alignée à gauche ; la place à droite revient à l'export. */
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		margin-bottom: 8px;
		padding-right: 120px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
	.legend-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		margin-right: 6px;
		vertical-align: -1px;
	}

	/* Colonne pleine hauteur : barres d'outils, légende et pagination gardent leur hauteur naturelle, le diagramme occupe l'espace restant du viewport. Hauteur = viewport moins l'en-tête fixe et le padding vertical du conteneur. */
	.stats-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - var(--header-height) - 48px);
	}

	.chart-area {
		padding-top: 40px;
		margin-bottom: 16px;
		position: relative;
		flex: 1 1 auto;
		min-height: 360px;
	}
	.chart-export {
		position: absolute;
		top: 0;
		right: 0;
	}

</style>
