import json

import pytest

from src import analyze


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


VALID = {
    "hook": "POV setup", "hook_type": "relatability", "payoff": "absurd reveal",
    "emotional_driver": "recognition", "humor_mechanism": "escalation",
    "social_driver": "tag a coworker", "comment_driver": "share your worst shift",
    "rewatch_driver": "fast cut loop", "visual_structure": "single take",
    "caption_role": "sets the premise", "audience": "restaurant staff",
    "timing": "none",
    "why_it_overperformed": ["specific", "recognisable", "short"],
    "reusable_pattern": "Insider frustration + recognisable setup + outsized reaction",
    "scores": {"hook": 92, "shareability": 88, "originality": 70,
               "relatability": 95, "rewatchability": 80, "cultural_relevance": 60},
    "ai_virality_score": 89,
}


def test_load_prompt_reads_file():
    text = analyze.load_prompt("analyze_text")
    assert "REUSABLE PATTERN" in text


def test_extract_json_plain():
    assert analyze.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert analyze.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_returns_none_on_garbage():
    assert analyze.extract_json("I'm sorry, I can't do that") is None


def test_analyze_text_returns_parsed_json(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    out = analyze.analyze_text(client, {"shortcode": "A", "caption": "c"},
                               {"name": "DTW", "voice": "v"}, "claude-sonnet-5")
    assert out["ai_virality_score"] == 89
    assert out["reusable_pattern"].startswith("Insider frustration")


def test_analyze_text_retries_once_then_gives_up(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("not json at all")
    out = analyze.analyze_text(client, {"shortcode": "A"}, {"name": "D", "voice": "v"},
                               "claude-sonnet-5")
    assert out is None
    assert client.messages.create.call_count == 2, "one retry, then give up"


def test_analyze_text_rejects_response_missing_required_keys(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response('{"hook": "only this"}')
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None


def test_analyze_text_survives_api_exception(mocker):
    client = mocker.Mock()
    client.messages.create.side_effect = Exception("rate limited")
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None


def test_analyze_text_rejects_response_missing_humor_mechanism(mocker):
    incomplete = {k: v for k, v in VALID.items() if k != "humor_mechanism"}
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(incomplete))
    out = analyze.analyze_text(client, {"shortcode": "A"}, {"name": "D", "voice": "v"},
                               "claude-sonnet-5")
    assert out is None
    assert client.messages.create.call_count == 2
