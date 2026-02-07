"""可視化モジュール — ヒートマップ + 折れ線グラフ生成.

時間帯ごとの快適度ヒートマップ（上段）と
直近24時間の download/ping 推移折れ線グラフ（下段）を
1枚の複合画像として出力する。
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib

# 非対話バックエンドを先に設定する（pyplot import 前が必須）
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from .config import load_config, get_assets_dir
from .storage import get_hourly_averages, get_recent_measurements

logger = logging.getLogger(__name__)

def _setup_japanese_font() -> None:
    """日本語フォントを自動設定する.

    macOS: Hiragino Sans
    Linux: Noto Sans CJK JP
    その他: デフォルトフォントにフォールバック
    """
    system = platform.system()
    if system == "Darwin":
        # macOS
        font_name = "Hiragino Sans"
    elif system == "Linux":
        # Linux
        font_name = "Noto Sans CJK JP"
    else:
        logger.warning("日本語フォントの自動設定に非対応のOS: %s", system)
        return

    matplotlib.rcParams["font.family"] = font_name
    # マイナス記号の文字化け対策
    matplotlib.rcParams["axes.unicode_minus"] = False
    logger.info("日本語フォントを設定した: %s", font_name)


def _build_heatmap_data(
    averages: list[dict],
    open_hour: int,
    close_hour: int,
    days_of_week: list[str],
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """集計データからヒートマップ用の2次元配列を構築する.

    Args:
        averages: get_hourly_averages() の戻り値
        open_hour: 開館時間
        close_hour: 閉館時間
        days_of_week: 曜日ラベルのリスト

    Returns:
        (data, mask, x_labels, y_labels) のタプル
        - data: スコアの2次元配列（行=曜日、列=時間帯）
        - mask: データ欠損セルの真偽値マスク
        - x_labels: 時間帯ラベル
        - y_labels: 曜日ラベル
    """
    hours = list(range(open_hour, close_hour))
    n_days = len(days_of_week)
    n_hours = len(hours)

    # NaN で初期化（データ欠損を表す）
    data = np.full((n_days, n_hours), np.nan)

    # 集計データを配列に埋める
    for entry in averages:
        day_idx = entry["day_of_week"]  # 0=月〜6=日
        hour_idx = entry["hour"] - open_hour
        if 0 <= day_idx < n_days and 0 <= hour_idx < n_hours:
            data[day_idx, hour_idx] = entry["avg_score"]

    # NaN のセルをマスクとする（グレー表示用）
    mask = np.isnan(data)

    # ラベル作成
    x_labels = [f"{h}時" for h in hours]
    y_labels = days_of_week

    logger.info(
        "ヒートマップデータを構築した: %d×%d（欠損: %d セル）",
        n_days,
        n_hours,
        int(mask.sum()),
    )

    return data, mask, x_labels, y_labels


def _build_annotation(data: np.ndarray, mask: np.ndarray) -> list[list[str]]:
    """ヒートマップのアノテーション文字列を構築する.

    データ有りのセルはスコア値、欠損セルは "-" を表示する。

    Args:
        data: スコアの2次元配列
        mask: 欠損マスク

    Returns:
        アノテーション文字列の2次元リスト
    """
    annot = []
    for i in range(data.shape[0]):
        row = []
        for j in range(data.shape[1]):
            if mask[i, j]:
                row.append("-")
            else:
                row.append(f"{data[i, j]:.0f}")
        annot.append(row)
    return annot


def generate_heatmap(
    output_path: str | Path | None = None,
    days: int = 28,
    config: dict | None = None,
    db_path: Path | None = None,
) -> Path:
    """ヒートマップ + 折れ線グラフの複合画像を生成する.

    上段: 開館時間帯（9-21時台）の快適度ヒートマップ（曜日×時間帯）
    下段: 直近24時間の download(Mbps) と ping(ms) の推移（2軸グラフ）

    Args:
        output_path: 出力ファイルパス（省略時は assets/YYYY-MM-DD.png）
        days: ヒートマップの集計対象日数（デフォルト28日）
        config: 設定辞書
        db_path: データベースファイルのパス

    Returns:
        出力ファイルの絶対パス
    """
    if config is None:
        config = load_config()

    viz_config = config["visualization"]
    cafe_config = config["cafe"]
    open_hour = cafe_config["open_hour"]
    close_hour = cafe_config["close_hour"]
    days_of_week = viz_config["days_of_week"]
    colormap = viz_config["colormap"]
    dpi = viz_config["dpi"]

    # 日本語フォントを設定する
    _setup_japanese_font()

    # 出力パスの決定
    if output_path is None:
        assets_dir = get_assets_dir(config)
        assets_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        output_path = assets_dir / f"{today}.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("レポート画像を生成する: %s", output_path)

    # データ取得
    averages = get_hourly_averages(
        days=days,
        open_hour=open_hour,
        close_hour=close_hour,
        db_path=db_path,
        config=config,
    )
    recent = get_recent_measurements(hours=24, db_path=db_path, config=config)

    # 複合画像を作成する（上段: ヒートマップ、下段: 折れ線グラフ）
    fig, axes = plt.subplots(
        2, 1,
        figsize=(14, 10),
        gridspec_kw={"height_ratios": [3, 2]},
    )

    # === 上段: ヒートマップ ===
    ax_heatmap = axes[0]

    data, mask, x_labels, y_labels = _build_heatmap_data(
        averages, open_hour, close_hour, days_of_week
    )
    annot = _build_annotation(data, mask)

    # 欠損セルをグレーで表示するため、背景色を設定する
    ax_heatmap.set_facecolor("#cccccc")

    sns.heatmap(
        data,
        ax=ax_heatmap,
        mask=mask,
        cmap=colormap,
        vmin=0,
        vmax=100,
        annot=np.array(annot),
        fmt="",
        linewidths=0.5,
        linecolor="white",
        xticklabels=x_labels,
        yticklabels=y_labels,
        cbar_kws={"label": "快適度スコア (0-100)"},
    )

    ax_heatmap.set_title(
        f"時間帯別 快適度ヒートマップ（過去{days}日間）",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_heatmap.set_xlabel("時間帯")
    ax_heatmap.set_ylabel("曜日")

    # === 下段: 折れ線グラフ（2軸）===
    ax_download = axes[1]

    if recent:
        # 日時文字列をパースする
        times = [datetime.fromisoformat(r["measured_at"]) for r in recent]
        downloads = [r["download_mbps"] for r in recent]
        pings = [r["ping_ms"] for r in recent]

        # ダウンロード速度（左軸）
        color_dl = "#2196F3"
        ax_download.plot(
            times, downloads,
            color=color_dl,
            marker="o",
            markersize=3,
            linewidth=1.5,
            label="Download (Mbps)",
        )
        ax_download.set_ylabel("Download (Mbps)", color=color_dl)
        ax_download.tick_params(axis="y", labelcolor=color_dl)
        ax_download.set_ylim(bottom=0)

        # Ping（右軸）
        ax_ping = ax_download.twinx()
        color_ping = "#FF5722"
        ax_ping.plot(
            times, pings,
            color=color_ping,
            marker="s",
            markersize=3,
            linewidth=1.5,
            label="Ping (ms)",
        )
        ax_ping.set_ylabel("Ping (ms)", color=color_ping)
        ax_ping.tick_params(axis="y", labelcolor=color_ping)
        ax_ping.set_ylim(bottom=0)

        # X軸のフォーマット
        ax_download.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax_download.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        fig.autofmt_xdate(rotation=45)

        # 凡例を統合する
        lines_dl, labels_dl = ax_download.get_legend_handles_labels()
        lines_ping, labels_ping = ax_ping.get_legend_handles_labels()
        ax_download.legend(
            lines_dl + lines_ping,
            labels_dl + labels_ping,
            loc="upper right",
        )
    else:
        # データがない場合のメッセージ
        ax_download.text(
            0.5, 0.5,
            "直近24時間のデータなし",
            transform=ax_download.transAxes,
            ha="center",
            va="center",
            fontsize=14,
            color="gray",
        )
        ax_download.set_yticks([])
        ax_download.set_xticks([])

    ax_download.set_title(
        "直近24時間の速度推移",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_download.set_xlabel("時刻")

    # レイアウト調整
    plt.tight_layout()

    # 保存
    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    logger.info("レポート画像を保存した: %s", output_path)
    return output_path
