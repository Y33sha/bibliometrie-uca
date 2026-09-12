<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';
	import type { components } from '$lib/api/schema';
	import { displayEntityLabel, entityLabel, rememberEntityLabel, type EntityKind } from '$lib/entityLabels';

	type EntityFacetResponse = components['schemas']['EntityFacetResponse'];

	/** Facette d'entité à forte cardinalité (éditeur, revue, auteur, sujet) : recherche serveur **contextuelle**. Le parent fournit `buildParams` (les filtres actifs) ; le composant y ajoute le `kind` et le terme de recherche pour lister les N premières entités sous ces filtres, avec décompte.
	 *
	 * Le parent tient la sélection sous forme d'**ids** : un au plus en choix simple, plusieurs avec `multiple`. Les libellés sont de la donnée dérivée, gérée ici : connus d'emblée quand l'utilisateur choisit une option, sinon résolus par `/api/entity-labels` quand un id est restauré depuis l'URL sans son nom. Un libellé ne dépend d'aucun filtre, là où les options proposées en dépendent. */
	interface Props {
		label: string;
		/** Base de la facette contextuelle (ex. /api/stats/facets) : `${endpoint}/entities` liste les premières entités sous les filtres actifs. */
		endpoint: string;
		kind: EntityKind;
		/** Filtres actifs du contexte (l'endpoint saute de lui-même celui de `kind`). */
		buildParams: () => URLSearchParams;
		/** Ids des entités sélectionnées. */
		selected?: string[];
		/** Cases à cocher : plusieurs entités, retenues si l'une au moins porte la publication. Sinon, un seul choix. */
		multiple?: boolean;
		onchange?: (ids: string[]) => void;
	}

	let { label, endpoint, kind, buildParams, selected = [], multiple = false, onchange }: Props = $props();

	interface Result {
		value: string;
		text: string;
		count: number;
	}

	let open = $state(false);
	let query = $state('');
	let results = $state<Result[]>([]);
	let loading = $state(false);
	// Libellés des entités sélectionnées, par id.
	let labels = $state<Record<string, string>>({});
	let debounce: ReturnType<typeof setTimeout>;
	const instanceId = Symbol();

	// Résout le libellé des ids sélectionnés dont le nom est inconnu (restaurés de l'URL). `entityLabel` mémorise les réponses.
	$effect(() => {
		for (const id of selected) {
			if (id in labels) continue;
			entityLabel(kind, id)
				.then((l) => {
					labels[id] = l ?? id;
				})
				.catch(() => {});
		}
	});

	const buttonText = $derived(!multiple && selected.length ? (labels[selected[0]] ?? label) : label);
	// Sélection absente des résultats (hors des premières entités, ou écartée par la recherche) : affichée en tête, pour rester visible et décochable.
	const selectedOutside = $derived(selected.filter((id) => !results.some((r) => r.value === id)));
	// En choix multiple, les entités cochées passent en tête.
	const orderedResults = $derived(
		multiple
			? [...results.filter((r) => selected.includes(r.value)), ...results.filter((r) => !selected.includes(r.value))]
			: results,
	);

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
		if (r) {
			// Le libellé de l'option choisie est déjà connu : on l'adopte sans relecture.
			rememberEntityLabel(kind, r.value, r.text);
			labels[r.value] = r.text;
		}
		if (!multiple) {
			onchange?.(r ? [r.value] : []);
			open = false;
		} else if (!r) {
			onchange?.([]);
		} else {
			onchange?.(selected.includes(r.value) ? selected.filter((v) => v !== r.value) : [...selected, r.value]);
		}
	}

	function pickAll(e: Event & { currentTarget: HTMLInputElement }) {
		// « Tous » sans sélection reste coché : il n'y a rien à retirer.
		if (!selected.length) {
			e.currentTarget.checked = true;
			return;
		}
		pick(null);
	}

	function openPanel() {
		window.dispatchEvent(new CustomEvent('facet-close', { detail: instanceId }));
		open = true;
		query = '';
		search();
	}

	function handleFacetClose(ev: Event) {
		if ((ev as CustomEvent).detail !== instanceId) open = false;
	}
	onMount(() => window.addEventListener('facet-close', handleFacetClose));
	onDestroy(() => window.removeEventListener('facet-close', handleFacetClose));
</script>

<svelte:window onclick={() => { open = false; }} />

<div class="facet">
	<button
		type="button"
		class="facet-btn"
		class:has-selection={selected.length > 0}
		onclick={(e) => {
			e.stopPropagation();
			if (open) open = false;
			else openPanel();
		}}
	>
		<span class="facet-label">{buttonText}</span>
		{#if multiple && selected.length}
			<span class="facet-badge">{selected.length}</span>
		{/if}
		<span class="facet-arrow">&#9662;</span>
	</button>

	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
		<div class="facet-panel" onclick={(e) => e.stopPropagation()}>
			<input type="text" class="facet-search" placeholder="Rechercher..." bind:value={query} oninput={onInput} />
			<div class="facet-options">
				<label>
					<input type={multiple ? 'checkbox' : 'radio'} checked={!selected.length} onchange={pickAll} />
					<span style="font-weight:500">Tous</span>
				</label>
				{#each selectedOutside as id (id)}
					<label>
						<input
							type={multiple ? 'checkbox' : 'radio'}
							checked
							onchange={() => (multiple ? pick({ value: id, text: labels[id] ?? id, count: 0 }) : (open = false))}
						/>
						<span class="facet-option-text"title={labels[id] ?? id}>{labels[id] ?? id}</span>
					</label>
				{/each}
				{#each orderedResults as e (e.value)}
					<label>
						<input type={multiple ? 'checkbox' : 'radio'} checked={selected.includes(e.value)} onchange={() => pick(e)} />
						<span class="facet-option-text"title={e.text}>{e.text}</span><span class="facet-count">{e.count}</span>
					</label>
				{/each}
				{#if !loading && results.length === 0}
					<div class="facet-empty">Aucun résultat</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	/* Bouton, panneau et options : styles communs des facettes, dans shared.css. Le nom choisi s'affiche sur le bouton, d'où une largeur bornée. */
	.facet-btn {
		max-width: 240px;
	}
	.facet-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.facet-panel {
		min-width: 260px;
	}
	.facet-empty {
		padding: 6px 12px;
		font-size: 0.85rem;
		color: var(--muted);
	}
</style>
