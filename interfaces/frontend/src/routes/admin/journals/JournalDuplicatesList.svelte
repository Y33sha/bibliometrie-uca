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

	/** `onchange` : appelé après chaque fusion, pour rafraîchir le compteur de l'onglet. */
	let { onchange }: { onchange: () => void } = $props();

	let groups: Group[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			groups = (await api<DuplicatesResponse>('/api/journals/duplicates')).groups;
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur lors du chargement des doublons : ' + msg, 'error');
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
	<p class="muted">Aucun doublon potentiel.</p>
{:else}
	<p class="muted intro">
		Revues de même titre, ou qui portent le même ISSN. Deux revues de même titre qui ont chacune un
		ISSN sont des homonymes probables : elles n'apparaissent pas ici.
	</p>
	{#each groups as group (`${group.shared}:${group.value}`)}
		<section class="group">
			<h3>{group.shared === 'issn' ? `Même ISSN : ${group.value}` : 'Même titre'}</h3>
			<table>
				<thead>
					<tr><th>Revue</th><th>Éditeur</th><th>ISSN</th><th class="num">Publications</th><th></th></tr>
				</thead>
				<tbody>
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
			</table>
		</section>
	{/each}
{/if}

<style>
	.intro { margin: 0 0 12px; }
	.group { margin-bottom: 18px; }
	h3 { font-size: 0.95rem; font-weight: 600; margin: 0 0 6px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); }
	th { font-weight: 600; color: var(--muted); }
	.num { text-align: right; }
	.action { text-align: right; white-space: nowrap; }
	.muted { color: var(--muted); }
</style>
