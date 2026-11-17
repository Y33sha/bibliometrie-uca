<script lang="ts">
	import { tooltip } from '#lib/actions/tooltip.svelte.js';
	import { issnPortalUrl } from '#lib/utils.js';

	// Badge d'un ISSN, lien vers sa notice sur le portail ISSN.
	let { issn }: { issn: string } = $props();
</script>

<a class="tag id-badge" href={issnPortalUrl(issn)} target="_blank" rel="noopener" use:tooltip={'Portail ISSN (nouvel onglet)'}>{issn}</a>
