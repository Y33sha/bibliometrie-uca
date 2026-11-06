/**
 * Graphique des statistiques des publications : un indicateur (mesure et ventilation), un axe de comparaison facultatif, et leur tracé.
 *
 * Le composable tient les réglages (indicateur, comparaison, mode, tri, page), interroge le pivot sous les filtres de la page et trace le graphique dans le canvas que lui confie `PivotChart`. Les contrôles (`PivotControls`) et le graphique (`PivotChart`) le partagent. La page tient l'URL : `onsettingchange` lui signale chaque réglage changé par l'utilisateur.
 */
import { tick } from 'svelte';
import { api, latestRequest } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';
import { Chart, fitsInBar, pieSegmentOptions, stackedSegmentOptions } from '#lib/components/charts/chart.js';
import { cssColor, fontSize } from '#lib/components/charts/cssVar.js';
import { readableOn } from '#lib/components/charts/contrast.js';
import { orderedPivotValues, pivotValueColor, pivotValueDescription, pivotValueLabel } from '#lib/pivotValues.js';
import { coreRange } from '#lib/filterRegistry.js';

type PivotSchema = components['schemas']['PivotSchemaResponse'];

/** Entrée du sélecteur d'indicateur qui remplace l'histogramme par la carte des collaborations internationales. Ce n'est pas une dimension du pivot. */
export const COLLAB_VIEW = 'collaborations';

/** Catégories affichées par page sur un axe à forte cardinalité. */
export const CHART_PAGE_SIZE = 10;

export type ChartMode = 'absolu' | 'part';

/** Réglages du graphique, tels que la page les écrit dans l'URL. */
export interface PivotSettings {
	indicator: string;
	groupBy: string;
	chartMode: ChartMode;
	chartPage: number;
	chartSort: string;
	chartSortDir: 'desc' | 'asc';
}

export const DEFAULT_PIVOT_SETTINGS: PivotSettings = {
	indicator: 'doc_type_grouped',
	groupBy: 'year',
	chartMode: 'absolu',
	chartPage: 1,
	chartSort: '',
	chartSortDir: 'desc',
};

/** Déclaration des réglages du graphique pour `useUrlFilters`. Le tri du graphique prend `chart_sort` : `sort` est celui de la liste. */
export const PIVOT_URL_FILTERS = {
	indicator: { type: 'single', urlKey: 'indicator', defaultValue: DEFAULT_PIVOT_SETTINGS.indicator },
	groupBy: { type: 'single', urlKey: 'group_by', defaultValue: DEFAULT_PIVOT_SETTINGS.groupBy },
	chartMode: { type: 'single', urlKey: 'mode', defaultValue: DEFAULT_PIVOT_SETTINGS.chartMode },
	chartPage: { type: 'page', urlKey: 'chart_page' },
	chartSort: { type: 'single', urlKey: 'chart_sort', defaultValue: DEFAULT_PIVOT_SETTINGS.chartSort },
	chartSortDir: { type: 'single', urlKey: 'chart_sort_dir', defaultValue: DEFAULT_PIVOT_SETTINGS.chartSortDir },
} as const;

/** Réglages du graphique lus par `useUrlFilters`, déclarés par `PIVOT_URL_FILTERS`. Un réglage absent de l'URL est omis. */
export function pivotSettingsFromUrl(restored: Record<string, unknown>): Partial<PivotSettings> {
	const settings: Partial<PivotSettings> = {};
	if (restored.indicator !== undefined) settings.indicator = restored.indicator as string;
	if (restored.groupBy !== undefined) settings.groupBy = restored.groupBy as string;
	if (restored.chartMode !== undefined) settings.chartMode = restored.chartMode as ChartMode;
	if (restored.chartPage) settings.chartPage = restored.chartPage as number;
	if (restored.chartSort !== undefined) settings.chartSort = restored.chartSort as string;
	if (restored.chartSortDir !== undefined) settings.chartSortDir = restored.chartSortDir as 'desc' | 'asc';
	return settings;
}

export type PivotChart = ReturnType<typeof usePivotChart>;

export function usePivotChart(config: {
	/** Paramètres des filtres actifs. */
	buildParams: () => URLSearchParams;
	/** Libellé d'une licence, servi par la facette des licences. */
	licenseLabel?: (value: string) => string | undefined;
	/** Appelé après chaque réglage changé par l'utilisateur. */
	onsettingchange?: () => void;
}) {
	// Chaque changement de filtre relance le graphe : la requête précédente, encore en vol, est annulée.
	const pivotRequest = latestRequest();

	let schema = $state<PivotSchema | null>(null);
	let settings = $state<PivotSettings>({ ...DEFAULT_PIVOT_SETTINGS });
	// Total des catégories sur l'axe de comparaison : 0 pour un axe à faible cardinalité.
	let catTotal = $state(0);
	// Séries proposées au sélecteur de tri, dérivées de l'empilement courant (mises à jour au tracé).
	let sortableSeries = $state<{ value: string; label: string }[]>([]);
	let legendItems = $state<{ label: string; color: string; description?: string }[]>([]);
	// Données du graphique pour les lecteurs d'écran : une ligne par catégorie de l'abscisse, une colonne par série, en valeurs absolues.
	let table = $state<{ columns: string[]; rows: { label: string; values: string[] }[] } | null>(null);
	let canvas: HTMLCanvasElement | undefined;
	let chart: Chart | null = null;
	// Dernières lignes du pivot renvoyées par l'API : source du tracé, réutilisée par les réglages d'affichage (mode, tri, page) qui re-tracent sans re-solliciter le serveur.
	let rows: Record<string, unknown>[] = [];
	let whiteBackground = false;

	const indicatorDef = $derived(schema?.indicators.find((i) => i.key === settings.indicator));
	// Dimension empilée dans chaque barre, imposée par l'indicateur.
	const breakdown = $derived(indicatorDef?.breakdown ?? '');
	const isCollab = $derived(settings.indicator === COLLAB_VIEW);
	// Comparaison : les dimensions déclarées `comparable` (l'année et les entités à forte cardinalité : laboratoire, éditeur, revue, organisation partenaire).
	const comparableDims = $derived(schema ? schema.dimensions.filter((d) => d.comparable) : []);

	function dimCard(dim: string): string {
		return schema?.dimensions.find((d) => d.key === dim)?.cardinality ?? 'low';
	}
	const dimLabel = (dim: string, value: string) => pivotValueLabel(dim, value, config.licenseLabel ?? (() => undefined));

	// Valeur affichée d'une barre ou d'un total : entier pour un nombre de publications, montant arrondi à l'euro suivi de l'unité pour une somme.
	function formatValue(value: number): string {
		const unit = indicatorDef?.unit;
		const text = Math.round(value).toLocaleString('fr-FR');
		return unit ? `${text} ${unit}` : text;
	}

	// Ordonne les catégories de l'axe `dim` par la part de la série `seriesValue` (lue sur `stackDim`) dans chaque catégorie : numérateur = valeur de cette série, dénominateur = total de la catégorie. Trier sur la part (et non la valeur brute) donne le classement « du plus au moins <série> » indépendamment de la taille de la catégorie, cohérent avec la vue en pourcentage.
	function orderBySeriesShare(
		dim: string,
		stackDim: string,
		seriesValue: string,
		dir: 'desc' | 'asc',
		data: Record<string, unknown>[],
	): string[] {
		const num = new Map<string, number>();
		const den = new Map<string, number>();
		for (const r of data) {
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

	// Années de `years` comprises dans la plage qui concentre les valeurs des lignes du pivot.
	function coreYears(years: string[]): string[] {
		const totals = new Map<number, number>();
		for (const r of rows) {
			const year = Number(r.year);
			if (Number.isInteger(year)) totals.set(year, (totals.get(year) ?? 0) + Number(r.value ?? 0));
		}
		if (!totals.size) return years;
		const [lo, hi] = coreRange([...totals].sort(([a], [b]) => a - b));
		return years.filter((y) => Number(y) >= lo && Number(y) <= hi);
	}

	/** Charge le vocabulaire du pivot : indicateurs et dimensions proposés aux sélecteurs. */
	async function loadSchema() {
		try {
			schema = await api<PivotSchema>('/api/stats/pivot/schema');
		} catch {
			schema = null;
		}
	}

	// Récupère les lignes du pivot depuis l'API, puis délègue le tracé. La requête dépend seulement des filtres, de l'indicateur et de la comparaison ; les réglages d'affichage (mode, tri, page) re-tracent depuis ce cache sans nouvel appel réseau (voir `render`).
	async function load() {
		// Vue Collaborations : la carte se dessine seule (composant dédié). L'histogramme éventuel est détruit, le pivot n'est pas interrogé (`collaborations` n'est pas une dimension valide).
		if (isCollab) {
			if (chart) {
				chart.destroy();
				chart = null;
			}
			legendItems = [];
			return;
		}
		const p = config.buildParams();
		p.set('indicator', settings.indicator);
		if (settings.groupBy) p.set('compare', settings.groupBy);
		const res = await pivotRequest<{ rows: Record<string, unknown>[] }>('/api/stats/pivot?' + p);
		rows = res.rows;
		await tick();
		render();
	}

	// Trace le graphe à partir des dernières lignes récupérées (`rows`). Purement client : appelé après chaque récupération, mais aussi seul quand seul l'affichage change (mode, tri, sens, page).
	function render() {
		if (chart) chart.destroy();
		if (!rows.length || !canvas) {
			chart = null;
			legendItems = [];
			table = null;
			return;
		}
		const { groupBy: comparison, chartMode, chartSortDir } = settings;

		// La comparaison occupe l'abscisse (on compare le long de l'axe des x ; l'année y va naturellement) ; la ventilation de l'indicateur est l'empilement (la catégorie lue dans chaque barre). Sans comparaison, la ventilation passe en abscisse, en barres simples.
		const xDim = comparison || breakdown;
		const stackDim = comparison ? breakdown : '';

		const stackValues = stackDim ? orderedPivotValues(stackDim, rows) : [];

		// Tri par part d'une série : n'a de sens que sur un axe entité à forte cardinalité (labo, éditeur, revue) avec un empilement. L'axe année reste chronologique, les axes à faible cardinalité gardent leur ordre métier. Le sélecteur n'apparaît que dans ce cas, et une clé devenue caduque (changement d'empilement ou d'axe) est réinitialisée.
		const highCard = dimCard(xDim) === 'high';
		const segment = stackDim ? stackedSegmentOptions(canvas, highCard) : {};
		const canSort = highCard && !!stackDim;
		sortableSeries = canSort ? stackValues.map((sv) => ({ value: sv, label: dimLabel(stackDim, sv) })) : [];
		if (settings.chartSort && (!canSort || !stackValues.includes(settings.chartSort))) settings.chartSort = '';
		const chartSort = settings.chartSort;

		// Abscisse : à forte cardinalité, on pagine les valeurs plutôt que de les tronquer — l'axe reste lisible, le détail reste atteignable. Ordre par défaut : total décroissant ; si une clé de tri est choisie, on classe par la part de la série correspondante.
		const ordered =
			chartSort && canSort ? orderBySeriesShare(xDim, stackDim, chartSort, chartSortDir, rows) : orderedPivotValues(xDim, rows);
		// Axe des années, sans filtre d'années : seules les années qui concentrent les valeurs s'affichent (`coreRange`). Aux deux bouts, les années qui réunissent ensemble moins de 1 % du total sont écartées.
		const allCats = xDim === 'year' && !config.buildParams().has('year') ? coreYears(ordered) : ordered;
		catTotal = highCard ? allCats.length : 0;
		if (highCard && (settings.chartPage - 1) * CHART_PAGE_SIZE >= allCats.length) settings.chartPage = 1;
		const chartPage = settings.chartPage;
		const cats = highCard ? allCats.slice((chartPage - 1) * CHART_PAGE_SIZE, chartPage * CHART_PAGE_SIZE) : allCats;
		const labels = cats.map((c) => dimLabel(xDim, c));

		// Valeur de chaque cellule (abscisse, série), indexée une fois : un axe à forte cardinalité compte des milliers de catégories.
		const cells = new Map<string, number>();
		const catTotals = new Map<string, number>();
		for (const r of rows) {
			const cv = String(r[xDim]);
			const value = Number(r.value);
			cells.set(stackDim ? `${cv}\u0000${String(r[stackDim])}` : cv, value);
			catTotals.set(cv, (catTotals.get(cv) ?? 0) + value);
		}
		const cell = (cv: string, sv: string) => cells.get(stackDim ? `${cv}\u0000${sv}` : cv) ?? 0;
		const series = stackDim ? stackValues : ['__all__'];

		// Échelle partagée entre pages : le maximum de l'axe des valeurs couvre toutes les catégories (pas seulement la page affichée), afin que l'échelle reste stable d'une page à l'autre et que les exports PNG soient comparables. `suggestedMax` laisse Chart.js arrondir les graduations ; comme ce maximum domine celui de chaque page, l'arrondi est identique partout.
		const valueMax = allCats.reduce((max, cv) => Math.max(max, catTotals.get(cv) ?? 0), 0);

		const datasets = series.map((sv, i) => ({
			label: stackDim ? dimLabel(stackDim, sv) : (indicatorDef?.label ?? ''),
			data: cats.map((cv) => cell(cv, sv)),
			backgroundColor: stackDim ? pivotValueColor(stackDim, sv, i) : cssColor('accent'),
			...segment,
			barPercentage: 0.85,
			categoryPercentage: 0.7,
		}));
		const descriptions = series.map((sv) => (stackDim ? pivotValueDescription(stackDim, sv) : undefined));
		legendItems = datasets.map((d, i) => ({ label: d.label, color: d.backgroundColor, description: descriptions[i] }));
		table = {
			columns: datasets.map((d) => d.label),
			rows: labels.map((label, ci) => ({ label, values: datasets.map((d) => formatValue(d.data[ci] as number)) })),
		};

		// Mode « part » sans comparaison : un camembert des parts de chaque catégorie du groupement primaire (l'empilement à 100 % d'une barre unique, déroulé en secteurs lisibles).
		if (chartMode === 'part' && !stackDim) {
			const values = datasets[0].data as number[];
			const colors = cats.map((cv, i) => pivotValueColor(xDim, cv, i));
			const sliceDescriptions = cats.map((cv) => pivotValueDescription(xDim, cv));
			legendItems = cats.map((cv, i) => ({ label: dimLabel(xDim, cv), color: colors[i], description: sliceDescriptions[i] }));
			const sliceTotal = (ctx: { dataset: { data: unknown[] } }) =>
				(ctx.dataset.data as number[]).reduce((s, v) => s + (v || 0), 0);
			chart = new Chart(canvas, {
				type: 'pie',
				plugins: [whiteBgPlugin],
				data: { labels, datasets: [{ data: values, backgroundColor: colors, ...pieSegmentOptions(canvas) }] },
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
								},
								afterLabel: (ctx) => sliceDescriptions[ctx.dataIndex] ?? '',
							},
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
							listeners: {},
						},
					},
				},
			});
			return;
		}

		// Mode « part » avec comparaison : aplatir chaque colonne (abscisse) à 100 % en remplaçant les comptes par leur proportion.
		const part = chartMode === 'part' && !!stackDim;
		if (part) {
			const totals = labels.map((_, ci) => datasets.reduce((s, d) => s + ((d.data[ci] as number) || 0), 0));
			for (const d of datasets) d.data = d.data.map((c, ci) => (totals[ci] ? ((c as number) / totals[ci]) * 100 : 0));
		}

		// Étiquette d'un segment : sa part dans la barre, affichée seulement si elle tient dans le segment.
		const BAR_LABEL_FONT = { weight: 'bold' as const };
		const barShareLabel = (ctx: { chart: Chart; dataIndex: number; datasetIndex: number }) => {
			const all = ctx.chart.data.datasets;
			const total = all.reduce((s, ds) => s + ((ds.data[ctx.dataIndex] as number) || 0), 0);
			const val = (all[ctx.datasetIndex].data[ctx.dataIndex] as number) || 0;
			return total ? Math.round((val / total) * 100) + '%' : '';
		};

		chart = new Chart(canvas, {
			type: 'bar',
			plugins: [whiteBgPlugin],
			data: { labels, datasets },
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
								return part ? `${ctx.dataset.label} : ${pct}%` : `${ctx.dataset.label} : ${formatValue(val)} (${pct}%)`;
							},
							afterLabel: (ctx) => descriptions[ctx.datasetIndex] ?? '',
							afterBody: (items) => {
								const total = items[0].chart.data.datasets.reduce((s, ds) => s + ((ds.data[items[0].dataIndex] as number) || 0), 0);
								return part ? [] : `Total : ${formatValue(total)}`;
							},
						},
					},
					datalabels: {
						color: (ctx) => readableOn(String(ctx.dataset.backgroundColor), cssColor('text')),
						font: BAR_LABEL_FONT,
						display: (ctx) => fitsInBar(ctx, barShareLabel(ctx), BAR_LABEL_FONT),
						formatter: (_val: number, ctx) => barShareLabel(ctx),
						anchor: 'center' as const,
						align: 'center' as const,
						listeners: {},
					},
				},
				interaction: { mode: 'point' as const, intersect: true },
				hover: { mode: 'point' as const, intersect: true },
				scales: {
					[highCard ? 'y' : 'x']: {
						stacked: true,
						grid: { display: false },
						ticks: {
							font: { size: highCard ? 12 : 14 },
							callback: (_v: string | number, i: number) => {
								const l = labels[i] ?? '';
								return l.length > 45 ? l.slice(0, 45) + '…' : l;
							},
						},
					},
					[highCard ? 'x' : 'y']: part
						? { stacked: true, min: 0, max: 100, ticks: { callback: (v: string | number) => v + ' %' } }
						: {
								stacked: true,
								beginAtZero: true,
								suggestedMax: valueMax,
								ticks: { precision: 0, callback: (v: string | number) => Number(v).toLocaleString('fr-FR') },
							},
				},
			},
		});
	}

	// Fond blanc du graphique, seulement pendant l'export PNG.
	const whiteBgPlugin = {
		id: 'whiteBg',
		beforeDraw(c: Chart) {
			if (!whiteBackground) return;
			const { ctx, width, height } = c;
			ctx.save();
			ctx.fillStyle = cssColor('card');
			ctx.fillRect(0, 0, width, height);
			ctx.restore();
		},
	};

	function exportPng() {
		if (!chart) return;
		whiteBackground = true;
		chart.options.plugins!.legend = { display: true, position: 'bottom' as const };
		chart.update('none');
		const a = document.createElement('a');
		a.href = chart.toBase64Image('image/png', 1);
		a.download = 'chart.png';
		a.click();
		whiteBackground = false;
		chart.options.plugins!.legend = { display: false };
		chart.update('none');
	}

	/** Change un réglage. L'indicateur et la comparaison relancent la requête et repartent de la première page ; les autres réglages re-tracent. */
	function set<K extends keyof PivotSettings>(key: K, value: PivotSettings[K]) {
		settings[key] = value;
		if (key === 'indicator' || key === 'groupBy') {
			settings.chartPage = 1;
			config.onsettingchange?.();
			load();
			return;
		}
		if (key === 'chartSort' || key === 'chartSortDir') settings.chartPage = 1;
		config.onsettingchange?.();
		render();
	}

	return {
		get schema() {
			return schema;
		},
		get settings() {
			return settings;
		},
		/** Remplace les réglages, par exemple lus dans l'URL, sans relancer la requête. */
		restore(values: Partial<PivotSettings>) {
			settings = { ...settings, ...values };
		},
		get indicatorDef() {
			return indicatorDef;
		},
		get isCollab() {
			return isCollab;
		},
		get comparableDims() {
			return comparableDims;
		},
		get sortableSeries() {
			return sortableSeries;
		},
		get legendItems() {
			return legendItems;
		},
		get table() {
			return table;
		},
		get catTotal() {
			return catTotal;
		},
		/** Filtres actifs sérialisés : pilotent la carte des collaborations, qui suit les mêmes filtres que le graphique mais ignore l'axe, le mode et la pagination. */
		get filterKey() {
			return config.buildParams().toString();
		},
		/** Canvas du graphique, confié par `PivotChart`. */
		attach(el: HTMLCanvasElement | undefined) {
			canvas = el;
		},
		loadSchema,
		load,
		render,
		exportPng,
		set,
	};
}
