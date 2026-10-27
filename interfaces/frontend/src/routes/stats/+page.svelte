<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { onMount, tick } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, latestRequest } from '#lib/api/index.js';
	import { Chart } from '#lib/components/charts/chart.js';
	import { cssVar, oaStatusColor } from '#lib/components/charts/cssVar.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import CollaborationMap from './CollaborationMap.svelte';
	import { defaultYears } from './defaultYears';
	import { paramsToQuery } from '#lib/utils.js';
	import {
		oaLabelsMap,
		oaStatusLabel,
		docTypePlural,
		docTypeFamilies,
		docTypeGroupedColors,
		licenseColors,
		licenseOrder,
		publicationsDocTypes,
		docTypeFilterToken,
		docTypeFilterFromToken,
		filterLabels,
	} from '#lib/labels.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';

	// Chaque changement de filtre relance le graphe : la requête précédente, encore en vol, est annulée.
	const pivotRequest = latestRequest();

	// --- Types ---
	import type { components } from '#lib/api/schema.js';
	// --- State ---
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedLicenses: string[] = $state([]);
	let selectedDocTypes: string[] = $state([]); // défaut = famille « Publications » (cf. onMount)
	// Facettes à forte cardinalité (recherche serveur) : une entité sélectionnée (id + libellé).
	// Facettes éditeur / revue : seul l'id (état canonique) ; le libellé de la pastille est résolu par EntityFilter.
	let selectedSerialId = $state<string | null>(null);
	let selectedPublisherId = $state<string | null>(null);
	let selectedPartnerRor = $state<string | null>(null);

	let chartCanvas: HTMLCanvasElement | undefined = $state();
	let yearChart: Chart | null = null;
	// Dernières lignes du pivot renvoyées par l'API : source du tracé, réutilisée par les contrôles d'affichage (mode, tri, page) qui re-tracent sans re-solliciter le serveur.
	let pivotRows: Record<string, unknown>[] = [];
	let initialYearsApplied = false;

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

	// Barre de facettes dérivée du registre `pivotSchema` : ensemble des dimensions filtrables, moins un groupement catégoriel déjà visible (l'année, ordinale, reste filtrable). Règle de présentation.
	const facetKeys = $derived.by(() => {
		if (!pivotSchema) return new Set(['year', 'lab', 'oa_voie', 'apc']);
		// Une facette reste offerte même quand le graphique compare sur sa dimension : elle restreint alors les valeurs comparées.
		return new Set(pivotSchema.dimensions.filter((d) => d.filterable).map((d) => d.key));
	});

	// Couleurs / libellés / ordre par dimension de découpage. Les valeurs OA réutilisent les variables CSS existantes ; les autres dimensions piochent dans une palette catégorielle.
	const OA_VOIE_ORDER = ['diamond', 'gold', 'hybrid', 'bronze', 'green', 'embargoed', 'closed', 'unknown'];
	const OA_ACCESS_ORDER = ['ouvert', 'embargo', 'ferme', 'indetermine'];
	const OA_ACCESS_LABELS: Record<string, string> = {
		ouvert: 'Ouvert', embargo: 'Sous embargo', ferme: 'Fermé', indetermine: 'Indéterminé',
	};
	const OA_ACCESS_STATUS: Record<string, string> = {
		ouvert: 'open', embargo: 'embargoed', ferme: 'closed', indetermine: 'unknown',
	};
	const PALETTE = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#b07aa1', '#76b7b2', '#ff9da7', '#9c755f', '#bab0ac', '#edc948'];

	function dimCard(dim: string): string {
		return pivotSchema?.dimensions.find((d) => d.key === dim)?.cardinality ?? 'low';
	}
	function dimLabel(dim: string, value: string): string {
		if (dim === 'oa_access') return OA_ACCESS_LABELS[value] ?? value;
		if (dim === 'oa_voie') return oaStatusLabel(value);
		if (dim === 'doc_type_grouped')
			return docTypePlural[value] ?? docTypeFamilies.find((f) => f.key === value)?.label ?? value;
		// Libellés servis par la facette, y compris celui des publications sans licence.
		if (dim === 'license') return facets.options.licenses.find((o) => o.value === value)?.text ?? value;
		return value;
	}
	function dimColor(dim: string, value: string, idx: number): string {
		if (dim === 'oa_voie') return oaStatusColor(value) ?? PALETTE[idx % PALETTE.length];
		if (dim === 'oa_access') return oaStatusColor(OA_ACCESS_STATUS[value]) ?? PALETTE[idx % PALETTE.length];
		if (dim === 'doc_type_grouped') return docTypeGroupedColors[value] ?? PALETTE[idx % PALETTE.length];
		if (dim === 'license') return licenseColors[value] ?? PALETTE[idx % PALETTE.length];
		return PALETTE[idx % PALETTE.length];
	}
	function orderedValues(dim: string, rows: Record<string, unknown>[]): string[] {
		const present = rows.map((r) => String(r[dim]));
		if (dim === 'year') return [...new Set(present)].sort((a, b) => Number(a) - Number(b));
		if (dim === 'oa_access') return OA_ACCESS_ORDER.filter((v) => present.includes(v));
		if (dim === 'oa_voie') return OA_VOIE_ORDER.filter((v) => present.includes(v));
		if (dim === 'license') return licenseOrder.filter((v) => present.includes(v));
		if (dim === 'doc_type_grouped') {
			// Famille « publications » éclatée en types fins, autres familles agrégées sous leur clé.
			const order = docTypeFamilies.flatMap((f) => (f.key === 'publications' ? f.types : [f.key]));
			return order.filter((k) => present.includes(k));
		}
		// Sinon : valeurs distinctes triées par total décroissant.
		const totals = new Map<string, number>();
		for (const r of rows) {
			const v = String(r[dim]);
			totals.set(v, (totals.get(v) ?? 0) + Number(r.value ?? 0));
		}
		return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([v]) => v);
	}

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
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedLicenses.length) p.set('license', selectedLicenses.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		if (selectedPublisherId) p.set('publisher_id', selectedPublisherId);
		if (selectedSerialId) p.set('serial_id', selectedSerialId);
		if (selectedPartnerRor) p.set('partner_ror', selectedPartnerRor);
		return p;
	}

	// --- Composable: facets ---
	const facets = useFacets<'years' | 'labs' | 'oa' | 'licenses' | 'apc' | 'docTypes'>({
		endpoint: '/api/stats/facets',
		apiKey: 'stats-facets',
		buildParams: chartParams,
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			labs: { type: 'labeled', apiKey: 'labs' },
			oa: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			licenses: { type: 'labeled', apiKey: 'licenses' },
			apc: { type: 'labeled', apiKey: 'apc' },
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
			selectedLicenses: { type: 'string_array', urlKey: 'license' },
			selectedDocTypes: { type: 'single', urlKey: 'doc_type', defaultValue: publicationsDocTypes.join(',') },
			publisherId: { type: 'single', urlKey: 'publisher_id' },
			serialId: { type: 'single', urlKey: 'serial_id' },
			partnerRor: { type: 'single', urlKey: 'partner_ror' },
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
			selectedYears,
			selectedLabs,
			selectedOa,
			selectedApc,
			selectedLicenses,
			selectedDocTypes: docTypeFilterToken(selectedDocTypes),
			publisherId: selectedPublisherId ?? '',
			serialId: selectedSerialId ?? '',
			partnerRor: selectedPartnerRor ?? '',
			indicator,
			groupBy,
			chartMode,
			chartPage,
			chartSort,
			chartSortDir,
		}));
	}

	// --- Derived: publications link ---
	const pubsUrl = $derived.by(() => {
		// Les entités passent par leur identifiant ; la liste résout elle-même le libellé de la pastille.
		const p = chartParams();
		p.set('doc_type', docTypeFilterToken(selectedDocTypes));
		return resolve('publications') + '?' + paramsToQuery(p);
	});

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
		if (!rows.length || !chartCanvas) { yearChart = null; legendItems = []; return; }
		const comparison = groupBy;

		// La comparaison occupe l'abscisse (on compare le long de l'axe des x ; l'année y va naturellement) ; la ventilation de l'indicateur est l'empilement (la catégorie lue dans chaque barre). Sans comparaison, la ventilation passe en abscisse, en barres simples.
		const xDim = comparison || breakdown;
		const stackDim = comparison ? breakdown : '';

		const stackValues = stackDim ? orderedValues(stackDim, rows) : [];

		// Tri par part d'une série : n'a de sens que sur un axe entité à forte cardinalité (labo, éditeur, revue) avec un empilement. L'axe année reste chronologique, les axes à faible cardinalité gardent leur ordre métier. Le sélecteur n'apparaît que dans ce cas, et une clé devenue caduque (changement d'empilement ou d'axe) est réinitialisée.
		const highCard = dimCard(xDim) === 'high';
		const canSort = highCard && !!stackDim;
		sortableSeries = canSort ? stackValues.map((sv) => ({ value: sv, label: dimLabel(stackDim, sv) })) : [];
		if (chartSort && (!canSort || !stackValues.includes(chartSort))) chartSort = '';

		// Abscisse : à forte cardinalité, on pagine les valeurs plutôt que de les tronquer — l'axe reste lisible, le détail reste atteignable. Ordre par défaut : total décroissant ; si une clé de tri est choisie, on classe par la part de la série correspondante.
		const allCats =
			chartSort && canSort
				? orderBySeriesShare(xDim, stackDim, chartSort, chartSortDir, rows)
				: orderedValues(xDim, rows);
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
			backgroundColor: stackDim ? dimColor(stackDim, sv, i) : cssVar('accent'),
			barPercentage: 0.85,
			categoryPercentage: 0.7
		}));
		legendItems = datasets.map((d) => ({ label: d.label, color: d.backgroundColor }));

		// Mode « part » sans comparaison : un camembert des parts de chaque catégorie du groupement primaire (l'empilement à 100 % d'une barre unique, déroulé en secteurs lisibles).
		if (chartMode === 'part' && !stackDim) {
			const values = datasets[0].data as number[];
			const colors = cats.map((cv, i) => dimColor(xDim, cv, i));
			legendItems = cats.map((cv, i) => ({ label: dimLabel(xDim, cv), color: colors[i] }));
			const sliceTotal = (ctx: { dataset: { data: unknown[] } }) =>
				(ctx.dataset.data as number[]).reduce((s, v) => s + (v || 0), 0);
			yearChart = new Chart(chartCanvas, {
				type: 'pie',
				plugins: [whiteBgPlugin],
				data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#fff', borderWidth: 1 }] },
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
									const total = sliceTotal(ctx);
									const pct = total ? ((val / total) * 100).toFixed(1) : '0.0';
									return `${ctx.label} : ${formatValue(val)} (${pct}%)`;
								}
							}
						},
						datalabels: {
							color: '#fff',
							font: { size: 13, weight: 'bold' },
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
						bodyFont: { size: 14 },
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
					[highCard ? 'y' : 'x']: { stacked: true, grid: { display: false }, ticks: { font: { size: highCard ? 12 : 14 }, callback: (_v: string | number, i: number) => { const l = labels[i] ?? ''; return l.length > 45 ? l.slice(0, 45) + '…' : l; } } },
					[highCard ? 'x' : 'y']: part
						? { stacked: true, min: 0, max: 100, ticks: { font: { size: 13 }, callback: (v: string | number) => v + ' %' } }
						: { stacked: true, beginAtZero: true, suggestedMax: valueMax, ticks: { font: { size: 13 }, precision: 0, callback: (v: string | number) => Number(v).toLocaleString('fr-FR') } }
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
	function onPublisherFilter(id: string | null) {
		selectedPublisherId = id;
		onFilterChange();
	}
	function onSerialFilter(id: string | null) {
		selectedSerialId = id;
		onFilterChange();
	}
	function onPartnerFilter(ror: string | null) {
		selectedPartnerRor = ror;
		onFilterChange();
	}

	onMount(async () => {
		// Restore state from URL params
		const u = new URLSearchParams(window.location.search);
		const restored = urlFilters.restoreFromUrl(u);
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.selectedLicenses) selectedLicenses = restored.selectedLicenses as string[];
		if (restored.selectedDocTypes != null)
			selectedDocTypes = docTypeFilterFromToken(restored.selectedDocTypes as string);
		if (restored.publisherId) selectedPublisherId = restored.publisherId as string;
		if (restored.serialId) selectedSerialId = restored.serialId as string;
		if (restored.partnerRor) selectedPartnerRor = restored.partnerRor as string;
		if (restored.indicator !== undefined) indicator = restored.indicator as string;
		if (restored.groupBy !== undefined) groupBy = restored.groupBy as string;
		if (restored.chartMode !== undefined) chartMode = restored.chartMode as 'absolu' | 'part';
		if (restored.chartPage) chartPage = restored.chartPage as number;
		if (restored.chartSort !== undefined) chartSort = restored.chartSort as string;
		if (restored.chartSortDir !== undefined) chartSortDir = restored.chartSortDir as 'desc' | 'asc';

		// Vocabulaire du pivot : dimensions graphables (faible cardinalité, hors l'axe année) proposées au sélecteur de découpage. Ajouter une dimension au registre l'y fait apparaître.
		try {
			pivotSchema = await api<components['schemas']['PivotSchemaResponse']>('/api/stats/pivot/schema');
		} catch { pivotSchema = null; }

		// Défaut du type de document : la famille « Publications ». Appliqué uniquement quand l'URL ne porte pas de filtre de types ; le token `all` (sélection « Tous » explicite) le laisse vide.
		if (!u.has('doc_type')) {
			selectedDocTypes = [...publicationsDocTypes];
		}

		await facets.load();
		if (!initialYearsApplied && selectedYears.length === 0 && facets.options.years.length > 0) {
			selectedYears = defaultYears(facets.options.years.map((o) => o.value), new Date().getFullYear());
			syncUrl();
		}
		initialYearsApplied = true;
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
<!-- Ligne 2 : filtres à facettes, dérivés du registre `pivotSchema` (cf. `facetKeys`). -->
<div class="toolbar facets-row">
	<span class="facets-label">Filtrer par&nbsp;:</span>
	{#if facetKeys.has('year')}
		<FacetDropdown label={filterLabels.years} allLabel="Toutes" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('lab')}
		<FacetDropdown label={filterLabels.labs} options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('oa_voie')}
		<FacetDropdown label={filterLabels.oaStatuses} options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('doc_type')}
		<FacetDropdown label={filterLabels.types} options={facets.options.docTypes} groups={docTypeFamilies.map((f) => ({ label: f.label, values: f.types }))} bind:selected={selectedDocTypes} onchange={onFilterChange} />
	{/if}
	{#if facetKeys.has('serial')}
		<EntityFilter label={filterLabels.serial} endpoint="/api/stats/facets" kind="serial" buildParams={chartParams} selected={selectedSerialId ? [selectedSerialId] : []} onchange={(ids) => onSerialFilter(ids[0] ?? null)} />
	{/if}
	{#if facetKeys.has('publisher')}
		<EntityFilter label={filterLabels.publisher} endpoint="/api/stats/facets" kind="publisher" buildParams={chartParams} selected={selectedPublisherId ? [selectedPublisherId] : []} onchange={(ids) => onPublisherFilter(ids[0] ?? null)} />
	{/if}
	{#if facetKeys.has('partner')}
		<EntityFilter label={filterLabels.partner} endpoint="/api/stats/facets" kind="partner" buildParams={chartParams} selected={selectedPartnerRor ? [selectedPartnerRor] : []} onchange={(ids) => onPartnerFilter(ids[0] ?? null)} />
	{/if}
	{#if facetKeys.has('license')}
		<FacetDropdown label={filterLabels.licenses} options={facets.options.licenses} bind:selected={selectedLicenses} onchange={onFilterChange} tooltip="Licence de la version éditeur" />
	{/if}
	{#if facetKeys.has('apc')}
		<FacetDropdown label={filterLabels.apc} options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip={"Pas d'info après 2024\nSans APC = ou APC non documentés"} />
	{/if}
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
	<canvas bind:this={chartCanvas}></canvas>
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

	.facets-row { margin-bottom: 16px; }
	.facets-label { font-size: 0.9rem; color: var(--muted); white-space: nowrap; }
	.groupby {
		font-size: 0.9rem;
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
	.sort-dir {
		font-family: inherit;
		font-size: 1rem;
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
		font-size: 0.85rem;
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
