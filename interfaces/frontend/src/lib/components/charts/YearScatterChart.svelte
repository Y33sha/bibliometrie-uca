<script lang="ts">
	import { cssColor } from '#lib/components/charts/cssVar.js';
	import { Chart } from '#lib/components/charts/chart.js';

	// Nuage de points par année : un point par élément, décalé dans la largeur de son année pour limiter les recouvrements.
	// `detail` s'affiche sous `label` dans l'infobulle.
	type Point = { key: number; year: number; value: number; label: string; detail?: string | null };
	// Coordonnées d'un point du canevas ; `point` manque sur la ligne de référence.
	type Datum = { x: number; y: number; point?: Point };

	let {
		points,
		valueLabel,
		reference,
		height = 320,
	}: {
		points: Point[];
		/** Nom de la valeur, titre de l'axe vertical. */
		valueLabel: string;
		/** Valeur de référence, tracée en pointillés. */
		reference?: number;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	// Décalage dans ]-0,35 ; 0,35[, fixe pour un élément donné : le nuage garde sa forme d'un affichage à l'autre.
	const jitter = (key: number) => (((key * 2654435761) >>> 0) / 2 ** 32 - 0.5) * 0.7;

	const years = $derived([...new Set(points.map((p) => p.year))].sort((a, b) => a - b));

	function median(values: number[]): number {
		const sorted = [...values].sort((a, b) => a - b);
		const mid = Math.floor(sorted.length / 2);
		return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
	}

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || points.length === 0) return;
		const color = cssColor('accent-mid');
		const minX = years[0] - 0.5;
		const maxX = years[years.length - 1] + 0.5;
		const scattered: Datum[] = points.map((p) => ({ x: p.year + jitter(p.key), y: p.value, point: p }));
		const referenceLine: Datum[] = reference === undefined ? [] : [{ x: minX, y: reference }, { x: maxX, y: reference }];
		chart = new Chart(canvas, {
			type: 'scatter',
			data: {
				datasets: [
					{
						label: valueLabel,
						data: scattered,
						backgroundColor: `${color}80`,
						borderWidth: 0,
						pointRadius: 3,
						pointHoverRadius: 6,
						pointHoverBackgroundColor: color,
					},
					...(referenceLine.length
						? [
								{
									type: 'line' as const,
									label: 'Référence',
									data: referenceLine,
									borderColor: cssColor('text-secondary'),
									borderWidth: 1,
									borderDash: [4, 4],
									pointRadius: 0,
									pointHitRadius: 0,
								},
							]
						: []),
				],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				plugins: {
					legend: { display: false },
					datalabels: { display: false },
					tooltip: {
						displayColors: false,
						filter: (item) => item.datasetIndex === 0,
						callbacks: {
							title: (items) => {
								const label = (items[0].raw as Datum).point?.label ?? '';
								return label.length > 90 ? `${label.slice(0, 90)}…` : label;
							},
							label: (item) => {
								const point = (item.raw as Datum).point;
								if (!point) return '';
								const value = `${valueLabel} : ${point.value.toLocaleString('fr-FR')} (${point.year})`;
								return point.detail ? [point.detail, value] : value;
							},
						},
					},
				},
				scales: {
					x: {
						type: 'linear',
						min: minX,
						max: maxX,
						grid: { display: false },
						ticks: {
							stepSize: 1,
							callback: (value) => (Number.isInteger(value) ? String(value) : ''),
						},
					},
					y: {
						beginAtZero: true,
						title: { display: true, text: valueLabel },
					},
				},
			},
		});
	}

	$effect(() => {
		void points;
		void valueLabel;
		void reference;
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

<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le résumé par année. -->
<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>
<div class="visually-hidden">
	<table>
		<thead>
			<tr><th scope="col">Année</th><th scope="col">Nombre</th><th scope="col">{valueLabel} médian</th></tr>
		</thead>
		<tbody>
			{#each years as year (year)}
				{@const values = points.filter((p) => p.year === year).map((p) => p.value)}
				<tr><th scope="row">{year}</th><td>{values.length}</td><td>{median(values)}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
