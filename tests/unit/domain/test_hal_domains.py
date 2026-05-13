"""Tests des helpers de `domain/sources/hal_domains.py` et du parser
`interfaces/cli/dev/refresh_hal_domain_labels.parse_label_s`."""

from domain.sources.hal_domains import HAL_DOMAINS, hal_domain_label, hal_domain_path
from interfaces.cli.dev.refresh_hal_domain_labels import parse_label_s


class TestHalDomainLabel:
    def test_known_code(self):
        # 'chim' est forcément dans le mapping généré.
        assert hal_domain_label("chim") == "Chimie"

    def test_unknown_code_falls_back(self):
        assert hal_domain_label("does.not.exist") == "does.not.exist"

    def test_leaf_label_only(self):
        # `info.info-bi` → "Bio-informatique" (feuille), PAS le chemin complet.
        assert hal_domain_label("info.info-bi") == "Bio-informatique"


class TestHalDomainPath:
    def test_root_returns_label(self):
        assert hal_domain_path("chim") == "Chimie"

    def test_two_levels(self):
        # Reconstitue depuis le code : chim → Chimie, chim.anal → Chimie analytique.
        assert hal_domain_path("chim.anal") == "Chimie / Chimie analytique"

    def test_three_levels(self):
        # phys → phys.astr → phys.astr.co
        assert hal_domain_path("phys.astr.co").startswith("Physique / Astrophysique / ")

    def test_unknown_segment_falls_back_to_code(self):
        # Si un préfixe est inconnu, il apparaît tel quel dans le path.
        assert hal_domain_path("zzz.unknown") == "zzz / zzz.unknown"


class TestParseLabelS:
    def test_simple(self):
        assert parse_label_s("chim = Chimie") == ("chim", "Chimie")

    def test_strips_brackets(self):
        # Annotations [physics], [cs], [q-bio.QM] retirées de la feuille.
        result = parse_label_s("info.info-bi = Informatique [cs]/Bio-informatique [q-bio.QM]")
        assert result == ("info.info-bi", "Bio-informatique")

    def test_preserves_slash_in_leaf(self):
        # 'et/ou' fait partie du nom de feuille — depth=2 (chim.theo) doit
        # forcer maxsplit=1 pour ne pas couper sur le '/' du nom.
        result = parse_label_s("chim.theo = Chimie/Chimie théorique et/ou physique")
        assert result == ("chim.theo", "Chimie théorique et/ou physique")

    def test_three_levels(self):
        result = parse_label_s(
            "phys.phys.phys-acc-ph = Physique [physics]/Physique [physics]/"
            "Physique des accélérateurs [physics.acc-ph]"
        )
        assert result == ("phys.phys.phys-acc-ph", "Physique des accélérateurs")

    def test_invalid_format_returns_none(self):
        assert parse_label_s("no-equals-sign") is None
        assert parse_label_s("") is None
        assert parse_label_s("code = ") is None


class TestHalDomainsContent:
    def test_has_393_entries(self):
        # Sanity check : on régénère depuis l'API qui en expose 393 (au moment
        # de la génération). Si HAL ajoute des domaines et qu'on régénère,
        # bumper ce seuil. On vérifie >= pour résister à un ajout sans casse.
        assert len(HAL_DOMAINS) >= 393

    def test_known_entries_present(self):
        # Quelques codes stables qu'on s'attend à toujours trouver.
        for code in ("chim", "info", "math", "phys", "sdv", "shs"):
            assert code in HAL_DOMAINS, f"{code} absent du mapping"
