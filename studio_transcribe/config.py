"""Configuration model.

Loadable from a dict (used in tests and programmatic use) or a YAML file
(``from_yaml`` imports PyYAML lazily). Every field has a sensible default so
``Config.from_dict({})`` yields a working offline-Hebrew configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class ChannelConfig:
    index: int
    speaker: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ChannelConfig":
        return cls(
            index=int(d["index"]),
            speaker=str(d.get("speaker", "")),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class VadConfig:
    enabled: bool = True
    # Silero speech probability threshold (0..1). Higher = stricter.
    threshold: float = 0.5
    min_speech_ms: int = 250
    min_silence_ms: int = 400
    speech_pad_ms: int = 150


@dataclass
class DecodeConfig:
    """faster-whisper decoding options tuned for Hebrew accuracy + anti-loop."""

    beam_size: int = 5
    temperature: float = 0.0
    # Carrying previous text fuels repetition loops in Hebrew; off by default.
    condition_on_previous_text: bool = False
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    word_timestamps: bool = True


@dataclass
class CloudConfig:
    """Optional cloud fallback / live code-switching engine."""

    enabled: bool = False
    provider: str = "soniox"  # soniox | elevenlabs | azure
    api_key_env: str = "STUDIO_TRANSCRIBE_CLOUD_KEY"


@dataclass
class LLMCorrectionConfig:
    enabled: bool = False
    # Only segments flagged low-confidence get sent to the LLM.
    logprob_threshold: float = -0.7
    compression_ratio_threshold: float = 2.4
    model: str = "claude-opus-4-8"


@dataclass
class LiveConfig:
    """Live-caption layer (Stage 3)."""

    enabled: bool = False
    engine: str = "soniox"  # soniox (cloud) | zipformer (local)
    model: str = "stt-rt-v4"
    throttle_ms: int = 300
    max_chars: int = 120
    max_lines: int = 2
    energy_threshold: float = 1e-4  # per-channel silence gate before streaming
    sink: str = "stdout"  # obs | vmix | file | stdout
    obs: Dict[str, Any] = field(default_factory=dict)  # host, port, password, source
    vmix: Dict[str, Any] = field(default_factory=dict)  # url, input, field
    file: Dict[str, Any] = field(default_factory=dict)  # path


@dataclass
class Config:
    engine: str = "faster-whisper"
    model: str = "ivrit-ai/whisper-large-v3-turbo-ct2"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"  # auto | float16 | int8_float16 | int8
    language: str = "he"
    sample_rate: int = 16000
    join_gap: float = 0.8
    glossary_path: Optional[str] = None
    db_path: Optional[str] = None
    channels: List[ChannelConfig] = field(default_factory=list)
    vad: VadConfig = field(default_factory=VadConfig)
    decode: DecodeConfig = field(default_factory=DecodeConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)
    llm_correction: LLMCorrectionConfig = field(default_factory=LLMCorrectionConfig)
    live: LiveConfig = field(default_factory=LiveConfig)

    def speaker_map(self) -> Dict[int, str]:
        return {c.index: c.speaker for c in self.channels if c.speaker}

    def enabled_channels(self) -> List[int]:
        return [c.index for c in self.channels if c.enabled]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Config":
        d = dict(d or {})
        channels = [ChannelConfig.from_dict(c) for c in d.get("channels", [])]
        return cls(
            engine=d.get("engine", cls.engine),
            model=d.get("model", cls.model),
            device=d.get("device", cls.device),
            compute_type=d.get("compute_type", cls.compute_type),
            language=d.get("language", cls.language),
            sample_rate=int(d.get("sample_rate", cls.sample_rate)),
            join_gap=float(d.get("join_gap", cls.join_gap)),
            glossary_path=d.get("glossary_path"),
            db_path=d.get("db_path"),
            channels=channels,
            vad=VadConfig(**d.get("vad", {})),
            decode=DecodeConfig(**d.get("decode", {})),
            cloud=CloudConfig(**d.get("cloud", {})),
            llm_correction=LLMCorrectionConfig(**d.get("llm_correction", {})),
            live=LiveConfig(**d.get("live", {})),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        import yaml  # lazy: only needed when loading a YAML file

        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(yaml.safe_load(handle) or {})
