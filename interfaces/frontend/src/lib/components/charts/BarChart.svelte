<script lang="ts">
	import { cssColor } from '#lib/components/charts/cssVar.js';
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
		const barColor = color ?? cssColor('accent-mid');
		const valueScale = { beginAtZero: true, ticks: { precision: 0 } };
		const categoryScale = { grid: { display: false } };

		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [{ label: datasetLabel, data: values, backgroundColor: barColor }]
			},
			options: {
				indexAxis: horizontal ? 'y' : 'x',
				responsive: true,
				maintainAspectRatio: false,
				// Place pour les valeurs affichées au bout des barres.
				layout: { padding: horizontal ? { right: 32 } : { top: 20 } },
				plugins: {
					legend: { display: false },
					datalabels: { anchor: 'end', align: 'end', font: { weight: 600 } }
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

<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>
<div class="visually-hidden">
	<table>
		<thead>
			<tr><td></td><th scope="col">{datasetLabel || 'Nombre'}</th></tr>
		</thead>
		<tbody>
			{#each labels as label, i (i)}
				<tr><th scope="row">{label}</th><td>{values[i]}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
