"""
Tab 7: 🚀 발행 / 배포
확정된 대본·제목·태그를 티스토리에 자동 발행하거나
유튜브 업로드에 필요한 메타데이터를 준비한다.
"""
import os
import re
import requests
import streamlit as st
from datetime import datetime

from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION,
    P2_TITLE, P2_THUMBNAIL, P2_HOOK_30SEC, P2_IMAGE_PROMPT,
    P3_VIDEO_LENGTH, P3_STRUCTURE, P3_MINI_HOOKS,
    P4_SCRIPT_FULL, P4_VIZ_MEMO, P4_CONFIRMED,
    UPLOAD_DESCRIPTION, UPLOAD_TAGS, UPLOAD_TISTORY_URL,
    render_pipeline_status,
)
from error_handler import handle_api_error


# ──────────────────────────────────────────
# 티스토리 API 헬퍼
# ──────────────────────────────────────────

def _get_tistory_creds() -> tuple:
    """secrets → 환경변수 순으로 티스토리 인증 정보를 가져온다."""
    try:
        token = st.secrets.get("TISTORY_ACCESS_TOKEN", "")
        blog  = st.secrets.get("TISTORY_BLOG_NAME", "")
    except Exception:
        token, blog = "", ""
    token = token or os.environ.get("TISTORY_ACCESS_TOKEN", "")
    blog  = blog  or os.environ.get("TISTORY_BLOG_NAME", "")
    return token, blog


def build_tistory_content(
    channel_name: str,
    title: str,
    script_full: str,
    thumbnail_text: str,
    description: str,
) -> str:
    """
    대본 + 메타 정보를 티스토리 HTML 포스트 형식으로 변환한다.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 대본 텍스트를 HTML 문단으로 변환
    def to_html_paragraphs(text: str) -> str:
        paragraphs = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # 타임코드 헤더 처리 ([00:00] HOOK 등)
            if re.match(r"^\[\d{2}:\d{2}\]", stripped):
                paragraphs.append(
                    f'<h3 style="color:#333; border-left:4px solid #4A90E2; '
                    f'padding-left:10px; margin-top:32px;">{stripped}</h3>'
                )
            # 미니훅 처리 (🔥 으로 시작)
            elif stripped.startswith("🔥"):
                paragraphs.append(
                    f'<p style="background:#fff3cd; border-radius:6px; '
                    f'padding:8px 14px; font-weight:600;">{stripped}</p>'
                )
            # DATA_SKETCH_SCENE 후보
            elif "[DATA_SKETCH_SCENE 후보]" in stripped:
                paragraphs.append(
                    f'<p style="background:#e3f2fd; border-radius:6px; '
                    f'padding:8px 14px; color:#1565C0;">{stripped}</p>'
                )
            else:
                paragraphs.append(f"<p>{stripped}</p>")
        return "\n".join(paragraphs)

    script_html = to_html_paragraphs(script_full) if script_full else "<p>(대본 없음)</p>"

    html = f"""
<div style="font-family: 'Noto Sans KR', sans-serif; max-width:800px; margin:0 auto; line-height:1.8;">

<div style="background:#f8f9fa; border-radius:10px; padding:20px; margin-bottom:30px;">
  <p><strong>채널:</strong> {channel_name}</p>
  <p><strong>제목:</strong> {title}</p>
  <p><strong>썸네일 문구:</strong> {thumbnail_text}</p>
  <p style="font-size:12px; color:#888;">작성일: {ts}</p>
</div>

{f'<div style="background:#fff8e1; border-radius:8px; padding:16px; margin-bottom:24px;"><strong>📋 영상 설명</strong><br>{description}</div>' if description else ""}

<hr style="border:none; border-top:2px solid #eee; margin:24px 0;">
<h2 style="color:#1a1a1a;">📝 대본 전문</h2>

{script_html}

<hr style="border:none; border-top:2px solid #eee; margin:32px 0;">
<p style="font-size:12px; color:#aaa; text-align:center;">
  YouTube 채널 전략 도구로 작성된 대본입니다. | {ts}
</p>

</div>
"""
    return html


def post_to_tistory(
    title: str,
    content: str,
    tags: list,
    category_id: str = "0",
    visibility: int = 0,
) -> dict:
    """
    티스토리 API를 통해 포스트를 발행한다.
    visibility: 0=비공개, 1=보호, 3=공개
    반환: {"success": bool, "url": str, "post_id": str, "error": str}
    """
    token, blog_name = _get_tistory_creds()
    if not token or not blog_name:
        return {"success": False, "url": "", "post_id": "",
                "error": "TISTORY_ACCESS_TOKEN 또는 TISTORY_BLOG_NAME이 설정되지 않았습니다."}

    tag_str = ",".join(tags) if tags else ""

    try:
        resp = requests.post(
            "https://www.tistory.com/apis/post/write",
            params={"access_token": token, "output": "json"},
            data={
                "blogName":   blog_name,
                "title":      title,
                "content":    content,
                "visibility": str(visibility),
                "categoryId": str(category_id),
                "tag":        tag_str,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("tistory", {}).get("status") == "200":
            post_id = data["tistory"].get("postId", "")
            url = data["tistory"].get("url", f"https://{blog_name}.tistory.com/{post_id}")
            return {"success": True, "url": url, "post_id": str(post_id), "error": ""}
        else:
            err = data.get("tistory", {}).get("error_message", str(data))
            return {"success": False, "url": "", "post_id": "", "error": err}

    except requests.exceptions.ConnectionError:
        return {"success": False, "url": "", "post_id": "",
                "error": "네트워크 연결 오류. 인터넷 연결을 확인해주세요."}
    except requests.exceptions.Timeout:
        return {"success": False, "url": "", "post_id": "",
                "error": "요청 시간 초과. 잠시 후 다시 시도해주세요."}
    except Exception as e:
        return {"success": False, "url": "", "post_id": "", "error": str(e)}


# ──────────────────────────────────────────
# 유튜브 메타데이터 자동 생성
# ──────────────────────────────────────────

def build_youtube_description(
    title: str,
    core_message: str,
    script_full: str,
    structure: dict,
    mini_hooks: list,
    channel_name: str,
) -> str:
    """확정된 내용을 바탕으로 유튜브 설명란 텍스트를 자동 생성한다."""
    # 타임스탬프 생성 (섹션 헤더 기반)
    timecodes = {
        "00:00": "HOOK",  "01:00": "TEASER",  "02:00": "BIG IDEA",
        "03:00": "INTRO", "04:00": "BODY 1",  "07:00": "BODY 2",
        "10:15": "BODY 3","13:30": "BODY 4",  "17:00": "REVEAL",
        "18:30": "IMPACT","19:00": "END",
    }
    stamps = [f"{tc} {label}" for tc, label in timecodes.items()]

    lines = [
        f"📌 {core_message}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📋 목차",
    ] + stamps + [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📺 채널: {channel_name}",
        "",
        "#유튜브 #콘텐츠 #채널전략",
    ]
    return "\n".join(lines)


def build_youtube_tags(
    topic_title: str,
    title: str,
    channel_name: str,
    target_emotion: str,
) -> str:
    """제목·주제에서 유튜브 태그를 자동 추출한다."""
    raw = f"{topic_title} {title} {channel_name} {target_emotion}"
    # 단어 분리 (특수문자 제거, 중복 제거)
    words = re.findall(r"[가-힣a-zA-Z0-9]+", raw)
    # 짧은 단어(2자 미만) 제거, 중복 제거, 최대 15개
    tags = list(dict.fromkeys(w for w in words if len(w) >= 2))[:15]
    return " ".join(f"#{t}" for t in tags)


# ──────────────────────────────────────────
# 메인 탭 렌더링
# ──────────────────────────────────────────

def render_deploy_tab():
    render_pipeline_status()

    st.header("🚀 발행 / 배포", divider="gray")
    st.caption(
        "완성된 대본을 티스토리에 자동 발행하거나  \n"
        "유튜브 업로드에 필요한 제목·설명·태그를 준비합니다."
    )

    # ── 사전 준비 상태 확인 ───────────────────────────────────────────────────
    script_ready = bool(st.session_state.get(P4_SCRIPT_FULL))
    title_ready  = bool(st.session_state.get(P2_TITLE))

    if not script_ready or not title_ready:
        st.warning("⚠️ 탭5(대본 작성)까지 완료해야 발행/배포를 진행할 수 있습니다.")
        if not title_ready:
            st.caption("→ 탭3(썸네일·제목)에서 제목을 확정해주세요.")
        if not script_ready:
            st.caption("→ 탭5(대본 작성)에서 전체 대본을 완성해주세요.")
        return

    # ── 업로드 메타데이터 자동 생성 ──────────────────────────────────────────
    channel_name   = st.session_state.get(P1_CHANNEL, "")
    topic_title    = st.session_state.get(P1_TOPIC_TITLE, "")
    core_message   = st.session_state.get(P1_CORE_MESSAGE, "")
    target_emotion = st.session_state.get(P1_EMOTION, "")
    confirmed_title   = st.session_state.get(P2_TITLE, "")
    confirmed_thumbnail = st.session_state.get(P2_THUMBNAIL, "")
    script_full    = st.session_state.get(P4_SCRIPT_FULL, "")
    structure      = st.session_state.get(P3_STRUCTURE, {})
    mini_hooks     = st.session_state.get(P3_MINI_HOOKS, [])

    # 설명/태그 자동 생성 (아직 없는 경우)
    if not st.session_state.get(UPLOAD_DESCRIPTION):
        st.session_state[UPLOAD_DESCRIPTION] = build_youtube_description(
            title=confirmed_title,
            core_message=core_message,
            script_full=script_full,
            structure=structure,
            mini_hooks=mini_hooks,
            channel_name=channel_name,
        )
    if not st.session_state.get(UPLOAD_TAGS):
        st.session_state[UPLOAD_TAGS] = build_youtube_tags(
            topic_title=topic_title,
            title=confirmed_title,
            channel_name=channel_name,
            target_emotion=target_emotion,
        )

    # ── 설명란 / 태그 편집 ────────────────────────────────────────────────────
    with st.expander("✏️ 업로드 메타데이터 편집", expanded=False):
        new_desc = st.text_area(
            "유튜브 설명란",
            value=st.session_state.get(UPLOAD_DESCRIPTION, ""),
            height=220,
            key="edit_upload_description",
        )
        new_tags = st.text_input(
            "태그 (#태그1 #태그2 형식)",
            value=st.session_state.get(UPLOAD_TAGS, ""),
            key="edit_upload_tags",
        )
        if st.button("💾 메타데이터 저장", key="save_meta"):
            st.session_state[UPLOAD_DESCRIPTION] = new_desc
            st.session_state[UPLOAD_TAGS] = new_tags
            st.success("저장되었습니다!")

    st.divider()

    # ── 2개 서브탭 ────────────────────────────────────────────────────────────
    deploy_tab1, deploy_tab2 = st.tabs(["📝 티스토리 자동 발행", "📋 유튜브 업로드 정보"])

    # ── 티스토리 발행 ─────────────────────────────────────────────────────────
    with deploy_tab1:
        st.subheader("📝 티스토리 자동 발행")

        tistory_token, tistory_blog = _get_tistory_creds()

        if not tistory_token or not tistory_blog:
            st.warning("⚠️ 티스토리 API 인증 정보가 설정되지 않았습니다.")
            st.info(
                "💡 `.streamlit/secrets.toml`에 아래 내용을 추가해주세요:  \n"
                "발급: https://www.tistory.com/guide/api/manage/register"
            )
            st.code(
                'TISTORY_ACCESS_TOKEN = "your_access_token"\n'
                'TISTORY_BLOG_NAME = "your_blog_name"  # myblog.tistory.com → myblog',
                language="toml",
            )
        else:
            st.success(f"✅ 티스토리 연결됨: `{tistory_blog}.tistory.com`")

            col1, col2 = st.columns(2)
            with col1:
                tistory_visibility = st.radio(
                    "발행 상태",
                    ["비공개 (검토 후 공개 권장)", "공개"],
                    index=0,
                    key="tistory_visibility",
                )
            with col2:
                tistory_category = st.text_input(
                    "카테고리 ID (선택)",
                    value="0",
                    key="tistory_category",
                    help="티스토리 카테고리 ID. 0이면 기본 카테고리",
                )

            visibility_val = 0 if "비공개" in tistory_visibility else 3

            # 발행 미리보기
            with st.expander("👁️ 발행 내용 미리보기", expanded=False):
                preview = build_tistory_content(
                    channel_name=channel_name,
                    title=confirmed_title,
                    script_full=script_full[:2000] + ("..." if len(script_full) > 2000 else ""),
                    thumbnail_text=confirmed_thumbnail,
                    description=st.session_state.get(UPLOAD_DESCRIPTION, ""),
                )
                st.markdown(preview, unsafe_allow_html=True)

            if st.button(
                "📝 티스토리에 발행",
                type="primary",
                use_container_width=True,
                disabled=not script_ready,
            ):
                with st.spinner("티스토리에 발행 중..."):
                    content = build_tistory_content(
                        channel_name=channel_name,
                        title=confirmed_title,
                        script_full=script_full,
                        thumbnail_text=confirmed_thumbnail,
                        description=st.session_state.get(UPLOAD_DESCRIPTION, ""),
                    )
                    tags_str = st.session_state.get(UPLOAD_TAGS, "")
                    tags = [t.strip().lstrip("#") for t in tags_str.split() if t.strip()]

                    result = post_to_tistory(
                        title=confirmed_title,
                        content=content,
                        tags=tags,
                        category_id=tistory_category,
                        visibility=visibility_val,
                    )

                    if result["success"]:
                        st.session_state[UPLOAD_TISTORY_URL] = result["url"]
                        st.success("✅ 발행 완료!")
                        st.markdown(f"**발행 URL:** [{result['url']}]({result['url']})")
                        if visibility_val == 0:
                            st.info("비공개로 발행됐습니다. 티스토리에서 검토 후 공개하세요.")
                    else:
                        st.error(f"발행 실패: {result['error']}")

            # 이전 발행 URL 표시
            prev_url = st.session_state.get(UPLOAD_TISTORY_URL, "")
            if prev_url:
                st.markdown(f"📌 **최근 발행 URL:** [{prev_url}]({prev_url})")

    # ── 유튜브 업로드 정보 ────────────────────────────────────────────────────
    with deploy_tab2:
        st.subheader("📋 유튜브 업로드 정보")
        st.caption("아래 내용을 복사해서 유튜브 업로드 시 사용하세요.")

        if confirmed_title:
            st.markdown("**📋 제목 (복사)**")
            st.code(confirmed_title, language=None)

            st.markdown("**📋 설명란 (복사)**")
            st.text_area(
                "설명란",
                value=st.session_state.get(UPLOAD_DESCRIPTION, ""),
                height=300,
                key="youtube_desc_copy",
                help="이 내용을 유튜브 설명란에 붙여넣으세요.",
            )

            st.markdown("**📋 태그 (복사)**")
            st.code(st.session_state.get(UPLOAD_TAGS, ""), language=None)

            # 썸네일 문구 참고
            if confirmed_thumbnail:
                with st.expander("🖼️ 썸네일 문구 참고", expanded=False):
                    st.text(confirmed_thumbnail)
                    image_prompt = st.session_state.get(P2_IMAGE_PROMPT, "")
                    if image_prompt:
                        st.markdown("**나노바나나 이미지 프롬프트:**")
                        st.text_area(
                            "이미지 프롬프트",
                            value=image_prompt,
                            height=100,
                            key="deploy_img_prompt",
                        )

            st.info(
                "📌 **유튜브 업로드 순서**  \n"
                "1. 영상 파일을 유튜브 스튜디오에 직접 업로드  \n"
                "2. 위 제목 / 설명란 / 태그를 복사하여 입력  \n"
                "3. 썸네일 이미지 업로드  \n"
                "4. 카드·최종 화면 설정  \n"
                "5. 공개 설정 후 게시 (또는 예약 설정)"
            )

            # 체크리스트
            st.markdown("**✅ 업로드 전 최종 체크리스트**")
            checks = [
                "영상 파일 인코딩 완료 (MP4 H.264 권장)",
                "썸네일 이미지 준비 (1280×720px, JPG/PNG)",
                "제목에 핵심 검색 키워드 포함 확인",
                "설명란 타임스탬프 정확도 확인",
                "유튜브 커뮤니티 가이드라인 썸네일 검토",
                "카드 / 최종 화면 / 자막 설정",
            ]
            for chk in checks:
                st.checkbox(chk, key=f"upload_chk_{chk[:20]}")

        else:
            st.info("탭3(썸네일·제목)과 탭5(대본 작성)를 먼저 완성해주세요.")
