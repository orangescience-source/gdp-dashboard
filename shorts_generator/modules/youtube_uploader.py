"""
YouTube Data API v3 uploader with OAuth2 authentication.
Always uploads as private (Phase 1 requirement).
"""

from __future__ import annotations

import http.client
import json
import os
import time
from pathlib import Path
from typing import Optional

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)

console = Console()

# OAuth2 scopes required for upload + thumbnail set
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

TOKEN_PATH = "token.json"
CHUNK_SIZE = 1024 * 1024 * 8   # 8 MB resumable upload chunk
MAX_RETRIES = 10
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.ImproperConnectionState,
    http.client.CanSendRequest,
    http.client.CanSendHeader,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
)


class YouTubeUploader:
    """
    Authenticates with YouTube Data API v3 and uploads Shorts videos.

    Usage:
        uploader = YouTubeUploader()
        uploader.authenticate("credentials.json")
        video_id = uploader.upload(
            video_path="output/shorts_xxx.mp4",
            thumbnail_path="output/thumb.jpg",   # or None
            upload_set={...},
            channel_id="UC_...",
        )
    """

    def __init__(self) -> None:
        self._service = None

    # ── Public API ────────────────────────────────────────────────────────────

    def authenticate(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = TOKEN_PATH,
    ) -> None:
        """
        Run or refresh OAuth2 flow; caches token in *token_path*.

        Args:
            credentials_path: Path to the OAuth2 client secrets JSON from
                              Google Cloud Console.
            token_path: Where to store/load the cached access token.
        """
        creds: Optional[Credentials] = None

        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                console.print("[cyan]YouTube 토큰 갱신 중...[/cyan]")
                creds.refresh(Request())
            else:
                if not Path(credentials_path).exists():
                    raise FileNotFoundError(
                        f"OAuth2 인증 파일을 찾을 수 없습니다: {credentials_path}\n"
                        "Google Cloud Console에서 OAuth2 클라이언트 ID를 다운로드하세요."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save the credentials
            with open(token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
            console.print(f"[green]✓ YouTube 인증 완료 (토큰 저장: {token_path})[/green]")

        self._service = build("youtube", "v3", credentials=creds)
        console.print("[green]✓ YouTube API 연결 성공[/green]")

    def upload(
        self,
        video_path: str,
        thumbnail_path: Optional[str],
        upload_set: dict,
        channel_id: str,
    ) -> str:
        """
        Upload a video as private and optionally set a thumbnail.

        Args:
            video_path: Path to the video file (MP4).
            thumbnail_path: Path to thumbnail image, or None to skip.
            upload_set: Dict with keys: title, description, tags,
                        category_id, privacy_status.
            channel_id: Target channel ID (UC...). Used for logging only
                        — the authenticated account determines the channel.

        Returns:
            The YouTube video ID (e.g. "dQw4w9WgXcQ").

        Raises:
            RuntimeError: If upload fails after all retries.
        """
        if self._service is None:
            raise RuntimeError("authenticate()를 먼저 호출하세요.")

        if not Path(video_path).exists():
            raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {video_path}")

        body = {
            "snippet": {
                "title": upload_set.get("title", "YouTube Shorts"),
                "description": upload_set.get("description", ""),
                "tags": upload_set.get("tags", []),
                "categoryId": upload_set.get("category_id", "22"),
                "defaultLanguage": "ko",
                "defaultAudioLanguage": "ko",
            },
            "status": {
                "privacyStatus": "private",   # always private in Phase 1
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            video_path,
            chunksize=CHUNK_SIZE,
            resumable=True,
            mimetype="video/mp4",
        )

        console.print(
            f"[cyan]⬆ YouTube 업로드 시작:[/cyan] [bold]{body['snippet']['title']}[/bold]"
        )
        console.print(
            f"  채널: {channel_id or '(기본 채널)'}  /  "
            f"파일: {Path(video_path).name}  "
            f"({Path(video_path).stat().st_size / 1024 / 1024:.1f} MB)"
        )

        request = self._service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        video_id = self._resumable_upload(request)

        # Set thumbnail if provided
        if thumbnail_path and Path(thumbnail_path).exists():
            self._set_thumbnail(video_id, thumbnail_path)

        console.print(
            f"[bold green]✓ 업로드 완료![/bold green]  "
            f"Video ID: [bold]{video_id}[/bold]  "
            f"URL: https://youtu.be/{video_id}"
        )
        return video_id

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resumable_upload(self, request) -> str:
        """
        Execute a resumable upload request with retry logic.

        Args:
            request: googleapiclient MediaFileUpload request object.

        Returns:
            YouTube video ID on success.

        Raises:
            RuntimeError: After exhausting retries.
        """
        response = None
        error = None
        retry = 0

        file_size = request.resumable._fd.seek(0, 2)  # seek to end for size
        request.resumable._fd.seek(0)

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]업로드 중...[/cyan]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task: TaskID = progress.add_task("upload", total=file_size)
            uploaded = 0

            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        new_uploaded = status.resumable_progress
                        progress.advance(task, new_uploaded - uploaded)
                        uploaded = new_uploaded
                except HttpError as exc:
                    if exc.resp.status in RETRIABLE_STATUS_CODES:
                        error = f"HTTP {exc.resp.status}: {exc.content}"
                    else:
                        raise
                except RETRIABLE_EXCEPTIONS as exc:
                    error = str(exc)

                if error:
                    retry += 1
                    if retry > MAX_RETRIES:
                        raise RuntimeError(
                            f"업로드 실패 ({MAX_RETRIES}회 재시도): {error}"
                        )
                    wait = 2 ** retry
                    console.print(
                        f"[yellow]  업로드 오류, {wait}초 후 재시도 ({retry}/{MAX_RETRIES}): "
                        f"{error}[/yellow]"
                    )
                    time.sleep(wait)
                    error = None

        if response is None:
            raise RuntimeError("업로드가 완료되지 않았습니다.")

        return response["id"]

    def _set_thumbnail(self, video_id: str, thumbnail_path: str) -> None:
        """Upload and set a custom thumbnail for the given video."""
        try:
            self._service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()
            console.print(f"[green]  ✓ 썸네일 설정 완료[/green]")
        except HttpError as exc:
            console.print(f"[yellow]  ⚠ 썸네일 설정 실패 (건너뜀): {exc}[/yellow]")
