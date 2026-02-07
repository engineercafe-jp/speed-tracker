"""src/collector.py のテスト.

subprocess をモック化し、実際の Speedtest CLI を呼び出さずにテストする。
"""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.config import load_config
from src.collector import (
    run_speedtest,
    _parse_result,
    _resolve_speedtest_command,
    SpeedtestError,
    SpeedtestTimeoutError,
    SpeedtestParseError,
)


@pytest.fixture
def config():
    """テスト用設定を返す（再試行待機を短くする）."""
    cfg = load_config()
    cfg["speedtest"]["retry_wait_sec"] = 0  # テスト高速化のため待機なし
    cfg["speedtest"]["retry_count"] = 3
    return cfg


def _make_speedtest_output(
    download_bandwidth: int = 12500000,
    upload_bandwidth: int = 6250000,
    ping_latency: float = 15.0,
    ping_jitter: float = 3.0,
    server_id: int = 12345,
    server_name: str = "Test Server",
    isp: str = "Test ISP",
) -> str:
    """Speedtest CLI の JSON 出力をシミュレートするヘルパー.

    bandwidth は bytes/sec 単位である。
    12500000 bytes/sec = 100 Mbps
    6250000 bytes/sec = 50 Mbps
    """
    return json.dumps({
        "type": "result",
        "timestamp": "2026-02-01T10:00:00Z",
        "ping": {
            "jitter": ping_jitter,
            "latency": ping_latency,
        },
        "download": {
            "bandwidth": download_bandwidth,
            "bytes": 125000000,
            "elapsed": 10000,
        },
        "upload": {
            "bandwidth": upload_bandwidth,
            "bytes": 62500000,
            "elapsed": 10000,
        },
        "server": {
            "id": server_id,
            "name": server_name,
            "location": "Tokyo",
            "country": "Japan",
        },
        "isp": isp,
        "result": {
            "url": "https://www.speedtest.net/result/12345",
        },
    })


class TestParseResult:
    """_parse_result のテストケース."""

    def test_parses_valid_json(self):
        """正常な JSON を正しくパースする."""
        raw = _make_speedtest_output()
        result = _parse_result(raw)

        # bandwidth(bytes/sec) × 8 = bits/sec
        assert result["download_bps"] == 12500000 * 8  # 100 Mbps
        assert result["upload_bps"] == 6250000 * 8  # 50 Mbps
        assert result["ping_ms"] == 15.0
        assert result["jitter_ms"] == 3.0
        assert result["server_id"] == 12345
        assert result["server_name"] == "Test Server"
        assert result["isp"] == "Test ISP"
        assert result["result_url"] == "https://www.speedtest.net/result/12345"
        assert result["raw_json"] == raw

    def test_raises_on_invalid_json(self):
        """不正な JSON でパースエラーを送出する."""
        with pytest.raises(SpeedtestParseError, match="JSON パース"):
            _parse_result("not json")

    def test_raises_on_missing_fields(self):
        """必須フィールドが欠落している場合にエラーを送出する."""
        # download キーが欠落
        with pytest.raises(SpeedtestParseError, match="必須フィールド"):
            _parse_result('{"ping": {"latency": 10, "jitter": 1}}')

    def test_handles_missing_optional_fields(self):
        """オプショナルフィールドが欠落しても正常にパースされる."""
        raw = json.dumps({
            "ping": {"latency": 10.0, "jitter": 1.0},
            "download": {"bandwidth": 1000000},
            "upload": {"bandwidth": 500000},
        })
        result = _parse_result(raw)
        assert result["server_id"] is None
        assert result["server_name"] is None
        assert result["isp"] is None
        assert result["result_url"] is None


class TestRunSpeedtest:
    """run_speedtest のテストケース."""

    @patch("src.collector.subprocess.run")
    def test_successful_run(self, mock_run, config):
        """正常な計測結果を返す."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_speedtest_output(),
            stderr="",
        )

        result = run_speedtest(config=config)

        assert result["download_bps"] == 12500000 * 8
        assert result["ping_ms"] == 15.0
        mock_run.assert_called_once()

    @patch("src.collector.subprocess.run")
    def test_retries_on_failure(self, mock_run, config):
        """失敗時にリトライし、最終的に成功する."""
        # 1回目: 失敗、2回目: 成功
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="Network error"),
            MagicMock(
                returncode=0,
                stdout=_make_speedtest_output(),
                stderr="",
            ),
        ]

        result = run_speedtest(config=config)
        assert result["download_bps"] == 12500000 * 8
        assert mock_run.call_count == 2

    @patch("src.collector.subprocess.run")
    def test_raises_after_all_retries_fail(self, mock_run, config):
        """全リトライ失敗後にエラーを送出する."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Connection refused"
        )

        with pytest.raises(SpeedtestError):
            run_speedtest(config=config)
        assert mock_run.call_count == config["speedtest"]["retry_count"]

    @patch("src.collector.subprocess.run")
    def test_timeout_handling(self, mock_run, config):
        """タイムアウト時に SpeedtestTimeoutError を送出する."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="speedtest", timeout=120
        )

        with pytest.raises(SpeedtestTimeoutError):
            run_speedtest(config=config)

    @patch("src.collector.subprocess.run")
    def test_parse_error_no_retry(self, mock_run, config):
        """パースエラーはリトライせず即座に送出する."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not valid json",
            stderr="",
        )

        with pytest.raises(SpeedtestParseError):
            run_speedtest(config=config)
        # パースエラーはリトライしないため1回のみ
        assert mock_run.call_count == 1

    @patch("src.collector.subprocess.run")
    def test_command_from_config(self, mock_run, config):
        """設定からコマンドが正しく構築される."""
        config["speedtest"]["command"] = "/usr/local/bin/speedtest"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_speedtest_output(),
            stderr="",
        )

        run_speedtest(config=config)

        # 呼び出されたコマンドを確認する
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "/usr/local/bin/speedtest"
        assert "--format=json" in called_cmd


class TestResolveSpeedtestCommand:
    """_resolve_speedtest_command のテストケース."""

    @patch("src.collector.shutil.which")
    def test_resolve_from_path(self, mock_which):
        """PATH 上で見つかる場合はそのパスを返す."""
        mock_which.side_effect = lambda cmd: "/mock/bin/speedtest" if cmd == "speedtest" else None
        assert _resolve_speedtest_command("speedtest") == "/mock/bin/speedtest"

    @patch("src.collector.shutil.which")
    def test_resolve_from_fallback(self, mock_which):
        """PATH 上で見つからない場合に既知パスを利用する."""
        def which_side_effect(cmd):
            if cmd == "speedtest":
                return None
            if cmd == "/opt/homebrew/bin/speedtest":
                return "/opt/homebrew/bin/speedtest"
            return None

        mock_which.side_effect = which_side_effect
        assert _resolve_speedtest_command("speedtest") == "/opt/homebrew/bin/speedtest"

    def test_keep_explicit_path(self):
        """明示パス指定はそのまま返す."""
        assert _resolve_speedtest_command("/custom/speedtest") == "/custom/speedtest"
