<script lang="ts">
	import { untrack } from 'svelte';
	import { api } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import { displayEntityLabel, type EntityKind } from '#lib/entityLabels.js';
	import { useEntityLabels } from '#lib/composables/useEntityLabels.svelte.js';

	type EntityFacetResponse = components['schemas']['EntityFacetResponse'];

	/** Options d'un filtre d'entité à forte cardinalité (éditeur, revue, auteur, sujet) : recherche serveur contextuelle. `buildParams` fournit les filtres actifs ; le composant y ajoute le `kind` et le terme de recherche, et liste les premières entités sous ces filtres, avec leur décompte. La liste se recharge quand les filtres actifs changent. Partagé par la liste déroulante d'un filtre et le panneau des filtres. */
	interface Props {
		/** Base de la facette contextuelle (ex. /api/publications/facets) : `${endpoint}/entities` liste les premières entités sous les filtres actifs. */
		endpoint: string;
		kind: EntityKind;
		/** Filtres actifs du contexte (l'endpoint saute de lui-même celui de `kind`). */
		buildParams: () => URLSearchParams;
		/** Ids des entités sélectionnées. */
		selected?: string[];
		/** Cases à cocher : plusieurs entités, retenues si l'une au moins porte la publication. Sinon, un seul choix. */
		multiple?: boolean;
		onchange?: (ids: string[]) => void;
		/** Appelé après un choix, en choix simple. */
		onchosen?: () => void;
	}

	let { endpoint, kind, buildParams, selected = [], multiple = false, onchange, onchosen }: Props = $props();

	interface Result {
		value: string;
		text: string;
		count: number;
	}

	let query = $state('');
	let results = $state<Result[]>([]);
	let loading = $state(false);
	let debounce: ReturnType<typeof setTimeout>;
	const names = useEntityLabels(() => kind, () => selected);

	// Sélection absente des résultats (hors des premières entités, ou écartée par la recherche) : affichée en tête, pour rester visible et décochable.
	const selectedOutside = $derived(selected.filter((id) => !results.some((r) => r.value === id)));
	// En choix multiple, les entités cochées passent en tête.
	const orderedResults = $derived(
		multiple
			? [...results.filter((r) => selected.includes(r.value)), ...results.filter((r) => !selected.includes(r.value))]
			: results,
	);

	const filterKey = $derived(buildParams().toString());
	$effect(() => {
		void filterKey;
		untrack(search);
	});

	async function search() {
		loading = true;
		const p = buildParams();
		p.set('kind', kind);
		if (query.trim().length >= 2) p.set('entity_search', query.trim());
		try {
			const data = await api<EntityFacetResponse>(`${endpoint}/entities?` + p);
			results = data.entities.map((e) => ({ value: String(e.id), text: displayEntityLabel(kind, e.label), count: e.count }));
		} catch {
			results = [];
		}
		loading = false;
	}

	function onInput() {
		clearTimeout(debounce);
		debounce = setTimeout(search, 250);
	}

	function pick(r: Result | null) {
		if (r) names.remember(r.value, r.text);
		if (!r) onchange?.([]);
		else if (!multiple) onchange?.([r.value]);
		else onchange?.(selected.includes(r.value) ? selected.filter((v) => v !== r.value) : [...selected, r.value]);
		if (!multiple) onchosen?.();
	}

	// Entité sélectionnée hors des résultats : en choix simple, la cliquer garde la sélection.
	function pickOutside(id: string) {
		if (multiple) pick({ value: id, text: names.labels[id] ?? id, count: 0 });
		else onchosen?.();
	}
</script>

<input type="text" class="panel-search input-sm" placeholder="Rechercher" aria-label="Rechercher" bind:value={query} oninput={onInput} />
{#if selected.length}
	<button type="button" class="option-row facet-clear" onclick={() => pick(null)}>Effacer</button>
{/if}
<div class="facet-options">
	{#each selectedOutside as id (id)}
		<label class="option-row">
			<input type={multiple ? 'checkbox' : 'radio'} checked onchange={() => pickOutside(id)} />
			<span class="facet-option-text" title={names.labels[id] ?? id}>{names.labels[id] ?? id}</span>
		</label>
	{/each}
	{#each orderedResults as e (e.value)}
		<label class="option-row">
			<input type={multiple ? 'checkbox' : 'radio'} checked={selected.includes(e.value)} onchange={() => pick(e)} />
			<span class="facet-option-text" title={e.text}>{e.text}</span><span class="facet-count">{e.count}</span>
		</label>
	{/each}
	{#if !loading && results.length === 0}
		<div class="facet-empty">Aucun résultat</div>
	{/if}
</div>

<style>
	.facet-empty {
		padding: 6px 12px;
		font-size: var(--fs-sm);
		color: var(--muted);
	}
</style>
