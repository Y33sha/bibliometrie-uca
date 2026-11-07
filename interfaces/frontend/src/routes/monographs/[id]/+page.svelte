<script lang="ts">
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { apiDetail } from '#lib/api/index.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TitleRow from '#lib/components/TitleRow.svelte';
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
		<TitleRow>
			<h1 class="entity-title"><PublicationTitle titre={monograph.title} /></h1>
			{#snippet identifierLinks()}
				<span class="title-identifier-text">
					{#if monograph!.isbn}<span><span class="identifier-label">ISBN</span> {monograph!.isbn}</span>{/if}
					{#if monograph!.eisbn}<span><span class="identifier-label">eISBN</span> {monograph!.eisbn}</span>{/if}
				</span>
			{/snippet}
		</TitleRow>
		<div class="entity-meta">
			<span>{monograph.proceedings ? "Volume d'actes" : 'Livre'}{#if monograph.year}, {monograph.year}{/if}</span>
			{#if monograph.publisher_id}
				<a href={resolve(`publishers/${monograph.publisher_id}`)}>{monograph.publisher_name}</a>
			{/if}
			{#if monograph.serial_id}
				<a href={resolve(`journals/${monograph.serial_id}`)}>{monograph.journal_title}</a>
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
