<script lang="ts">
	import { Chart } from 'chart.js';
	import { ChoroplethController, GeoFeature, ColorScale, ProjectionScale } from 'chartjs-chart-geo';
	import { feature as topoFeature } from 'topojson-client';
	import type { Topology } from 'topojson-specification';
	import world from 'world-atlas/countries-110m.json';
	import iso from 'i18n-iso-countries';
	import frLocale from 'i18n-iso-countries/langs/fr.json';
	import { api } from '$lib/api';
	import type { components } from '$lib/api/schema';

	iso.registerLocale(frLocale);
	Chart.register(ChoroplethController, GeoFeature, ColorScale, ProjectionScale);

	type CollaborationsResponse = components['schemas']['CollaborationsResponse'];

	// Fraction du corpus filtré à laquelle l'échelle de couleur sature (teinte la plus foncée). En
	// indexant le maximum sur la taille du corpus plutôt que sur le pays le plus collaborateur, les
	// collaborations d'un ensemble peu ouvert restent claires au lieu de saturer. À régler ici.
	const SCALE_MAX_SHARE = 0.5;

	let { params = '' }: { params?: string } = $props();

	// Arrondit un maximum d'échelle à une borne lisible : centaine supérieure au-delà de 100, dizaine
	// supérieure en deçà. Plancher à 10 pour un corpus minuscule.
	function niceCeil(value: number): number {
		if (value <= 10) return 10;
		const step = value < 100 ? 10 : 100;
		return Math.ceil(value / step) * step;
	}

	let canvas: HTMLCanvasElement | undefined = $state();
	let chart: Chart | null = null;
	let countryCount = $state(0);
	let internationalCount = $state(0);
	let pctLabel = $state('');

	// Géométrie du monde : convertie une fois depuis le TopoJSON vers des entités GeoJSON. Les entités
	// sont indexées par code ISO 3166-1 numérique (`feature.id`), d'où le mapping alpha-2 → numérique.
	const topology = world as unknown as Topology;
	const features = (
		topoFeature(topology, topology.objects.countries) as unknown as {
			features: { id: string; properties: { name: string } }[];
		}
	).features;

	// Libellé français d'un pays à partir de son code numérique ; repli sur le nom porté par la carte.
	function frenchName(numericId: string, fallback: string): string {
		const alpha2 = iso.numericToAlpha2(numericId.padStart(3, '0'));
		return (alpha2 && iso.getName(alpha2, 'fr')) || fallback;
	}

	async function render(query: string) {
		const res = await api<CollaborationsResponse>('/api/stats/collaborations?' + query);
		// Décomptes indexés par code numérique (comparaison sur `Number`, pour ignorer les zéros de
		// tête : `alpha2ToNumeric` renvoie « 004 » là où la carte porte « 4 »).
		const byNumeric = new Map<number, number>();
		for (const row of res.rows) {
			const numeric = iso.alpha2ToNumeric(row.code.toUpperCase());
			if (numeric) byNumeric.set(Number(numeric), row.value);
		}
		countryCount = res.rows.length;
		internationalCount = res.international_count;
		pctLabel = res.total_count
			? ((res.international_count / res.total_count) * 100).toLocaleString('fr-FR', {
					maximumFractionDigits: 1
				})
			: '0';

		// Échelle de couleur : départ à 0, graduations entières, maximum proportionnel à la taille du
		// corpus filtré et arrondi à une borne lisible.
		const colorMax = niceCeil(res.total_count * SCALE_MAX_SHARE);

		const labels = features.map((f) => frenchName(String(f.id), f.properties.name));
		// Les pays sans collaboration reçoivent `null` : la couleur « missing » (neutre) les distingue
		// du dégradé, qui ne s'applique qu'aux pays effectivement co-affiliés.
		const data = features.map((f) => ({ feature: f, value: byNumeric.get(Number(f.id)) ?? null }));

		if (chart) chart.destroy();
		if (!canvas) return;
		chart = new Chart(canvas, {
			type: 'choropleth',
			data: { labels, datasets: [{ label: 'Collaborations', outline: features, data }] },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				showOutline: true,
				showGraticule: false,
				plugins: {
					legend: { display: false },
					datalabels: { display: false },
					tooltip: {
						callbacks: {
							label: (ctx: {
								raw: { value: number | null };
								dataIndex: number;
								chart: Chart;
							}) => {
								const value = ctx.raw.value;
								const name = ctx.chart.data.labels?.[ctx.dataIndex] ?? '';
								return value == null ? `${name} : —` : `${name} : ${value}`;
							}
						}
					}
				},
				scales: {
					projection: { axis: 'x', projection: 'naturalEarth1' },
					color: {
						axis: 'x',
						interpolate: 'blues',
						missing: '#ececec',
						min: 0,
						max: colorMax,
						ticks: { precision: 0 },
						legend: { position: 'bottom-right', align: 'bottom' }
					}
				}
			}
		} as never);
	}

	$effect(() => {
		const query = params;
		void render(query);
		return () => {
			if (chart) {
				chart.destroy();
				chart = null;
			}
		};
	});
</script>

<div class="collab-map">
	<canvas bind:this={canvas}></canvas>
</div>
{#if internationalCount}
	<p class="collab-caption">
		{internationalCount.toLocaleString('fr-FR')} publications en collaboration internationale, soit
		{pctLabel}&nbsp;% · {countryCount} pays
	</p>
{/if}

<style>
	.collab-map {
		position: relative;
		width: 100%;
		flex: 1 1 auto;
		min-height: 360px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
	}
	.collab-caption {
		text-align: center;
		color: var(--text-muted, #666);
		font-size: 0.85rem;
		margin-top: 0.5rem;
	}
</style>
