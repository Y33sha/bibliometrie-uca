<script lang="ts">
  import { resolve } from "$app/paths";
  import RhCheck from "#lib/components/RhCheck.svelte";
  import SectionLabel from "./SectionLabel.svelte";
  import { titleCase } from "#lib/utils.js";
  import type { Contribution } from "./types";

  let { contributions }: { contributions: Contribution[] } = $props();

  // Personnes des contributions du périmètre, une par lien, dédupliquées (un même `person_id` peut apparaître sur deux contributions sources), ordre d'apparition conservé.
  const persons = $derived.by(() => {
    const seen = new Set<number>();
    const out: Contribution[] = [];
    for (const a of contributions) {
      if (a.in_perimeter && a.person_id != null && !seen.has(a.person_id)) {
        seen.add(a.person_id);
        out.push(a);
      }
    }
    return out;
  });

  function personName(a: Contribution): string {
    return `${titleCase(a.first_name)} ${titleCase(a.last_name)}`.trim();
  }
</script>

{#if persons.length > 0}
  <div class="detail-section detail-row">
    <SectionLabel icon="person" text="Personnes liées" />
    <div class="detail-tags">
      {#each persons as a (a.person_id)}
        <a href={resolve(`persons/${a.person_id}`)}>
          {personName(a)}
          {#if a.has_rh}<RhCheck />{/if}
        </a>
      {/each}
    </div>
  </div>
{/if}
