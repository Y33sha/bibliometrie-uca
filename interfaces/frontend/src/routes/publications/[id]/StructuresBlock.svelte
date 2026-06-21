<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import { structIsLabo, structLabel, type StructInfo } from "./types";

  let {
    structureIds,
    structures,
  }: {
    structureIds: number[];
    structures: Record<string, StructInfo>;
  } = $props();
</script>

{#if structureIds.length > 0}
  <div class="detail-section">
    <SectionLabel icon="building" text="Structures liées" />
    <div class="detail-tags">
      {#each structureIds as sid (sid)}
        {#if structIsLabo(structures, sid)}
          <a href="{base}/laboratories/{sid}">{structLabel(structures, sid)}</a>
        {:else}
          <span class="detail-tag">{structLabel(structures, sid)}</span>
        {/if}
      {/each}
    </div>
  </div>
{/if}
