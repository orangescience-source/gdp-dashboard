"""
Pexels API integration for fetching stock portrait videos.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from tqdm import tqdm

from config import get_api_key

# Avoid circular import — Scene is defined in core.script_analyzer
# We import it lazily / use TYPE_CHECKING to keep the module importable standalone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.script_analyzer import Scene

console = Console()

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
PEXELS_VIDEO_POPULAR_URL = "https://api.pexels.com/videos/popular"
CHUNK_SIZE = 1024 * 256   # 256 KB per chunk


class PexelsVideoFetcher:
    """Fetch and download portrait videos from the Pexels API."""

    def __init__(self) -> None:
        self._api_key: str | None = None

    @property
    def api_key(self) -> str:
        if self._api_key is None:
            self._api_key = get_api_key("pexels")
        return self._api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    # ── Public methods ────────────────────────────────────────────────────────

    def search_video(
        self,
        query: str,
        orientation: str = "portrait",
        per_page: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search Pexels for videos matching *query*.

        Args:
            query: Search term (Korean or English).
            orientation: "portrait" | "landscape" | "square".
            per_page: Number of results to request (max 80).

        Returns:
            List of Pexels video objects (raw dicts from the API).
        """
        params: dict[str, Any] = {
            "query": query,
            "orientation": orientation,
            "per_page": per_page,
            "size": "medium",
        }
        try:
            resp = requests.get(
                PEXELS_VIDEO_SEARCH_URL,
                headers=self._headers,
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("videos", [])
        except requests.RequestException as exc:
            console.print(f"[red]Pexels 검색 오류 ({query!r}): {exc}[/red]")
            return []

    def download_video(self, video_url: str, output_path: str) -> str:
        """
        Download a video from *video_url* to *output_path* with a progress bar.

        Args:
            video_url: Direct download URL from Pexels.
            output_path: Local file path to save the video.

        Returns:
            The resolved output path.

        Raises:
            IOError: If the download fails.
        """
        output_path = str(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with requests.get(
            video_url, stream=True, timeout=60, headers=self._headers
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task(
                    f"다운로드: {Path(output_path).name}", total=total or None
                )
                with open(output_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            fh.write(chunk)
                            progress.advance(task, len(chunk))

        return output_path

    def fetch_for_scenes(
        self,
        scenes: list["Scene"],
        temp_dir: str,
    ) -> dict[int, str]:
        """
        Fetch one portrait video per scene and download to temp_dir.

        Args:
            scenes: List of Scene objects (from ScriptAnalyzer).
            temp_dir: Directory to save downloaded clips.

        Returns:
            Mapping of {scene_index: local_file_path}.
            Scenes that could not be matched will be absent from the dict.
        """
        temp_dir_path = Path(temp_dir)
        temp_dir_path.mkdir(parents=True, exist_ok=True)

        result: dict[int, str] = {}

        for scene in scenes:
            scene_idx = scene.index
            console.print(
                f"[cyan]🔍 장면 {scene_idx} 영상 검색:[/cyan] "
                f"[italic]{scene.visual_description[:60]}...[/italic]"
                if len(scene.visual_description) > 60
                else f"[cyan]🔍 장면 {scene_idx} 영상 검색:[/cyan] {scene.visual_description}"
            )

            # Primary search using English visual description
            videos = self.search_video(scene.visual_description, orientation="portrait")

            # Fallback: use first Korean keyword if no portrait results
            if not videos and scene.keywords:
                fallback_query = scene.keywords[0]
                console.print(
                    f"[yellow]  ⟳ portrait 영상 없음, 폴백 검색: {fallback_query!r}[/yellow]"
                )
                videos = self.search_video(fallback_query, orientation="portrait")

            # Second fallback: broader type-only search
            if not videos:
                type_query = scene.type.lower()
                console.print(f"[yellow]  ⟳ 2차 폴백 검색: {type_query!r}[/yellow]")
                videos = self.search_video(type_query, orientation="portrait")

            if not videos:
                console.print(f"[red]  ✗ 장면 {scene_idx}: 적합한 영상을 찾지 못했습니다.[/red]")
                continue

            # Pick the best portrait video file
            video_url, video_id = self._pick_best_portrait(videos)
            if not video_url:
                console.print(f"[red]  ✗ 장면 {scene_idx}: portrait 파일을 찾지 못했습니다.[/red]")
                continue

            out_path = str(temp_dir_path / f"scene_{scene_idx:02d}_{video_id}.mp4")

            # Skip re-download if already on disk
            if Path(out_path).exists() and Path(out_path).stat().st_size > 0:
                console.print(f"[dim]  ↩ 장면 {scene_idx}: 캐시된 파일 사용[/dim]")
                result[scene_idx] = out_path
                continue

            try:
                self.download_video(video_url, out_path)
                console.print(f"[green]  ✓ 장면 {scene_idx}: 다운로드 완료[/green]")
                result[scene_idx] = out_path
            except Exception as exc:
                console.print(f"[red]  ✗ 장면 {scene_idx}: 다운로드 실패 — {exc}[/red]")

            # Be polite to the Pexels API
            time.sleep(0.3)

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _pick_best_portrait(
        self, videos: list[dict[str, Any]]
    ) -> tuple[str, int]:
        """
        From a list of Pexels video objects, return (download_url, video_id)
        for the highest-quality portrait-oriented file.

        Returns:
            (url, video_id) or ("", 0) if no suitable file found.
        """
        best_url = ""
        best_id = 0
        best_height = 0

        for video in videos:
            video_id = video.get("id", 0)
            video_files: list[dict] = video.get("video_files", [])

            for vf in video_files:
                width = vf.get("width") or 0
                height = vf.get("height") or 0
                link = vf.get("link", "")
                quality = vf.get("quality", "")

                # We want portrait: height > width
                if height <= width:
                    continue
                # Prefer HD or SD quality, skip tiny files
                if height < 480:
                    continue
                if height > best_height:
                    best_height = height
                    best_url = link
                    best_id = video_id

        return best_url, best_id
