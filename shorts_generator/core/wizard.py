"""
Interactive 8-step CLI wizard for the YouTube Shorts generation system.
Uses the `rich` library for all terminal output.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console()

# ─── BGM moods ───────────────────────────────────────────────────────────────
BGM_MOODS: list[tuple[str, str]] = [
    ("dramatic",    "🎭 드라마틱 — 긴장감, 강렬함"),
    ("business",    "💼 비즈니스 — 전문적, 차분함"),
    ("upbeat",      "🎵 업비트 — 경쾌하고 밝음"),
    ("emotional",   "💝 이모셔널 — 감성적, 뭉클함"),
    ("epic",        "⚡ 에픽 — 웅장하고 거대한 느낌"),
    ("calm",        "🌿 차분한 — 로파이, 집중"),
    ("suspense",    "🔍 서스펜스 — 미스터리, 궁금증"),
    ("motivational","🔥 모티베이셔널 — 자기계발"),
    ("fun",         "😄 펀 — 유머, 가볍고 재밌음"),
    ("cinematic",   "🎬 시네마틱 — 영화같은 분위기"),
]

# ─── Cost estimate table ──────────────────────────────────────────────────────
COST_ESTIMATES: dict[str, dict] = {
    "script_mode": {
        "A": {"label": "직접 대본", "cost_usd": 0.10},
        "B": {"label": "YouTube URL 분석", "cost_usd": 0.15},
        "C": {"label": "트렌드 탐색", "cost_usd": 0.20},
    },
    "video_source": {
        "A": {"label": "Pexels만", "cost_usd": 0.00},
        "B": {"label": "스톡+AI", "cost_usd": 0.30},
        "C": {"label": "전체AI", "cost_usd": 0.80},
        "D": {"label": "YouTube 클립", "cost_usd": 0.00},
        "E": {"label": "YT클립+스톡", "cost_usd": 0.00},
    },
    "tts_engine": {
        "A": {"label": "Minimax TTS", "cost_usd": 0.05},
        "B": {"label": "Edge TTS", "cost_usd": 0.00},
        "C": {"label": "없음", "cost_usd": 0.00},
    },
    "bgm": {
        "A": {"label": "Minimax Music", "cost_usd": 0.10},
        "B": {"label": "Suno AI", "cost_usd": 0.05},
        "C": {"label": "무료 BGM", "cost_usd": 0.00},
        "D": {"label": "음악 없음", "cost_usd": 0.00},
    },
    "thumbnail": {
        "A": {"label": "완전 자동", "cost_usd": 0.05},
        "B": {"label": "AI 배경", "cost_usd": 0.20},
        "C": {"label": "영상 스크린샷", "cost_usd": 0.00},
        "D": {"label": "스킵", "cost_usd": 0.00},
    },
}


@dataclass
class WizardConfig:
    """All user selections from the 8-step wizard."""

    # Step 1
    script_mode: str = "A"          # A | B | C
    script_text: Optional[str] = None
    youtube_url: Optional[str] = None

    # Step 2
    video_source: str = "A"         # A | B | C | D | E

    # Step 3
    tts_engine: str = "B"           # A | B | C
    tts_voice_id: Optional[str] = None

    # Step 4
    bgm_source: str = "D"           # A | B | C | D
    bgm_mood: Optional[str] = None
    bgm_volume: float = 0.15
    bgm_ducking: bool = True
    bgm_fade: bool = True

    # Step 5
    thumbnail_mode: str = "C"       # A | B | C | D

    # Step 6
    effects_mode: str = "B"         # A | B | C

    # Step 7
    quality_check: str = "B"        # A | B | C

    # Step 8
    channel: dict = field(default_factory=dict)

    # Computed
    estimated_cost_usd: float = 0.0


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _header(step: int, total: int, title: str) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold cyan]STEP {step}/{total}[/bold cyan]  [bold white]{title}[/bold white]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def _menu(options: list[tuple[str, str]], prompt: str = "선택") -> str:
    """Print a lettered menu and return the user's uppercase choice."""
    for key, label in options:
        console.print(f"  [bold yellow]{key}[/bold yellow]  {label}")
    console.print()
    valid = [k for k, _ in options]
    while True:
        choice = Prompt.ask(f"[bold green]{prompt}[/bold green]").strip().upper()
        if choice in valid:
            return choice
        console.print(f"[red]  잘못된 입력입니다. 다시 선택해 주세요: {', '.join(valid)}[/red]")


def _read_multiline_script() -> str:
    """Prompt user to paste a multiline script terminated by '---'."""
    console.print()
    console.print(
        Panel(
            "[bold]대본을 붙여넣으세요.[/bold]\n"
            "입력이 끝나면 새 줄에 [bold yellow]---[/bold yellow] 를 입력하고 Enter를 누르세요.",
            border_style="yellow",
            title="📝 대본 입력",
        )
    )
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "---":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _load_channels(channels_yaml: Path) -> list[dict]:
    if not channels_yaml.exists():
        console.print(f"[red]channels.yaml 파일을 찾을 수 없습니다: {channels_yaml}[/red]")
        return []
    with channels_yaml.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("channels", [])


def _compute_cost(cfg: WizardConfig) -> float:
    total = 0.0
    total += COST_ESTIMATES["script_mode"].get(cfg.script_mode, {}).get("cost_usd", 0)
    total += COST_ESTIMATES["video_source"].get(cfg.video_source, {}).get("cost_usd", 0)
    total += COST_ESTIMATES["tts_engine"].get(cfg.tts_engine, {}).get("cost_usd", 0)
    total += COST_ESTIMATES["bgm"].get(cfg.bgm_source, {}).get("cost_usd", 0)
    total += COST_ESTIMATES["thumbnail"].get(cfg.thumbnail_mode, {}).get("cost_usd", 0)
    # Always add Claude analysis cost
    total += 0.10
    return round(total, 2)


def _summary_table(cfg: WizardConfig) -> None:
    table = Table(
        title="📋 제작 설정 요약",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("항목", style="cyan", width=20)
    table.add_column("선택", style="white")

    script_label = {"A": "직접 대본", "B": "YouTube URL 분석", "C": "트렌드 탐색"}.get(
        cfg.script_mode, cfg.script_mode
    )
    source_label = {
        "A": "Pexels만",
        "B": "스톡+AI",
        "C": "전체AI",
        "D": "YouTube 클립",
        "E": "YT클립+스톡",
    }.get(cfg.video_source, cfg.video_source)
    tts_label = {"A": "Minimax TTS", "B": "Edge TTS", "C": "없음"}.get(
        cfg.tts_engine, cfg.tts_engine
    )
    bgm_label = {"A": "Minimax Music", "B": "Suno AI", "C": "무료 BGM", "D": "음악 없음"}.get(
        cfg.bgm_source, cfg.bgm_source
    )
    thumb_label = {
        "A": "완전 자동",
        "B": "AI 배경",
        "C": "영상 스크린샷",
        "D": "스킵",
    }.get(cfg.thumbnail_mode, cfg.thumbnail_mode)
    effects_label = {"A": "Klipy GIF", "B": "기본 트랜지션", "C": "없음"}.get(
        cfg.effects_mode, cfg.effects_mode
    )
    qc_label = {"A": "전체 검증", "B": "빠른 체크", "C": "스킵"}.get(
        cfg.quality_check, cfg.quality_check
    )

    table.add_row("제작 모드", script_label)
    if cfg.youtube_url:
        table.add_row("YouTube URL", cfg.youtube_url)
    table.add_row("영상 소스", source_label)
    table.add_row("나레이션 TTS", tts_label)
    if cfg.tts_voice_id:
        table.add_row("TTS 보이스", cfg.tts_voice_id)
    table.add_row("BGM", bgm_label)
    if cfg.bgm_mood:
        mood_label = next((label for key, label in BGM_MOODS if key == cfg.bgm_mood), cfg.bgm_mood)
        table.add_row("BGM 분위기", mood_label)
        table.add_row("BGM 볼륨", f"{int(cfg.bgm_volume * 100)}%")
        table.add_row("BGM 더킹", "ON" if cfg.bgm_ducking else "OFF")
        table.add_row("BGM 페이드", "ON" if cfg.bgm_fade else "OFF")
    table.add_row("썸네일", thumb_label)
    table.add_row("효과", effects_label)
    table.add_row("품질 검증", qc_label)
    channel_name = cfg.channel.get("name", "(미선택)") if cfg.channel else "(미선택)"
    table.add_row("채널", channel_name)
    table.add_row(
        "[bold yellow]예상 비용[/bold yellow]",
        f"[bold yellow]~${cfg.estimated_cost_usd:.2f} USD[/bold yellow]",
    )

    console.print()
    console.print(table)


# ─── Main wizard ──────────────────────────────────────────────────────────────

def run_wizard(channels_yaml_path: Path) -> WizardConfig:
    """
    Run the 8-step interactive wizard and return a populated WizardConfig.

    Args:
        channels_yaml_path: Absolute path to channels.yaml.

    Returns:
        Completed WizardConfig dataclass.
    """
    cfg = WizardConfig()
    total_steps = 8

    console.print()
    console.print(
        Panel(
            "[bold magenta]🎬 YouTube Shorts 자동 제작 시스템 v1.0[/bold magenta]\n"
            "[dim]Phase 1 — 직접 대본 + Pexels + Edge TTS + 기본 트랜지션 + 비공개 업로드[/dim]",
            border_style="magenta",
            padding=(1, 4),
        )
    )

    # ── Step 1: 제작 모드 ─────────────────────────────────────────────────────
    _header(1, total_steps, "제작 모드 선택")
    cfg.script_mode = _menu(
        [
            ("A", "직접 대본  — 대본을 직접 입력하거나 붙여넣기"),
            ("B", "YouTube URL  — 기존 영상 분석 후 재구성 [준비중 - Phase 2]"),
            ("C", "트렌드 탐색  — 실시간 트렌드 기반 자동 생성 [준비중 - Phase 6]"),
        ],
        prompt="모드 선택 (A/B/C)",
    )

    if cfg.script_mode == "A":
        cfg.script_text = _read_multiline_script()
        if not cfg.script_text:
            console.print("[red]대본이 비어 있습니다. 프로그램을 종료합니다.[/red]")
            sys.exit(1)
        console.print(f"[green]✓ 대본 입력 완료 ({len(cfg.script_text)}자)[/green]")

    elif cfg.script_mode == "B":
        cfg.youtube_url = Prompt.ask("[bold green]YouTube URL을 입력하세요[/bold green]").strip()

    # ── Step 2: 영상 소스 ─────────────────────────────────────────────────────
    _header(2, total_steps, "영상 소스 선택")
    cfg.video_source = _menu(
        [
            ("A", "Pexels만  — 무료 스톡 영상 (Phase 1 권장)"),
            ("B", "스톡+AI  — Pexels + AI 생성 영상 [준비중 - Phase 3]"),
            ("C", "전체AI  — 100% AI 생성 영상 [준비중 - Phase 3]"),
            ("D", "YouTube 클립  — YouTube에서 클립 다운로드 [준비중 - Phase 2]"),
            ("E", "YT클립+스톡  — YouTube 클립 + Pexels [준비중 - Phase 2]"),
        ],
        prompt="소스 선택 (A~E)",
    )

    # ── Step 3: 나레이션 TTS ──────────────────────────────────────────────────
    _header(3, total_steps, "나레이션 TTS 선택")
    cfg.tts_engine = _menu(
        [
            ("A", "Minimax TTS  — 고품질 한국어 음성 [준비중 - Phase 2]"),
            ("B", "Edge TTS  — Microsoft Edge 무료 TTS (Phase 1 권장)"),
            ("C", "없음  — 나레이션 없이 제작"),
        ],
        prompt="TTS 선택 (A/B/C)",
    )

    if cfg.tts_engine == "B":
        console.print()
        console.print("[dim]Edge TTS 한국어 보이스:[/dim]")
        voices = [
            ("ko-KR-SunHiNeural", "SunHi — 여성, 차분하고 전문적 (기본값)"),
            ("ko-KR-InJoonNeural", "InJoon — 남성, 신뢰감 있는 목소리"),
            ("ko-KR-HyunsuNeural", "Hyunsu — 남성, 젊고 에너지 넘침"),
        ]
        for i, (vid, label) in enumerate(voices, 1):
            console.print(f"  [bold yellow]{i}[/bold yellow]  {label}")
        console.print()
        while True:
            choice = Prompt.ask("[bold green]보이스 번호 선택 (기본값: 1)[/bold green]", default="1").strip()
            if choice in ("1", "2", "3"):
                cfg.tts_voice_id = voices[int(choice) - 1][0]
                break
            console.print("[red]1~3 중에서 선택해 주세요.[/red]")

    elif cfg.tts_engine == "A":
        cfg.tts_voice_id = Prompt.ask(
            "[bold green]Minimax Voice ID (기본값: male-qn-calm)[/bold green]",
            default="male-qn-calm",
        ).strip()

    # ── Step 4: BGM ───────────────────────────────────────────────────────────
    _header(4, total_steps, "BGM 선택")
    cfg.bgm_source = _menu(
        [
            ("A", "Minimax Music  — AI 생성 BGM [준비중 - Phase 3]"),
            ("B", "Suno AI  — Suno 생성 BGM [준비중 - Phase 3]"),
            ("C", "무료 BGM  — 로열티 프리 음악 라이브러리 [준비중 - Phase 3]"),
            ("D", "음악 없음  — BGM 없이 제작"),
        ],
        prompt="BGM 선택 (A~D)",
    )

    if cfg.bgm_source in ("A", "B", "C"):
        # Mood selection
        console.print()
        console.print("[dim]BGM 분위기를 선택하세요:[/dim]")
        for i, (key, label) in enumerate(BGM_MOODS, 1):
            console.print(f"  [bold yellow]{i:2d}[/bold yellow]  {label}")
        console.print()
        while True:
            mood_input = Prompt.ask(
                "[bold green]분위기 번호 선택 (기본값: 1)[/bold green]", default="1"
            ).strip()
            try:
                idx = int(mood_input) - 1
                if 0 <= idx < len(BGM_MOODS):
                    cfg.bgm_mood = BGM_MOODS[idx][0]
                    break
            except ValueError:
                pass
            console.print(f"[red]1~{len(BGM_MOODS)} 중에서 선택해 주세요.[/red]")

        # Volume
        console.print()
        console.print("[dim]BGM 볼륨:[/dim]")
        vol_choice = _menu(
            [
                ("A", "낮음 (15%) — 나레이션 위주"),
                ("B", "보통 (25%) — 균형"),
                ("C", "높음 (40%) — BGM 강조"),
            ],
            prompt="볼륨 선택 (A/B/C)",
        )
        cfg.bgm_volume = {"A": 0.15, "B": 0.25, "C": 0.40}[vol_choice]

        # Ducking
        console.print()
        cfg.bgm_ducking = Confirm.ask(
            "[bold green]나레이션 중 BGM 볼륨 자동 감소(더킹) ON?[/bold green]", default=True
        )

        # Fade
        cfg.bgm_fade = Confirm.ask(
            "[bold green]BGM 시작/끝 페이드 효과 ON?[/bold green]", default=True
        )

    # ── Step 5: 썸네일 ────────────────────────────────────────────────────────
    _header(5, total_steps, "썸네일 생성 방식")
    cfg.thumbnail_mode = _menu(
        [
            ("A", "완전 자동  — 텍스트+아이콘 자동 합성 [준비중 - Phase 4]"),
            ("B", "AI 배경  — AI 생성 이미지 + 텍스트 [준비중 - Phase 4]"),
            ("C", "영상 스크린샷  — 영상에서 최적 프레임 추출 (Phase 1 권장)"),
            ("D", "스킵  — 썸네일 없이 업로드"),
        ],
        prompt="썸네일 방식 (A~D)",
    )

    # ── Step 6: 효과 ─────────────────────────────────────────────────────────
    _header(6, total_steps, "영상 효과 선택")
    cfg.effects_mode = _menu(
        [
            ("A", "Klipy GIF  — 움직이는 스티커 오버레이 [준비중 - Phase 5]"),
            ("B", "기본 트랜지션  — Fade/Slide 장면 전환 (Phase 1 기본)"),
            ("C", "없음  — 단순 컷 편집"),
        ],
        prompt="효과 선택 (A/B/C)",
    )

    # ── Step 7: 품질 검증 ─────────────────────────────────────────────────────
    _header(7, total_steps, "품질 검증 방식")
    cfg.quality_check = _menu(
        [
            ("A", "전체 검증  — 음량, 해상도, 재생 전체 체크 [준비중 - Phase 5]"),
            ("B", "빠른 체크  — 파일 크기, 길이만 확인 (Phase 1 기본)"),
            ("C", "스킵  — 검증 없이 바로 업로드"),
        ],
        prompt="검증 방식 (A/B/C)",
    )

    # ── Step 8: 채널 선택 ─────────────────────────────────────────────────────
    _header(8, total_steps, "업로드 채널 선택")
    channels = _load_channels(channels_yaml_path)

    if not channels:
        console.print(
            "[yellow]등록된 채널이 없습니다. channels.yaml을 먼저 설정해 주세요.[/yellow]"
        )
        console.print("[yellow]임시로 빈 채널 설정으로 계속합니다.[/yellow]")
        cfg.channel = {"id": "", "name": "미설정", "default_tags": [], "default_category": "22"}
    else:
        for i, ch in enumerate(channels, 1):
            console.print(
                f"  [bold yellow]{i}[/bold yellow]  "
                f"[bold]{ch.get('name', '이름 없음')}[/bold]  "
                f"[dim]({ch.get('id', '?')})[/dim]"
            )
        console.print()
        while True:
            choice_str = Prompt.ask(
                f"[bold green]채널 번호 선택 (1~{len(channels)})[/bold green]"
            ).strip()
            try:
                idx = int(choice_str) - 1
                if 0 <= idx < len(channels):
                    cfg.channel = channels[idx]
                    break
            except ValueError:
                pass
            console.print(f"[red]1~{len(channels)} 중에서 선택해 주세요.[/red]")

    # ── Compute cost & show summary ───────────────────────────────────────────
    cfg.estimated_cost_usd = _compute_cost(cfg)
    _summary_table(cfg)

    console.print()
    confirmed = Confirm.ask(
        "[bold green]위 설정으로 숏츠 제작을 시작하시겠습니까?[/bold green]", default=True
    )
    if not confirmed:
        console.print("[yellow]취소되었습니다.[/yellow]")
        sys.exit(0)

    return cfg
