<script lang="ts">
  import { CELL_BG, CELL_COLOR, STATUS_LABEL, type Status } from "./helpers";

  let {
    allPhases,
    statuses,
    fanoutAfter = "normalize",
  }: {
    allPhases: string[];
    statuses: Record<string, Status>;
    fanoutAfter?: string;
  } = $props();
</script>

<div class="ribbon">
  {#each allPhases as phase, i (phase)}
    {#if i > 0 && allPhases[i - 1] === fanoutAfter}
      <span class="sep" aria-hidden="true"></span>
    {/if}
    {@const st = (statuses[phase] ?? "ghost") as Status | "ghost"}
    <span
      class="cell"
      title="{phase} — {st === 'ghost' ? 'non jouée' : STATUS_LABEL[st]}"
      style="background:{CELL_BG[st]}; border-color:{CELL_COLOR[st]};"
    ></span>
  {/each}
</div>

<style>
  /* Une seule ligne : les cellules rétrécissent quand la largeur manque. */
  .ribbon {
    display: flex;
    align-items: center;
    gap: 3px;
  }
  .cell {
    flex: 0 1 15px;
    min-width: 0;
    aspect-ratio: 1;
    border-radius: var(--radius);
    border: 1.5px solid;
  }
  .sep {
    flex: none;
    width: 1px;
    height: 15px;
    background: var(--muted);
    opacity: 0.5;
    margin: 0 3px;
  }
</style>
