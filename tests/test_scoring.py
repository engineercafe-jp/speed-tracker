"""src/scoring.py のテスト."""

import pytest

from src.config import load_config
from src.scoring import calculate_comfort_score, get_comfort_label


@pytest.fixture
def config():
    """テスト用設定を返す."""
    return load_config()


class TestCalculateComfortScore:
    """calculate_comfort_score のテストケース."""

    def test_perfect_score(self, config):
        """全指標が最良の場合、100点になる."""
        score = calculate_comfort_score(
            download_mbps=100.0,
            upload_mbps=50.0,
            ping_ms=0.0,
            jitter_ms=0.0,
            config=config,
        )
        assert score == 100.0

    def test_worst_score(self, config):
        """全指標が最悪の場合、0点になる."""
        score = calculate_comfort_score(
            download_mbps=0.0,
            upload_mbps=0.0,
            ping_ms=100.0,
            jitter_ms=50.0,
            config=config,
        )
        assert score == 0.0

    def test_above_threshold_caps_at_max(self, config):
        """閾値を超える download/upload はスコアが 1.0 にクリップされる."""
        score = calculate_comfort_score(
            download_mbps=200.0,  # 閾値100の2倍
            upload_mbps=100.0,  # 閾値50の2倍
            ping_ms=0.0,
            jitter_ms=0.0,
            config=config,
        )
        assert score == 100.0

    def test_mid_range_score(self, config):
        """中間的な値で妥当なスコアが算出される."""
        score = calculate_comfort_score(
            download_mbps=50.0,  # 50/100 = 0.5
            upload_mbps=25.0,  # 25/50 = 0.5
            ping_ms=50.0,  # 1 - 50/100 = 0.5
            jitter_ms=25.0,  # 1 - 25/50 = 0.5
            config=config,
        )
        # 全指標 0.5 × 合計重み 1.0 × 100 = 50.0
        assert score == 50.0

    def test_download_only_contribution(self, config):
        """download のみ満点、他は 0 の場合のスコアを確認する."""
        score = calculate_comfort_score(
            download_mbps=100.0,
            upload_mbps=0.0,
            ping_ms=100.0,
            jitter_ms=50.0,
            config=config,
        )
        # download の重み (0.35) × 1.0 × 100 = 35.0
        assert score == 35.0

    def test_ping_only_contribution(self, config):
        """ping のみ満点、他は 0 の場合のスコアを確認する."""
        score = calculate_comfort_score(
            download_mbps=0.0,
            upload_mbps=0.0,
            ping_ms=0.0,  # 最良
            jitter_ms=50.0,  # 最悪
            config=config,
        )
        # ping の重み (0.30) × 1.0 × 100 = 30.0
        assert score == 30.0

    def test_negative_ping_clips_to_zero(self, config):
        """ping が閾値を大幅に超えてもスコアが負にならない."""
        score = calculate_comfort_score(
            download_mbps=0.0,
            upload_mbps=0.0,
            ping_ms=500.0,  # 閾値100の5倍
            jitter_ms=200.0,  # 閾値50の4倍
            config=config,
        )
        assert score == 0.0

    def test_result_is_rounded(self, config):
        """スコアが小数第1位に丸められる."""
        score = calculate_comfort_score(
            download_mbps=33.3,
            upload_mbps=16.7,
            ping_ms=33.3,
            jitter_ms=16.7,
            config=config,
        )
        # 結果が小数第1位であることを確認
        assert score == round(score, 1)


class TestGetComfortLabel:
    """get_comfort_label のテストケース."""

    def test_very_comfortable(self, config):
        """90〜100 は '非常に快適' を返す."""
        assert get_comfort_label(95.0, config) == "非常に快適"
        assert get_comfort_label(90.0, config) == "非常に快適"
        assert get_comfort_label(100.0, config) == "非常に快適"

    def test_comfortable(self, config):
        """70〜89 は '快適' を返す."""
        assert get_comfort_label(80.0, config) == "快適"
        assert get_comfort_label(70.0, config) == "快適"
        assert get_comfort_label(89.0, config) == "快適"

    def test_somewhat_unstable(self, config):
        """50〜69 は 'やや不安定' を返す."""
        assert get_comfort_label(60.0, config) == "やや不安定"
        assert get_comfort_label(50.0, config) == "やや不安定"
        assert get_comfort_label(69.0, config) == "やや不安定"

    def test_uncomfortable(self, config):
        """0〜49 は '不快' を返す."""
        assert get_comfort_label(30.0, config) == "不快"
        assert get_comfort_label(0.0, config) == "不快"
        assert get_comfort_label(49.0, config) == "不快"

    def test_boundary_values(self, config):
        """境界値でのラベルを確認する."""
        assert get_comfort_label(89.0, config) == "快適"
        assert get_comfort_label(90.0, config) == "非常に快適"
        assert get_comfort_label(69.0, config) == "やや不安定"
        assert get_comfort_label(70.0, config) == "快適"
        assert get_comfort_label(49.0, config) == "不快"
        assert get_comfort_label(50.0, config) == "やや不安定"

    def test_decimal_boundaries(self, config):
        """小数境界値が正しく分類される."""
        assert get_comfort_label(89.9, config) == "快適"
        assert get_comfort_label(69.9, config) == "やや不安定"
        assert get_comfort_label(49.9, config) == "不快"

    def test_out_of_range_values_are_clamped(self, config):
        """0-100 範囲外の値は丸めて分類される."""
        assert get_comfort_label(120.0, config) == "非常に快適"
        assert get_comfort_label(-5.0, config) == "不快"
