<script lang="ts">
	import { Chart } from '#lib/components/charts/chart.js';

	// Barres verticales empilées : une série par segment, la légende sous le graphique.
	let {
		labels,
		series,
		height = 280,
	}: {
		labels: string[];
		/** Un segment de chaque barre : `values` suit `labels`. */
		series: { label: string; values: number[]; color: string }[];
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
		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: series.map((s) => ({ label: s.label, data: s.values, backgroundColor: s.color })),
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { position: 'bottom', labels: { boxWidth: 12 } },
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
