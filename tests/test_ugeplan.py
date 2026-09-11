import datetime
import os
import pytest
import json

from custom_components.aula.client import (
    DANISH_WEEKDAYS,
    parse_mu_ugebrev_html,
    build_easyiq_skoleportal_ugeplan,
    build_easyiq_legacy_ugeplan,
    build_meebook_ugeplan,
    extract_easyiq_skoleportal_general_description,
)


def load_json_fixture(filename):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", filename)
    with open(fixture_path) as f:
        return json.load(f)


def load_text_fixture(filename):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", filename)
    with open(fixture_path, encoding="utf-8") as f:
        return f.read()


def weekday_name(year, month, day):
    return DANISH_WEEKDAYS[datetime.date(year, month, day).weekday()]


@pytest.fixture
def mu_ugebrev_html():
    return load_text_fixture("mu_ugebrev.html")


@pytest.fixture
def easyiq_skoleportal_events():
    return load_json_fixture("easyiq_skoleportal_weekplan_events.json")


@pytest.fixture
def easyiq_skoleportal_general():
    return load_json_fixture("easyiq_skoleportal_weekplan_general.json")


@pytest.fixture
def easyiq_legacy_events():
    return load_json_fixture("easyiq_legacy_events.json")["Events"]


@pytest.fixture
def meebook_weekplan():
    return load_json_fixture("meebook_weekplan.json")


# --- parse_mu_ugebrev_html -----------------------------------------------


def test_mu__structure_and_week(mu_ugebrev_html):
    result = parse_mu_ugebrev_html(mu_ugebrev_html, "2026-W37")
    assert result["week"] == "2026-W37"
    assert result["notices"] == []
    assert [day["day"] for day in result["days"]] == [
        "Mandag",
        "Tirsdag",
        "Onsdag",
        "Torsdag",
        "Fredag",
    ]
    assert [day["date"] for day in result["days"]] == [
        "2026-09-07",
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
    ]


def test_mu__mandag_lessons(mu_ugebrev_html):
    result = parse_mu_ugebrev_html(mu_ugebrev_html, "2026-W37")
    mandag = result["days"][0]
    assert [(l["time"], l["title"]) for l in mandag["lessons"]] == [
        ("08:00-09:30", "Idræt"),
        ("10:00-11:30", "Dansk"),
        ("12:15-13:00", "Trivsel"),
    ]
    assert "Vi skal i gul sal." in mandag["lessons"][0]["description"]
    assert "øver stafet" in mandag["lessons"][0]["description"]
    assert "Klokken 11: Mindfulness" in mandag["lessons"][1]["description"]
    assert (
        mandag["lessons"][2]["description"]
        == "<br/>Vi tjekker ind i SFO og ser dagens bogstav med Hr. skæg<br/><br/>"
    )
    for lesson in mandag["lessons"]:
        assert lesson["teacher"] is None


def test_mu__tirsdag_lesson_order_preserved(mu_ugebrev_html):
    # source lists the 12:15 lesson before the 08:00 one - order must be preserved, not sorted
    result = parse_mu_ugebrev_html(mu_ugebrev_html, "2026-W37")
    tirsdag = result["days"][1]
    assert [(l["time"], l["title"]) for l in tirsdag["lessons"]] == [
        ("12:15-13:00", "Leg og lær"),
        ("08:00-09:30", "Dansk"),
        ("10:00-11:30", "Matematik"),
    ]
    assert "øvelser med tal" in tirsdag["lessons"][0]["description"]
    assert "på et nyt emne om geometri" in tirsdag["lessons"][2]["description"]


def test_mu__last_day_and_lesson_are_not_dropped(mu_ugebrev_html):
    # the last lesson of the last day only gets flushed by an explicit
    # end-of-document flush, easy to accidentally omit
    result = parse_mu_ugebrev_html(mu_ugebrev_html, "2026-W37")
    fredag = result["days"][-1]
    assert fredag["day"] == "Fredag"
    assert [(l["time"], l["title"]) for l in fredag["lessons"]] == [
        ("08:00-09:30", "Dansk"),
        ("10:00-11:30", "Leg og lær"),
        ("12:15-13:00", "Trivsel"),
    ]
    assert "Fredagshygge med leg og tjek ind i SFO" in fredag["lessons"][-1]["description"]


def test_mu__html_entities_are_decoded_not_left_raw(mu_ugebrev_html):
    result = parse_mu_ugebrev_html(mu_ugebrev_html, "2026-W37")
    flat = json.dumps(result, ensure_ascii=False)
    assert "&aelig;" not in flat
    assert "&oslash;" not in flat
    assert "&aring;" not in flat
    assert "æ" in flat and "ø" in flat and "å" in flat


def test_mu__empty_indhold_returns_empty_schema():
    assert parse_mu_ugebrev_html("", "2026-W37") == {
        "week": "2026-W37",
        "days": [],
        "notices": [],
        "general": None,
    }
    assert parse_mu_ugebrev_html(None, "2026-W37") == {
        "week": "2026-W37",
        "days": [],
        "notices": [],
        "general": None,
    }


def test_mu__bold_before_first_heading_becomes_a_notice():
    html = "<b>Skolen holder lukket fredag</b><br>Se mere info på Aula.<h3>Mandag 07/09</h3><b>08:00-09:30 Dansk</b><br>Indhold."
    result = parse_mu_ugebrev_html(html, "2026-W37")
    assert result["notices"] == [
        {
            "title": "Skolen holder lukket fredag",
            "description": "<br/>Se mere info på Aula.",
            "teacher": None,
        }
    ]
    assert len(result["days"]) == 1
    assert result["days"][0]["notices"] == []
    assert result["days"][0]["lessons"][0]["title"] == "Dansk"


def test_mu__bold_without_time_prefix_falls_back_to_title_only():
    html = "<h3>Mandag 07/09</h3><b>Info</b><br>Ingen tidspunkt angivet."
    result = parse_mu_ugebrev_html(html, "2026-W37")
    lesson = result["days"][0]["lessons"][0]
    assert lesson["time"] is None
    assert lesson["title"] == "Info"


# --- build_easyiq_skoleportal_ugeplan ------------------------------------


def test_easyiq_skoleportal__groups_and_sorts_days(easyiq_skoleportal_events):
    result = build_easyiq_skoleportal_ugeplan(easyiq_skoleportal_events, "2026-W37")
    assert result["week"] == "2026-W37"
    assert len(result["days"]) == 2

    day1, day2 = result["days"]
    assert day1["day"] == weekday_name(2026, 9, 7)
    assert day1["date"] == "2026-09-07"
    assert len(day1["lessons"]) == 2
    assert day1["lessons"][0] == {
        "time": "08:00-09:30",
        "title": "Læsebånd",
        "description": "<p>Vi læser i grupper.</p>",
        "teacher": "Anna Andersen",
    }
    assert day1["lessons"][1]["title"] == "Geometri"

    assert day2["day"] == weekday_name(2026, 9, 8)
    assert day2["date"] == "2026-09-08"
    assert len(day2["lessons"]) == 1
    assert day2["lessons"][0]["title"] == "Boldspil"
    assert day2["lessons"][0]["teacher"] == "Peter Petersen"
    assert day2["notices"] == []


def test_easyiq_skoleportal__courseless_item_becomes_a_notice(easyiq_skoleportal_events):
    result = build_easyiq_skoleportal_ugeplan(easyiq_skoleportal_events, "2026-W37")
    assert len(result["notices"]) == 1
    notice = result["notices"][0]
    assert notice["title"] == "Vigtig besked"
    assert notice["teacher"] is None
    assert "Husk gymnastiktøj hele ugen." in notice["description"]


def test_easyiq_skoleportal__courseless_item_with_date_becomes_a_day_notice(easyiq_skoleportal_events):
    result = build_easyiq_skoleportal_ugeplan(easyiq_skoleportal_events, "2026-W37")
    day1 = result["days"][0]
    assert day1["date"] == "2026-09-07"
    assert len(day1["notices"]) == 1
    assert day1["notices"][0]["title"] == "Bytur"
    assert "Husk madpakke til turen." in day1["notices"][0]["description"]


def test_easyiq_skoleportal__general_description_defaults_to_none(easyiq_skoleportal_events):
    result = build_easyiq_skoleportal_ugeplan(easyiq_skoleportal_events, "2026-W37")
    assert result["general"] is None


def test_easyiq_skoleportal__general_description_is_passed_through(easyiq_skoleportal_events):
    result = build_easyiq_skoleportal_ugeplan(easyiq_skoleportal_events, "2026-W37", "<p>God uge til jer alle.</p>")
    assert result["general"] == "<p>God uge til jer alle.</p>"


# --- extract_easyiq_skoleportal_general_description ----------------------


def test_extract_general_description__returns_visible_weekplan_text(easyiq_skoleportal_general):
    text = extract_easyiq_skoleportal_general_description(easyiq_skoleportal_general)
    assert text == "<p>Kære forældre</p><p>God uge til jer alle.</p>"


def test_extract_general_description__matches_by_activity_name(easyiq_skoleportal_general):
    text = extract_easyiq_skoleportal_general_description(easyiq_skoleportal_general, activity_name="0C")
    assert text == "<p>Kære forældre</p><p>God uge til jer alle.</p>"


def test_extract_general_description__no_match_for_other_activity_falls_back(easyiq_skoleportal_general):
    text = extract_easyiq_skoleportal_general_description(easyiq_skoleportal_general, activity_name="9Z")
    assert text == "<p>Kære forældre</p><p>God uge til jer alle.</p>"


def test_extract_general_description__invisible_entries_are_skipped():
    weekplan_json = {
        "WeekPlans": [
            {"ActivityName": "0C", "Text": "<p>Skjult</p>", "IsVisible": False},
        ]
    }
    assert extract_easyiq_skoleportal_general_description(weekplan_json) is None


def test_extract_general_description__missing_weekplans_returns_none():
    assert extract_easyiq_skoleportal_general_description({}) is None
    assert extract_easyiq_skoleportal_general_description(None) is None


# --- build_easyiq_legacy_ugeplan -----------------------------------------


def test_easyiq_legacy__groups_single_day_events(easyiq_legacy_events):
    result = build_easyiq_legacy_ugeplan(easyiq_legacy_events, "2026-W37")
    assert result["week"] == "2026-W37"
    assert len(result["days"]) == 2

    day = result["days"][0]
    assert day["day"] == weekday_name(2026, 9, 7)
    assert day["date"] == "2026-09-07"
    assert day["notices"] == []
    assert day["lessons"] == [
        {
            "time": "08:00-09:30",
            "title": "Idræt",
            "description": "Husk indendørssko.",
            "teacher": "Peter Petersen",
        },
        {
            "time": "10:00-11:30",
            "title": "Anna Andersen",
            "description": "Vi arbejder med former.",
            "teacher": "Anna Andersen",
        },
    ]


def test_easyiq_legacy__multi_day_event_becomes_a_notice(easyiq_legacy_events):
    result = build_easyiq_legacy_ugeplan(easyiq_legacy_events, "2026-W37")
    assert result["notices"] == []

    day2 = result["days"][1]
    assert day2["day"] == weekday_name(2026, 9, 8)
    assert day2["date"] == "2026-09-08"
    assert day2["lessons"] == []
    assert len(day2["notices"]) == 1
    assert day2["notices"][0]["description"] == "Husk pakket taske."


def test_easyiq_legacy__malformed_timestamp_is_skipped(easyiq_legacy_events):
    result = build_easyiq_legacy_ugeplan(easyiq_legacy_events, "2026-W37")
    all_descriptions = [l["description"] for d in result["days"] for l in d["lessons"]]
    all_descriptions += [n["description"] for d in result["days"] for n in d["notices"]]
    all_descriptions += [n["description"] for n in result["notices"]]
    assert "Skal ignoreres." not in all_descriptions


# --- build_meebook_ugeplan ------------------------------------------------


def test_meebook__comment_and_assignment_description_source(meebook_weekplan):
    result = build_meebook_ugeplan(meebook_weekplan, "2026-W48")
    assert result["week"] == "2026-W48"
    assert result["notices"] == []

    mandag = result["days"][0]
    assert mandag["day"] == "Mandag"
    assert mandag["date"] == "2026-11-23"
    assert mandag["notices"] == []
    assert mandag["lessons"][0]["title"] == "Dansk"
    assert mandag["lessons"][0]["teacher"] == "Mette Mettesen"
    assert mandag["lessons"][0]["description"] == "1. lektion: morgenbånd med læsning."
    # the old markdown numbered-list escape hack must not resurface
    assert "1\\." not in mandag["lessons"][0]["description"]

    tirsdag = result["days"][1]
    assert tirsdag["lessons"][0]["title"] == "Matematik"
    assert tirsdag["lessons"][0]["description"] == "Aflever opgave 3 i Kontext."


def test_meebook__no_fag_tilknyttet_means_no_title(meebook_weekplan):
    result = build_meebook_ugeplan(meebook_weekplan, "2026-W48")
    onsdag = result["days"][2]
    assert onsdag["lessons"][0]["title"] is None
    assert onsdag["lessons"][0]["description"] == "Husk gymnastiktøj."


def test_meebook__empty_tasks_means_empty_lessons_list(meebook_weekplan):
    result = build_meebook_ugeplan(meebook_weekplan, "2026-W48")
    torsdag = result["days"][3]
    assert torsdag["lessons"] == []


def test_meebook__unknown_task_type_does_not_raise(meebook_weekplan):
    result = build_meebook_ugeplan(meebook_weekplan, "2026-W48")
    fredag = result["days"][4]
    assert fredag["lessons"][0]["description"] == ""
