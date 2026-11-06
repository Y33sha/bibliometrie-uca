<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import { rangeSelection } from '#lib/filterRegistry.js';

	// Options d'un filtre d'intervalle (années) : histogramme des décomptes, et curseur à deux poignées qui fixe les bornes de l'intervalle. La sélection est la liste des valeurs de l'intervalle.
	interface Props {
		/** Options de valeur entière, avec leur décompte. */
		options: FacetOption[];
		/** Valeurs sélectionnées. Une sélection vide ne filtre rien. */
		selected?: string[];
		onchange?: (selected: string[]) => void;
	}

	let { options, selected = $bindable([]), onchange }: Props = $props();

	const counts = $derived(new Map(options.filter((o) => o.count).map((o) => [Number(o.value), o.count ?? 0])));
	const available = $derived([...counts.keys()].sort((a, b) => a - b));
	const first = $derived(available[0]);
	const last = $derived(available[available.length - 1]);
	// Toutes les valeurs entre la première et la dernière : une valeur sans décompte garde sa place dans l'histogramme.
	const span = $derived(available.length ? rangeSelection(first, last).map(Number) : []);
	const maxCount = $derived(Math.max(1, ...counts.values()));

	// Bornes de la sélection, ou extrémités quand rien n'est sélectionné.
	const selectedYears = $derived(selected.map(Number));
	const selectedFrom = $derived(selected.length ? Math.min(...selectedYears) : first);
	const selectedTo = $derived(selected.length ? Math.max(...selectedYears) : last);

	// Bornes des poignées : elles suivent le glissement, et la sélection change au relâchement.
	let dragFrom = $state<number | null>(null);
	let dragTo = $state<number | null>(null);
	const from = $derived(dragFrom ?? selectedFrom);
	const to = $derived(dragTo ?? selectedTo);
	const filtered = $derived(selected.length > 0 || dragFrom !== null || dragTo !== null);

	function commit() {
		const [a, b] = [Math.min(from, to), Math.max(from, to)];
		dragFrom = dragTo = null;
		const next = a === first && b === last ? [] : rangeSelection(a, b);
		if (next.join() === selected.join()) return;
		selected = next;
		onchange?.(selected);
	}

	function clear() {
		selected = [];
		onchange?.(selected);
	}
</script>

{#if span.length}
	<div class="range">
		<div class="range-head">
			<span class="range-value" class:filtered>{filtered ? (Math.min(from, to) === Math.max(from, to) ? from : `${Math.min(from, to)} – ${Math.max(from, to)}`) : 'Toutes les années'}</span>
			{#if selected.length}<button type="button" class="btn-text facet-clear" onclick={clear}>Effacer</button>{/if}
		</div>
		<div class="histogram" aria-hidden="true">
			{#each span as year (year)}
				{@const c = counts.get(year) ?? 0}
				<span class="bar" class:in-range={filtered && year >= Math.min(from, to) && year <= Math.max(from, to)} style:height="{c ? Math.max(4, (c / maxCount) * 100) : 0}%" title="{year} : {c.toLocaleString('fr-FR')}"></span>
			{/each}
		</div>
		<div class="slider">
			<input type="range" aria-label="Première année" min={first} max={last} step="1" value={from} oninput={(e) => (dragFrom = Number(e.currentTarget.value))} onchange={commit} />
			<input type="range" aria-label="Dernière année" min={first} max={last} step="1" value={to} oninput={(e) => (dragTo = Number(e.currentTarget.value))} onchange={commit} />
		</div>
		<div class="ends" aria-hidden="true"><span>{first}</span><span>{last}</span></div>
	</div>
{/if}

<style>
	.range {
		--thumb: 14px;
		padding-top: 2px;
	}
	.range-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		font-size: var(--fs-sm);
	}
	.range-value {
		color: var(--muted);
	}
	.range-value.filtered {
		color: var(--text);
		font-weight: 600;
	}
	/* Histogramme aligné sur la course des poignées : une demi-poignée de marge de chaque côté. */
	.histogram {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 40px;
		margin: 6px calc(var(--thumb) / 2) 0;
	}
	.bar {
		flex: 1;
		min-width: 0;
		border-radius: 1px 1px 0 0;
		background: var(--border);
	}
	.bar.in-range {
		background: var(--accent-mid);
	}
	/* Deux curseurs superposés : seule la poignée de chacun capte le pointeur. */
	.slider {
		position: relative;
		height: 18px;
	}
	.slider input[type='range'] {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 18px;
		margin: 0;
		background: transparent;
		appearance: none;
		pointer-events: none;
	}
	.slider input[type='range']:first-child::-webkit-slider-runnable-track {
		height: 2px;
		background: var(--border);
	}
	.slider input[type='range']:first-child::-moz-range-track {
		height: 2px;
		background: var(--border);
	}
	.slider input[type='range']::-webkit-slider-thumb {
		appearance: none;
		width: var(--thumb);
		height: var(--thumb);
		margin-top: calc((2px - var(--thumb)) / 2);
		border: 2px solid var(--card);
		border-radius: 50%;
		background: var(--accent);
		box-shadow: var(--shadow-sm);
		cursor: grab;
		pointer-events: auto;
	}
	.slider input[type='range']::-moz-range-thumb {
		width: var(--thumb);
		height: var(--thumb);
		border: 2px solid var(--card);
		border-radius: 50%;
		background: var(--accent);
		cursor: grab;
		pointer-events: auto;
	}
	.slider input[type='range']:focus-visible::-webkit-slider-thumb {
		box-shadow: var(--focus-ring);
	}
	.ends {
		display: flex;
		justify-content: space-between;
		font-size: var(--fs-xs);
		color: var(--muted);
	}
</style>
