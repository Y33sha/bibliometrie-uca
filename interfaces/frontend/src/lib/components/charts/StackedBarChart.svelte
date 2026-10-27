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

<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas}></canvas>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
