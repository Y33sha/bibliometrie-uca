import { describe, it, expect } from "vitest";
import { structsTooltip, type StructInfo, type SourceAuthorship } from "./types";

const struct = (over: Partial<StructInfo>): StructInfo =>
  ({ id: 1, name: "Laboratoire", acronym: "LAB", type: "labo", ...over }) as StructInfo;

const authorship = (over: Partial<SourceAuthorship>): SourceAuthorship =>
  ({ raw_affiliation: null, structure_ids: [], ...over }) as SourceAuthorship;

describe("structsTooltip", () => {
  it("assemble l'affiliation brute et les structures identifiées", () => {
    const out = structsTooltip(
      authorship({ raw_affiliation: "Université Clermont Auvergne", structure_ids: [1] }),
      { "1": struct({ acronym: "LMBP" }) },
    );
    expect(out).toBe("Université Clermont Auvergne\nStructures identifiées : LMBP");
  });

  it("ne produit aucun balisage HTML autour d'une affiliation malveillante (non-régression XSS)", () => {
    // L'affiliation brute vient des sources externes : le tooltip la rend en texte,
    // la fonction ne doit introduire aucune balise autour d'elle.
    const payload = '<img src=x onerror="alert(1)">';
    const out = structsTooltip(authorship({ raw_affiliation: payload }), {});
    // La charge utile ressort telle quelle (elle sera affichée comme texte par Tooltip),
    // sans balise ajoutée par la fonction (pas de <em>, pas de <br>).
    expect(out).toBe(payload);
    expect(out).not.toContain("<em>");
    expect(out).not.toContain("<br>");
  });
});
