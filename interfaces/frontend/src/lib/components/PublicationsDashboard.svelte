<script lang="ts">
	import type { Snippet } from 'svelte';
	import { api } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import KeyFigures from '#lib/components/KeyFigures.svelte';
	import BarChart from '#lib/components/charts/BarChart.svelte';
	import StackedBarChart from '#lib/components/charts/StackedBarChart.svelte';
	import { cssColor } from '#lib/components/charts/cssVar.js';
	import { countryName } from '#lib/countryNames.js';
	import { defaultYears } from '#lib/defaultYears.js';
	import { publicationsDocTypes } from '#lib/docTypes.svelte.js';
	import { orderedPivotValues, pivotValueColor, pivotValueLabel } from '#lib/pivotValues.js';
	import { contextParams, type PublicationListContext } from '#lib/publicationListContext.js';
	import { paramsToQuery } from '#lib/utils.js';

	type PivotResponse = components['schemas']['PivotResponse'];
	type CollaborationsResponse = components['schemas']['CollaborationsResponse'];
	type Row = PivotResponse['rows'][number];
	type Figure = { value: string; label: string; tone?: 'open' };

	// Dashboard des publications d'une entité, calculé par le moteur de la page Statistiques. Le corpus est celui de l'onglet Publications, restreint à la famille « Publications » et aux années récentes. La répartition par types de documents compte toutes les familles, sur les mêmes années.
	let {
		context,
		apiKey,
		thesesFigure = true,
		countries = true,
		oaBreakdown = 'oa_access',
		figures = [],
		subjects,
	}: {
		context: PublicationListContext;
		/** Préfixe des clés de requête. */
		apiKey: string;
		/** Affiche le nombre de thèses parmi les chiffres clés. */
		thesesFigure?: boolean;
		/** Affiche les pays partenaires. */
		countries?: boolean;
		/** Découpage des publications par année : niveau d'accès, ou modèle open access. */
		oaBreakdown?: 'oa_access' | 'oa_voie';
		/** Chiffres clés propres à la page, après ceux du dashboard. */
		figures?: Figure[];
		/** Bloc des sujets, fourni par la page, à côté des publications par année. */
		subjects?: Snippet;
	} = $props();

	let loaded = $state(false);
	let years = $state<number[]>([]);
	// Publications par année et par niveau d'accès : total et part en open access.
	let byYear = $state<Row[]>([]);
	// Publications par année selon `oaBreakdown`, pour le graphique.
	let chartRows = $state<Row[]>([]);
	let types = $state<Row[]>([]);
	let collab = $state<CollaborationsResponse | null>(null);

	function query(docTypes: string[] | null, extra: Record<string, string>): string {
		const params = contextParams(context);
		if (docTypes) params.set('doc_type', docTypes.join(','));
		for (const [key, value] of Object.entries(extra)) params.set(key, value);
		return paramsToQuery(params);
	}

	async function load() {
		loaded = false;
		const all = await api<PivotResponse>(
			`/api/stats/pivot?${query(publicationsDocTypes(),{ indicator: 'oa_access', compare: 'year' })}`,
			{ key: `${apiKey}-by-year` },
		);
		const recent = defaultYears([...new Set(all.rows.map((r) => String(r.year)))], new Date().getFullYear());
		years = recent.map(Number).sort((a, b) => a - b);
		byYear = all.rows.filter((r) => recent.includes(String(r.year)));
		if (recent.length) {
			const year = recent.join(',');
			[types, collab, chartRows] = await Promise.all([
				api<PivotResponse>(`/api/stats/pivot?${query(null, { indicator: 'doc_type_grouped', year })}`, {
					key: `${apiKey}-types`,
				}).then((r) => r.rows),
				api<CollaborationsResponse>(`/api/stats/collaborations?${query(publicationsDocTypes(),{ year })}`, {
					key: `${apiKey}-collaborations`,
				}),
				oaBreakdown === 'oa_access'
					? Promise.resolve(byYear)
					: api<PivotResponse>(
							`/api/stats/pivot?${query(publicationsDocTypes(),{ indicator: oaBreakdown, compare: 'year', year })}`,
							{ key: `${apiKey}-by-year-${oaBreakdown}` },
						).then((r) => r.rows),
			]);
		} else {
			types = [];
			collab = null;
			chartRows = [];
		}
		loaded = true;
	}

	$effect(() => {
		void context;
		void load();
	});

	const sum = (rows: Row[]) => rows.reduce((total, r) => total + Number(r.value ?? 0), 0);
	const percent = (part: number, whole: number) => `${Math.round((part / whole) * 100)} %`;

	const total = $derived(sum(byYear));
	const openAccess = $derived(sum(byYear.filter((r) => r.oa_access === 'ouvert')));
	const theses = $derived(sum(types.filter((r) => r.doc_type_grouped === 'theses')));

	const keyFigures = $derived<Figure[]>([
		{ value: total.toLocaleString('fr-FR'), label: 'publications' },
		...(total > 0 ? [{ value: percent(openAccess, total), label: 'en open access', tone: 'open' as const }] : []),
		...(collab && collab.total_count > 0
			? [{ value: percent(collab.international_count, collab.total_count), label: 'en collaboration internationale' }]
			: []),
		...(thesesFigure && theses > 0 ? [{ value: theses.toLocaleString('fr-FR'), label: 'thèses' }] : []),
		...figures,
	]);

	// Publications par année, empilées selon `oaBreakdown`. L'année en cours est incomplète.
	const currentYear = new Date().getFullYear();
	const yearLabels = $derived(years.map((y) => (y === currentYear ? `${y} (en cours)` : String(y))));
	const accessSeries = $derived(
		orderedPivotValues(oaBreakdown, chartRows).map((value, i) => ({
			label: pivotValueLabel(oaBreakdown, value),
			color: pivotValueColor(oaBreakdown, value, i),
			values: years.map((y) => sum(chartRows.filter((r) => r.year === y && r[oaBreakdown] === value))),
		})),
	);

	const typeValues = $derived(orderedPivotValues('doc_type_grouped', types));
	const topCountries = $derived(countries ? (collab?.rows ?? []).slice(0, 5) : []);
</script>

{#if !loaded}
	<div class="loading">Chargement…</div>
{:else}
	<KeyFigures items={keyFigures} />
	{#if years.length}
		<p class="dash-corpus">Publications parues de {years[0]} à {years[years.length - 1]}.</p>
	{/if}
	<div class="dash-grid">
		<div class="dash-card">
			<h2>Publications par année</h2>
			<StackedBarChart labels={yearLabels} series={accessSeries} />
		</div>
		{@render subjects?.()}
		<div class="dash-card">
			<h2>Types de documents</h2>
			<BarChart
				labels={typeValues.map((v) => pivotValueLabel('doc_type_grouped', v))}
				values={typeValues.map((v) => sum(types.filter((r) => r.doc_type_grouped === v)))}
				color={typeValues.map((v, i) => pivotValueColor('doc_type_grouped', v, i))}
				datasetLabel="Documents"
				horizontal
			/>
		</div>
		{#if topCountries.length}
			<div class="dash-card">
				<h2>Pays partenaires</h2>
				<BarChart
					labels={topCountries.map((c) => countryName(c.code) ?? c.code.toUpperCase())}
					values={topCountries.map((c) => c.value)}
					color={cssColor('doctype-article')}
					datasetLabel="Publications"
					horizontal
				/>
			</div>
		{/if}
	</div>
{/if}

<style>
	.dash-corpus {
		margin: -24px 0 24px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
</style>
