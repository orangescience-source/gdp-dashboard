"""
FFmpeg-based video editor for YouTube Shorts (1080x1920).
All processing targets a 9:16 portrait format at 30 fps.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import ffmpeg
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

import config

if TYPE_CHECKING:
    from core.script_analyzer import Scene

console = Console()


class VideoEditor:
    """
    FFmpeg-based editor that handles format conversion, subtitle burning,
    transitions, audio mixing, and final rendering.
    """

    def __init__(
        self,
        width: int = config.VIDEO_WIDTH,
        height: int = config.VIDEO_HEIGHT,
        fps: int = config.VIDEO_FPS,
        crf: int = config.CRF,
        preset: str = config.PRESET,
        video_codec: str = config.VIDEO_CODEC,
        audio_codec: str = config.AUDIO_CODEC,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.crf = crf
        self.preset = preset
        self.video_codec = video_codec
        self.audio_codec = audio_codec

    # ── Public methods ────────────────────────────────────────────────────────

    def convert_to_916(self, input_path: str, output_path: str) -> str:
        """
        Crop and scale *input_path* to 1080×1920 (9:16) with smart centre crop.

        The filter chain:
          1. Scale so the *shorter* dimension fills the target (cover-fill).
          2. Centre-crop to exactly 1080×1920.
          3. Set fps to 30.

        Args:
            input_path: Source video file path.
            output_path: Destination file path (will be overwritten).

        Returns:
            Resolved *output_path*.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        console.print(f"[cyan]  ↻ 9:16 변환:[/cyan] {Path(input_path).name}")

        # scale=w:h while keeping aspect, then centre-crop
        vf = (
            f"scale='if(gt(iw/ih,{self.width}/{self.height}),"
            f"-2\\,{self.height})':"
            f"'if(gt(iw/ih,{self.width}/{self.height}),"
            f"{self.height}\\,-2)',"
            f"crop={self.width}:{self.height},"
            f"fps={self.fps}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", self.video_codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", self.audio_codec,
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
        self._run(cmd, description=f"convert_to_916: {Path(input_path).name}")
        return output_path

    def add_subtitles(
        self,
        video_path: str,
        scenes: list["Scene"],
        output_path: str,
    ) -> str:
        """
        Burn scene subtitles into *video_path* using the FFmpeg drawtext filter.

        Each scene's text is displayed for its duration_estimate seconds.
        Text wraps at ~28 characters per line with a line-break escape.

        Args:
            video_path: Input video (should already be 1080×1920).
            scenes: Ordered list of Scene objects with duration_estimate.
            output_path: Output file path.

        Returns:
            Resolved *output_path*.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        console.print(f"[cyan]  ✍ 자막 추가 중...[/cyan]")

        # Build a chain of drawtext filters
        filters: list[str] = []
        current_time = 0.0

        font_size = config.SUBTITLE_FONT_SIZE
        color = config.SUBTITLE_COLOR
        stroke_color = config.SUBTITLE_STROKE_COLOR
        stroke_w = config.SUBTITLE_STROKE_WIDTH
        margin_b = config.SUBTITLE_MARGIN_BOTTOM
        y_pos = f"h-{margin_b + font_size}"

        for scene in scenes:
            text = self._escape_drawtext(scene.text)
            start = current_time
            end = current_time + scene.duration_estimate

            filter_str = (
                f"drawtext="
                f"text='{text}':"
                f"fontsize={font_size}:"
                f"fontcolor={color}:"
                f"borderw={stroke_w}:"
                f"bordercolor={stroke_color}:"
                f"x=(w-text_w)/2:"
                f"y={y_pos}:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
            )
            filters.append(filter_str)
            current_time = end

        vf_chain = ",".join(filters)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf_chain,
            "-c:v", self.video_codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "copy",
            output_path,
        ]
        self._run(cmd, description="add_subtitles")
        return output_path

    def apply_transition(
        self,
        clip_paths: list[str],
        output_path: str,
        transition: str = "fade",
        transition_duration: float = 0.5,
    ) -> str:
        """
        Concatenate video clips with fade or slide transitions between them.

        For Phase 1 we use a simple approach:
          - Each clip is trimmed to its natural length.
          - A crossfade (fade) or directional wipe (slide) is applied via
            the xfade filter between consecutive clips.
          - Audio is crossfaded with acrossfade.

        Args:
            clip_paths: Ordered list of input clip paths (already 1080×1920).
            output_path: Final concatenated video path.
            transition: "fade" | "slide" | "none".
            transition_duration: Duration of each transition in seconds.

        Returns:
            Resolved *output_path*.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        console.print(f"[cyan]  🎬 클립 연결 중 (전환: {transition})...[/cyan]")

        if len(clip_paths) == 1:
            # Nothing to concatenate
            import shutil
            shutil.copy2(clip_paths[0], output_path)
            return output_path

        if transition == "none" or len(clip_paths) < 2:
            return self._simple_concat(clip_paths, output_path)

        # Use xfade for smooth transitions
        xfade_type = "fade" if transition == "fade" else "slideleft"
        return self._xfade_concat(clip_paths, output_path, xfade_type, transition_duration)

    def mix_audio(
        self,
        video_path: str,
        tts_path: Optional[str],
        bgm_path: Optional[str],
        output_path: str,
        bgm_volume: float = 0.15,
        ducking: bool = True,
    ) -> str:
        """
        Mix TTS narration + optional BGM into the video.

        Args:
            video_path: Input video (may have audio or be silent).
            tts_path: Path to TTS audio file (WAV/MP3). None = skip.
            bgm_path: Path to BGM audio file (WAV/MP3). None = skip.
            output_path: Output video path.
            bgm_volume: BGM volume ratio (0.0–1.0).
            ducking: If True, side-chain duck BGM under TTS via volume filter.

        Returns:
            Resolved *output_path*.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        console.print(f"[cyan]  🔊 오디오 믹싱 중...[/cyan]")

        # Build ffmpeg command dynamically
        inputs = ["-i", video_path]
        if tts_path:
            inputs += ["-i", tts_path]
        if bgm_path:
            inputs += ["-i", bgm_path]

        if not tts_path and not bgm_path:
            # Nothing to mix — just copy
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        if tts_path and bgm_path:
            # Mix TTS at full volume + BGM at reduced volume
            filter_complex = (
                f"[1:a]volume=1.0[tts];"
                f"[2:a]volume={bgm_volume:.3f}[bgm];"
                f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", self.audio_codec,
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]
        elif tts_path:
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", self.audio_codec,
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]
        else:
            # BGM only
            filter_complex = f"[1:a]volume={bgm_volume:.3f}[aout]"
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", self.audio_codec,
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]

        self._run(cmd, description="mix_audio")
        return output_path

    def build_final(
        self,
        scene_clips: dict[int, str],
        scenes: list["Scene"],
        tts_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.15,
        output_path: Optional[str] = None,
        temp_dir: Optional[str] = None,
    ) -> str:
        """
        Full pipeline: convert → concat → add subs → mix audio.

        Args:
            scene_clips: {scene_index: raw_clip_path} from video_fetcher.
            scenes: Ordered Scene list (for subtitles & durations).
            tts_path: Optional TTS audio file.
            bgm_path: Optional BGM audio file.
            bgm_volume: BGM volume ratio.
            output_path: Final output file path. Defaults to output/final.mp4.
            temp_dir: Working directory for intermediate files.

        Returns:
            Resolved final output path.
        """
        if output_path is None:
            output_path = str(config.OUTPUT_DIR / f"shorts_{int(time.time())}.mp4")
        if temp_dir is None:
            temp_dir = str(config.TEMP_DIR)

        temp = Path(temp_dir)
        temp.mkdir(parents=True, exist_ok=True)

        console.print("[bold cyan]🎞 영상 편집 파이프라인 시작[/bold cyan]")

        # ── Step A: Convert each clip to 1080×1920 ─────────────────────────
        converted_clips: list[str] = []
        ordered_scenes = sorted(scenes, key=lambda s: s.index)

        for scene in ordered_scenes:
            idx = scene.index
            if idx not in scene_clips:
                console.print(f"[yellow]  ⚠ 장면 {idx}: 영상 없음 — 건너뜀[/yellow]")
                continue
            raw = scene_clips[idx]
            converted = str(temp / f"converted_{idx:02d}.mp4")
            self.convert_to_916(raw, converted)
            # Trim to scene duration
            trimmed = str(temp / f"trimmed_{idx:02d}.mp4")
            self._trim(converted, trimmed, scene.duration_estimate)
            converted_clips.append(trimmed)

        if not converted_clips:
            raise RuntimeError("변환된 클립이 없습니다. 영상 소스를 확인해 주세요.")

        # ── Step B: Concat with transitions ───────────────────────────────
        concat_path = str(temp / "concat.mp4")
        self.apply_transition(converted_clips, concat_path, transition="fade")

        # ── Step C: Add subtitles ─────────────────────────────────────────
        sub_path = str(temp / "with_subs.mp4")
        # Use only scenes that had a clip
        present_scene_indices = {s.index for s in ordered_scenes if s.index in scene_clips}
        sub_scenes = [s for s in ordered_scenes if s.index in present_scene_indices]
        self.add_subtitles(concat_path, sub_scenes, sub_path)

        # ── Step D: Mix audio ─────────────────────────────────────────────
        final = self.mix_audio(
            video_path=sub_path,
            tts_path=tts_path,
            bgm_path=bgm_path,
            output_path=output_path,
            bgm_volume=bgm_volume,
        )

        console.print(f"[bold green]✓ 최종 영상 완성:[/bold green] {final}")
        return final

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _trim(self, input_path: str, output_path: str, duration: float) -> str:
        """Trim a clip to *duration* seconds."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            output_path,
        ]
        self._run(cmd, description=f"trim {Path(input_path).name} → {duration:.1f}s")
        return output_path

    def _simple_concat(self, clip_paths: list[str], output_path: str) -> str:
        """Simple concat using the FFmpeg concat demuxer (no transition)."""
        list_file = Path(output_path).parent / "_concat_list.txt"
        with list_file.open("w", encoding="utf-8") as fh:
            for cp in clip_paths:
                fh.write(f"file '{Path(cp).resolve()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            output_path,
        ]
        self._run(cmd, description="simple_concat")
        list_file.unlink(missing_ok=True)
        return output_path

    def _xfade_concat(
        self,
        clip_paths: list[str],
        output_path: str,
        xfade_type: str,
        duration: float,
    ) -> str:
        """
        Concatenate clips with xfade transitions using FFmpeg filter_complex.
        Builds a chain: [0][1]xfade=... [tmp1][2]xfade=... etc.
        """
        # We need to know each clip's duration for correct offset calculation
        clip_durations = [self._get_duration(p) for p in clip_paths]

        # Build filter_complex dynamically
        inputs_args: list[str] = []
        for p in clip_paths:
            inputs_args += ["-i", p]

        filter_parts: list[str] = []
        # Running offset for xfade
        offset = 0.0
        prev_label = "[0:v]"
        prev_audio = "[0:a]"

        for i in range(1, len(clip_paths)):
            out_v = f"[v{i}]"
            out_a = f"[a{i}]"
            offset += clip_durations[i - 1] - duration

            filter_parts.append(
                f"{prev_label}[{i}:v]xfade=transition={xfade_type}:"
                f"duration={duration:.3f}:offset={offset:.3f}{out_v}"
            )
            filter_parts.append(
                f"{prev_audio}[{i}:a]acrossfade=d={duration:.3f}{out_a}"
            )
            prev_label = out_v
            prev_audio = out_a

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            *inputs_args,
            "-filter_complex", filter_complex,
            "-map", prev_label,
            "-map", prev_audio,
            "-c:v", self.video_codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", self.audio_codec,
            "-b:a", "192k",
            output_path,
        ]
        self._run(cmd, description="xfade_concat")
        return output_path

    def _get_duration(self, path: str) -> float:
        """Return the duration of a video/audio file in seconds via ffprobe."""
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """
        Escape special characters for the FFmpeg drawtext filter.
        Also wraps long lines at ~28 chars using the drawtext newline token.
        """
        # Escape characters that break the filter syntax
        for ch in ("\\", ":", "'", "%"):
            text = text.replace(ch, "\\" + ch)

        # Wrap at word boundaries
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > 28 and current:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines.append(current)

        return r"\n".join(lines)

    @staticmethod
    def _run(cmd: list[str], description: str = "") -> None:
        """Run an FFmpeg command, raising RuntimeError on failure."""
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[cyan]{description or 'ffmpeg'}[/cyan]"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task("", total=None)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg 오류 ({description}):\n{result.stderr[-2000:]}"
            )
