<script lang="ts">
	import { base } from "$app/paths";
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";

	// Redirige /docs vers /docs/exploitation (première page de la sidebar)
	onMount(() => {
		goto(`${base}/docs/exploitation`, { replaceState: true });
	});
</script>
