<script lang="ts">
	import { institution } from '#lib/institution.svelte.js';
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

<PageHeader title="Affiliations HAL divergentes">
	Publications affiliées à {institution.name} dans HAL mais pas dans une autre source. La publication est présente dans au moins une source non-HAL avec des adresses, mais sans signature {institution.name} à la même position d'auteur.
</PageHeader>

<ListToolbar {list} one="publication" many="publications" exportUrl={withBase('/api/hal-problems/affiliation-conflicts/export.csv')} />

<ListStatus {list} emptyText="Aucun conflit détecté">
	<div class="table-scroll">
		<table class="data-table">
			<thead>
				<tr>
					<th>{columnLabels.type}</th>
					<th>{columnLabels.year}</th>
					<th>{columnLabels.doi}</th>
					<th>{columnLabels.title}</th>
					<th>{columnLabels.labs}</th>
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
						<td>{#each pub.laboratories as lab (lab.name)}<span class="lab-tag" title={lab.name}>{structureLabel(lab)}</span>{/each}</td>
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
	</div>
	<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
</ListStatus>
