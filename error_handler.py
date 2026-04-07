import streamlit as st


def handle_api_error(e: Exception, context: str = "") -> None:
    """
    Claude API 호출 실패 시 사용자 친화적 메시지 표시.
    오류 유형별로 다른 안내를 제공한다.
    """
    err_str = str(e).lower()

    if "overloaded" in err_str or "529" in err_str:
        st.error("⚠️ Claude API 서버가 현재 과부하 상태입니다.")
        st.info("💡 30초~1분 후 다시 시도하세요. 입력 내용은 유지됩니다.")

    elif "rate_limit" in err_str or "429" in err_str:
        st.error("⚠️ API 요청 한도에 도달했습니다.")
        st.info("💡 1~2분 후 다시 시도하세요.")

    elif "authentication" in err_str or "401" in err_str:
        st.error("🔑 API 키가 유효하지 않습니다.")
        st.info("💡 Streamlit secrets에서 ANTHROPIC_API_KEY를 확인하세요.")

    elif "context_length" in err_str or "400" in err_str:
        st.error("📝 입력 내용이 너무 깁니다.")
        st.info("💡 추가 요구사항을 줄이거나 내용을 간략하게 수정 후 재시도하세요.")

    elif "timeout" in err_str:
        st.error("⏱️ 응답 시간이 초과되었습니다.")
        st.info("💡 네트워크 상태를 확인하고 다시 시도하세요.")

    else:
        st.error(f"예기치 않은 오류가 발생했습니다: {str(e)[:200]}")
        if context:
            st.caption(f"오류 위치: {context}")

    st.button(
        "🔄 다시 시도",
        key=f"retry_{context}_{hash(str(e))}",
        on_click=lambda: None,
    )


def safe_api_call(func, *args, context="", **kwargs):
    """
    API 호출을 안전하게 래핑하는 헬퍼.
    성공 시 결과 반환, 실패 시 None 반환 + 오류 표시.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        handle_api_error(e, context)
        return None
