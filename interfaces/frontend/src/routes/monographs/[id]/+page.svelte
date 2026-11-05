<script lang="ts">
	import EntityMetaItem from '#lib/components/EntityMetaItem.svelte';
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { apiDetail } from '#lib/api/index.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import { titleText } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Monograph = components['schemas']['MonographListItem'];

	const monographId = $derived(Number(page.params.id));

	let monograph = $state<Monograph | null>(null);
	let error = $state(false);
	onMount(async () => {
		try {
			monograph = await apiDetail<Monograph>(`/api/monographs/${monographId}`);
		} catch {
			error = true;
		}
	});
</script>

<EntityBreadcrumb section={{ label: 'Monographies', path: 'monographs' }} name={titleText(monograph?.title)} fallback="Monographie" />

{#if error || !monograph}
	<EntityStatus {error} notFound="Monographie introuvable" />
{:else}
	<div class="entity-header">
		<h1 class="entity-title"><PublicationTitle titre={monograph.title} /></h1>
		<div class="entity-meta">
			<span class="tag">{monograph.proceedings ? "Volume d'actes" : 'Livre'}</span>
			{#if monograph.year}
				<EntityMetaItem label="Année"><span>{monograph.year}</span></EntityMetaItem>
			{/if}
			{#if monograph.isbn}
				<EntityMetaItem label="ISBN"><span class="tag id-badge">{monograph.isbn}</span></EntityMetaItem>
			{/if}
			{#if monograph.eisbn}
				<EntityMetaItem label="ISBN électronique"><span class="tag id-badge">{monograph.eisbn}</span></EntityMetaItem>
			{/if}
		</div>
		<div class="entity-meta">
			{#if monograph.publisher_id}
				<EntityMetaItem label="Éditeur">
					<a href={resolve(`publishers/${monograph.publisher_id}`)}>{monograph.publisher_name}</a>
				</EntityMetaItem>
			{/if}
			{#if monograph.serial_id}
				<EntityMetaItem label="Collection">
					<a href={resolve(`journals/${monograph.serial_id}`)}>{monograph.journal_title}</a>
				</EntityMetaItem>
			{/if}
		</div>
	</div>

	<div class="m-publications">
		<PublicationsListView
			apiKey={`monograph-${monographId}-publications`}
			context={{ kind: 'monograph', id: monographId }}
			basePath={`/monographs/${monographId}`}
			perPage={50}
		/>
	</div>
{/if}

<style>
	.m-publications { margin-top: 28px; }
</style>
