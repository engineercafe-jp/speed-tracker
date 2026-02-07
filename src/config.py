"""設定ファイル（config.yaml）の読み込みとデフォルト値管理.

環境変数 ST_CONFIG_PATH でパスをオーバーライドできる。
ファイルが存在しない場合はデフォルト値を返す。
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from copy import deepcopy

import yaml

logger = logging.getLogger(__name__)

# プロジェクトルートディレクトリ（src/ の親）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# デフォルト設定値
# config.yaml が存在しない場合や、キーが欠落している場合に使用される
DEFAULT_CONFIG: dict = {
    "cafe": {
        "open_hour": 9,
        "close_hour": 22,
    },
    "speedtest": {
        "command": "speedtest",
        "timeout_sec": 120,
        "retry_count": 3,
        "retry_wait_sec": 10,
    },
    "schedule": {
        "interval_minutes": 15,
    },
    "storage": {
        "db_path": "data/speedtest.db",
        "retention_days": 90,
    },
    "scoring": {
        "weights": {
            "download": 0.35,
            "upload": 0.20,
            "ping": 0.30,
            "jitter": 0.15,
        },
        "thresholds": {
            "download_max_mbps": 100,
            "upload_max_mbps": 50,
            "ping_max_ms": 100,
            "jitter_max_ms": 50,
        },
        "labels": [
            {"min": 90, "max": 100, "label": "非常に快適"},
            {"min": 70, "max": 89, "label": "快適"},
            {"min": 50, "max": 69, "label": "やや不安定"},
            {"min": 0, "max": 49, "label": "不快"},
        ],
    },
    "visualization": {
        "colormap": "RdYlGn",
        "dpi": 150,
        "assets_dir": "assets",
        "days_of_week": ["月", "火", "水", "木", "金", "土", "日"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """base の辞書に override を再帰的にマージする.

    override に存在するキーは base の値を上書きする。
    base にのみ存在するキーはそのまま保持される。

    Args:
        base: ベースとなる辞書（デフォルト値）
        override: 上書きする辞書（ユーザ設定）

    Returns:
        マージされた新しい辞書
    """
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            # 両方が辞書の場合は再帰的にマージ
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config(path: str | None = None) -> dict:
    """設定ファイルを読み込み、デフォルト値とマージして返す.

    読み込み優先順位:
    1. 引数 path が指定された場合はそのパス
    2. 環境変数 ST_CONFIG_PATH が設定されている場合はそのパス
    3. プロジェクトルートの config.yaml

    ファイルが存在しない場合はデフォルト値のみを返す。

    Args:
        path: 設定ファイルのパス（省略可）

    Returns:
        マージ済みの設定辞書
    """
    # 設定ファイルパスの決定
    if path is not None:
        config_path = Path(path)
    elif os.environ.get("ST_CONFIG_PATH"):
        config_path = Path(os.environ["ST_CONFIG_PATH"])
    else:
        config_path = PROJECT_ROOT / "config.yaml"

    # ファイル読み込み
    if config_path.exists():
        logger.info("設定ファイルを読み込む: %s", config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        # デフォルト値とマージ
        return _deep_merge(DEFAULT_CONFIG, user_config)
    else:
        logger.warning(
            "設定ファイルが見つからない: %s — デフォルト値を使用する", config_path
        )
        return deepcopy(DEFAULT_CONFIG)


def get_db_path(config: dict | None = None) -> Path:
    """設定からデータベースの絶対パスを取得する.

    相対パスの場合はプロジェクトルートからの相対パスとして解決する。

    Args:
        config: 設定辞書（省略時は load_config() で読み込む）

    Returns:
        データベースファイルの絶対パス
    """
    if config is None:
        config = load_config()
    db_path = Path(config["storage"]["db_path"])
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def get_assets_dir(config: dict | None = None) -> Path:
    """設定からアセット出力ディレクトリの絶対パスを取得する.

    相対パスの場合はプロジェクトルートからの相対パスとして解決する。

    Args:
        config: 設定辞書（省略時は load_config() で読み込む）

    Returns:
        アセットディレクトリの絶対パス
    """
    if config is None:
        config = load_config()
    assets_dir = Path(config["visualization"]["assets_dir"])
    if not assets_dir.is_absolute():
        assets_dir = PROJECT_ROOT / assets_dir
    return assets_dir
