<script lang="ts" generics="Group">
	import { untrack, type Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { errorMessage } from '#lib/api/index.js';
	import { confirmDialog, toast } from '#lib/dialogs.svelte.js';
	import type { components } from '#lib/api/schema.js';
	import { mergeSerial } from './mergeSerial';

	type Serial = components['schemas']['SerialListItem'];

	// File de triage de publications en série regroupées : « Garder celle-ci » fusionne dans la publication choisie les autres publications de son groupe.
	let {
		fetchGroups,
		serialsOf,
		keyOf,
		emptyText,
		intro,
		groupHead,
		onchange,
	}: {
		fetchGroups: () => Promise<Group[]>;
		serialsOf: (group: Group) => Serial[];
		keyOf: (group: Group) => string;
		emptyText: string;
		intro?: Snippet;
		/** En-tête d'un groupe, sur toute la largeur du tableau. */
		groupHead?: Snippet<[Group]>;
		/** Appelé après chaque fusion, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let groups: Group[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			groups = await fetchGroups();
		} catch (e) {
			toast('Erreur lors du chargement de la file : ' + errorMessage(e), 'error');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		untrack(load);
	});

	async function keep(group: Group, target: Serial) {
		const sources = serialsOf(group).filter((j) => j.id !== target.id);
		const merged =
			sources.length === 1 ? `« ${sources[0].title} »` : `${sources.length} publications en série`;
		const message = `Garder « ${target.title} » et y fusionner ${merged} ?`;
		if (!(await confirmDialog({ message, danger: true }))) return;
		busy = true;
		try {
			for (const source of sources) {
				if (!(await mergeSerial(target, source.id))) break;
			}
		} finally {
			busy = false;
			await load();
			onchange();
		}
	}

	function issns(j: Serial): string {
		return j.issns.join(' / ') || 'sans ISSN';
	}
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if groups.length === 0}
	<p class="muted">{emptyText}</p>
{:else}
	{#if intro}<p class="muted intro">{@render intro()}</p>{/if}
	<table class="data-table triage-table">
		<colgroup>
			<col class="col-title" />
			<col class="col-publisher" />
			<col class="col-issn" />
			<col class="col-publications" />
			<col class="col-action" />
		</colgroup>
		<thead>
			<tr><th>Publication en série</th><th>Éditeur</th><th>ISSN</th><th class="num">Publications</th><th></th></tr>
		</thead>
		{#each groups as group (keyOf(group))}
			<tbody class="group">
				{#if groupHead}
					<tr class="group-head"><th colspan="5">{@render groupHead(group)}</th></tr>
				{/if}
				{#each serialsOf(group) as j (j.id)}
					<tr>
						<td><a href={resolve(`journals/${j.id}`)}>{j.title}</a> <span class="muted">#{j.id}</span></td>
						<td>{j.publisher_name ?? '—'}</td>
						<td>{issns(j)}</td>
						<td class="num">{j.publication_count}</td>
						<td class="action">
							<button class="btn btn-sm" disabled={busy} onclick={() => keep(group, j)}>
								Garder celle-ci
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		{/each}
	</table>
{/if}

<style>
	.intro { margin: 0 0 12px; }
	.col-title { width: 38%; }
	.col-publisher { width: 24%; }
	.col-issn { width: 16%; }
	.col-publications { width: 9%; }
	.col-action { width: 13%; }
	.group-head th { font-weight: normal; }
	.muted { color: var(--muted); }
</style>
