<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api';

	/** Facette d'entité à forte cardinalité (éditeur, revue) : recherche serveur **contextuelle**.
	 *  Le parent fournit `buildParams` (les filtres actifs) ; le composant y ajoute le `kind` et le
	 *  terme de recherche pour lister les N premières entités sous ces filtres, avec décompte.
	 *
	 *  L'état canonique côté parent est le seul **id** sélectionné. Le libellé de la pastille est de la
	 *  donnée dérivée, gérée ici : connu d'emblée quand l'utilisateur choisit une option, sinon résolu
	 *  par `/api/entity-labels` quand un id est restauré depuis l'URL sans son nom. Ce libellé ne
	 *  dépend d'aucun filtre, là où les options proposées en dépendent. */
	interface Props {
		label: string;
		/** Base de la facette contextuelle (ex. /api/stats/facets) : `${endpoint}/entities` liste les
		 *  premières entités sous les filtres actifs. */
		endpoint: string;
		kind: 'publisher' | 'journal';
		/** Filtres actifs du contexte (l'endpoint saute de lui-même celui de `kind`). */
		buildParams: () => URLSearchParams;
		/** Id de l'entité sélectionnée (état canonique), ou null. */
		selectedId?: string | null;
		onchange?: (id: string | null) => void;
	}

	let { label, endpoint, kind, buildParams, selectedId = null, onchange }: Props = $props();

	interface Result {
		value: string;
		text: string;
		count: number;
	}

	let open = $state(false);
	let query = $state('');
	let results = $state<Result[]>([]);
	let loading = $state(false);
	let selectedLabel = $state<string | null>(null);
	let resolvedId: string | null = null; // id pour lequel `selectedLabel` est à jour
	let debounce: ReturnType<typeof setTimeout>;
	const instanceId = Symbol();

	// Résolution du libellé de la pastille. Quand un id est présélectionné (restauré de l'URL) dont on
	// ne connaît pas encore le nom, on le demande à l'endpoint. Idempotent (mémoïsé par `resolvedId`),
	// et tolérant aux changements rapides (on n'applique la réponse que si l'id n'a pas changé entre-temps).
	$effect(() => {
		if (!selectedId) {
			selectedLabel = null;
			resolvedId = null;
			return;
		}
		if (selectedId === resolvedId) return;
		resolvedId = selectedId;
		const id = selectedId;
		api<{ label: string | null }>(`/api/entity-labels?kind=${kind}&entity_id=${id}`)
			.then((d) => {
				if (resolvedId === id) selectedLabel = d.label;
			})
			.catch(() => {});
	});

	async function search() {
		loading = true;
		const p = buildParams();
		p.set('kind', kind);
		if (query.trim().length >= 2) p.set('entity_search', query.trim());
		try {
			const data = await api<{ entities: { id: number; label: string; count: number }[] }>(
				`${endpoint}/entities?` + p,
			);
			results = data.entities.map((e) => ({ value: String(e.id), text: e.label, count: e.count }));
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
		// Le libellé de l'option choisie est déjà connu : on l'adopte sans relecture.
		selectedLabel = r?.text ?? null;
		resolvedId = r?.value ?? null;
		onchange?.(r?.value ?? null);
		open = false;
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
		class:has-selection={!!selectedId}
		onclick={(e) => {
			e.stopPropagation();
			if (open) open = false;
			else openPanel();
		}}
	>
		<span class="facet-label">{selectedLabel ?? label}</span>
		<span class="facet-arrow">&#9662;</span>
	</button>

	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
		<div class="facet-panel" onclick={(e) => e.stopPropagation()}>
			<input type="text" class="facet-search" placeholder="Rechercher..." bind:value={query} oninput={onInput} />
			<div class="facet-options">
				<label>
					<input type="radio" checked={!selectedId} onchange={() => pick(null)} />
					<span style="font-weight:500">Tous</span>
				</label>
				{#if selectedId && !results.some((r) => r.value === selectedId)}
					<label>
						<input type="radio" checked onchange={() => (open = false)} />
						<span class="facet-name" title={selectedLabel ?? selectedId}>{selectedLabel ?? selectedId}</span>
					</label>
				{/if}
				{#each results as e (e.value)}
					<label>
						<input type="radio" checked={selectedId === e.value} onchange={() => pick(e)} />
						<span class="facet-name" title={e.text}>{e.text}</span><span class="facet-count">{e.count}</span>
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
	.facet {
		position: relative;
		display: inline-block;
	}
	.facet-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 0.95rem;
		cursor: pointer;
		color: var(--text);
		white-space: nowrap;
		font-family: inherit;
		max-width: 240px;
	}
	.facet-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.facet-btn:hover {
		border-color: #ccc;
	}
	.facet-btn.has-selection {
		border-color: var(--accent);
		background: var(--accent-light);
	}
	.facet-arrow {
		font-size: 0.7rem;
		color: var(--muted);
		margin-left: 2px;
		flex-shrink: 0;
	}
	.facet-panel {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		min-width: 260px;
		max-width: 360px;
		max-height: 320px;
		overflow-y: auto;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
		z-index: 100;
		padding: 6px 0;
	}
	.facet-search {
		display: block;
		width: calc(100% - 12px);
		margin: 2px 6px 6px;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.facet-options label {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 12px;
		font-size: 0.95rem;
		cursor: pointer;
	}
	.facet-options label:hover {
		background: #f5f5f2;
	}
	.facet-options input[type='radio'] {
		margin: 0;
		flex-shrink: 0;
	}
	.facet-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		/* Indispensable pour que l'ellipse s'applique à un enfant flex (sinon min-width: auto
		   empêche le rétrécissement et le panneau s'élargit au plus long nom). */
		min-width: 0;
	}
	.facet-count {
		font-size: 0.8rem;
		color: #888;
		margin-left: auto;
		padding-left: 12px;
		flex-shrink: 0;
	}
	.facet-empty {
		padding: 6px 12px;
		font-size: 0.85rem;
		color: var(--muted);
	}
</style>
