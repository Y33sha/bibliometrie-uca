<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
	import type { components } from '$lib/api/schema';

	type Monograph = components['schemas']['MonographListItem'];

	const monographId = $derived(Number($page.params.id));

	let monograph = $state<Monograph | null>(null);
	let error = $state(false);
	let canGoBack = $state(false);

	onMount(async () => {
		canGoBack =
			(window as any).navigation?.canGoBack ??
			document.referrer.startsWith(window.location.origin);
		try {
			monograph = await api<Monograph>(`/api/monographs/${monographId}`);
		} catch {
			error = true;
		}
	});
</script>

<svelte:head>
	<title>{pageTitle(monograph?.title ?? 'Monographie')}</title>
</svelte:head>

{#if canGoBack}
	<!-- svelte-ignore a11y_invalid_attribute -->
	<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="no-results">Monographie introuvable</div>
{:else if !monograph}
	<div class="loading">Chargement…</div>
{:else}
	<div class="m-header">
		<h1 class="m-title">{monograph.title}</h1>
		<div class="meta-row">
			<span class="type-tag">{monograph.proceedings ? "Volume d'actes" : 'Livre'}</span>
			{#if monograph.year}
				<span class="meta-label">Année</span>
				<span>{monograph.year}</span>
			{/if}
			{#if monograph.isbn}
				<span class="meta-label">ISBN</span>
				<span class="id-badge">{monograph.isbn}</span>
			{/if}
			{#if monograph.eisbn}
				<span class="meta-label">ISBN électronique</span>
				<span class="id-badge">{monograph.eisbn}</span>
			{/if}
		</div>
		<div class="meta-row">
			{#if monograph.publisher_id}
				<span class="meta-label">Éditeur</span>
				<a href="{base}/publishers/{monograph.publisher_id}">{monograph.pub_name}</a>
			{/if}
			{#if monograph.journal_id}
				<span class="meta-label">Collection</span>
				<a href="{base}/journals/{monograph.journal_id}">{monograph.journal_title}</a>
			{/if}
		</div>
	</div>

	<div class="m-publications">
		<PublicationsListView
			apiKey={`monograph-${monographId}-pubs`}
			externalFilters={{ monographId }}
			basePath={`/monographs/${monographId}`}
			showFilterBanner={false}
			perPage={50}
		/>
	</div>
{/if}

<style>
	.m-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.m-title { font-size: 1.3rem; font-weight: 600; margin: 0 0 4px; }
	.meta-row {
		display: flex; align-items: center; gap: 6px;
		flex-wrap: wrap; font-size: 0.95rem;
	}
	.meta-label {
		font-size: 0.8rem; font-weight: 600; color: var(--muted);
		text-transform: uppercase; letter-spacing: 0.3px;
		margin-left: 8px;
	}
	.meta-label:first-child { margin-left: 0; }
	.type-tag {
		background: var(--border-subtle); color: var(--muted);
		padding: 2px 8px; border-radius: 10px; font-size: 0.85rem;
	}
	.m-publications { margin-top: 16px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }
</style>
