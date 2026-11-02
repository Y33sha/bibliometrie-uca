<script lang="ts">
	import { issnPortalUrl } from '#lib/utils.js';

	// Badge d'un ISSN, lien vers sa notice sur le portail ISSN.
	let { issn }: { issn: string } = $props();
</script>

<a class="id-badge" href={issnPortalUrl(issn)} target="_blank" rel="noopener" title="Portail ISSN (nouvel onglet)">{issn}</a>
