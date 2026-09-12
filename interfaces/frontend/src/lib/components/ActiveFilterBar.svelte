<script lang="ts">
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import { entityLabel } from '$lib/entityLabels';
	import {
		checkboxSummary,
		isActive,
		isAvailable,
		presenceSummary,
		type FilterValues,
		type ListFilter,
	} from '$lib/filterRegistry';

	/** Barre des filtres actifs : une pastille par filtre, qui retire ce filtre, et un bouton qui les retire tous. Les valeurs fixées par la page n'y figurent pas. */
	interface Props {
		filters: ListFilter[];
		values: FilterValues;
		/** Options des cases à cocher, par clé de filtre, pour afficher les libellés des valeurs. */
		options: Record<string, FacetOption[]>;
		onclear: (filter: ListFilter) => void;
		onclearall: () => void;
	}

	let { filters, values, options, onclear, onclearall }: Props = $props();

	const active = $derived(filters.filter((f) => isAvailable(f) && isActive(f, values)));

	// Libellés des entités sélectionnées (éditeur, revue, auteur), par `kind:id`.
	let entityLabels = $state<Record<string, string>>({});
	$effect(() => {
		for (const f of active) {
			if (f.control !== 'entity') continue;
			const id = values.entity[f.key];
			if (!id) continue;
			const key = `${f.entity}:${id}`;
			if (key in entityLabels) continue;
			entityLabel(f.entity, id)
				.then((label) => {
					entityLabels[key] = label ?? id;
				})
				.catch(() => {});
		}
	});

	function summary(f: ListFilter): string {
		if (f.control === 'checkbox') return checkboxSummary(f, values.checkbox[f.key] ?? [], options[f.key] ?? []);
		if (f.control === 'presence') return presenceSummary(f, values.presence[f.key] ?? {});
		const id = values.entity[f.key];
		return (id && entityLabels[`${f.entity}:${id}`]) || '…';
	}
</script>

{#if active.length}
	<div class="active-filters">
		<span class="active-filters-label">Filtres actifs&nbsp;:</span>
		{#each active as f (f.key)}
			{@const text = summary(f)}
			<button type="button" class="active-filter" title="Retirer ce filtre ({f.label} : {text})" onclick={() => onclear(f)}>
				<span class="active-filter-name">{f.label}&nbsp;:</span>
				<span class="active-filter-value">{text}</span>
				<span class="active-filter-remove" aria-hidden="true">✕</span>
			</button>
		{/each}
		<button type="button" class="clear-all" onclick={onclearall}>Supprimer les filtres</button>
	</div>
{/if}

<style>
	.active-filters {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		padding-top: 8px;
		border-top: 1px solid var(--border-subtle);
	}
	.active-filters-label {
		font-size: 0.9rem;
		color: var(--muted);
		white-space: nowrap;
	}
	.active-filter {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 320px;
		padding: 3px 8px 3px 10px;
		border: 1px solid var(--accent);
		border-radius: 12px;
		background: var(--accent-light);
		font: inherit;
		font-size: 0.85rem;
		color: var(--text);
		cursor: pointer;
	}
	.active-filter-name {
		font-weight: 600;
		white-space: nowrap;
	}
	.active-filter-value {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.active-filter-remove {
		flex-shrink: 0;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.active-filter:hover .active-filter-remove {
		color: var(--danger);
	}
	.clear-all {
		padding: 3px 4px;
		border: none;
		background: none;
		font: inherit;
		font-size: 0.85rem;
		color: var(--accent);
		text-decoration: underline;
		cursor: pointer;
	}
</style>
