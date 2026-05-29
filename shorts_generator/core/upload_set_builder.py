"""
Builds the YouTube upload metadata (title, description, tags, category, privacy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from core.script_analyzer import ScriptAnalysis
    from core.wizard import WizardConfig

console = Console()

# Maximum YouTube title length
_MAX_TITLE_LEN = 100
# Maximum YouTube tag list length (total chars)
_MAX_TAGS_CHARS = 400


class UploadSetBuilder:
    """Assembles the upload metadata dict used by YouTubeUploader."""

    def build(
        self,
        script_analysis: "ScriptAnalysis",
        channel: dict,
        wizard_config: "WizardConfig",
    ) -> dict:
        """
        Build upload metadata for a single Shorts video.

        Args:
            script_analysis: Result from ScriptAnalyzer.analyze().
            channel: Channel dict loaded from channels.yaml.
            wizard_config: Completed wizard configuration.

        Returns:
            Dict with keys: title, description, tags, category_id, privacy_status.
        """
        title = self.generate_title(script_analysis)
        description = self.generate_description(script_analysis, channel)
        tags = self._build_tags(script_analysis, channel)
        category_id = channel.get("default_category", "22")

        upload_set = {
            "title": title,
            "description": description,
            "tags": tags,
            "category_id": category_id,
            "privacy_status": "private",   # Phase 1: always private
        }

        console.print("[green]✓ 업로드 메타데이터 생성 완료[/green]")
        console.print(f"  제목: [bold]{title}[/bold]")
        console.print(f"  카테고리: {category_id}  /  공개 상태: private")
        console.print(f"  태그: {', '.join(tags[:5])}{'...' if len(tags) > 5 else ''}")

        return upload_set

    def generate_title(self, script_analysis: "ScriptAnalysis") -> str:
        """
        Pick or synthesise a YouTube title.

        Priority:
          1. First item in title_suggestions (from Claude).
          2. Hook scene text (truncated).
          3. Generic fallback.

        Args:
            script_analysis: ScriptAnalysis from Claude.

        Returns:
            A UTF-8 title string, max _MAX_TITLE_LEN chars.
        """
        if script_analysis.title_suggestions:
            candidate = script_analysis.title_suggestions[0].strip()
            if candidate:
                return candidate[:_MAX_TITLE_LEN]

        # Fallback: use the HOOK scene text
        for scene in script_analysis.scenes:
            if scene.type == "HOOK" and scene.text.strip():
                return scene.text.strip()[:_MAX_TITLE_LEN]

        return "YouTube Shorts — 자동 생성"[:_MAX_TITLE_LEN]

    def generate_description(
        self,
        script_analysis: "ScriptAnalysis",
        channel: dict,
    ) -> str:
        """
        Assemble the YouTube description.

        Structure:
          - Main description body from Claude
          - Alternative titles section
          - Hashtags
          - Channel footer

        Args:
            script_analysis: ScriptAnalysis from Claude.
            channel: Channel dict from channels.yaml.

        Returns:
            Full description string.
        """
        parts: list[str] = []

        # Body from Claude
        if script_analysis.description.strip():
            parts.append(script_analysis.description.strip())
        else:
            # Build a minimal description from scene texts
            body_lines = [
                scene.text for scene in script_analysis.scenes if scene.type == "BODY"
            ]
            if body_lines:
                parts.append("\n".join(body_lines))

        # Alternative titles section
        if len(script_analysis.title_suggestions) > 1:
            alt_titles = "\n".join(
                f"• {t}" for t in script_analysis.title_suggestions[1:]
            )
            parts.append(f"\n📌 관련 주제:\n{alt_titles}")

        # Hashtags — combine channel defaults + keywords from analysis
        hashtags = self._build_hashtags(script_analysis, channel)
        if hashtags:
            parts.append("\n" + " ".join(hashtags))

        # Channel footer
        footer = channel.get("description_footer", "")
        if footer:
            parts.append(f"\n{footer}")

        return "\n\n".join(parts)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_tags(
        self,
        script_analysis: "ScriptAnalysis",
        channel: dict,
    ) -> list[str]:
        """
        Combine channel default tags + analysis keywords into a tag list.
        Deduplicated, max total chars ~400 (YouTube limit).
        """
        seen: set[str] = set()
        tags: list[str] = []
        total_chars = 0

        def _add(tag: str) -> None:
            nonlocal total_chars
            tag = tag.strip()
            if not tag or tag.lower() in seen:
                return
            cost = len(tag) + 1  # comma separator
            if total_chars + cost > _MAX_TAGS_CHARS:
                return
            seen.add(tag.lower())
            tags.append(tag)
            total_chars += cost

        # Channel defaults first
        for t in channel.get("default_tags", []):
            _add(t)

        # Keywords from all scenes
        for scene in script_analysis.scenes:
            for kw in scene.keywords:
                _add(kw)

        # Thumbnail keywords
        for kw in script_analysis.thumbnail_keywords:
            _add(kw)

        # Add "숏츠" and "Shorts" if not already present
        for mandatory in ("숏츠", "Shorts", "YouTube Shorts"):
            _add(mandatory)

        return tags

    def _build_hashtags(
        self,
        script_analysis: "ScriptAnalysis",
        channel: dict,
    ) -> list[str]:
        """Return a list of #hashtag strings (max 15)."""
        raw_tags = self._build_tags(script_analysis, channel)
        hashtags: list[str] = []
        for tag in raw_tags[:15]:
            ht = f"#{tag.replace(' ', '')}"
            hashtags.append(ht)
        return hashtags
