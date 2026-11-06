<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import { revealTruncated } from '#lib/actions/revealTruncated.js';

	// Options d'un filtre à cases à cocher : recherche, « Effacer », options avec leur décompte. Une option de décompte nul est omise, sauf cochée ou déjà affichée : une option affichée reste à sa place, grisée, quand son décompte tombe à zéro, pour que la liste ne change pas de hauteur sous le pointeur. Partagé par la liste déroulante d'un filtre et le panneau des filtres.
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
		/** Bouton « Effacer » en tête des options. Le panneau des filtres le place sur la ligne du nom du filtre. */
		clearable?: boolean;
		onchange?: (selected: string[]) => void;
	}

	let { options, searchable = false, selected = $bindable([]), groups, groupSeparators = false, limit, clearable = true, onchange }: Props = $props();

	// Options déjà affichées.
	const seen = new SvelteSet<string>();

	/** Nombre d'options au-delà duquel une liste sans limite propose la recherche. */
	const SEARCH_THRESHOLD = 10;

	let filterText = $state('');
	let showAll = $state(false);

	const available = $derived(options.filter((o) => o.count !== 0 || selected.includes(o.value) || seen.has(o.value)));
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

	$effect(() => {
		for (const o of shown) seen.add(o.value);
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
{#if clearable && selected.length}
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
			{@const empty = opt.count === 0 && !selected.includes(opt.value)}
			<label class="option-row" class:empty>
				<input type="checkbox" checked={selected.includes(opt.value)} disabled={empty} onchange={() => toggle(opt.value)} />
				<span class="facet-option-text" use:revealTruncated>{opt.text}</span>{#if opt.count != null}<span class="facet-count">{opt.count.toLocaleString('fr-FR')}</span>{/if}
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
	/* Option restée affichée dont le décompte est tombé à zéro. */
	.option-row.empty {
		color: var(--text-faint);
		cursor: default;
	}
	.facet-group-separator {
		margin: 3px 0;
		border-top: 1px solid var(--border-subtle);
	}
</style>
