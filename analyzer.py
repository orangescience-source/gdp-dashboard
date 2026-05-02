"""니치 영상 분석 로직."""

import pandas as pd


def build_dataframe(videos: list[dict]) -> pd.DataFrame:
    """영상 목록을 DataFrame으로 변환합니다."""
    df = pd.DataFrame(videos)
    if df.empty:
        return df
    df = df.drop(columns=["pub_dt"], errors="ignore")
    return df


def filter_by_recency(df: pd.DataFrame, max_days: int) -> pd.DataFrame:
    """최근 N일 이내 영상만 필터링합니다."""
    if df.empty or "days_ago" not in df.columns:
        return df
    return df[df["days_ago"].notna() & (df["days_ago"] <= max_days)].copy()


def compute_average_views(df: pd.DataFrame) -> float:
    """평균 조회수를 계산합니다."""
    if df.empty:
        return 0.0
    return df["view_count"].mean()


def classify_niche(df: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    """평균 대비 배수 이상인 영상을 니치로 분류합니다."""
    if df.empty:
        return df

    avg = compute_average_views(df)
    df = df.copy()
    df["avg_view_count"] = avg
    df["ratio"] = df["view_count"] / avg if avg > 0 else 0.0
    df["is_niche"] = df["ratio"] >= multiplier
    return df


def get_niche_videos(df: pd.DataFrame) -> pd.DataFrame:
    """니치 영상만 반환하고 ratio 내림차순으로 정렬합니다."""
    if df.empty or "is_niche" not in df.columns:
        return pd.DataFrame()
    niche = df[df["is_niche"]].copy()
    return niche.sort_values("ratio", ascending=False).reset_index(drop=True)


def run_analysis(
    videos: list[dict],
    multiplier: float = 3.0,
    recent_only: bool = False,
    max_days: int = 90,
) -> dict:
    """전체 분석 파이프라인을 실행하고 결과 dict를 반환합니다."""
    df = build_dataframe(videos)

    if df.empty:
        return {
            "df_all": df,
            "df_filtered": df,
            "df_classified": df,
            "df_niche": pd.DataFrame(),
            "avg_views": 0.0,
            "niche_count": 0,
            "total_count": 0,
        }

    df_filtered = filter_by_recency(df, max_days) if recent_only else df.copy()
    df_classified = classify_niche(df_filtered, multiplier)
    df_niche = get_niche_videos(df_classified)
    avg_views = compute_average_views(df_filtered)

    return {
        "df_all": df,
        "df_filtered": df_filtered,
        "df_classified": df_classified,
        "df_niche": df_niche,
        "avg_views": avg_views,
        "niche_count": len(df_niche),
        "total_count": len(df_filtered),
    }
