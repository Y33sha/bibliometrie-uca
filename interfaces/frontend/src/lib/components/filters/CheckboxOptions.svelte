<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';

	// Options d'un filtre à cases à cocher : recherche, « Effacer », options avec leur décompte. Partagé par la liste déroulante d'un filtre et le panneau des filtres.
	interface Props {
		options: FacetOption[];
		searchable?: boolean;
		/** Valeurs cochées. Une sélection vide ne filtre rien. */
		selected?: string[];
		/** En-têtes des options regroupées (ex. familles de types de document). Les options hors groupe suivent, sans en-tête. Le regroupement est seulement visuel. */
		groups?: { label: string; values: string[] }[];
		/** Nombre d'options affichées avant le bouton qui affiche les autres. Les options cochées restent toujours affichées. Sans valeur, toutes les options s'affichent. */
		limit?: number;
		/** Barre sous chaque option, de longueur proportionnelle à son décompte. */
		bars?: boolean;
		onchange?: (selected: string[]) => void;
	}

	let { options, searchable = false, selected = $bindable([]), groups, limit, bars = false, onchange }: Props = $props();

	let filterText = $state('');
	let showAll = $state(false);

	const matching = $derived(
		filterText ? options.filter((o) => o.text.toLowerCase().includes(filterText.toLowerCase())) : options,
	);
	const truncated = $derived(limit !== undefined && !showAll && !filterText && matching.length > limit);
	const shown = $derived(
		truncated ? matching.filter((o, i) => i < limit! || selected.includes(o.value)) : matching,
	);
	const hiddenCount = $derived(matching.length - shown.length);
	const maxCount = $derived(Math.max(1, ...options.map((o) => o.count ?? 0)));
	const ungrouped = $derived(groups ? shown.filter((o) => !groups.some((g) => g.values.includes(o.value))) : shown);

	function toggle(value: string) {
		selected = selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
		onchange?.(selected);
	}

	function clear() {
		selected = [];
		onchange?.(selected);
	}
</script>

{#snippet optionRow(opt: FacetOption)}
	<label class="option-row" class:with-bar={bars}>
		<input type="checkbox" checked={selected.includes(opt.value)} onchange={() => toggle(opt.value)} />
		<span class="facet-option-text" title={opt.text}>{opt.text}</span>{#if opt.count != null}<span class="facet-count">{opt.count.toLocaleString('fr-FR')}</span>{/if}
		{#if bars && opt.count != null}<span class="option-bar" class:checked={selected.includes(opt.value)} style:width="{(opt.count / maxCount) * 100}%" aria-hidden="true"></span>{/if}
	</label>
{/snippet}

{#if searchable}
	<input type="text" class="panel-search input-sm" placeholder="Filtrer" aria-label="Filtrer les options" bind:value={filterText} />
{/if}
{#if selected.length}
	<button type="button" class="option-row facet-clear" onclick={clear}>Effacer</button>
{/if}
<div class="facet-options">
	{#if groups}
		{#each groups as g (g.label)}
			{@const opts = shown.filter((o) => g.values.includes(o.value))}
			{#if opts.length}
				<div class="facet-group-label">{g.label}</div>
				{#each opts as opt (opt.value)}{@render optionRow(opt)}{/each}
			{/if}
		{/each}
	{/if}
	{#each ungrouped as opt (opt.value)}{@render optionRow(opt)}{/each}
</div>
{#if truncated && hiddenCount > 0}
	<button type="button" class="option-row facet-more" onclick={() => (showAll = true)}>{hiddenCount.toLocaleString('fr-FR')} autres</button>
{:else if showAll && limit !== undefined && !filterText}
	<button type="button" class="option-row facet-more" onclick={() => (showAll = false)}>Réduire</button>
{/if}

<style>
	.facet-group-label {
		margin-top: 4px;
		padding: 7px 12px 3px;
		border-top: 1px solid var(--border);
		font-size: var(--fs-sm);
		font-weight: 600;
		color: var(--muted);
	}
	.facet-options label {
		white-space: nowrap;
	}
	/* Barre de décompte : une deuxième ligne de la grille, sous le libellé. */
	.option-row.with-bar {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		column-gap: 6px;
		row-gap: 1px;
	}
	.option-bar {
		grid-column: 2;
		height: 2px;
		border-radius: 1px;
		background: var(--border);
	}
	.option-bar.checked {
		background: var(--accent-mid);
	}
	.facet-more {
		color: var(--accent);
		font-size: var(--fs-sm);
	}
</style>
