<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import { rangeBounds, rangeSelection } from '#lib/filterRegistry.js';

	// Options d'un filtre d'intervalle (années) : histogramme des décomptes, intervalle choisi par ses bornes. La sélection est la liste des valeurs de l'intervalle.
	interface Props {
		/** Options de valeur entière, avec leur décompte. */
		options: FacetOption[];
		/** Valeurs sélectionnées. Une sélection vide ne filtre rien. */
		selected?: string[];
		onchange?: (selected: string[]) => void;
	}

	let { options, selected = $bindable([]), onchange }: Props = $props();

	const counts = $derived(
		new Map(options.filter((o) => o.count).map((o) => [Number(o.value), o.count ?? 0])),
	);
	const available = $derived([...counts.keys()].sort((a, b) => a - b));
	const first = $derived(available[0]);
	const last = $derived(available[available.length - 1]);
	// Toutes les valeurs entre la première et la dernière : une valeur sans décompte garde sa place dans l'histogramme.
	const span = $derived(available.length ? rangeSelection(first, last).map(Number) : []);
	const maxCount = $derived(Math.max(1, ...counts.values()));

	// Bornes affichées : celles de la sélection, ou les extrémités quand rien n'est sélectionné.
	const bounds = $derived(rangeBounds(selected) ?? (selected.length ? [Math.min(...selected.map(Number)), Math.max(...selected.map(Number))] : null));
	const from = $derived(bounds?.[0] ?? first);
	const to = $derived(bounds?.[1] ?? last);

	function inRange(year: number): boolean {
		return selected.length > 0 && year >= from && year <= to;
	}

	function set(newFrom: number, newTo: number) {
		const [a, b] = newFrom <= newTo ? [newFrom, newTo] : [newTo, newFrom];
		selected = a === first && b === last ? [] : rangeSelection(a, b);
		onchange?.(selected);
	}

	function clear() {
		selected = [];
		onchange?.(selected);
	}
</script>

{#if selected.length}
	<button type="button" class="option-row facet-clear" onclick={clear}>Effacer</button>
{/if}
{#if span.length}
	<div class="histogram" aria-hidden="true">
		{#each span as year (year)}
			{@const c = counts.get(year) ?? 0}
			<span class="bar" class:in-range={inRange(year)} style:height="{Math.max(c ? 4 : 0, (c / maxCount) * 100)}%" title="{year} : {c.toLocaleString('fr-FR')}"></span>
		{/each}
	</div>
	<div class="bounds">
		<label>De
			<select class="select" aria-label="Première année" value={from} onchange={(e) => set(Number(e.currentTarget.value), to)}>
				{#each span as year (year)}<option value={year}>{year}</option>{/each}
			</select>
		</label>
		<label>à
			<select class="select" aria-label="Dernière année" value={to} onchange={(e) => set(from, Number(e.currentTarget.value))}>
				{#each span as year (year)}<option value={year}>{year}</option>{/each}
			</select>
		</label>
	</div>
{/if}

<style>
	.histogram {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 44px;
		margin: 4px 0 6px;
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
	.bounds {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		font-size: var(--fs-sm);
		color: var(--muted);
	}
	.bounds label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.bounds .select {
		height: 28px;
		font-size: var(--fs-sm);
	}
</style>
