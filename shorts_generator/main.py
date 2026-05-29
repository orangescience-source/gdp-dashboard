#!/usr/bin/env python3
"""
숏츠 자동 제작 시스템 v1.0
Phase 1: 직접 대본 + Pexels 스톡 + Edge TTS + 기본 트랜지션 + 비공개 업로드
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.traceback import install as rich_traceback_install

# Rich pretty tracebacks
rich_traceback_install(show_locals=False)
console = Console()

# ─── Resolve project root so relative imports work regardless of cwd ──────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── Project imports ──────────────────────────────────────────────────────────
import config
from config import check_ffmpeg, CHANNELS_YAML, TEMP_DIR, OUTPUT_DIR, LOGS_DIR
from core.wizard import run_wizard, WizardConfig
from core.script_analyzer import ScriptAnalyzer
from core.video_editor import VideoEditor
from core.upload_set_builder import UploadSetBuilder
from modules.video_fetcher import PexelsVideoFetcher
from modules.tts_engine import TTSEngine
from modules.youtube_uploader import YouTubeUploader


# ─── Logging setup ───────────────────────────────────────────────────────────

def _setup_logging(run_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"run_{run_id}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("shorts")
    logger.info("로그 파일: %s", log_file)
    return logger


# ─── Phase stub helpers ───────────────────────────────────────────────────────

def _phase_stub(feature: str, phase: int) -> None:
    console.print(
        Panel(
            f"[yellow]⏳ {feature}[/yellow]\n"
            f"[dim]이 기능은 Phase {phase}에서 구현 예정입니다. 현재 단계에서는 건너뜁니다.[/dim]",
            border_style="yellow",
            title=f"[준비중 - Phase {phase}]",
        )
    )


# ─── Thumbnail extraction (Phase 1 minimal) ───────────────────────────────────

def _extract_thumbnail(video_path: str, output_path: str) -> str | None:
    """Extract the best frame around 25% of video duration for thumbnail."""
    import subprocess
    try:
        # Get duration
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(result.stdout.strip() or "10")
        seek_time = max(1.0, duration * 0.25)

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{seek_time:.2f}",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                output_path,
            ],
            capture_output=True, check=True, timeout=30,
        )
        return output_path if Path(output_path).exists() else None
    except Exception as exc:
        console.print(f"[yellow]썸네일 추출 실패 (건너뜀): {exc}[/yellow]")
        return None


# ─── Quality check (Phase 1 minimal) ─────────────────────────────────────────

def _quick_quality_check(video_path: str) -> bool:
    """Check file size and approximate duration."""
    path = Path(video_path)
    if not path.exists():
        console.print("[red]  ✗ 영상 파일이 존재하지 않습니다.[/red]")
        return False

    size_mb = path.stat().st_size / 1024 / 1024
    console.print(f"  파일 크기: {size_mb:.1f} MB")
    if size_mb < 0.1:
        console.print("[red]  ✗ 파일이 너무 작습니다 (손상 가능).[/red]")
        return False
    if size_mb > 256:
        console.print("[yellow]  ⚠ 파일이 256 MB를 초과합니다 (YouTube 권장 한도).[/yellow]")

    import subprocess
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True, text=True, timeout=10,
    )
    try:
        dur = float(result.stdout.strip())
    except ValueError:
        console.print("[yellow]  ⚠ 영상 길이를 확인할 수 없습니다.[/yellow]")
        return True

    console.print(f"  영상 길이: {dur:.1f}초")
    if dur > config.MAX_DURATION + 2:
        console.print(
            f"[yellow]  ⚠ 영상이 {config.MAX_DURATION}초를 초과합니다 "
            f"({dur:.1f}초). YouTube Shorts 기준을 벗어날 수 있습니다.[/yellow]"
        )
    return True


# ─── Save run log ─────────────────────────────────────────────────────────────

def _save_run_log(run_id: str, data: dict) -> None:
    log_path = LOGS_DIR / f"run_{run_id}_summary.json"
    with log_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    console.print(f"[dim]📄 실행 요약 저장: {log_path}[/dim]")


# ─── Clean temp ───────────────────────────────────────────────────────────────

def _clean_temp(keep: bool = False) -> None:
    if keep:
        console.print("[dim]임시 파일 유지 (--keep-temp 옵션)[/dim]")
        return
    for item in TEMP_DIR.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            pass
    console.print("[dim]🗑 임시 파일 정리 완료[/dim]")


# ─── Main pipeline ────────────────────────────────────────────────────────────

async def main() -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = _setup_logging(run_id)
    run_log: dict = {"run_id": run_id, "started_at": datetime.now().isoformat()}

    console.print()
    console.print(
        Panel(
            "[bold magenta]🎬 YouTube Shorts 자동 제작 시스템[/bold magenta]\n"
            "[bold white]Phase 1  —  v1.0[/bold white]\n"
            "[dim]직접 대본 + Pexels + Edge TTS + 기본 트랜지션 + 비공개 업로드[/dim]",
            border_style="magenta",
            padding=(1, 4),
        )
    )

    # ── 1. Check FFmpeg ───────────────────────────────────────────────────────
    try:
        ffmpeg_path = check_ffmpeg()
        console.print(f"[green]✓ FFmpeg 확인:[/green] {ffmpeg_path}")
    except RuntimeError as exc:
        console.print(f"[bold red]❌ FFmpeg 오류:[/bold red] {exc}")
        sys.exit(1)

    # ── 2. Load channels ──────────────────────────────────────────────────────
    if not CHANNELS_YAML.exists():
        console.print(f"[red]channels.yaml 파일을 찾을 수 없습니다: {CHANNELS_YAML}[/red]")
        sys.exit(1)

    with CHANNELS_YAML.open(encoding="utf-8") as fh:
        channels_data = yaml.safe_load(fh)
    channels: list[dict] = channels_data.get("channels", [])
    console.print(f"[green]✓ 채널 로드:[/green] {len(channels)}개")

    # ── 3. Run wizard ─────────────────────────────────────────────────────────
    wizard_cfg: WizardConfig = run_wizard(CHANNELS_YAML)
    run_log["wizard"] = {
        "script_mode": wizard_cfg.script_mode,
        "video_source": wizard_cfg.video_source,
        "tts_engine": wizard_cfg.tts_engine,
        "bgm_source": wizard_cfg.bgm_source,
        "channel": wizard_cfg.channel.get("name", ""),
        "estimated_cost_usd": wizard_cfg.estimated_cost_usd,
    }

    # ── 4. Resolve script ─────────────────────────────────────────────────────
    script_text: str

    if wizard_cfg.script_mode == "A":
        # Direct script — already captured in wizard
        script_text = wizard_cfg.script_text or ""
        if not script_text.strip():
            console.print("[red]대본이 비어 있습니다. 종료합니다.[/red]")
            sys.exit(1)
        logger.info("직접 대본 모드: %d자", len(script_text))

    elif wizard_cfg.script_mode == "B":
        _phase_stub("YouTube URL 기반 대본 분석", phase=2)
        console.print("[yellow]Phase 1에서는 직접 대본 모드(A)만 지원합니다.[/yellow]")
        sys.exit(0)

    elif wizard_cfg.script_mode == "C":
        _phase_stub("트렌드 탐색 기반 자동 대본 생성", phase=6)
        console.print("[yellow]Phase 1에서는 직접 대본 모드(A)만 지원합니다.[/yellow]")
        sys.exit(0)

    else:
        console.print(f"[red]알 수 없는 제작 모드: {wizard_cfg.script_mode}[/red]")
        sys.exit(1)

    # ── 5. Analyze script with Claude ─────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 1/7  대본 분석[/bold cyan]", border_style="cyan"))
    try:
        analyzer = ScriptAnalyzer()
        analysis = analyzer.analyze(script_text)
    except Exception as exc:
        console.print(f"[red]대본 분석 실패: {exc}[/red]")
        logger.error("Script analysis failed: %s", exc)
        sys.exit(1)

    run_log["analysis"] = {
        "scene_count": len(analysis.scenes),
        "total_duration_estimate": analysis.total_duration_estimate,
        "hook_score": analysis.hook_score,
        "overall_mood": analysis.overall_mood,
    }

    # Warn if estimated duration exceeds limit
    if analysis.total_duration_estimate > config.MAX_DURATION:
        console.print(
            f"[yellow]⚠ 예상 길이({analysis.total_duration_estimate:.1f}초)가 "
            f"{config.MAX_DURATION}초를 초과합니다.[/yellow]"
        )

    # ── 6. Fetch videos ────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 2/7  영상 소스 수집[/bold cyan]", border_style="cyan"))

    temp_run = TEMP_DIR / run_id
    temp_run.mkdir(parents=True, exist_ok=True)

    scene_clips: dict[int, str] = {}

    if wizard_cfg.video_source == "A":
        # Pexels only
        try:
            fetcher = PexelsVideoFetcher()
            scene_clips = fetcher.fetch_for_scenes(analysis.scenes, str(temp_run / "clips"))
        except Exception as exc:
            console.print(f"[red]영상 수집 실패: {exc}[/red]")
            logger.error("Video fetch failed: %s", exc)
            sys.exit(1)

    elif wizard_cfg.video_source in ("B", "C"):
        _phase_stub("AI 생성 영상 통합", phase=3)
        # Fall back to Pexels for Phase 1
        console.print("[dim]Pexels로 폴백합니다...[/dim]")
        fetcher = PexelsVideoFetcher()
        scene_clips = fetcher.fetch_for_scenes(analysis.scenes, str(temp_run / "clips"))

    elif wizard_cfg.video_source in ("D", "E"):
        _phase_stub("YouTube 클립 다운로드", phase=2)
        # Fall back to Pexels for Phase 1
        console.print("[dim]Pexels로 폴백합니다...[/dim]")
        fetcher = PexelsVideoFetcher()
        scene_clips = fetcher.fetch_for_scenes(analysis.scenes, str(temp_run / "clips"))

    if not scene_clips:
        console.print("[red]수집된 영상 클립이 없습니다. 종료합니다.[/red]")
        sys.exit(1)

    run_log["video_clips_fetched"] = len(scene_clips)

    # ── 7. Generate TTS ────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 3/7  나레이션 TTS 생성[/bold cyan]", border_style="cyan"))

    tts_path: str | None = None

    if wizard_cfg.tts_engine == "C":
        console.print("[dim]TTS 없음 — 건너뜁니다.[/dim]")

    elif wizard_cfg.tts_engine == "A":
        _phase_stub("Minimax TTS", phase=2)
        console.print("[dim]Phase 1에서는 Edge TTS로 폴백합니다...[/dim]")
        wizard_cfg.tts_engine = "B"
        wizard_cfg.tts_voice_id = wizard_cfg.tts_voice_id or "ko-KR-SunHiNeural"
        try:
            engine = TTSEngine()
            tts_path = engine.generate(
                scenes=analysis.scenes,
                engine="edge",
                voice_id=wizard_cfg.tts_voice_id,
                temp_dir=str(temp_run / "tts"),
            )
        except Exception as exc:
            console.print(f"[yellow]TTS 생성 실패 (건너뜀): {exc}[/yellow]")

    elif wizard_cfg.tts_engine == "B":
        voice_id = wizard_cfg.tts_voice_id or "ko-KR-SunHiNeural"
        try:
            engine = TTSEngine()
            tts_path = engine.generate(
                scenes=analysis.scenes,
                engine="edge",
                voice_id=voice_id,
                temp_dir=str(temp_run / "tts"),
            )
        except Exception as exc:
            console.print(f"[yellow]TTS 생성 실패 (건너뜀): {exc}[/yellow]")

    run_log["tts_generated"] = tts_path is not None

    # ── 8. BGM ────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 4/7  BGM[/bold cyan]", border_style="cyan"))

    bgm_path: str | None = None

    if wizard_cfg.bgm_source == "D":
        console.print("[dim]BGM 없음 — 건너뜁니다.[/dim]")
    else:
        _phase_stub(
            f"BGM 생성 ({['', 'Minimax Music', 'Suno AI', '무료 BGM'][ord(wizard_cfg.bgm_source) - ord('A') + 1] if wizard_cfg.bgm_source in 'ABC' else wizard_cfg.bgm_source})",
            phase=3,
        )
        console.print("[dim]Phase 1: BGM 없이 진행합니다.[/dim]")

    run_log["bgm_used"] = bgm_path is not None

    # ── 9. Edit video ─────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 5/7  영상 편집[/bold cyan]", border_style="cyan"))

    output_path = str(OUTPUT_DIR / f"shorts_{run_id}.mp4")

    editor = VideoEditor()
    try:
        final_video = editor.build_final(
            scene_clips=scene_clips,
            scenes=analysis.scenes,
            tts_path=tts_path,
            bgm_path=bgm_path,
            bgm_volume=wizard_cfg.bgm_volume,
            output_path=output_path,
            temp_dir=str(temp_run / "edit"),
        )
    except Exception as exc:
        console.print(f"[red]영상 편집 실패: {exc}[/red]")
        logger.error("Video edit failed: %s\n%s", exc, traceback.format_exc())
        sys.exit(1)

    run_log["output_video"] = final_video

    # ── 10. Thumbnail ─────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 6/7  썸네일[/bold cyan]", border_style="cyan"))

    thumbnail_path: str | None = None

    if wizard_cfg.thumbnail_mode == "D":
        console.print("[dim]썸네일 스킵.[/dim]")

    elif wizard_cfg.thumbnail_mode in ("A", "B"):
        _phase_stub("AI 썸네일 생성", phase=4)
        console.print("[dim]영상 스크린샷으로 폴백합니다...[/dim]")
        thumbnail_path = _extract_thumbnail(
            final_video, str(temp_run / "thumbnail.jpg")
        )

    elif wizard_cfg.thumbnail_mode == "C":
        thumbnail_path = _extract_thumbnail(
            final_video, str(temp_run / "thumbnail.jpg")
        )
        if thumbnail_path:
            console.print(f"[green]✓ 썸네일 추출 완료:[/green] {thumbnail_path}")

    run_log["thumbnail"] = thumbnail_path

    # ── 11. Quality check ─────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 6.5  품질 검증[/bold cyan]", border_style="cyan"))

    if wizard_cfg.quality_check == "C":
        console.print("[dim]품질 검증 스킵.[/dim]")

    elif wizard_cfg.quality_check == "A":
        _phase_stub("전체 품질 검증", phase=5)
        console.print("[dim]빠른 체크로 폴백합니다...[/dim]")
        _quick_quality_check(final_video)

    elif wizard_cfg.quality_check == "B":
        console.print("[cyan]  ⚡ 빠른 품질 체크 중...[/cyan]")
        if not _quick_quality_check(final_video):
            console.print("[red]품질 검증 실패. 업로드를 취소합니다.[/red]")
            sys.exit(1)
        console.print("[green]✓ 품질 검증 통과[/green]")

    # ── 12. Build upload set ──────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]STEP 7/7  업로드 준비[/bold cyan]", border_style="cyan"))

    builder = UploadSetBuilder()
    upload_set = builder.build(analysis, wizard_cfg.channel, wizard_cfg)
    run_log["upload_set"] = {
        "title": upload_set["title"],
        "tags_count": len(upload_set.get("tags", [])),
        "category_id": upload_set.get("category_id"),
        "privacy_status": upload_set.get("privacy_status"),
    }

    # ── 13. Upload to YouTube ─────────────────────────────────────────────────
    console.print()

    credentials_path = str(PROJECT_ROOT / "credentials.json")
    if not Path(credentials_path).exists():
        console.print(
            Panel(
                "[yellow]credentials.json 파일이 없습니다.[/yellow]\n"
                "Google Cloud Console에서 OAuth2 클라이언트 ID를 다운로드하여\n"
                f"{credentials_path} 에 저장하세요.\n\n"
                "[dim]업로드를 건너뜁니다. 영상 파일은 output/ 폴더에 저장되었습니다.[/dim]",
                border_style="yellow",
                title="⚠ YouTube 인증 파일 없음",
            )
        )
        run_log["upload"] = {"status": "skipped", "reason": "credentials.json not found"}
    else:
        try:
            uploader = YouTubeUploader()
            uploader.authenticate(credentials_path)
            video_id = uploader.upload(
                video_path=final_video,
                thumbnail_path=thumbnail_path,
                upload_set=upload_set,
                channel_id=wizard_cfg.channel.get("id", ""),
            )
            run_log["upload"] = {
                "status": "success",
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
            }
            console.print(
                Panel(
                    f"[bold green]🎉 업로드 성공![/bold green]\n"
                    f"Video ID: [bold]{video_id}[/bold]\n"
                    f"URL: https://youtu.be/{video_id}\n"
                    f"[dim](비공개 상태로 업로드되었습니다)[/dim]",
                    border_style="green",
                    title="✅ 완료",
                )
            )
        except Exception as exc:
            console.print(f"[red]YouTube 업로드 실패: {exc}[/red]")
            logger.error("YouTube upload failed: %s", exc)
            run_log["upload"] = {"status": "failed", "error": str(exc)}

    # ── 14. Save log ──────────────────────────────────────────────────────────
    run_log["finished_at"] = datetime.now().isoformat()
    _save_run_log(run_id, run_log)

    # ── 15. Clean temp ────────────────────────────────────────────────────────
    _clean_temp(keep=False)

    console.print()
    console.print(
        Panel(
            f"[bold]실행 완료[/bold]  run_id: {run_id}\n"
            f"최종 영상: [cyan]{final_video}[/cyan]",
            border_style="green",
        )
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main())
