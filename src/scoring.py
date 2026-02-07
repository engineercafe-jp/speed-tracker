"""快適度スコア算出ロジック.

各計測値（download, upload, ping, jitter）を正規化し、
重み付け合算で 0〜100 の快適度スコアを算出する。
閾値・重みは config.yaml から読み込むため、
実データ蓄積後の再調整が容易である。
"""

import logging

logger = logging.getLogger(__name__)


def calculate_comfort_score(
    download_mbps: float,
    upload_mbps: float,
    ping_ms: float,
    jitter_ms: float,
    config: dict,
) -> float:
    """快適度スコアを算出する（0〜100）.

    各指標を閾値で正規化（0〜1）し、重み付け合算で 0〜100 のスコアを返す。
    - download / upload: 高いほど良い（閾値以上で満点）
    - ping / jitter: 低いほど良い（0 で満点、閾値以上で 0 点）

    Args:
        download_mbps: ダウンロード速度（Mbps）
        upload_mbps: アップロード速度（Mbps）
        ping_ms: レイテンシ（ms）
        jitter_ms: ジッター（ms）
        config: 設定辞書（scoring セクションを含む）

    Returns:
        快適度スコア（0〜100 の float）
    """
    scoring_config = config["scoring"]
    weights = scoring_config["weights"]
    thresholds = scoring_config["thresholds"]

    # 各指標を 0〜1 に正規化する
    # download / upload: 値が大きいほど良い → 閾値で割ってクリップ
    download_score = min(download_mbps / thresholds["download_max_mbps"], 1.0)
    upload_score = min(upload_mbps / thresholds["upload_max_mbps"], 1.0)

    # ping / jitter: 値が小さいほど良い → 1 - (値 / 閾値) でクリップ
    ping_score = max(1.0 - ping_ms / thresholds["ping_max_ms"], 0.0)
    jitter_score = max(1.0 - jitter_ms / thresholds["jitter_max_ms"], 0.0)

    # 重み付け合算（0〜100 スケール）
    score = (
        weights["download"] * download_score
        + weights["upload"] * upload_score
        + weights["ping"] * ping_score
        + weights["jitter"] * jitter_score
    ) * 100

    # 念のため 0〜100 にクリップ
    score = max(0.0, min(100.0, score))

    logger.debug(
        "スコア算出: DL=%.1f(%.2f) UL=%.1f(%.2f) Ping=%.1f(%.2f) Jitter=%.1f(%.2f) → %.1f",
        download_mbps,
        download_score,
        upload_mbps,
        upload_score,
        ping_ms,
        ping_score,
        jitter_ms,
        jitter_score,
        score,
    )

    return round(score, 1)


def get_comfort_label(score: float, config: dict) -> str:
    """快適度スコアからラベル文字列を返す.

    config.yaml の scoring.labels を参照し、
    スコアに対応するラベルを返す。

    Args:
        score: 快適度スコア（0〜100）
        config: 設定辞書（scoring セクションを含む）

    Returns:
        ラベル文字列（例: "非常に快適"、"快適"、"やや不安定"、"不快"）
    """
    labels = config["scoring"]["labels"]
    for entry in labels:
        if entry["min"] <= score <= entry["max"]:
            return entry["label"]
    # どのラベルにも該当しない場合（通常到達しない）
    logger.warning("スコア %.1f に対応するラベルが見つからない", score)
    return "不明"
