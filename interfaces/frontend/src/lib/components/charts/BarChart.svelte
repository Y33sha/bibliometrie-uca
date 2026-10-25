<script lang="ts">
	import { cssVar } from '#lib/components/charts/cssVar.js';
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
		/** Couleur des barres, unique ou une par barre ; défaut = variable CSS `--accent-mid`. */
		color?: string | string[];
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
		const barColor = color ?? cssVar('accent-mid');
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
				// Place pour les valeurs affichées au bout des barres.
				layout: { padding: horizontal ? { right: 32 } : { top: 20 } },
				plugins: {
					legend: { display: false },
					datalabels: { anchor: 'end', align: 'end', font: { weight: 600, size: 11 } }
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
