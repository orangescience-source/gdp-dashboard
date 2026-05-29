"""
Configuration module for the YouTube Shorts automatic generation system.
All API keys are loaded from environment variables only — never hardcoded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

# ─── Locate project root ────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent

# Load .env from project root (silently ignored if absent)
load_dotenv(BASE_DIR / ".env")


# ─── Video parameters ────────────────────────────────────────────────────────
VIDEO_WIDTH: int = 1080
VIDEO_HEIGHT: int = 1920
VIDEO_FPS: int = 30
MAX_DURATION: int = 59          # YouTube Shorts hard limit (seconds)
VIDEO_CODEC: str = "libx264"
AUDIO_CODEC: str = "aac"
CRF: int = 23
PRESET: str = "fast"

# Subtitle / drawtext settings
SUBTITLE_FONT_SIZE: int = 68
SUBTITLE_COLOR: str = "white"
SUBTITLE_STROKE_COLOR: str = "black"
SUBTITLE_STROKE_WIDTH: int = 4
SUBTITLE_MARGIN_BOTTOM: int = 80


# ─── Directory paths ─────────────────────────────────────────────────────────
OUTPUT_DIR: Path = BASE_DIR / "output"
TEMP_DIR: Path = BASE_DIR / "temp"
LOGS_DIR: Path = BASE_DIR / "logs"
FONTS_DIR: Path = BASE_DIR / "assets" / "fonts"
LOGOS_DIR: Path = BASE_DIR / "assets" / "logos"
BGM_CACHE_DIR: Path = BASE_DIR / "assets" / "bgm_cache"

# Ensure all directories exist at import time
for _d in (OUTPUT_DIR, TEMP_DIR, LOGS_DIR, FONTS_DIR, LOGOS_DIR, BGM_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─── Channels config path ────────────────────────────────────────────────────
CHANNELS_YAML: Path = BASE_DIR / "channels.yaml"


# ─── API key registry ────────────────────────────────────────────────────────
_API_KEY_ENV_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "fal": "FAL_API_KEY",
    "freepik": "FREEPIK_API_KEY",
    "klipy": "KLIPY_API_KEY",
    "serper": "SERPER_API_KEY",
    "youtube": "YOUTUBE_API_KEY",
    "suno": "SUNO_API_KEY",
}


def get_api_key(name: str) -> str:
    """
    Retrieve an API key by logical name.

    Args:
        name: Logical key name (e.g. "anthropic", "pexels").

    Returns:
        The API key string from the environment.

    Raises:
        EnvironmentError: If the key is missing or empty.
    """
    env_var = _API_KEY_ENV_MAP.get(name.lower())
    if env_var is None:
        raise EnvironmentError(
            f"Unknown API key name: '{name}'. "
            f"Known names: {', '.join(_API_KEY_ENV_MAP)}"
        )
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise EnvironmentError(
            f"API key '{name}' is not set. "
            f"Please add {env_var} to your .env file or environment."
        )
    return value


# Convenience properties (lazily retrieved so missing keys only error on use)
class _ApiKeys:
    """Namespace for typed API key accessors."""

    @property
    def anthropic(self) -> str:
        return get_api_key("anthropic")

    @property
    def pexels(self) -> str:
        return get_api_key("pexels")

    @property
    def minimax(self) -> str:
        return get_api_key("minimax")

    @property
    def fal(self) -> str:
        return get_api_key("fal")

    @property
    def freepik(self) -> str:
        return get_api_key("freepik")

    @property
    def klipy(self) -> str:
        return get_api_key("klipy")

    @property
    def serper(self) -> str:
        return get_api_key("serper")

    @property
    def youtube(self) -> str:
        return get_api_key("youtube")

    @property
    def suno(self) -> str:
        return get_api_key("suno")


API_KEYS = _ApiKeys()


# ─── FFmpeg helpers ──────────────────────────────────────────────────────────
def check_ffmpeg() -> str:
    """
    Verify that FFmpeg is installed and accessible on PATH.

    Returns:
        The resolved path to the ffmpeg binary.

    Raises:
        RuntimeError: If FFmpeg is not found or cannot be executed.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "FFmpeg not found on PATH. "
            "Please install FFmpeg: https://ffmpeg.org/download.html"
        )
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg returned non-zero exit code: {result.returncode}\n"
                f"{result.stderr}"
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg version check timed out.") from exc
    return ffmpeg_path
