<script lang="ts">
	import { cssVar } from '#lib/components/charts/cssVar.js';
	import type { LegendItem } from 'chart.js';
	import { Chart } from '#lib/components/charts/chart.js';

	export type DoughnutSegment = {
		label: string;
		value: number;
		/** Couleur explicite (ex. statut OA sémantique) ; sinon palette tournante. */
		color?: string;
		/** Quand `flagAnomalies` est actif, un segment `expected === false` est stylé en alerte. */
		expected?: boolean;
	};

	let {
		segments,
		flagAnomalies = false,
		height = 280
	}: {
		segments: DoughnutSegment[];
		flagAnomalies?: boolean;
		height?: number;
	} = $props();

	// Palette neutre tournante pour les distributions sans couleur sémantique (doc_types, serial_types). Stable par position.
	const PALETTE = [
		'#2f8a8a',
		'#2a7d4f',
		'#b08900',
		'#7c3aed',
		'#0369a1',
		'#be123c',
		'#b45309',
		'#0f766e',
		'#9333ea',
		'#64748b'
	];

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	function isAnomaly(seg: DoughnutSegment): boolean {
		return flagAnomalies && seg.expected === false;
	}

	function colorFor(seg: DoughnutSegment, index: number): string {
		if (isAnomaly(seg)) return cssVar('danger');
		return seg.color ?? PALETTE[index % PALETTE.length];
	}

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas) return;
		// On masque les modalités à 0 cas (cohérent avec les dashboards existants).
		const data = segments.filter((s) => s.value > 0);
		if (data.length === 0) return;
		const colors = data.map((s, i) => colorFor(s, i));

		chart = new Chart(canvas, {
			type: 'doughnut',
			data: {
				labels: data.map((s) => s.label),
				datasets: [{ data: data.map((s) => s.value), backgroundColor: colors }]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: {
						position: 'bottom',
						labels: {
							generateLabels: (): LegendItem[] =>
								data.map((s, i) => ({
									text: isAnomaly(s) ? `⚠ ${s.label}` : s.label,
									fillStyle: colors[i],
									strokeStyle: colors[i],
									lineWidth: 0,
									fontColor: isAnomaly(s) ? cssVar('danger') : undefined,
									hidden: false,
									index: i
								}))
						}
					},
					datalabels: {
						color: '#fff',
						font: { weight: 'bold', size: 13 },
						formatter: (value: number, ctx: any) => {
							const total = ctx.dataset.data.reduce((a: number, b: number) => a + b, 0);
							const pct = total > 0 ? Math.round((value / total) * 100) : 0;
							return pct > 3 ? `${pct}%` : '';
						}
					}
				}
			}
		});
	}

	$effect(() => {
		// Dépendances : re-render quand les données, le mode anomalie ou le canvas changent.
		void segments;
		void flagAnomalies;
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
	{#if segments.filter((s) => s.value > 0).length === 0}
		<p class="empty">Aucune donnée</p>
	{/if}
	<canvas bind:this={canvas}></canvas>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
	.empty {
		color: var(--muted);
		font-size: 0.9rem;
		margin: 0;
	}
</style>
