import json
import os
import streamlit as st
from channel_db import CHANNEL_DB

USER_CHANNELS_FILE = "user_channels.json"
BASE_CHANNEL_NAMES = list(CHANNEL_DB.keys())


def _load_user_channels() -> dict:
    if not os.path.exists(USER_CHANNELS_FILE):
        return {}
    try:
        with open(USER_CHANNELS_FILE, "r",
                  encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_user_channels(data: dict) -> bool:
    try:
        with open(USER_CHANNELS_FILE, "w",
                  encoding="utf-8") as f:
            json.dump(data, f,
                      ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_merged_channel_db() -> dict:
    """
    기존 CHANNEL_DB + 사용자 채널 병합.
    기존 채널은 override_base=True 일 때만 덮어씀.
    """
    user_channels = _load_user_channels()
    merged = dict(CHANNEL_DB)

    for ch_name, ch_data in user_channels.items():
        db_data = ch_data.get("db", {})
        if not db_data:
            continue
        if ch_name in merged:
            if ch_data.get("override_base", False):
                merged[ch_name] = {
                    **merged[ch_name], **db_data
                }
        else:
            merged[ch_name] = db_data

    return merged


def get_all_channel_names() -> list:
    return list(get_merged_channel_db().keys())


def is_base_channel(name: str) -> bool:
    return name in BASE_CHANNEL_NAMES


def save_channel(
    channel_name: str,
    db_data: dict,
    visual_data: dict,
    override_base: bool = False
) -> tuple:
    if not channel_name.strip():
        return False, "채널명을 입력해주세요."

    if is_base_channel(channel_name) and not override_base:
        return False, (
            f"'{channel_name}'은 기본 채널입니다.\n"
            "'기본 채널 수정 허용'을 체크해야 합니다."
        )

    user_channels = _load_user_channels()
    user_channels[channel_name] = {
        "db":            db_data,
        "visual":        visual_data,
        "override_base": override_base,
        "is_base":       is_base_channel(channel_name),
    }

    if _save_user_channels(user_channels):
        return True, f"✅ '{channel_name}' 저장 완료!"
    return False, "저장 중 오류가 발생했습니다."


def delete_channel(channel_name: str) -> tuple:
    if is_base_channel(channel_name):
        user_channels = _load_user_channels()
        if channel_name in user_channels:
            del user_channels[channel_name]
            _save_user_channels(user_channels)
            return True, (
                f"✅ '{channel_name}' 커스텀 설정 초기화 완료"
            )
        return False, "기본 채널은 삭제할 수 없습니다."

    user_channels = _load_user_channels()
    if channel_name not in user_channels:
        return False, "채널을 찾을 수 없습니다."

    del user_channels[channel_name]
    if _save_user_channels(user_channels):
        return True, f"✅ '{channel_name}' 삭제 완료!"
    return False, "삭제 중 오류가 발생했습니다."


def validate_channel(channel_name: str) -> tuple:
    """파이프라인 연동 가능 여부 검증"""
    merged = get_merged_channel_db()
    data   = merged.get(channel_name, {})
    errors = []

    required = [
        "character_name", "tone",
        "target_audience", "color_primary"
    ]
    for field in required:
        if not data.get(field, "").strip():
            errors.append(f"필수 항목 누락: {field}")

    color = data.get("color_primary", "")
    if color and not color.startswith("#"):
        errors.append("color_primary는 #HEX 형식이어야 합니다.")

    return (len(errors) == 0), errors
