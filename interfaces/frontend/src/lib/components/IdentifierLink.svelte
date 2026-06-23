<script lang="ts">
  import { base } from "$app/paths";

  let {
    id_type,
    id_value,
    confirmed = true,
  }: {
    id_type: string;
    id_value: string;
    /** Icône en pleine opacité si vrai, atténuée sinon. */
    confirmed?: boolean;
  } = $props();

  const META: Record<
    string,
    { url: (v: string) => string; icon: string; cls: string; label: string }
  > = {
    orcid: {
      url: (v) => `https://orcid.org/${v}`,
      icon: "orcid.ico",
      cls: "id-orcid",
      label: "ORCID",
    },
    idhal: {
      url: (v) => `https://hal.science/search/index/?q=%2A&authIdHal_s=${v}`,
      icon: "hal.ico",
      cls: "id-hal",
      label: "idHAL",
    },
    idref: {
      url: (v) => `https://www.idref.fr/${v}`,
      icon: "idref.png",
      cls: "id-idref",
      label: "IdRef",
    },
  };

  const meta = $derived(META[id_type] ?? null);
</script>

{#if meta}
  <a
    class="id-icon {meta.cls}"
    class:id-confirmed={confirmed}
    href={meta.url(id_value)}
    target="_blank"
    rel="noopener"
    title="{meta.label} : {id_value}"
  >
    <img src="{base}/icons/{meta.icon}" alt={meta.label} />
  </a>
{:else}
  <span class="id-icon id-placeholder"></span>
{/if}
