<script lang="ts">
	import { Chart } from '#lib/components/charts/chart.js';
	import ChartLegend from '#lib/components/charts/ChartLegend.svelte';

	// Courbes par année : une courbe par série, les années en abscisse, la légende sous le graphique. Une valeur `null` interrompt la courbe.
	let {
		years,
		series,
		format,
		detail,
		max,
		height = 280,
	}: {
		years: number[];
		/** `values` suit `years`. */
		series: { label: string; values: (number | null)[]; color: string }[];
		/** Écriture d'une valeur, sur l'axe vertical et dans l'infobulle. */
		format: (value: number) => string;
		/** Précision ajoutée à la valeur de la série `seriesIndex` pour l'année de rang `yearIndex`, dans l'infobulle. */
		detail?: (seriesIndex: number, yearIndex: number) => string;
		/** Borne haute de l'axe vertical. */
		max?: number;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || years.length === 0) return;
		chart = new Chart(canvas, {
			type: 'line',
			data: {
				labels: years.map(String),
				datasets: series.map((s) => ({
					label: s.label,
					data: s.values,
					borderColor: s.color,
					backgroundColor: s.color,
					borderWidth: 2,
					pointRadius: 4,
					pointHoverRadius: 6,
					pointHitRadius: 10,
					spanGaps: false,
				})),
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				// Infobulle de toutes les séries de l'année survolée.
				interaction: { mode: 'index', intersect: false },
				plugins: {
					legend: { display: false },
					datalabels: { display: false },
					tooltip: {
						itemSort: (a, b) => (b.parsed.y ?? 0) - (a.parsed.y ?? 0),
						callbacks: {
							label: (item) => {
								const value = `${item.dataset.label} : ${format(item.parsed.y ?? 0)}`;
								const extra = detail?.(item.datasetIndex, item.dataIndex);
								return extra ? `${value} (${extra})` : value;
							},
						},
					},
				},
				scales: {
					x: { grid: { display: false } },
					y: { beginAtZero: true, max, ticks: { callback: (value) => format(Number(value)) } },
				},
			},
		});
	}

	$effect(() => {
		void years;
		void series;
		void format;
		void detail;
		void max;
		void canvas;
		render();
		return () => {
			if (chart) {
				chart.destroy();
				chart = null;
			}
		};
	});
</script>

<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>
<ChartLegend items={series} centered />
<div class="visually-hidden">
	<table>
		<thead>
			<tr>
				<td></td>
				{#each series as s (s.label)}<th scope="col">{s.label}</th>{/each}
			</tr>
		</thead>
		<tbody>
			{#each years as year, i (year)}
				<tr>
					<th scope="row">{year}</th>
					{#each series as s (s.label)}{@const value = s.values[i]}<td>{value === null ? '' : format(value)}</td>{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
