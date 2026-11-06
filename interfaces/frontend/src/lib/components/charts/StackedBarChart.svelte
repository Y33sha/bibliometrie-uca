<script lang="ts">
	import { Chart, stackedSegmentOptions } from '#lib/components/charts/chart.js';
	import ChartLegend from '#lib/components/charts/ChartLegend.svelte';

	// Barres verticales empilées : une série par segment, la légende sous le graphique.
	let {
		labels,
		series,
		height = 280,
	}: {
		labels: string[];
		/** Un segment de chaque barre : `values` suit `labels`. `description` s'affiche au survol de la légende et du segment. */
		series: { label: string; values: number[]; color: string; description?: string }[];
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || labels.length === 0) return;
		const segment = stackedSegmentOptions(canvas);
		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: series.map((s) => ({ label: s.label, data: s.values, backgroundColor: s.color, ...segment })),
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { display: false },
					tooltip: { callbacks: { afterLabel: (ctx) => series[ctx.datasetIndex]?.description ?? '' } },
					datalabels: { display: false },
				},
				scales: {
					x: { stacked: true, grid: { display: false } },
					y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
				},
			},
		});
	}

	$effect(() => {
		void labels;
		void series;
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
			{#each labels as label, i (i)}
				<tr>
					<th scope="row">{label}</th>
					{#each series as s (s.label)}<td>{s.values[i]}</td>{/each}
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
