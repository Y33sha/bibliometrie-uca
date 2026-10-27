<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import PresenceFilterToggle from '#lib/components/PresenceFilterToggle.svelte';
	import { PUBLICATION_FACETS_ENDPOINT } from '#lib/composables/usePublicationFacets.svelte.js';
	import {
		filterSections,
		isActive,
		isAvailable,
		isShown,
		type CheckboxFilter,
		type EntityChoiceFilter,
		type FilterValues,
		type ListFilter,
	} from '#lib/filterRegistry.js';

	// Barre de filtres des publications, partagée par la liste des publications et la page Statistiques : les contrôles de la barre principale et le panneau « Plus de filtres ». Chaque page place la barre des filtres actifs (`ActiveFilterBar`).
	let {
		filters,
		values = $bindable(),
		options,
		sourceCounts,
		buildParams,
		onchange,
		leading,
	}: {
		filters: ListFilter[];
		values: FilterValues;
		/** Options des cases à cocher, par clé de filtre. */
		options: Record<string, FacetOption[]>;
		/** Décomptes du filtre de présence des sources. */
		sourceCounts: Record<string, { yes: number; no: number }>;
		/** Paramètres des filtres actifs, pour la facette contextuelle des entités. */
		buildParams: () => URLSearchParams;
		/** Appelé après chaque changement de filtre. */
		onchange: () => void;
		/** Contrôles placés en tête de la barre principale. */
		leading?: Snippet;
	} = $props();

	// svelte-ignore state_referenced_locally
	const sections = filterSections(filters);
	let showMoreFilters = $state(false);
	const moreFiltersActive = $derived(
		sections.groups.flatMap((g) => g.filters).filter((f) => isAvailable(f) && isActive(f, values)).length,
	);
	const optionCount = (key: string): number => options[key]?.length ?? 0;

	function onCheckboxChange(filter: CheckboxFilter, selected: string[]) {
		values.checkbox[filter.key] = filter.normalize ? filter.normalize(selected) : selected;
		onchange();
	}

	function onEntityChange(filter: EntityChoiceFilter, ids: string[]) {
		values.entity[filter.key] = ids;
		onchange();
	}

</script>

<div class="toolbar">
	<span class="filters-label">Filtrer par&nbsp;:</span>
	{@render leading?.()}
	{#each sections.primary as f (f.key)}
		{#if isShown(f, optionCount)}{@render filterControl(f)}{/if}
	{/each}
	<button type="button" class="more-filters-btn" class:open={showMoreFilters} aria-expanded={showMoreFilters} onclick={() => (showMoreFilters = !showMoreFilters)}>
		{showMoreFilters ? 'Cacher les filtres' : 'Plus de filtres'}
		{#if moreFiltersActive > 0}<span class="facet-badge">{moreFiltersActive}</span>{/if}
		<span class="chevron" class:up={showMoreFilters} aria-hidden="true"></span>
	</button>
</div>
{#if showMoreFilters}
	<div class="more-filters">
		{#each sections.groups as g (g.label)}
			{@const shown = g.filters.filter((f) => isShown(f, optionCount))}
			{#if shown.length}
				<div class="filter-group" role="group" aria-label={g.label} title={g.label}>
					{#each shown as f (f.key)}{@render filterControl(f)}{/each}
				</div>
			{/if}
		{/each}
	</div>
{/if}

{#snippet filterControl(f: ListFilter)}
	{#if f.control === 'checkbox'}
		<FacetDropdown label={f.label} options={options[f.key] ?? []} searchable={f.searchable} groups={f.groups} tooltip={f.tooltip} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
	{:else if f.control === 'entity'}
		<EntityFilter label={f.label} endpoint={PUBLICATION_FACETS_ENDPOINT} kind={f.entity} multiple={f.multiple} {buildParams} selected={values.entity[f.key]} onchange={(ids) => onEntityChange(f, ids)} />
	{:else}
		<PresenceFilterToggle label={f.label} items={f.items} bind:states={values.presence[f.key]} counts={sourceCounts} onchange={onchange} />
	{/if}
{/snippet}

<style>
	.toolbar {
		margin-bottom: 0;
	}
	.filters-label {
		font-size: 0.9rem;
		color: var(--muted);
		white-space: nowrap;
	}
	.more-filters-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: 34px;
		padding: 0 10px;
		border: none;
		border-radius: var(--radius);
		background: none;
		font: inherit;
		font-size: 0.9rem;
		color: var(--text-secondary);
		white-space: nowrap;
		cursor: pointer;
	}
	.more-filters-btn:hover,
	.more-filters-btn.open { background: var(--hover); }
	/* Facettes optionnelles sur une ligne, rubriques séparées par un filet vertical. */
	.more-filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 0;
	}
	.filter-group { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
	.filter-group + .filter-group {
		margin-left: 10px;
		padding-left: 10px;
		border-left: 1px solid var(--border);
	}
</style>
