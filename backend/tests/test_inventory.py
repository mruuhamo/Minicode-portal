from pathlib import Path

import pytest

from minicode.inventory.__main__ import main
from minicode.inventory.analysis import build_inventory, title_issues
from minicode.inventory.models import Recording, RecordingStatus
from minicode.inventory.report import to_markdown
from minicode.inventory.sources import GraphRecordingSource, MockRecordingSource, RecordingSource


@pytest.fixture
def titles_file(tmp_path: Path) -> Path:
    path = tmp_path / "titles.txt"
    path.write_text(
        "\n".join(
            [
                "Minicode: Azure ML Web Services",
                "Minicode: Azure ML Web Services",
                "Minicode: User Research for All",
                "Minicode: User Research For All",
                "PowerPoint Presentation",
                "",
                "Minicode\\_ Introduction to K6 for developers-20221221_11331",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_sources_implement_protocol() -> None:
    assert isinstance(MockRecordingSource(), RecordingSource)
    assert isinstance(GraphRecordingSource(site_id="x"), RecordingSource)


def test_mock_source_is_deterministic_and_skips_blank_lines(titles_file: Path) -> None:
    first = list(MockRecordingSource(titles_file).list_recordings())
    second = list(MockRecordingSource(titles_file).list_recordings())
    assert first == second
    assert len(first) == 6
    assert all(r.source == "mock" and r.has_transcript is not None for r in first)


def test_graph_source_requires_site_id() -> None:
    with pytest.raises(ValueError, match="MINICODE_SITE_ID"):
        list(GraphRecordingSource(site_id="").list_recordings())


def test_build_inventory_counts_and_duplicates(titles_file: Path) -> None:
    report = build_inventory(MockRecordingSource(titles_file).list_recordings(), source="mock")
    assert (report.total, report.unique_titles) == (6, 5)
    assert report.exact_duplicates == {"Minicode: Azure ML Web Services": 2}
    assert report.near_duplicates == [["Minicode: User Research for All", "Minicode: User Research For All"]]
    assert sum(report.transcript_counts().values()) == 6


def test_status_and_transcript_counts() -> None:
    recs = [
        Recording(id="1", title="Minicode: A", status=RecordingStatus.EXPIRED, has_transcript=False),
        Recording(id="2", title="Minicode: B", status=RecordingStatus.AVAILABLE, has_transcript=True),
        Recording(id="3", title="Minicode: C"),
    ]
    report = build_inventory(recs, source="test")
    assert report.status_counts()[RecordingStatus.EXPIRED] == 1
    assert report.transcript_counts() == {"no": 1, "yes": 1, "unknown": 1}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Minicode\\_ Introduction to K6 for developers-20221221_11331", {"TIMESTAMP_SUFFIX", "ESCAPED_CHARS", "PREFIX_VARIANT"}),
        ("Minikode: Azure App Service deployment with containers", {"PREFIX_VARIANT"}),
        ("Valmet: Azure DevOps läpikäynti", {"FINNISH", "MISSING_SERIES_PREFIX"}),
        ("PowerPoint Presentation", {"NON_RECORDING", "MISSING_SERIES_PREFIX"}),
        ("Azure PaaS tool selection 17.12.2018", {"DATE_IN_TITLE", "MISSING_SERIES_PREFIX"}),
        ("Minicode: MediatR and vertical slices Part II", {"PART_NUMBERING"}),
        ("Minicode: Let's talk about HTMX! 🔥", {"EMOJI"}),
        ("Minicode: Azure Batch", set()),
        ("Project Intro: Axla Customer Portal", set()),
    ],
)  # fmt: skip
def test_title_issues(title: str, expected: set[str]) -> None:
    assert set(title_issues(title)) == expected


def test_report_and_cli(titles_file: Path, tmp_path: Path) -> None:
    out, csv_path = tmp_path / "report.md", tmp_path / "inventory.csv"
    assert main(["--titles", str(titles_file), "--out", str(out), "--csv", str(csv_path)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "SIMULATED" in text and "| Recordings (rows) | 6 |" in text
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 7


def test_markdown_for_real_source_has_no_simulation_note() -> None:
    report = build_inventory([Recording(id="1", title="Minicode: A", has_transcript=True)], source="graph")
    assert "SIMULATED" not in to_markdown(report)
