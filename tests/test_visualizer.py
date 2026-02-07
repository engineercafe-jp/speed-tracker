"""src/visualizer.py のテスト.

実際の画像生成を行い、ファイルが正しく出力されることを検証する。
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.config import load_config
from src.storage import init_db, save_measurement
from src.visualizer import (
    generate_heatmap,
    build_trend_summary_text,
    generate_trend_summary_file,
    _build_heatmap_data,
    _build_annotation,
)


@pytest.fixture
def config():
    """テスト用設定を返す."""
    return load_config()


@pytest.fixture
def db_path(tmp_path):
    """テスト用の一時データベースパスを返す."""
    return tmp_path / "test.db"


@pytest.fixture
def initialized_db(db_path, config):
    """初期化済みのデータベースパスを返す."""
    init_db(db_path=db_path, config=config)
    return db_path


def _insert_sample_data(db_path, config, days=7):
    """テスト用のサンプルデータを挿入するヘルパー.

    過去 N 日間、各開館時間帯に1件ずつデータを挿入する。
    """
    now = datetime.utcnow()
    for day_offset in range(days):
        dt = now - timedelta(days=day_offset)
        for hour in range(9, 22):
            measured_at = dt.replace(hour=hour, minute=0, second=0).isoformat()
            # 時間帯によって少しスコアを変動させる
            score = 60.0 + (hour - 9) * 3.0 + day_offset * 0.5
            score = min(score, 100.0)
            data = {
                "measured_at": measured_at,
                "download_mbps": 50.0 + hour,
                "upload_mbps": 25.0 + hour * 0.5,
                "ping_ms": 20.0 - hour * 0.3,
                "jitter_ms": 5.0,
                "comfort_score": score,
            }
            save_measurement(data, db_path=db_path, config=config)


class TestBuildHeatmapData:
    """_build_heatmap_data のテストケース."""

    def test_empty_data(self, config):
        """データなしの場合、全セルが NaN になる."""
        data, mask, x_labels, y_labels = _build_heatmap_data(
            averages=[],
            open_hour=9,
            close_hour=22,
            days_of_week=config["visualization"]["days_of_week"],
        )
        assert data.shape == (7, 13)  # 7曜日 × 13時間帯(9-21)
        assert mask.all()  # 全セルが欠損

    def test_with_data(self, config):
        """データがある場合、該当セルに値が入る."""
        averages = [
            {"day_of_week": 0, "hour": 10, "avg_score": 85.0, "count": 5},
            {"day_of_week": 4, "hour": 15, "avg_score": 72.0, "count": 3},
        ]
        data, mask, x_labels, y_labels = _build_heatmap_data(
            averages=averages,
            open_hour=9,
            close_hour=22,
            days_of_week=config["visualization"]["days_of_week"],
        )
        # 月曜 10時 (行0, 列1)
        assert data[0, 1] == 85.0
        assert not mask[0, 1]
        # 金曜 15時 (行4, 列6)
        assert data[4, 6] == 72.0
        assert not mask[4, 6]
        # それ以外は欠損
        assert mask[0, 0]  # 月曜9時

    def test_labels(self, config):
        """ラベルが正しく生成される."""
        _, _, x_labels, y_labels = _build_heatmap_data(
            averages=[],
            open_hour=9,
            close_hour=22,
            days_of_week=config["visualization"]["days_of_week"],
        )
        assert x_labels[0] == "9時"
        assert x_labels[-1] == "21時"
        assert len(x_labels) == 13
        assert y_labels == ["月", "火", "水", "木", "金", "土", "日"]


class TestBuildAnnotation:
    """_build_annotation のテストケース."""

    def test_with_data_and_missing(self):
        """データありと欠損のアノテーションを確認する."""
        data = np.array([[85.3, np.nan], [np.nan, 72.0]])
        mask = np.isnan(data)
        annot = _build_annotation(data, mask)
        assert annot[0][0] == "85"
        assert annot[0][1] == "-"
        assert annot[1][0] == "-"
        assert annot[1][1] == "72"


class TestGenerateHeatmap:
    """generate_heatmap のテストケース."""

    def test_generates_image_with_no_data(self, tmp_path, initialized_db, config):
        """データなしでも画像が生成される."""
        output = tmp_path / "test_output.png"
        result = generate_heatmap(
            output_path=output,
            days=28,
            config=config,
            db_path=initialized_db,
        )
        assert result == output
        assert output.exists()
        # PNG ファイルであることを確認（マジックバイト）
        with open(output, "rb") as f:
            assert f.read(4) == b"\x89PNG"

    def test_generates_image_with_data(self, tmp_path, initialized_db, config):
        """データありで画像が正しく生成される."""
        _insert_sample_data(initialized_db, config, days=3)

        output = tmp_path / "test_with_data.png"
        result = generate_heatmap(
            output_path=output,
            days=28,
            config=config,
            db_path=initialized_db,
        )
        assert result == output
        assert output.exists()
        # ファイルサイズが適切であることを確認（空画像より大きい）
        assert output.stat().st_size > 1000

    def test_default_output_path(self, initialized_db, config, tmp_path):
        """出力パス省略時に assets/YYYY-MM-DD.png が生成される."""
        config["visualization"]["assets_dir"] = str(tmp_path / "assets")
        result = generate_heatmap(
            config=config,
            db_path=initialized_db,
        )
        today = datetime.now().strftime("%Y-%m-%d")
        assert result.name == f"{today}.png"
        assert result.exists()

    def test_creates_output_directory(self, tmp_path, initialized_db, config):
        """出力ディレクトリが存在しない場合に自動作成される."""
        output = tmp_path / "nested" / "dir" / "output.png"
        result = generate_heatmap(
            output_path=output,
            config=config,
            db_path=initialized_db,
        )
        assert result.exists()

    def test_embeds_custom_summary_text(self, tmp_path, initialized_db, config):
        """カスタムサマリ文字列を指定しても画像生成できる."""
        output = tmp_path / "with_summary.png"
        result = generate_heatmap(
            output_path=output,
            summary_text="テストサマリ\n2行目",
            config=config,
            db_path=initialized_db,
        )
        assert result.exists()

    def test_hourly_default_output_path(self, initialized_db, config, tmp_path):
        """hourly 指定時に YYYY-MM-DD_HH00.png が生成される."""
        config["visualization"]["assets_dir"] = str(tmp_path / "assets")
        result = generate_heatmap(
            filename_granularity="hourly",
            config=config,
            db_path=initialized_db,
        )
        assert result.exists()
        # 例: 2026-02-07_1400.png
        assert len(result.stem.split("_")) == 2
        assert result.name.endswith("00.png")


class TestTrendSummary:
    """傾向サマリ生成のテストケース."""

    def test_build_summary_with_data(self, initialized_db, config):
        """データありの場合にサマリ文字列が生成される."""
        _insert_sample_data(initialized_db, config, days=3)
        summary = build_trend_summary_text(
            days=7,
            config=config,
            db_path=initialized_db,
        )
        assert "快適度トレンドサマリ" in summary
        assert "観測カバレッジ" in summary
        assert "良好な時間帯" in summary

    def test_generate_summary_file(self, tmp_path, initialized_db, config):
        """サマリファイルを生成できる."""
        _insert_sample_data(initialized_db, config, days=2)
        summary_path = tmp_path / "report_summary.txt"
        result = generate_trend_summary_file(
            summary_path=summary_path,
            days=7,
            config=config,
            db_path=initialized_db,
        )
        assert result == summary_path
        assert result.exists()
        assert "観測カバレッジ" in result.read_text(encoding="utf-8")
