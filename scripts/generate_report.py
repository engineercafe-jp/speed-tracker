#!/usr/bin/env python3
"""レポート画像生成エントリポイント.

ヒートマップ + 折れ線グラフの複合画像を生成する。
cron から毎時実行される想定である。

使用例:
    python scripts/generate_report.py
    python scripts/generate_report.py --days 14
    python scripts/generate_report.py -o assets/custom.png
"""

import sys
import argparse
import logging
from pathlib import Path

# プロジェクトルートを sys.path に追加する（cron 実行時のため）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.storage import init_db
from src.visualizer import (
    build_trend_summary_text,
    generate_heatmap,
)


def _setup_logging() -> None:
    """ロギングを設定する."""
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


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする.

    Returns:
        パース結果の Namespace オブジェクト
    """
    parser = argparse.ArgumentParser(
        description="Speed Tracker レポート画像を生成する"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=28,
        help="ヒートマップの集計対象日数（デフォルト: 28）",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="出力ファイルパス（省略時: granularity に応じた自動命名）",
    )
    parser.add_argument(
        "--granularity",
        choices=["daily", "hourly"],
        default="hourly",
        help="デフォルト出力名の粒度（デフォルト: hourly）",
    )
    return parser.parse_args()


def main() -> None:
    """メイン処理: レポート画像を生成する."""
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== レポート生成を開始する ===")

    args = parse_args()
    config = load_config()

    # データベースを初期化する（テーブルが存在しない場合のみ作成）
    init_db(config=config)

    try:
        summary_text = build_trend_summary_text(days=args.days, config=config)
        output_path = generate_heatmap(
            output_path=args.output,
            days=args.days,
            filename_granularity=args.granularity,
            summary_text=summary_text,
            config=config,
        )
        logger.info("レポート画像を生成した: %s", output_path)
    except Exception as e:
        logger.exception("レポート生成に失敗した: %s", e)
        sys.exit(1)

    logger.info("=== レポート生成が完了した ===")


if __name__ == "__main__":
    main()
