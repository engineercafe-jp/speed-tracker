"""Speedtest CLI ラッパーモジュール.

Ookla Speedtest CLI を subprocess で実行し、
JSON 出力をパースして計測結果を返す。
再試行ロジック・タイムアウト処理を含む。
"""

from __future__ import annotations

import json
import time
import logging
import subprocess
from datetime import datetime

from src.config import load_config

logger = logging.getLogger(__name__)


class SpeedtestError(Exception):
    """Speedtest CLI の実行に失敗した場合の基底例外."""


class SpeedtestTimeoutError(SpeedtestError):
    """Speedtest CLI の実行がタイムアウトした場合の例外."""


class SpeedtestParseError(SpeedtestError):
    """Speedtest CLI の出力の JSON パースに失敗した場合の例外."""


def _parse_result(raw_json: str) -> dict:
    """Speedtest CLI の JSON 出力をパースし、必要なフィールドを抽出する.

    Ookla CLI の出力形式:
    {
        "timestamp": "2024-01-01T00:00:00Z",
        "ping": {"jitter": 1.23, "latency": 4.56},
        "download": {"bandwidth": 12345678},  # bytes/sec
        "upload": {"bandwidth": 12345678},    # bytes/sec
        "server": {"id": 123, "name": "Server Name"},
        "isp": "ISP Name",
        "result": {"url": "https://..."}
    }

    Args:
        raw_json: Speedtest CLI の JSON 出力文字列

    Returns:
        パース済みの辞書

    Raises:
        SpeedtestParseError: JSON パースまたは必須フィールドの欠落時
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise SpeedtestParseError(f"JSON パースに失敗した: {e}") from e

    try:
        result = {
            "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
            # bandwidth は bytes/sec なので bits/sec に変換し、さらに Mbps にする
            # Ookla CLI は bandwidth を bytes/sec で返す
            "download_bps": data["download"]["bandwidth"] * 8,
            "upload_bps": data["upload"]["bandwidth"] * 8,
            "ping_ms": data["ping"]["latency"],
            "jitter_ms": data["ping"]["jitter"],
            "server_id": data.get("server", {}).get("id"),
            "server_name": data.get("server", {}).get("name"),
            "isp": data.get("isp"),
            "result_url": data.get("result", {}).get("url"),
            "raw_json": raw_json,
        }
    except (KeyError, TypeError) as e:
        raise SpeedtestParseError(f"必須フィールドが欠落している: {e}") from e

    logger.debug(
        "パース結果: DL=%.0f bps, UL=%.0f bps, Ping=%.1f ms, Jitter=%.1f ms",
        result["download_bps"],
        result["upload_bps"],
        result["ping_ms"],
        result["jitter_ms"],
    )
    return result


def run_speedtest(config: dict | None = None) -> dict:
    """Speedtest CLI を実行して計測結果を返す.

    再試行ロジック:
    - 失敗時は config.retry_wait_sec 秒待機
    - 最大 config.retry_count 回再試行
    - タイムアウトは config.timeout_sec 秒

    Args:
        config: 設定辞書（省略時は load_config() で読み込む）

    Returns:
        計測結果の辞書（_parse_result の戻り値と同一形式）

    Raises:
        SpeedtestError: 全再試行失敗時
        SpeedtestTimeoutError: タイムアウト時
        SpeedtestParseError: JSON パース失敗時
    """
    if config is None:
        config = load_config()

    st_config = config["speedtest"]
    command = st_config["command"]
    timeout = st_config["timeout_sec"]
    retry_count = st_config["retry_count"]
    retry_wait = st_config["retry_wait_sec"]

    # 実行するコマンドを組み立てる
    cmd = [command, "--format=json", "--accept-license", "--accept-gdpr"]
    logger.info("Speedtest CLI を実行する: %s", " ".join(cmd))

    last_error = None

    for attempt in range(1, retry_count + 1):
        logger.info("計測試行 %d/%d", attempt, retry_count)
        try:
            # subprocess で CLI を実行する
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # 非ゼロ終了コードの場合
            if proc.returncode != 0:
                error_msg = proc.stderr.strip() or f"終了コード: {proc.returncode}"
                raise SpeedtestError(f"Speedtest CLI がエラーで終了した: {error_msg}")

            # JSON パース
            result = _parse_result(proc.stdout)
            logger.info(
                "計測成功 (試行 %d/%d): DL=%.0f bps, Ping=%.1f ms",
                attempt,
                retry_count,
                result["download_bps"],
                result["ping_ms"],
            )
            return result

        except subprocess.TimeoutExpired as e:
            last_error = SpeedtestTimeoutError(
                f"タイムアウト（{timeout}秒）: {e}"
            )
            logger.warning("計測がタイムアウトした (試行 %d/%d)", attempt, retry_count)

        except SpeedtestParseError:
            # パースエラーは再試行しても改善しないため即座に送出する
            raise

        except SpeedtestError as e:
            last_error = e
            logger.warning(
                "計測に失敗した (試行 %d/%d): %s", attempt, retry_count, e
            )

        # 最後の試行でなければ待機する
        if attempt < retry_count:
            logger.info("%d 秒待機して再試行する", retry_wait)
            time.sleep(retry_wait)

    # 全試行失敗
    raise last_error
