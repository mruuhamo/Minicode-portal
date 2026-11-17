import pytest

from minicode.paths import TITLES_FILE
from minicode.taxonomy import compile_keyword, load_taxonomy, tag_title

TITLES = list(dict.fromkeys(TITLES_FILE.read_text(encoding="utf-8").splitlines()))


def test_taxonomy_structure() -> None:
    tax = load_taxonomy()
    assert set(tax.dimensions) == {"topic", "content_type", "level"}
    for dim in tax.dimensions.values():
        ids = dim.tag_ids()
        assert len(ids) == len(set(ids)), f"duplicate tag ids in {dim.id}"
    assert tax.topic.fallback in tax.topic.tag_ids()
    assert tax.content_type.default in tax.content_type.tag_ids()
    assert sorted(int(i) for i in tax.level.tag_ids()) == [100, 200, 300, 400]


@pytest.mark.parametrize("title", TITLES)
def test_every_title_gets_valid_tags(title: str) -> None:
    tax = load_taxonomy()
    result = tag_title(title, tax)
    assert result.topics, title
    assert set(result.topics) <= set(tax.topic.tag_ids())
    assert result.content_type in tax.content_type.tag_ids()
    assert str(result.level) in tax.level.tag_ids()


def test_fallback_only_for_titles_needing_review() -> None:
    fallback = {t for t in TITLES if tag_title(t).topics == ("general",)}
    assert fallback <= {
        "PowerPoint Presentation",
        "Minicode: Assets",
        "Minicode: Exports",
        'Meeting in "Minicode"',
        "Juval Nadav - perjantai 7. syyskuuta 2018 15.09.03",
    }


@pytest.mark.parametrize(
    ("title", "topic", "content_type", "level"),
    [
        ("Minicode: Intro to Bicep", "devops-iac", "knowledge-share", 100),
        ("Minicode: Fabcon Europe 2026 highlights", "data-analytics", "conference-recap", 200),
        ("Minicode: Advanced GenAI development", "ai-genai", "knowledge-share", 300),
        ("DeepData minicode: Transformer architecture", "ai-genai", "knowledge-share", 400),
        ("Minicode: Email (security) - Level 100", "security-identity", "knowledge-share", 100),
        ("Project Intro: Valmet ServiceNow AI", "customer-projects", "project-intro", 100),
        ("Security Guild: HTTP Headers (Mandatory for tech roles, see description)", "security-identity", "training", 200),
        ("MiniHR: stress & burnout", "people-culture", "knowledge-share", 200),
        ("Minicode: Playwright test-automation framework", "testing-qa", "knowledge-share", 200),
    ],
)  # fmt: skip
def test_known_titles(title: str, topic: str, content_type: str, level: int) -> None:
    result = tag_title(title)
    assert topic in result.topics
    assert (result.content_type, result.level) == (content_type, level)


def test_keyword_matching_respects_word_boundaries() -> None:
    assert compile_keyword("ai").search("ai tools")
    assert not compile_keyword("ai").search("maintain")
    assert compile_keyword("test*").search("testautomation")
    assert compile_keyword("c#").search("minicode: c# 8")
    assert "iot-location" not in tag_title("UX & methodology guild training: User story mapping").topics
