<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';

	// Options d'un filtre à cases à cocher : recherche, « Effacer », options avec leur décompte. Une option de décompte nul est omise, sauf cochée. Partagé par la liste déroulante d'un filtre et le panneau des filtres.
	interface Props {
		options: FacetOption[];
		searchable?: boolean;
		/** Valeurs cochées. Une sélection vide ne filtre rien. */
		selected?: string[];
		/** Options regroupées (ex. familles de types de document). Les options hors groupe suivent. Le regroupement est seulement visuel. */
		groups?: { label: string; values: string[] }[];
		/** Groupes séparés par un filet seul, sans leur nom. */
		groupSeparators?: boolean;
		/** Nombre d'options affichées avant le bouton qui affiche les autres. Les options cochées restent toujours affichées. Sans valeur, toutes les options s'affichent. */
		limit?: number;
		onchange?: (selected: string[]) => void;
	}

	let { options, searchable = false, selected = $bindable([]), groups, groupSeparators = false, limit, onchange }: Props = $props();

	/** Nombre d'options au-delà duquel une liste sans limite propose la recherche. */
	const SEARCH_THRESHOLD = 10;

	let filterText = $state('');
	let showAll = $state(false);

	const available = $derived(options.filter((o) => o.count !== 0 || selected.includes(o.value)));
	// La recherche sert quand des options sont masquées, ou quand la liste est longue.
	const showSearch = $derived(searchable && available.length > (limit ?? SEARCH_THRESHOLD));
	const matching = $derived(
		filterText ? available.filter((o) => o.text.toLowerCase().includes(filterText.toLowerCase())) : available,
	);
	const truncated = $derived(limit !== undefined && !showAll && !filterText && matching.length > limit);
	const shown = $derived(
		truncated ? matching.filter((o, i) => i < limit! || selected.includes(o.value)) : matching,
	);
	const hiddenCount = $derived(matching.length - shown.length);
	// Options de chaque groupe affiché, puis options hors groupe.
	const sections = $derived.by(() => {
		if (!groups) return [{ label: '', options: shown }];
		const grouped = groups.map((g) => ({ label: g.label, options: shown.filter((o) => g.values.includes(o.value)) }));
		const rest = shown.filter((o) => !groups.some((g) => g.values.includes(o.value)));
		return [...grouped, { label: '', options: rest }].filter((s) => s.options.length);
	});

	function toggle(value: string) {
		selected = selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
		onchange?.(selected);
	}

	function clear() {
		selected = [];
		onchange?.(selected);
	}
</script>

{#if showSearch}
	<input type="text" class="panel-search input-sm" placeholder="Filtrer" aria-label="Filtrer les options" bind:value={filterText} />
{/if}
{#if selected.length}
	<button type="button" class="option-row facet-clear" onclick={clear}>Effacer</button>
{/if}
<div class="facet-options">
	{#each sections as s, i (s.label)}
		{#if groupSeparators}
			{#if i > 0}<div class="facet-group-separator" role="separator"></div>{/if}
		{:else if s.label}
			<div class="facet-group-label">{s.label}</div>
		{/if}
		{#each s.options as opt (opt.value)}
			<label class="option-row">
				<input type="checkbox" checked={selected.includes(opt.value)} onchange={() => toggle(opt.value)} />
				<span class="facet-option-text" title={opt.text}>{opt.text}</span>{#if opt.count != null}<span class="facet-count">{opt.count.toLocaleString('fr-FR')}</span>{/if}
			</label>
		{/each}
	{/each}
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
	.facet-group-separator {
		margin: 3px 0;
		border-top: 1px solid var(--border-subtle);
	}
</style>
