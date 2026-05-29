"""
TTS (Text-to-Speech) engine module.
Phase 1 supports Edge TTS (free) and a Minimax TTS stub.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiofiles
import aiohttp
import edge_tts
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

import config

if TYPE_CHECKING:
    from core.script_analyzer import Scene

console = Console()

# Default Korean voices
DEFAULT_EDGE_VOICE = "ko-KR-SunHiNeural"
MINIMAX_TTS_URL = "https://api.minimax.chat/v1/t2a_v2"


class TTSEngine:
    """
    Generates TTS audio for script scenes.

    Supported engines:
      - "edge"    : Microsoft Edge TTS (free, via edge-tts library)
      - "minimax" : Minimax TTS API (paid, Phase 2+)
    """

    def __init__(self) -> None:
        self._minimax_key: Optional[str] = None

    # ── Public async API ──────────────────────────────────────────────────────

    async def generate_edge_tts(
        self,
        text: str,
        output_path: str,
        voice: str = DEFAULT_EDGE_VOICE,
    ) -> str:
        """
        Generate TTS audio using Microsoft Edge TTS.

        Args:
            text: Korean text to synthesise.
            output_path: Path to write the MP3/WAV output.
            voice: Edge TTS voice ID (e.g. "ko-KR-SunHiNeural").

        Returns:
            Resolved *output_path*.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return output_path

    async def generate_minimax_tts(
        self,
        text: str,
        voice_id: str,
        output_path: str,
    ) -> str:
        """
        Generate TTS audio using the Minimax TTS API.

        Args:
            text: Korean text to synthesise.
            voice_id: Minimax voice identifier.
            output_path: Path to write the MP3 output.

        Returns:
            Resolved *output_path*.

        Raises:
            RuntimeError: On API errors.
        """
        if self._minimax_key is None:
            self._minimax_key = config.get_api_key("minimax")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": "speech-01-turbo",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._minimax_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                MINIMAX_TTS_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Minimax TTS API 오류 {resp.status}: {body[:500]}"
                    )
                data = await resp.json()

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError(f"Minimax TTS: 응답에 오디오 데이터 없음. 응답: {data}")

        audio_bytes = bytes.fromhex(audio_hex)
        async with aiofiles.open(output_path, "wb") as fh:
            await fh.write(audio_bytes)

        return output_path

    # ── Synchronous entry point ───────────────────────────────────────────────

    def generate(
        self,
        scenes: list["Scene"],
        engine: str,
        voice_id: str,
        temp_dir: str,
    ) -> str:
        """
        Generate TTS for all scenes and concatenate into one audio file.

        Args:
            scenes: Ordered list of Scene objects (text will be concatenated).
            engine: "edge" | "minimax".
            voice_id: Voice identifier (depends on engine).
            temp_dir: Working directory for per-scene audio files.

        Returns:
            Path to the final concatenated MP3 audio file.
        """
        return asyncio.run(
            self._generate_async(scenes, engine, voice_id, temp_dir)
        )

    # ── Internal async implementation ─────────────────────────────────────────

    async def _generate_async(
        self,
        scenes: list["Scene"],
        engine: str,
        voice_id: str,
        temp_dir: str,
    ) -> str:
        temp = Path(temp_dir)
        temp.mkdir(parents=True, exist_ok=True)

        console.print(f"[cyan]🎙 TTS 생성 중 (엔진: {engine}, 보이스: {voice_id})...[/cyan]")

        segment_paths: list[str] = []

        for scene in sorted(scenes, key=lambda s: s.index):
            seg_path = str(temp / f"tts_scene_{scene.index:02d}.mp3")

            if engine == "edge":
                await self.generate_edge_tts(scene.text, seg_path, voice=voice_id)
            elif engine == "minimax":
                await self.generate_minimax_tts(scene.text, voice_id, seg_path)
            else:
                raise ValueError(f"지원하지 않는 TTS 엔진: {engine!r}")

            if Path(seg_path).exists() and Path(seg_path).stat().st_size > 0:
                segment_paths.append(seg_path)
                console.print(f"  [green]✓ 장면 {scene.index} TTS 완료[/green]")
            else:
                console.print(f"  [red]✗ 장면 {scene.index} TTS 실패 (빈 파일)[/red]")

        if not segment_paths:
            raise RuntimeError("TTS 세그먼트를 하나도 생성하지 못했습니다.")

        # Concatenate segments using FFmpeg
        concat_path = str(temp / "tts_combined.mp3")
        self._concat_audio(segment_paths, concat_path)
        console.print(f"[green]✓ TTS 최종 파일:[/green] {concat_path}")
        return concat_path

    @staticmethod
    def _concat_audio(segment_paths: list[str], output_path: str) -> None:
        """Concatenate audio segments into a single MP3 using FFmpeg."""
        list_file = Path(output_path).parent / "_tts_concat.txt"
        with list_file.open("w", encoding="utf-8") as fh:
            for p in segment_paths:
                fh.write(f"file '{Path(p).resolve()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        list_file.unlink(missing_ok=True)

        if result.returncode != 0:
            raise RuntimeError(f"TTS 오디오 연결 실패:\n{result.stderr[-1000:]}")
