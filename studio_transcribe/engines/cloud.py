"""Cloud engine scaffold — the fallback used when the local GPU is saturated
during a heavy recording/stream, and the option for best-in-class live
Hebrew-English code-switching (Soniox).

This is deliberately a thin, honest scaffold: each provider path is wired to
write the channel audio to a temp 16 kHz WAV and hand it to the provider SDK,
but the actual API calls must be completed against the chosen provider's SDK
and credentials (kept out of source — read from ``config.cloud.api_key_env``).
It raises a clear error rather than pretending to transcribe.
"""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional

from ..config import Config
from ..models import Segment
from .base import TranscriptionEngine


class CloudEngine(TranscriptionEngine):
    def __init__(self, config: Config):
        self.config = config
        self.provider = (config.cloud.provider or config.engine).lower()
        self.api_key = os.environ.get(config.cloud.api_key_env, "")
        if not self.api_key:
            raise RuntimeError(
                f"cloud provider {self.provider!r} needs an API key in "
                f"${config.cloud.api_key_env}"
            )

    def _write_temp_wav(self, audio, sample_rate: int) -> str:
        import soundfile as sf  # type: ignore

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(path, audio, sample_rate)
        return path

    def transcribe(
        self,
        audio,
        language: str = "he",
        initial_prompt: Optional[str] = None,
    ) -> List[Segment]:
        path = self._write_temp_wav(audio, self.config.sample_rate)
        try:
            raise NotImplementedError(
                f"Complete the {self.provider!r} integration in engines/cloud.py "
                "using the provider SDK (the temp WAV is at "
                f"{path!r}); keep credentials in the configured env var."
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
