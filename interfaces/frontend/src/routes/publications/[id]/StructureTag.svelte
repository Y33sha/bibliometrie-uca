<script lang="ts">
  import { resolve } from "$app/paths";
  import { structIsLabo, structLabelById, type StructInfo } from "#lib/structureLabels.js";

  // Tag d'une structure liée à une publication : lien vers la fiche labo si c'en est un, sinon span non cliquable (établissement, partenaires…).
  // `tab` : onglet ciblé sur la fiche labo (ex. "theses").
  let {
    structures,
    sid,
    tab,
  }: {
    structures: Record<string, StructInfo>;
    sid: number;
    tab?: string;
  } = $props();
</script>

{#if structIsLabo(structures, sid)}
  <a href={resolve(`structures/${sid}${tab ? `?tab=${tab}` : ''}`)} class="structure-tag"
    >{structLabelById(structures, sid)}</a
  >
{:else}
  <span class="structure-tag">{structLabelById(structures, sid)}</span>
{/if}
