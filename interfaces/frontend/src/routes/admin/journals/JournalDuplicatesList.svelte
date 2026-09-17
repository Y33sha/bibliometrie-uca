<script lang="ts">
	import { untrack } from 'svelte';
	import { base } from '$app/paths';
	import { api, ApiError } from '$lib/api';
	import { confirmDialog, toast } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';
	import { mergeJournal } from './mergeJournal';

	type DuplicatesResponse = components['schemas']['JournalDuplicatesResponse'];
	type Group = components['schemas']['JournalDuplicateGroup'];
	type Journal = components['schemas']['JournalListItem'];

	let {
		url,
		valueLabel,
		intro,
		onchange,
	}: {
		/** Route de la file : `/api/journals/same-titles` ou `/api/journals/shared-issns`. */
		url: string;
		/** Libellé de la valeur partagée, affiché en tête de chaque groupe (« ISSN ») ; sans libellé, les groupes se suivent sans en-tête. */
		valueLabel?: string;
		intro?: string;
		/** Appelé après chaque fusion, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let groups: Group[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			groups = (await api<DuplicatesResponse>(url)).groups;
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur lors du chargement de la file : ' + msg, 'error');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		untrack(load);
	});

	async function keep(group: Group, target: Journal) {
		const sources = group.journals.filter((j) => j.id !== target.id);
		const plural = sources.length > 1 ? 's' : '';
		const message = `Garder « ${target.title} » et y fusionner ${sources.length} revue${plural} ?`;
		if (!(await confirmDialog({ message, danger: true }))) return;
		busy = true;
		try {
			for (const source of sources) {
				if (!(await mergeJournal(target, source.id))) break;
			}
		} finally {
			busy = false;
			await load();
			onchange();
		}
	}

	function issns(j: Journal): string {
		return [j.issn, j.eissn].filter(Boolean).join(' / ') || 'sans ISSN';
	}
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if groups.length === 0}
	<p class="muted">Aucun groupe.</p>
{:else}
	{#if intro}<p class="muted intro">{intro}</p>{/if}
	<table>
		<colgroup>
			<col class="col-title" />
			<col class="col-publisher" />
			<col class="col-issn" />
			<col class="col-pubs" />
			<col class="col-action" />
		</colgroup>
		<thead>
			<tr><th>Revue</th><th>Éditeur</th><th>ISSN</th><th class="num">Publications</th><th></th></tr>
		</thead>
		{#each groups as group (group.value)}
			<tbody class="group">
				{#if valueLabel}
					<tr class="group-head"><th colspan="5">{valueLabel} {group.value}</th></tr>
				{/if}
				{#each group.journals as j (j.id)}
					<tr>
						<td><a href="{base}/journals/{j.id}">{j.title}</a> <span class="muted">#{j.id}</span></td>
						<td>{j.pub_name ?? '—'}</td>
						<td>{issns(j)}</td>
						<td class="num">{j.pub_count}</td>
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
	table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 0.9rem; }
	.col-title { width: 38%; }
	.col-publisher { width: 24%; }
	.col-issn { width: 16%; }
	.col-pubs { width: 9%; }
	.col-action { width: 13%; }
	th, td { text-align: left; padding: 4px 8px; overflow-wrap: anywhere; }
	thead th { font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--border); }
	tbody.group { border-top: 2px solid var(--border); }
	.group-head th { font-weight: 600; background: var(--accent-light); }
	.num { text-align: right; }
	.action { text-align: right; white-space: nowrap; }
	.muted { color: var(--muted); }
</style>
