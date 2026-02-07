"""可視化モジュール — ヒートマップ + 折れ線グラフ生成.

時間帯ごとの快適度ヒートマップ（上段）と
直近24時間の download/ping 推移折れ線グラフ（下段）を
1枚の複合画像として出力する。
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime, timedelta, timezone
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


def _parse_iso_datetime(value: str) -> datetime:
    """ISO 8601 文字列を datetime に変換する.

    Speedtest の timestamp は末尾が `Z` の場合があるため、
    Python 標準で解釈可能な `+00:00` に置換して扱う。
    """
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    # aware/naive 混在を防ぐため、内部では UTC naive に正規化して扱う
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_iso_datetime_local(value: str) -> datetime:
    """ISO 8601 文字列をローカル時刻の naive datetime に変換する."""
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


def _filter_today_open_hours_measurements(
    measurements: list[dict],
    open_hour: int,
    close_hour: int,
) -> list[dict]:
    """計測データを当日開館時間内のデータに絞り込む."""
    today = datetime.now().date()
    filtered = []
    for row in measurements:
        measured = _parse_iso_datetime_local(row["measured_at"])
        if measured.date() != today:
            continue
        if open_hour <= measured.hour < close_hour:
            filtered.append(row)
    return filtered


def _resolve_output_path(
    config: dict,
    output_path: str | Path | None,
    filename_granularity: str,
) -> Path:
    """出力パスを決定する.

    Args:
        config: 設定辞書
        output_path: 明示指定パス
        filename_granularity: `daily` または `hourly`

    Returns:
        出力ファイルパス
    """
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    assets_dir = get_assets_dir(config)
    assets_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    if filename_granularity == "hourly":
        filename = f"{now.strftime('%Y-%m-%d_%H00')}.png"
    else:
        filename = f"{now.strftime('%Y-%m-%d')}.png"
    return assets_dir / filename


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
    filename_granularity: str = "daily",
    summary_text: str | None = None,
    config: dict | None = None,
    db_path: Path | None = None,
) -> Path:
    """ヒートマップ + 折れ線グラフの複合画像を生成する.

    上段: 開館時間帯（9-21時台）の快適度ヒートマップ（曜日×時間帯）
    下段: 直近24時間の download(Mbps) と ping(ms) の推移（2軸グラフ）

    Args:
        output_path: 出力ファイルパス（省略時は assets/YYYY-MM-DD.png）
        days: ヒートマップの集計対象日数（デフォルト28日）
        filename_granularity: デフォルト出力名の粒度（`daily`/`hourly`）
        summary_text: 画像に埋め込む傾向サマリ文字列（省略時は自動生成）
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
    output_path = _resolve_output_path(config, output_path, filename_granularity)

    logger.info("レポート画像を生成する: %s", output_path)

    # データ取得
    averages = get_hourly_averages(
        days=days,
        open_hour=open_hour,
        close_hour=close_hour,
        db_path=db_path,
        config=config,
    )
    # 開館時間内の推移を描くため、前日分も含む範囲で取得して当日分に絞り込む
    recent_candidates = get_recent_measurements(hours=48, db_path=db_path, config=config)
    recent = _filter_today_open_hours_measurements(
        measurements=recent_candidates,
        open_hour=open_hour,
        close_hour=close_hour,
    )
    if summary_text is None:
        summary_text = build_trend_summary_text(days=days, config=config, db_path=db_path)

    # 複合画像を作成する（上段: ヒートマップ、中段: 折れ線、下段: サマリ）
    fig, axes = plt.subplots(
        3, 1,
        figsize=(14, 12),
        gridspec_kw={"height_ratios": [3, 2, 1.2]},
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

    # === 下段: 折れ線グラフ（2軸、当日開館時間）===
    ax_download = axes[1]

    if recent:
        # 日時文字列をパースする
        times = [_parse_iso_datetime_local(r["measured_at"]) for r in recent]
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
        day_start = datetime.now().replace(
            hour=open_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        day_end = datetime.now().replace(
            hour=close_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        ax_download.set_xlim(day_start, day_end)
        ax_download.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        ax_download.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        fig.autofmt_xdate(rotation=0)

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
            "本日開館時間のデータなし",
            transform=ax_download.transAxes,
            ha="center",
            va="center",
            fontsize=14,
            color="gray",
        )
        ax_download.set_yticks([])
        ax_download.set_xticks([])

    ax_download.set_title(
        f"本日開館時間（{open_hour}:00-{close_hour}:00）の速度推移",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax_download.set_xlabel("時刻")

    # === 下段: テキストサマリ ===
    ax_summary = axes[2]
    ax_summary.axis("off")
    score_guide = build_score_explanation_text(config=config)

    # 左側: 傾向サマリ
    ax_summary.text(
        0.01,
        0.98,
        summary_text,
        transform=ax_summary.transAxes,
        va="top",
        ha="left",
        fontsize=10,
        linespacing=1.5,
        bbox={"facecolor": "#f5f5f5", "edgecolor": "#dddddd", "boxstyle": "round,pad=0.4"},
    )
    # 右側: 快適度スコア説明
    ax_summary.text(
        0.56,
        0.98,
        score_guide,
        transform=ax_summary.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        linespacing=1.4,
        bbox={"facecolor": "#eef6ff", "edgecolor": "#cfe3ff", "boxstyle": "round,pad=0.4"},
    )

    # レイアウト調整
    plt.tight_layout()

    # 保存
    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    logger.info("レポート画像を保存した: %s", output_path)
    return output_path


def build_trend_summary_text(
    days: int = 28,
    config: dict | None = None,
    db_path: Path | None = None,
) -> str:
    """過去データから傾向サマリを生成する.

    欠損があっても要約できるよう、取得できたデータだけで集計する。
    """
    if config is None:
        config = load_config()

    cafe_config = config["cafe"]
    open_hour = cafe_config["open_hour"]
    close_hour = cafe_config["close_hour"]
    days_of_week = config["visualization"]["days_of_week"]

    averages = get_hourly_averages(
        days=days,
        open_hour=open_hour,
        close_hour=close_hour,
        db_path=db_path,
        config=config,
    )
    recent_48h = get_recent_measurements(hours=48, db_path=db_path, config=config)

    total_slots = len(days_of_week) * (close_hour - open_hour)
    observed_slots = len(averages)
    coverage = (observed_slots / total_slots * 100.0) if total_slots > 0 else 0.0

    values_24h: list[float] = []
    values_prev24h: list[float] = []
    parsed_rows: list[tuple[datetime, float]] = []
    for row in recent_48h:
        score = row.get("comfort_score")
        if score is None:
            continue
        measured = _parse_iso_datetime(row["measured_at"])
        parsed_rows.append((measured, score))

    if parsed_rows:
        reference_time = max(measured for measured, _ in parsed_rows)
    else:
        reference_time = datetime.utcnow()
    cutoff = reference_time - timedelta(hours=24)

    for measured, score in parsed_rows:
        if measured >= cutoff:
            values_24h.append(score)
        else:
            values_prev24h.append(score)

    by_hour: dict[int, list[float]] = {}
    for entry in averages:
        by_hour.setdefault(entry["hour"], []).append(entry["avg_score"])

    best_hour_text = "データ不足"
    worst_hour_text = "データ不足"
    if by_hour:
        hour_avg = {
            hour: sum(scores) / len(scores)
            for hour, scores in by_hour.items()
        }
        best_hour, best_score = max(hour_avg.items(), key=lambda item: item[1])
        worst_hour, worst_score = min(hour_avg.items(), key=lambda item: item[1])
        best_hour_text = f"{best_hour}時台（平均 {best_score:.1f}）"
        worst_hour_text = f"{worst_hour}時台（平均 {worst_score:.1f}）"

    delta_text = "比較データ不足"
    if values_24h and values_prev24h:
        avg_24 = sum(values_24h) / len(values_24h)
        avg_prev = sum(values_prev24h) / len(values_prev24h)
        delta = avg_24 - avg_prev
        trend = "改善" if delta >= 0 else "悪化"
        delta_text = f"{trend}（直近24h: {avg_24:.1f}, 前24h: {avg_prev:.1f}, 差分: {delta:+.1f}）"
    elif values_24h:
        avg_24 = sum(values_24h) / len(values_24h)
        delta_text = f"直近24h平均のみ算出（{avg_24:.1f}）"

    lines = [
        f"快適度トレンドサマリ（生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        f"対象期間: 過去{days}日 / 開館時間 {open_hour}:00-{close_hour}:00",
        f"観測カバレッジ: {observed_slots}/{total_slots} スロット（{coverage:.1f}%）",
        f"良好な時間帯: {best_hour_text}",
        f"不安定な時間帯: {worst_hour_text}",
        f"短期トレンド: {delta_text}",
        "補足: 欠損データは除外して集計している。",
    ]
    return "\n".join(lines)


def build_score_explanation_text(config: dict | None = None) -> str:
    """快適度スコアの見方を説明するテキストを返す."""
    if config is None:
        config = load_config()

    scoring = config["scoring"]
    weights = scoring["weights"]
    labels = scoring["labels"]

    lines = [
        "快適度スコアの見方",
        "・0-100点（高いほど快適）",
        (
            "・重み: DL {dl:.0f}% / UL {ul:.0f}% / Ping {ping:.0f}% / Jitter {jitter:.0f}%".format(
                dl=weights["download"] * 100,
                ul=weights["upload"] * 100,
                ping=weights["ping"] * 100,
                jitter=weights["jitter"] * 100,
            )
        ),
        "・評価帯:",
    ]
    for entry in sorted(labels, key=lambda x: x["min"], reverse=True):
        lines.append(f"  {entry['min']}-{entry['max']}: {entry['label']}")
    return "\n".join(lines)


def generate_trend_summary_file(
    summary_path: str | Path | None = None,
    days: int = 28,
    filename_granularity: str = "daily",
    summary_text: str | None = None,
    config: dict | None = None,
    db_path: Path | None = None,
) -> Path:
    """傾向サマリのテキストファイルを出力する."""
    if config is None:
        config = load_config()

    if summary_path is None:
        image_path = _resolve_output_path(
            config=config,
            output_path=None,
            filename_granularity=filename_granularity,
        )
        summary = image_path.with_name(f"{image_path.stem}_summary.txt")
    else:
        summary = Path(summary_path)
    summary.parent.mkdir(parents=True, exist_ok=True)

    content = summary_text or build_trend_summary_text(days=days, config=config, db_path=db_path)
    summary.write_text(content, encoding="utf-8")
    logger.info("傾向サマリを保存した: %s", summary)
    return summary
