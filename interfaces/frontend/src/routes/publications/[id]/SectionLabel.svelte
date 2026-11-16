<script module lang="ts">
  import FileText from "@lucide/svelte/icons/file-text";
  import Landmark from "@lucide/svelte/icons/landmark";
  import Tag from "@lucide/svelte/icons/tag";
  import User from "@lucide/svelte/icons/user";

  const ICONS = { person: User, building: Landmark, document: FileText, tag: Tag };
</script>

<script lang="ts">
  // Label de section de la fiche détail : petite icône discrète (stroke = couleur du label) + texte.
  let {
    icon,
    text,
  }: {
    icon: keyof typeof ICONS;
    text: string;
  } = $props();

  const Icon = $derived(ICONS[icon]);
</script>

<h2 class="detail-label">
  <Icon class="detail-icon" />
  <span>{text}</span>
</h2>

<style>
  .detail-label {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .detail-label :global(.detail-icon) {
    width: 15px;
    height: 15px;
    opacity: 0.85;
    flex-shrink: 0;
  }
</style>
