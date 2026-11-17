import pytest

from minicode.naming import normalize_title
from minicode.paths import TITLES_FILE


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        ("Minicode: Azure Batch", "Minicode: Azure Batch"),
        ("MiniCode: Microsoft Fabric & SQL Europe 2026 news", "Minicode: Microsoft Fabric & SQL Europe 2026 news"),
        ("Minikode: Azure App Service deployment with containers", "Minicode: Azure App Service deployment with containers"),
        ("Mini-Code ZureBot Redesign work at Tooling", "Minicode: ZureBot Redesign work at Tooling"),
        ("Minicode - Material UI", "Minicode: Material UI"),
        ("Minicode  JavaScript - ES2018 features", "Minicode: JavaScript - ES2018 features"),
        ("Minicode(?): Criticize our \"data-platform\" implementation", 'Minicode: Criticize our "data-platform" implementation'),
        ("Minicode (Nano Edition): OpenWebUI", "Minicode: OpenWebUI"),
        ("🤖 Zure AI Minicode: Google NotebookLM and DeepSeek (run locally)", "Minicode: Google NotebookLM and DeepSeek (run locally)"),
        ("Minicode: Let's talk about HTMX! 🔥", "Minicode: Let's talk about HTMX!"),
        ("Minicode on simple tips how to enhance project accessibility", "Minicode: On simple tips how to enhance project accessibility"),
        ("Minicode\\_ Data Vault 2.0 intro", "Minicode: Data Vault 2.0 intro"),
        ("Minicode\\_ Introduction to K6 for developers-20221221_11331", "Minicode: Introduction to K6 for developers"),
        ("Minicode\\_ Profile photo manipulation with Affinity Photo-20220621_140008-Meeting Recording",
         "Minicode: Profile photo manipulation with Affinity Photo"),
        ("(Optional) [Minicode]\\_ Outbox pattern in ASP.NET Core application with CAP-20210827_100114",
         "Minicode: Outbox pattern in ASP.NET Core application with CAP"),
        ("Minicode\\_ Epic Azure API Management Trilogy - Part III", "Minicode: Epic Azure API Management Trilogy - Part 3"),
        ("Minicode: Seure employee recommendation, pt. 2", "Minicode: Seure employee recommendation - Part 2"),
        ("Minicode Modular Bicep in Energinet, everything as code 1/2", "Minicode: Modular Bicep in Energinet, everything as code - Part 1"),
        ("Minicode\\_ Experiences from Energinet, everything as code, part 2/2",
         "Minicode: Experiences from Energinet, everything as code - Part 2"),
        ("Minicode: The making of Zpeedy - part 1: Just enough analysis", "Minicode: The making of Zpeedy: Just enough analysis - Part 1"),
        ("Minicode: Email (security) - Level 100", "Minicode: Email (security)"),
        ("Project Intro - Monitzion-20210326_093313", "Project Intro: Monitzion"),
        ("POC Intro - Digita BTS Site locator", "Project Intro: Digita BTS Site locator"),
        ("Project intro: Valmet ML operating framework", "Project Intro: Valmet ML operating framework"),
        ("Seuren projekti-intro", "Project Intro: Seuren projekti-intro"),
        ("Training - Azure Networking 201 (Mandatory for technical roles)", "Training: Azure Networking 201 (Mandatory for technical roles)"),
        ("Minitraining: DevSecOps security safetyguards in continuous integration (disobey workshop test run)",
         "Training: DevSecOps security safetyguards in continuous integration (disobey workshop test run)"),
        ("[Mandatory for Devs] Zure Integration Platform template training and Q&A",
         "Training: Zure Integration Platform template training and Q&A"),
        ("Backend -template koulutus 3/2019", "Training: Backend -template koulutus"),
        ("MiniHR: stress & burnout", "People & Culture: Stress & burnout"),
        ("AI series: Join Jani as he presents how he uses AI tools in his daily work",
         "AI Series: Join Jani as he presents how he uses AI tools in his daily work"),
        ("Azure PaaS tool selection 17.12.2018", "Minicode: Azure PaaS tool selection"),
        # Two capitalized words must not be mistaken for a presenter name.
        ("Minicode: Threat Modeling", "Minicode: Threat Modeling"),
        ("Minicode: Case Seure - User research and feedback to drive mobile development",
         "Minicode: Case Seure - User research and feedback to drive mobile development"),
    ],
)  # fmt: skip
def test_display_title(raw: str, display: str) -> None:
    assert normalize_title(raw).display == display


@pytest.mark.parametrize(
    ("raw", "presenter", "date_hint"),
    [
        ("Minicode - Lauri Lehman - 2018-12-14 - Text Analysis", "Lauri Lehman", "2018-12-14"),
        ("What the hell is Zero Knowledge technology - Lauri Peltonen", "Lauri Peltonen", None),
        ("Juval Nadav - perjantai 7. syyskuuta 2018 15.09.03", "Juval Nadav", "2018-09-07"),
        ("VSTS käyttö mobiili DevOps projektissa - Okko Oulasvirta - perjantai 1. kesäkuuta 2018 14.11.07",
         "Okko Oulasvirta", "2018-06-01"),
        ("Minicode  Blockchains and Azure - Friday, 14 December 2018 14.03.11", None, "2018-12-14"),
        ("Minicode  EF Core, transactions ja ha. . . - 25 January 2019 12.00.29", None, "2019-01-25"),
        ("AI series: Join Pasi Huuhka as he presents how he uses AI tools in his daily work", "Pasi Huuhka", None),
        ("Minicode: Zure Template updates 09/2021", None, "2021-09"),
        ("Minicode: Zure Template BasicApp Updates 01/25", None, "2025-01"),
    ],
)  # fmt: skip
def test_metadata_extracted(raw: str, presenter: str | None, date_hint: str | None) -> None:
    n = normalize_title(raw)
    assert (n.presenter, n.date_hint) == (presenter, date_hint)


def test_metadata_flags() -> None:
    assert normalize_title("DevOps & QA Guild Training: Zure.Template.BasicApp Setup for a new project").guild == "DevOps & QA"
    assert normalize_title("Minicode: Migrate existing Service Bus standard namespace to premium tier- Level 200/300").level_hint == 300
    assert normalize_title("(Optional) [Minicode]\\_ Outbox pattern").optional
    assert normalize_title("Security Guild: HTTP Headers (Mandatory for tech roles, see description)").mandatory
    assert normalize_title("Juval Nadav - perjantai 7. syyskuuta 2018 15.09.03").title == "Untitled recording"


def test_normalizer_is_idempotent_on_all_titles() -> None:
    for raw in TITLES_FILE.read_text(encoding="utf-8").splitlines():
        first = normalize_title(raw)
        again = normalize_title(first.display)
        assert again.display == first.display, raw
        assert "\\" not in first.display and "  " not in first.display
