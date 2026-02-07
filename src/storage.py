"""SQLite によるデータ保存・集計モジュール.

計測結果の保存、時間帯別集計、古いデータの削除を行う。
テーブルは measurements の単一テーブル構成である。
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta

from src.config import load_config, get_db_path

logger = logging.getLogger(__name__)

# テーブル作成 SQL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_at     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ok',
    download_mbps   REAL,
    upload_mbps     REAL,
    ping_ms         REAL,
    jitter_ms       REAL,
    comfort_score   REAL,
    server_id       INTEGER,
    server_name     TEXT,
    isp             TEXT,
    result_url      TEXT,
    error_message   TEXT,
    raw_json        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# インデックス作成 SQL
_CREATE_INDEXES_SQL = [
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_measured_at
        ON measurements(measured_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_status
        ON measurements(status);
    """,
]


def init_db(db_path: Path | None = None, config: dict | None = None) -> Path:
    """データベースを初期化する（テーブル・インデックス作成）.

    既にテーブルが存在する場合は何もしない（IF NOT EXISTS）。

    Args:
        db_path: データベースファイルのパス（省略時は設定から取得）
        config: 設定辞書（省略時は load_config() で読み込む）

    Returns:
        データベースファイルの絶対パス
    """
    if config is None:
        config = load_config()
    if db_path is None:
        db_path = get_db_path(config)

    # ディレクトリがなければ作成する
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("データベースを初期化する: %s", db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        # テーブル作成
        cursor.execute(_CREATE_TABLE_SQL)
        # インデックス作成
        for sql in _CREATE_INDEXES_SQL:
            cursor.execute(sql)
        conn.commit()
        logger.info("データベースの初期化が完了した")
    finally:
        conn.close()

    return db_path


def _get_connection(db_path: Path | None = None, config: dict | None = None) -> sqlite3.Connection:
    """データベース接続を取得する.

    行を辞書形式で取得するために row_factory を設定する。

    Args:
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        sqlite3.Connection オブジェクト
    """
    if db_path is None:
        if config is None:
            config = load_config()
        db_path = get_db_path(config)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def save_measurement(data: dict, db_path: Path | None = None, config: dict | None = None) -> int:
    """計測結果をデータベースに保存する.

    Args:
        data: 計測結果の辞書。以下のキーを含む:
            - measured_at (str): 計測日時（ISO 8601）
            - download_mbps (float): ダウンロード速度
            - upload_mbps (float): アップロード速度
            - ping_ms (float): レイテンシ
            - jitter_ms (float): ジッター
            - comfort_score (float): 快適度スコア
            - server_id (int, optional): サーバID
            - server_name (str, optional): サーバ名
            - isp (str, optional): ISP名
            - result_url (str, optional): 結果URL
            - raw_json (str, optional): 生JSON
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        挿入された行の ID
    """
    conn = _get_connection(db_path, config)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO measurements (
                measured_at, status, download_mbps, upload_mbps,
                ping_ms, jitter_ms, comfort_score,
                server_id, server_name, isp, result_url, raw_json
            ) VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["measured_at"],
                data["download_mbps"],
                data["upload_mbps"],
                data["ping_ms"],
                data["jitter_ms"],
                data["comfort_score"],
                data.get("server_id"),
                data.get("server_name"),
                data.get("isp"),
                data.get("result_url"),
                data.get("raw_json"),
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
        logger.info(
            "計測結果を保存した (id=%d): DL=%.1f Mbps, UL=%.1f Mbps, Ping=%.1f ms, Score=%.1f",
            row_id,
            data["download_mbps"],
            data["upload_mbps"],
            data["ping_ms"],
            data["comfort_score"],
        )
        return row_id
    finally:
        conn.close()


def save_error(
    error_message: str,
    raw_output: str | None = None,
    db_path: Path | None = None,
    config: dict | None = None,
) -> int:
    """計測エラーをデータベースに記録する.

    再試行全失敗後に呼び出され、欠測理由を追跡可能にする。

    Args:
        error_message: エラーメッセージ
        raw_output: エラー時の生出力（デバッグ用）
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        挿入された行の ID
    """
    conn = _get_connection(db_path, config)
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute(
            """
            INSERT INTO measurements (measured_at, status, error_message, raw_json)
            VALUES (?, 'error', ?, ?)
            """,
            (now, error_message, raw_output),
        )
        conn.commit()
        row_id = cursor.lastrowid
        logger.warning("計測エラーを記録した (id=%d): %s", row_id, error_message)
        return row_id
    finally:
        conn.close()


def get_hourly_averages(
    days: int = 28,
    open_hour: int | None = None,
    close_hour: int | None = None,
    db_path: Path | None = None,
    config: dict | None = None,
) -> list[dict]:
    """開館時間内の時間帯×曜日の平均スコアを取得する.

    ヒートマップ用のデータを返す。
    曜日は 0=月曜〜6=日曜（Python の weekday() に準拠）。

    Args:
        days: 集計対象日数（デフォルト28日）
        open_hour: 開館時間（デフォルトは設定値）
        close_hour: 閉館時間（デフォルトは設定値）
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        辞書のリスト。各辞書は以下のキーを含む:
        - day_of_week (int): 曜日（0=月〜6=日）
        - hour (int): 時間帯（例: 9, 10, ..., 21）
        - avg_score (float): 平均快適度スコア
        - count (int): 計測回数
    """
    if config is None:
        config = load_config()
    if open_hour is None:
        open_hour = config["cafe"]["open_hour"]
    if close_hour is None:
        close_hour = config["cafe"]["close_hour"]
    utc_offset_hours = int(config["cafe"].get("utc_offset_hours", 9))
    offset_modifier = f"{utc_offset_hours:+d} hours"

    conn = _get_connection(db_path, config)
    try:
        # 集計対象の開始日を計算する
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # SQLite の strftime で曜日と時間帯を抽出して集計する
        # Speedtest の measured_at は UTC(Z) を含むため、開館時間の判定前に
        # カフェのローカル時刻へ変換して扱う。
        local_dt_expr = (
            "CASE WHEN measured_at LIKE '%Z' "
            "THEN datetime(measured_at, ?) "
            "ELSE measured_at END"
        )
        # strftime('%w', ...) は 0=日曜 なので、Python の weekday() に変換する
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                -- SQLite %w: 0=日,1=月,...,6=土 → Python weekday: 0=月,...,6=日
                CASE CAST(strftime('%w', {local_dt_expr}) AS INTEGER)
                    WHEN 0 THEN 6  -- 日曜 → 6
                    ELSE CAST(strftime('%w', {local_dt_expr}) AS INTEGER) - 1
                END AS day_of_week,
                CAST(strftime('%H', {local_dt_expr}) AS INTEGER) AS hour,
                AVG(comfort_score) AS avg_score,
                COUNT(*) AS count
            FROM measurements
            WHERE status = 'ok'
              AND measured_at >= ?
              AND CAST(strftime('%H', {local_dt_expr}) AS INTEGER) >= ?
              AND CAST(strftime('%H', {local_dt_expr}) AS INTEGER) < ?
            GROUP BY day_of_week, hour
            ORDER BY day_of_week, hour
            """,
            (
                offset_modifier,
                offset_modifier,
                offset_modifier,
                since,
                offset_modifier,
                open_hour,
                offset_modifier,
                close_hour,
            ),
        )
        rows = cursor.fetchall()
        result = [
            {
                "day_of_week": row["day_of_week"],
                "hour": row["hour"],
                "avg_score": round(row["avg_score"], 1),
                "count": row["count"],
            }
            for row in rows
        ]
        logger.info("時間帯別平均スコアを取得した: %d 件", len(result))
        return result
    finally:
        conn.close()


def get_recent_measurements(
    hours: int = 24,
    db_path: Path | None = None,
    config: dict | None = None,
) -> list[dict]:
    """直近 N 時間の計測結果を取得する（折れ線グラフ用）.

    Args:
        hours: 取得対象の時間数（デフォルト24時間）
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        辞書のリスト。各辞書は以下のキーを含む:
        - measured_at (str): 計測日時
        - download_mbps (float): ダウンロード速度
        - upload_mbps (float): アップロード速度
        - ping_ms (float): レイテンシ
        - jitter_ms (float): ジッター
        - comfort_score (float): 快適度スコア
    """
    conn = _get_connection(db_path, config)
    try:
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT measured_at, download_mbps, upload_mbps,
                   ping_ms, jitter_ms, comfort_score
            FROM measurements
            WHERE status = 'ok'
              AND measured_at >= ?
            ORDER BY measured_at ASC
            """,
            (since,),
        )
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        logger.info("直近 %d 時間の計測結果を取得した: %d 件", hours, len(result))
        return result
    finally:
        conn.close()


def cleanup_old_data(
    retention_days: int | None = None,
    db_path: Path | None = None,
    config: dict | None = None,
) -> int:
    """保存期間を超えた古いデータを削除する.

    Args:
        retention_days: 保存期間（日数）。省略時は設定値を使用
        db_path: データベースファイルのパス
        config: 設定辞書

    Returns:
        削除された行数
    """
    if config is None:
        config = load_config()
    if retention_days is None:
        retention_days = config["storage"]["retention_days"]

    conn = _get_connection(db_path, config)
    try:
        cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM measurements WHERE measured_at < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cursor.rowcount
        logger.info(
            "%d 日以上前のデータを %d 件削除した（カットオフ: %s）",
            retention_days,
            deleted,
            cutoff,
        )
        return deleted
    finally:
        conn.close()
