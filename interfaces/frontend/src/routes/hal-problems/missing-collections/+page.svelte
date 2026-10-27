<script lang="ts">
	import { institution } from '#lib/institution.svelte.js';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { withBase } from '#lib/paths.js';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type Lab = components['schemas']['HalCollectionLab'];
	type Pub = components['schemas']['HalMissingCollectionPublication'];

	let labs: Lab[] = $state([]);
	let labsLoaded = $state(false);
	let selectedLabId: number | null = $state(null);
	const selectedLab = $derived(labs.find((lab) => lab.id === selectedLabId));

	const list = usePaginatedFetch<Pub>({
		endpoint: '/api/hal-problems/missing-collections',
		itemsKey: 'publications',
		apiKey: 'hal-missing-collections',
		buildParams() {
			const params = new URLSearchParams();
			if (selectedLabId) params.set('lab_id', String(selectedLabId));
			return params;
		},
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (selectedLabId) p.set('lab_id', String(selectedLabId));
		if (list.page > 1) p.set('page', String(list.page));
		void replaceQuery(resolve('hal-problems/missing-collections'), p);
	}

	async function loadLabs() {
		labs = await api<Lab[]>('/api/hal-problems/missing-collections/labs');
		if (labs.length > 0 && !selectedLabId) {
			selectedLabId = labs[0].id;
		}
		labsLoaded = true;
		if (!selectedLabId) return;
		await list.load();
		syncUrl();
	}

	function onLabChange() {
		list.page = 1;
		syncUrl();
		list.load();
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
		if (urlParams.get('lab_id')) selectedLabId = parseInt(urlParams.get('lab_id')!);
		if (urlParams.get('page')) list.page = parseInt(urlParams.get('page')!) || 1;
		loadLabs();
	});
</script>

<PageHeader title="Publications absentes des collections HAL">
	Publications présentes dans OpenAlex ou WoS avec signature d'un labo {institution.name}, et présentes dans HAL mais absentes de la collection HAL de ce labo.
</PageHeader>

<ListToolbar {list} one="publication" many="publications" exportUrl={selectedLabId ? withBase(`/api/hal-problems/missing-collections/export.csv?lab_id=${selectedLabId}`) : undefined}>
	{#snippet filters()}
		<select class="lab-select" aria-label="Laboratoire" bind:value={selectedLabId} onchange={onLabChange}>
			{#each labs as lab}
				<option value={lab.id}>{lab.acronym} — {lab.name} ({lab.hal_collection})</option>
			{/each}
		</select>
	{/snippet}
</ListToolbar>

{#if !labsLoaded}
	<div class="loading">Chargement…</div>
{:else if selectedLabId}
	<ListStatus {list} emptyText="Aucune publication manquante pour {selectedLab?.acronym ?? ''} (collection {selectedLab?.hal_collection ?? ''})">
		<div class="publication-list">
			{#each list.items as pub}
				<div class="publication-card">
					<div class="publication-meta-line">
						{#if pub.publication_year}<span class="meta-badge">{pub.publication_year}</span>{/if}
						{#if pub.doc_type}<DocTypePill docType={pub.doc_type} />{/if}
						{#if pub.outside_perimeter_collections}<span class="badge-hors-uca">Hors collections de l'établissement</span>{/if}
						<a href={resolve(`publications/${pub.id}`)} class="publication-title"><PublicationTitle titre={pub.title} /></a>
					</div>
					<div class="hal-list">
						{#if pub.hal_links.length}
							{#each pub.hal_links as link (link.source_id)}
								<a href={link.record_url} target="_blank" rel="noopener" class="hal-link-badge">{link.source_id}</a>
							{/each}
						{/if}
						{#if pub.doi}
							<span class="doi-ref">DOI : <a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a></span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
		<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
	</ListStatus>
{/if}

<style>
	.lab-select {
		max-width: 100%;
	}
	.publication-list { display: flex; flex-direction: column; gap: 8px; }
	.publication-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 10px 14px;
	}
	.publication-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.meta-badge { flex-shrink: 0; }
	.badge-hors-uca {
		display: inline-block; padding: 1px 8px; background: var(--attention-light);
		border: 1px solid color-mix(in srgb, var(--attention) 40%, white); border-radius: var(--radius); font-size: 0.78rem;
		color: var(--attention); font-weight: 600; flex-shrink: 0;
	}
	.hal-list {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin-top: 6px; padding-left: 20px;
	}
	.doi-ref { font-size: 0.82rem; color: var(--muted); }
</style>
