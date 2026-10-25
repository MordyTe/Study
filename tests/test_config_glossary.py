import textwrap

from studio_transcribe.config import Config
from studio_transcribe.glossary import build_initial_prompt, load_glossary
from studio_transcribe.models import Segment


def test_config_defaults_are_offline_hebrew():
    cfg = Config.from_dict({})
    assert cfg.language == "he"
    assert "ivrit-ai" in cfg.model
    assert cfg.decode.condition_on_previous_text is False
    assert cfg.vad.enabled is True


def test_config_channels_and_speaker_map():
    cfg = Config.from_dict(
        {
            "channels": [
                {"index": 1, "speaker": "מנחה"},
                {"index": 2, "speaker": "אורח", "enabled": False},
                {"index": 3, "speaker": ""},
            ]
        }
    )
    assert cfg.speaker_map() == {1: "מנחה", 2: "אורח"}
    assert cfg.enabled_channels() == [1, 3]


def test_config_overrides_decode_and_vad():
    cfg = Config.from_dict({"decode": {"beam_size": 1}, "vad": {"threshold": 0.7}})
    assert cfg.decode.beam_size == 1
    assert cfg.vad.threshold == 0.7


def test_load_glossary_skips_comments_and_dupes(tmp_path):
    p = tmp_path / "glossary.txt"
    p.write_text(
        textwrap.dedent(
            """\
            # names
            דני
            Deepgram

            דני
            vMix
            """
        ),
        encoding="utf-8",
    )
    assert load_glossary(str(p)) == ["דני", "Deepgram", "vMix"]


def test_build_initial_prompt_truncates_at_term_boundary():
    terms = ["alpha", "beta", "gamma", "delta"]
    prompt = build_initial_prompt(terms, max_chars=15)
    # "alpha, beta" = 11 chars; adding ", gamma" would exceed 15.
    assert prompt == "alpha, beta"


def test_segment_low_confidence_detection():
    assert Segment(0, 1, "x", avg_logprob=-1.2).is_low_confidence()
    assert Segment(0, 1, "x", compression_ratio=3.0).is_low_confidence()
    assert not Segment(0, 1, "x", avg_logprob=-0.2, compression_ratio=1.5).is_low_confidence()
