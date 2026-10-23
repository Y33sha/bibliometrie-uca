<script lang="ts">
  import { base } from "$app/paths";
  import SectionLabel from "./SectionLabel.svelte";
  import { structIsLabo, structLabelById, type StructInfo } from "$lib/structureLabels";

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
          <a href="{base}/laboratories/{sid}">{structLabelById(structures, sid)}</a>
        {:else}
          <span class="detail-tag">{structLabelById(structures, sid)}</span>
        {/if}
      {/each}
    </div>
  </div>
{/if}
