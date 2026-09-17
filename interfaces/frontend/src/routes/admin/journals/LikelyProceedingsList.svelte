<script lang="ts">
	import { untrack } from 'svelte';
	import { base } from '$app/paths';
	import { api, ApiError, journals as journalsApi } from '$lib/api';
	import { confirmDialog, toast } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';

	type Response = components['schemas']['LikelyProceedingsResponse'];
	type Item = components['schemas']['LikelyProceedingsItem'];

	let {
		onchange,
	}: {
		/** Appelé après chaque typage, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let items: Item[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			items = (await api<Response>('/api/journals/likely-proceedings')).journals;
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

	async function markProceedings(item: Item) {
		const j = item.journal;
		busy = true;
		try {
			const impact = await journalsApi.typeChangeImpact(j.id, 'proceedings');
			const plural = impact.count > 1 ? 's' : '';
			const recalcul = impact.count
				? ` Le type de document de ${impact.count} publication${plural} sera recalculé.`
				: '';
			const message = `Typer « ${j.title} » en recueil d'actes ?${recalcul}`;
			if (!(await confirmDialog({ message }))) return;
			await journalsApi.update(j.id, { journal_type: 'proceedings' });
			await load();
			onchange();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur : ' + msg, 'error');
		} finally {
			busy = false;
		}
	}

	function issns(item: Item): string {
		const j = item.journal;
		return [j.issn, j.eissn].filter(Boolean).join(' / ') || 'sans ISSN';
	}
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if items.length === 0}
	<p class="muted">Aucune revue.</p>
{:else}
	<p class="muted intro">
		Revues typées « revue » dont la majorité des documents sont des articles de congrès, d'après le type donné par chaque source. Les revues sans ISSN viennent en tête.
	</p>
	<table>
		<colgroup>
			<col class="col-title" />
			<col class="col-publisher" />
			<col class="col-issn" />
			<col class="col-share" />
			<col class="col-action" />
		</colgroup>
		<thead>
			<tr>
				<th>Revue</th><th>Éditeur</th><th>ISSN</th><th class="num">Articles de congrès</th><th></th>
			</tr>
		</thead>
		<tbody>
			{#each items as item (item.journal.id)}
				<tr>
					<td>
						<a href="{base}/journals/{item.journal.id}">{item.journal.title}</a>
						<span class="muted">#{item.journal.id}</span>
					</td>
					<td>{item.journal.pub_name ?? '—'}</td>
					<td>{issns(item)}</td>
					<td class="num">{item.conference_papers} / {item.records}</td>
					<td class="action">
						<button class="btn btn-sm" disabled={busy} onclick={() => markProceedings(item)}>
							Recueil d'actes
						</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.intro { margin: 0 0 12px; }
	table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 0.9rem; }
	.col-title { width: 40%; }
	.col-publisher { width: 22%; }
	.col-issn { width: 14%; }
	.col-share { width: 11%; }
	.col-action { width: 13%; }
	th, td { text-align: left; padding: 4px 8px; overflow-wrap: anywhere; }
	thead th { font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--border); }
	tbody tr { border-top: 1px solid var(--border); }
	.num { text-align: right; }
	.action { text-align: right; white-space: nowrap; }
	.muted { color: var(--muted); }
</style>
