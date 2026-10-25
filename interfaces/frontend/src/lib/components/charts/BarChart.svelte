<script lang="ts">
	import { cssColor } from '#lib/components/charts/cssColor.js';
	import { Chart } from '#lib/components/charts/chart.js';

	let {
		labels,
		values,
		datasetLabel = '',
		color,
		horizontal = false,
		height = 280
	}: {
		labels: string[];
		values: number[];
		datasetLabel?: string;
		/** Couleur des barres ; défaut = variable CSS `--accent`. */
		color?: string;
		/** Barres horizontales (axe des valeurs en X). */
		horizontal?: boolean;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || values.length === 0) return;
		const barColor = color ?? cssColor('accent');
		const valueScale = { beginAtZero: true, ticks: { precision: 0 } };
		const categoryScale = { grid: { display: false } };

		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [{ label: datasetLabel, data: values, backgroundColor: barColor, borderRadius: 3 }]
			},
			options: {
				indexAxis: horizontal ? 'y' : 'x',
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { display: false },
					datalabels: { color: '#fff', font: { weight: 'bold', size: 12 } }
				},
				scales: horizontal
					? { x: valueScale, y: categoryScale }
					: { y: valueScale, x: categoryScale }
			}
		});
	}

	$effect(() => {
		void labels;
		void values;
		void color;
		void horizontal;
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
