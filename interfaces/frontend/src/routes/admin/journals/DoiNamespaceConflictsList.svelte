<script lang="ts">
	import { untrack } from 'svelte';
	import { base } from '$app/paths';
	import { api, ApiError } from '$lib/api';
	import { confirmDialog, toast } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';
	import { mergeJournal } from './mergeJournal';

	type Response = components['schemas']['DoiNamespaceConflictsResponse'];
	type Conflict = components['schemas']['DoiNamespaceConflict'];
	type Journal = components['schemas']['JournalListItem'];

	let {
		onchange,
	}: {
		/** Appelé après chaque fusion, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let conflicts: Conflict[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			conflicts = (await api<Response>('/api/journals/doi-namespace-conflicts')).conflicts;
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

	async function keep(target: Journal, source: Journal) {
		const message = `Garder « ${target.title} » et y fusionner « ${source.title} » ?`;
		if (!(await confirmDialog({ message, danger: true }))) return;
		busy = true;
		try {
			await mergeJournal(target, source.id);
		} finally {
			busy = false;
			await load();
			onchange();
		}
	}

	function issns(j: Journal): string {
		return [j.issn, j.eissn].filter(Boolean).join(' / ') || 'sans ISSN';
	}

	function sources(c: Conflict): string {
		return Object.entries(c.sources)
			.map(([source, n]) => `${source} ${n}`)
			.join(', ');
	}

	const percent = new Intl.NumberFormat('fr-FR', { style: 'percent', maximumFractionDigits: 0 });
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if conflicts.length === 0}
	<p class="muted">Aucune contradiction.</p>
{:else}
	<p class="muted intro">
		Enregistrements dont la revue diffère de celle que désigne l'espace de noms de leur DOI. La première ligne de chaque paire est la revue de l'espace de noms, la seconde celle des enregistrements.
	</p>
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
		{#each conflicts as c (`${c.record_journal.id}-${c.namespace_journal.id}`)}
			<tbody class="group">
				<tr class="group-head">
					<th colspan="5">
						<code>{c.namespace}</code>
						<span class="muted">
							— {percent.format(c.share)} de {c.dois} DOI ;
							{c.records} enregistrement{c.records > 1 ? 's' : ''} contredit{c.records > 1 ? 's' : ''} ({sources(c)}) :
						</span>
						{#each c.sample_dois as doi, i (doi)}
							{#if i > 0}, {/if}<a href="https://doi.org/{doi}" target="_blank" rel="noopener">{doi}</a>
						{/each}
					</th>
				</tr>
				{#each [[c.namespace_journal, c.record_journal], [c.record_journal, c.namespace_journal]] as [j, other] (j.id)}
					<tr>
						<td><a href="{base}/journals/{j.id}">{j.title}</a> <span class="muted">#{j.id}</span></td>
						<td>{j.pub_name ?? '—'}</td>
						<td>{issns(j)}</td>
						<td class="num">{j.pub_count}</td>
						<td class="action">
							<button class="btn btn-sm" disabled={busy} onclick={() => keep(j, other)}>
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
	.group-head th { font-weight: normal; background: var(--accent-light); }
	.num { text-align: right; }
	.action { text-align: right; white-space: nowrap; }
	.muted { color: var(--muted); }
</style>
