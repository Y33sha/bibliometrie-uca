<script lang="ts">
	import { docTypeColorVar, docTypeLabel } from '#lib/labels.js';

	// Pastille du type de document, colorée selon sa famille.
	let { docType }: { docType: string } = $props();
</script>

<span class="type-pill" style="--type-color: var(--{docTypeColorVar(docType)})">{docTypeLabel(docType)}</span>
