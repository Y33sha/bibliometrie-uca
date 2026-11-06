<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import CheckboxOptions from '#lib/components/filters/CheckboxOptions.svelte';
	import EntityOptions from '#lib/components/filters/EntityOptions.svelte';
	import PresenceOptions from '#lib/components/filters/PresenceOptions.svelte';
	import RangeOptions from '#lib/components/filters/RangeOptions.svelte';
	import {
		filterGroups,
		isActive,
		isShown,
		type CheckboxFilter,
		type FilterGroup,
		type FilterValues,
		type ListFilter,
	} from '#lib/filterRegistry.js';
	import type { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';

	// Panneau des filtres d'une liste : les filtres du registre, par rubrique, chacun dépliable. Les décomptes suivent les filtres actifs.
	let {
		filters,
		groups,
		values = $bindable(),
		options,
		sourceCounts,
		entityEndpoint,
		buildParams,
		panel,
		onchange,
	}: {
		filters: ListFilter[];
		/** Rubriques du panneau, dans l'ordre d'affichage. */
		groups: readonly FilterGroup[];
		values: FilterValues;
		/** Options des cases à cocher, par clé de filtre. */
		options: Record<string, FacetOption[]>;
		/** Décomptes du filtre de présence des sources. */
		sourceCounts: Record<string, { yes: number; no: number }>;
		/** Base de la facette contextuelle des filtres d'entité. */
		entityEndpoint: string;
		/** Paramètres des filtres actifs, pour la facette contextuelle des entités. */
		buildParams: () => URLSearchParams;
		/** État du panneau : ouverture et filtres dépliés. */
		panel: ReturnType<typeof useFilterPanel>;
		/** Appelé après chaque changement de filtre. */
		onchange: () => void;
	} = $props();

	/** Options affichées d'un filtre à cases à cocher avant le bouton qui affiche les autres. */
	const OPTION_LIMIT = 6;

	// svelte-ignore state_referenced_locally
	const sections = filterGroups(filters, groups);
	const nonZeroOptions = (key: string): number => options[key]?.filter((o) => o.count).length ?? 0;

	/** Nombre affiché sur le nom d'un filtre actif : valeurs cochées, entités choisies, éléments filtrés ; un pour un intervalle. */
	function selectionCount(f: ListFilter): number {
		if (f.control === 'checkbox') return f.range ? 1 : (values.checkbox[f.key] ?? []).length;
		if (f.control === 'entity') return (values.entity[f.key] ?? []).length;
		return Object.keys(values.presence[f.key] ?? {}).length;
	}

	function onCheckboxChange(filter: CheckboxFilter, selected: string[]) {
		values.checkbox[filter.key] = filter.normalize ? filter.normalize(selected) : selected;
		onchange();
	}
</script>

<aside id="filter-panel" class="filter-panel" aria-label="Filtres">
	<div class="filter-panel-head">
		<span class="filter-panel-title">Filtres</span>
		<button type="button" class="btn-text filter-panel-close" onclick={() => (panel.open = false)}>Fermer</button>
	</div>
	{#each sections as s (s.group.key)}
		{@const shown = s.filters.filter((f) => isShown(f, values, nonZeroOptions, sourceCounts))}
		{#if shown.length}
			<section class="filter-group" aria-label={s.group.label}>
				<h2 class="filter-group-label">{s.group.label}</h2>
				{#each shown as f (f.key)}
					{@const open = panel.isExpanded(f.key, f.expanded ?? false)}
					{@const count = selectionCount(f)}
					<div class="filter-block">
						<button type="button" class="filter-head" aria-expanded={open} title={f.tooltip} onclick={() => panel.setExpanded(f.key, !open)}>
							<span class="filter-name">{f.label}</span>
							{#if count && isActive(f, values)}<span class="facet-badge">{count}</span>{/if}
							<span class="chevron" class:up={open} aria-hidden="true"></span>
						</button>
						{#if open}
							<div class="filter-body">
								{#if f.control === 'checkbox' && f.range}
									<RangeOptions options={options[f.key] ?? []} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
								{:else if f.control === 'checkbox'}
									<CheckboxOptions options={options[f.key] ?? []} searchable={f.searchable} groups={f.groups} groupSeparators limit={OPTION_LIMIT} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
								{:else if f.control === 'entity'}
									<EntityOptions endpoint={entityEndpoint} kind={f.entity} multiple={f.multiple} limit={OPTION_LIMIT} {buildParams} selected={values.entity[f.key]} onchange={(ids) => { values.entity[f.key] = ids; onchange(); }} />
								{:else}
									<PresenceOptions items={f.items} bind:states={values.presence[f.key]} counts={sourceCounts} {onchange} />
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/if}
	{/each}
</aside>

<style>
	.filter-panel {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding-bottom: 16px;
	}
	/* En-tête du panneau, sur écran étroit seulement : sur grand écran, le bouton de la barre d'outils nomme et ferme le panneau. */
	.filter-panel-head {
		display: none;
		align-items: baseline;
		justify-content: space-between;
		padding: 4px 0 6px;
	}
	.filter-panel-title {
		font-weight: 600;
		font-size: var(--fs-md);
	}
	.filter-group {
		padding-top: 8px;
	}
	.filter-group + .filter-group {
		border-top: 1px solid var(--border-subtle);
	}
	.filter-group-label {
		margin: 2px 0 2px;
		font-size: var(--fs-sm);
		font-weight: 600;
		color: var(--muted);
	}
	.filter-head {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 5px 0;
		border: none;
		background: none;
		font: inherit;
		font-size: var(--fs-md);
		font-weight: 600;
		color: var(--accent);
		text-align: left;
		cursor: pointer;
	}
	.filter-head:hover {
		color: color-mix(in srgb, var(--accent), black 20%);
	}
	.filter-head .chevron {
		margin-left: auto;
	}
	.filter-body {
		margin: 0 0 6px;
	}
	/* Les options s'alignent sur le nom du filtre. */
	.filter-body :global(.option-row) {
		padding: 3px 0;
	}
	.filter-body :global(.panel-search) {
		width: 100%;
		margin: 2px 0 6px;
	}
	@media not all and (min-width: 1100px) {
		.filter-panel-head {
			display: flex;
		}
	}
</style>
