<script lang="ts">
	import { base } from "$app/paths";
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";

	// Redirige /docs vers /docs/architecture (première page)
	onMount(() => {
		goto(`${base}/docs/architecture`, { replaceState: true });
	});
</script>
