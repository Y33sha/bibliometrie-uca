<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import { columnLabels } from '#lib/labels.js';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { withBase } from '#lib/paths.js';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type Pub = components['schemas']['HalAffiliationConflictPublication'];

	const list = usePaginatedFetch<Pub>({
		endpoint: '/api/hal-problems/affiliation-conflicts',
		itemsKey: 'publications',
		apiKey: 'hal-affiliation-conflicts',
		buildParams: () => new URLSearchParams(),
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (list.page > 1) p.set('page', String(list.page));
		void replaceQuery(resolve('hal-problems/affiliation-conflicts'), p);
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
		if (urlParams.get('page')) list.page = parseInt(urlParams.get('page')!) || 1;
		list.load();
	});
</script>

<PageHeader title="Affiliations HAL divergentes" />

<ListToolbar {list} one="publication" many="publications" exportUrl={withBase('/api/hal-problems/affiliation-conflicts/export.csv')} />

<ListStatus {list} emptyText="Aucun conflit détecté">
	<TableScroll>
		<table class="data-table">
			<thead>
				<tr>
					<th>{columnLabels.type}</th>
					<th>{columnLabels.year}</th>
					<th>{columnLabels.doi}</th>
					<th>{columnLabels.title}</th>
					<th>Auteurs en conflit</th>
					<th>Dépôts HAL</th>
				</tr>
			</thead>
			<tbody>
				{#each list.items as pub (pub.id)}
					<tr>
						<td>{#if pub.doc_type}<DocTypePill docType={pub.doc_type} />{/if}</td>
						<td>{pub.publication_year ?? ''}</td>
						<td>{#if pub.doi}<DoiLink doi={pub.doi} />{/if}</td>
						<td><a href={resolve(`publications/${pub.id}`)} class="publication-title"><PublicationTitle titre={pub.title} /></a></td>
						<td>
							{#each pub.authors as author, i (i)}
								<div class="conflict-author">
									{#if author.person_id}<a href={resolve(`persons/${author.person_id}`)}>{author.name}</a>{:else}{author.name}{/if}
									{#each author.structures as structure (structure.name)}<span class="lab-tag" title={structure.name}>{structureLabel(structure)}</span>{/each}
								</div>
							{/each}
						</td>
						<td>
							<div class="id-list">
								{#each pub.hal_links as link (link.source_id)}
									<a href={link.record_url} target="_blank" rel="noopener" class="id-badge">{link.source_id}</a>
								{/each}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</TableScroll>
	<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
</ListStatus>

<style>
	.conflict-author {
		white-space: nowrap;
	}
	.conflict-author + .conflict-author {
		margin-top: 0.25rem;
	}
	.conflict-author .lab-tag {
		color: var(--text-secondary);
		font-weight: 400;
	}
	.conflict-author .lab-tag:first-of-type {
		margin-left: 0.5rem;
	}
</style>
