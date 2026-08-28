<script lang="ts">
	import { sanitizeAbstract } from '$lib/utils';

	/** Résumé de publication assaini puis rendu en HTML : il porte, outre le formatage des titres, la structure de paragraphe déposée par les sources. Composant sans balise enveloppante. */
	let { resume }: { resume: string | null | undefined } = $props();
</script>

{@html sanitizeAbstract(resume ?? '')}
