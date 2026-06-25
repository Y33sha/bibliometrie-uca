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
  .ribbon {
    display: flex;
    align-items: center;
    gap: 3px;
    flex-wrap: wrap;
  }
  .cell {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1.5px solid;
    flex: none;
  }
  .sep {
    width: 1px;
    height: 15px;
    background: var(--muted);
    opacity: 0.5;
    margin: 0 3px;
  }
</style>
