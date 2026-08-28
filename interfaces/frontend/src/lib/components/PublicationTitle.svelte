<script lang="ts">
	import { sanitizeTitle } from '$lib/utils';

	/** Titre de publication assaini puis rendu en HTML : le formatage porte du sens (exposants, indices, notation mathématique). Composant sans balise enveloppante, utilisable partout où le texte l'était. */
	let { titre }: { titre: string | null | undefined } = $props();
</script>

{@html sanitizeTitle(titre ?? '')}
