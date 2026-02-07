"""src/storage.py のテスト."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.config import load_config
from src.storage import (
    init_db,
    save_measurement,
    save_error,
    get_hourly_averages,
    get_recent_measurements,
    cleanup_old_data,
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


def _make_measurement(
    measured_at: str | None = None,
    download_mbps: float = 80.0,
    upload_mbps: float = 40.0,
    ping_ms: float = 15.0,
    jitter_ms: float = 5.0,
    comfort_score: float = 85.0,
) -> dict:
    """テスト用の計測データを生成するヘルパー."""
    if measured_at is None:
        measured_at = datetime.utcnow().isoformat()
    return {
        "measured_at": measured_at,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "ping_ms": ping_ms,
        "jitter_ms": jitter_ms,
        "comfort_score": comfort_score,
        "server_id": 12345,
        "server_name": "Test Server",
        "isp": "Test ISP",
        "result_url": "https://www.speedtest.net/result/12345",
        "raw_json": '{"test": true}',
    }


class TestInitDb:
    """init_db のテストケース."""

    def test_creates_database_file(self, db_path, config):
        """データベースファイルが作成される."""
        init_db(db_path=db_path, config=config)
        assert db_path.exists()

    def test_creates_measurements_table(self, db_path, config):
        """measurements テーブルが作成される."""
        init_db(db_path=db_path, config=config)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='measurements'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent(self, db_path, config):
        """二重初期化してもエラーにならない."""
        init_db(db_path=db_path, config=config)
        init_db(db_path=db_path, config=config)
        assert db_path.exists()

    def test_creates_parent_directory(self, tmp_path, config):
        """親ディレクトリが存在しない場合でも作成される."""
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        init_db(db_path=nested_path, config=config)
        assert nested_path.exists()


class TestSaveMeasurement:
    """save_measurement のテストケース."""

    def test_saves_and_returns_id(self, initialized_db, config):
        """計測結果を保存し、行IDを返す."""
        data = _make_measurement()
        row_id = save_measurement(data, db_path=initialized_db, config=config)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_saved_data_is_correct(self, initialized_db, config):
        """保存されたデータが正しい値を持つ."""
        data = _make_measurement(download_mbps=95.5, ping_ms=12.3)
        row_id = save_measurement(data, db_path=initialized_db, config=config)

        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM measurements WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        conn.close()

        assert row["status"] == "ok"
        assert row["download_mbps"] == 95.5
        assert row["ping_ms"] == 12.3

    def test_multiple_saves(self, initialized_db, config):
        """複数回保存できる."""
        ids = []
        for i in range(5):
            data = _make_measurement(download_mbps=float(50 + i * 10))
            ids.append(save_measurement(data, db_path=initialized_db, config=config))
        assert len(set(ids)) == 5  # すべてユニークなID


class TestSaveError:
    """save_error のテストケース."""

    def test_saves_error_record(self, initialized_db, config):
        """エラー記録を保存する."""
        row_id = save_error(
            "Connection timed out",
            raw_output="stderr output",
            db_path=initialized_db,
            config=config,
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_error_status_is_set(self, initialized_db, config):
        """status が 'error' に設定される."""
        row_id = save_error(
            "Network error",
            db_path=initialized_db,
            config=config,
        )

        conn = sqlite3.connect(str(initialized_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM measurements WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        conn.close()

        assert row["status"] == "error"
        assert row["error_message"] == "Network error"
        assert row["download_mbps"] is None
        assert row["comfort_score"] is None


class TestGetHourlyAverages:
    """get_hourly_averages のテストケース."""

    def test_returns_empty_for_no_data(self, initialized_db, config):
        """データがない場合は空リストを返す."""
        result = get_hourly_averages(db_path=initialized_db, config=config)
        assert result == []

    def test_aggregates_by_hour_and_day(self, initialized_db, config):
        """時間帯×曜日で集計される."""
        # 月曜 10時台のデータを2件作成する
        # 2026-02-02 は月曜日
        save_measurement(
            _make_measurement(
                measured_at="2026-02-02T10:00:00",
                comfort_score=80.0,
            ),
            db_path=initialized_db,
            config=config,
        )
        save_measurement(
            _make_measurement(
                measured_at="2026-02-02T10:15:00",
                comfort_score=90.0,
            ),
            db_path=initialized_db,
            config=config,
        )

        result = get_hourly_averages(days=365, db_path=initialized_db, config=config)
        assert len(result) == 1
        assert result[0]["day_of_week"] == 0  # 月曜
        assert result[0]["hour"] == 10
        assert result[0]["avg_score"] == 85.0  # (80+90)/2
        assert result[0]["count"] == 2

    def test_excludes_outside_open_hours(self, initialized_db, config):
        """開館時間外のデータは除外される."""
        # 8時台（開館前）のデータ
        save_measurement(
            _make_measurement(measured_at="2026-02-02T08:00:00"),
            db_path=initialized_db,
            config=config,
        )
        # 22時台（閉館後）のデータ
        save_measurement(
            _make_measurement(measured_at="2026-02-02T22:30:00"),
            db_path=initialized_db,
            config=config,
        )

        result = get_hourly_averages(days=365, db_path=initialized_db, config=config)
        assert len(result) == 0

    def test_excludes_error_records(self, initialized_db, config):
        """エラーレコードは集計から除外される."""
        save_error("Network error", db_path=initialized_db, config=config)
        result = get_hourly_averages(db_path=initialized_db, config=config)
        assert len(result) == 0


class TestGetRecentMeasurements:
    """get_recent_measurements のテストケース."""

    def test_returns_empty_for_no_data(self, initialized_db, config):
        """データがない場合は空リストを返す."""
        result = get_recent_measurements(db_path=initialized_db, config=config)
        assert result == []

    def test_returns_recent_data(self, initialized_db, config):
        """直近のデータを返す."""
        now = datetime.utcnow()
        save_measurement(
            _make_measurement(measured_at=now.isoformat()),
            db_path=initialized_db,
            config=config,
        )
        result = get_recent_measurements(hours=1, db_path=initialized_db, config=config)
        assert len(result) == 1

    def test_excludes_old_data(self, initialized_db, config):
        """古いデータは含まれない."""
        old_time = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        save_measurement(
            _make_measurement(measured_at=old_time),
            db_path=initialized_db,
            config=config,
        )
        result = get_recent_measurements(hours=24, db_path=initialized_db, config=config)
        assert len(result) == 0

    def test_ordered_by_time(self, initialized_db, config):
        """計測日時の昇順で返される."""
        now = datetime.utcnow()
        times = [
            (now - timedelta(hours=2)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
            now.isoformat(),
        ]
        for t in times:
            save_measurement(
                _make_measurement(measured_at=t),
                db_path=initialized_db,
                config=config,
            )
        result = get_recent_measurements(hours=24, db_path=initialized_db, config=config)
        assert len(result) == 3
        assert result[0]["measured_at"] <= result[1]["measured_at"] <= result[2]["measured_at"]


class TestCleanupOldData:
    """cleanup_old_data のテストケース."""

    def test_deletes_old_records(self, initialized_db, config):
        """保存期間を超えたレコードが削除される."""
        # 100日前のデータ
        old_time = (datetime.utcnow() - timedelta(days=100)).isoformat()
        save_measurement(
            _make_measurement(measured_at=old_time),
            db_path=initialized_db,
            config=config,
        )
        # 最近のデータ
        save_measurement(
            _make_measurement(),
            db_path=initialized_db,
            config=config,
        )

        deleted = cleanup_old_data(
            retention_days=90, db_path=initialized_db, config=config
        )
        assert deleted == 1

        # 残っているのは最近のデータのみ
        result = get_recent_measurements(hours=24, db_path=initialized_db, config=config)
        assert len(result) == 1

    def test_keeps_recent_records(self, initialized_db, config):
        """保存期間内のレコードは削除されない."""
        save_measurement(
            _make_measurement(),
            db_path=initialized_db,
            config=config,
        )
        deleted = cleanup_old_data(
            retention_days=90, db_path=initialized_db, config=config
        )
        assert deleted == 0
