#!/usr/bin/env python3
"""計測エントリポイント — cron から定期実行される.

1回の速度計測を行い、結果をデータベースに保存する。
失敗時（再試行全失敗後）はエラーを記録する。

使用例:
    python scripts/run_speedtest.py
    # cron: */15 9-21 * * * cd /path/to/speed-tracker && python scripts/run_speedtest.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# プロジェクトルートを sys.path に追加する（cron 実行時のため）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.collector import run_speedtest, SpeedtestError
from src.scoring import calculate_comfort_score
from src.storage import init_db, save_measurement, save_error


def _setup_logging() -> None:
    """ロギングを設定する.

    コンソール出力と logs/collector.log への追記を行う。
    """
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "collector.log", encoding="utf-8"),
        ],
    )


def main() -> None:
    """メイン処理: 速度計測 → スコア算出 → DB 保存."""
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== 速度計測を開始する ===")

    config = load_config()

    # データベースを初期化する（テーブルが存在しない場合のみ作成）
    init_db(config=config)

    try:
        # Speedtest CLI を実行する
        result = run_speedtest(config=config)

        # bytes/sec → Mbps に変換する
        download_mbps = result["download_bps"] / 1_000_000
        upload_mbps = result["upload_bps"] / 1_000_000

        logger.info(
            "計測結果: DL=%.2f Mbps, UL=%.2f Mbps, Ping=%.1f ms, Jitter=%.1f ms",
            download_mbps,
            upload_mbps,
            result["ping_ms"],
            result["jitter_ms"],
        )

        # 快適度スコアを算出する
        comfort_score = calculate_comfort_score(
            download_mbps=download_mbps,
            upload_mbps=upload_mbps,
            ping_ms=result["ping_ms"],
            jitter_ms=result["jitter_ms"],
            config=config,
        )
        logger.info("快適度スコア: %.1f", comfort_score)

        # データベースに保存する
        measurement_data = {
            "measured_at": result["timestamp"],
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "ping_ms": result["ping_ms"],
            "jitter_ms": result["jitter_ms"],
            "comfort_score": comfort_score,
            "server_id": result.get("server_id"),
            "server_name": result.get("server_name"),
            "isp": result.get("isp"),
            "result_url": result.get("result_url"),
            "raw_json": result.get("raw_json"),
        }
        row_id = save_measurement(measurement_data, config=config)
        logger.info("計測結果を保存した (id=%d)", row_id)

    except SpeedtestError as e:
        # 計測失敗をエラーとして記録する
        logger.error("計測に失敗した: %s", e)
        error_id = save_error(str(e), config=config)
        logger.info("エラーを記録した (id=%d)", error_id)
        sys.exit(1)

    except Exception as e:
        # 予期しないエラー
        logger.exception("予期しないエラーが発生した: %s", e)
        try:
            save_error(f"予期しないエラー: {e}", config=config)
        except Exception:
            logger.exception("エラーの記録にも失敗した")
        sys.exit(2)

    logger.info("=== 速度計測が完了した ===")


if __name__ == "__main__":
    main()
