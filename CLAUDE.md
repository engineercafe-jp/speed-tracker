# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

エンジニアカフェのネットワーク回線速度を継続的に監視し、時間帯ごとの快適度をヒートマップ画像で可視化するツールである。Ookla Speedtest CLI で計測し、SQLite に保存、matplotlib/seaborn で可視化する。

## Language & Style Rules

- 回答とmarkdownドキュメントは日本語の常体（だ・である調）で記述する
- docstring・コメント・ログは多めに記載する
- Conventional Commits を使用する（例: `feat: add speed sampling script`）

## Tech Stack

- Python 3.12（`uv` で管理、`.venv` 内で実行）
- Ookla Speedtest CLI（`brew tap teamookla/speedtest && brew install teamookla/speedtest/speedtest`）
- SQLite（データ保存）、matplotlib + seaborn（可視化）、PyYAML（設定）
- pytest（テスト）

## Project Layout

- `src/` — アプリケーションコード
  - `config.py` — config.yaml 読み込み・デフォルト値管理
  - `collector.py` — Speedtest CLI ラッパー（計測・JSON パース・再試行）
  - `storage.py` — SQLite 操作（保存・集計クエリ・クリーンアップ）
  - `scoring.py` — 快適度スコア算出ロジック（0〜100）
  - `visualizer.py` — ヒートマップ + 折れ線グラフ生成
- `tests/` — テストコード（ソースのパス構造をミラーする）
- `scripts/` — 運用スクリプト（`run_speedtest.py`, `generate_report.py`）
- `assets/` — 生成されたレポート画像
- `config.yaml` — ユーザ設定（重み・閾値・開館時間等）
- `data/` — SQLite DB（.gitignore 対象）
- `logs/` — 実行ログ（.gitignore 対象）

## Commands

- `uv pip install -r requirements.txt` — 依存パッケージインストール
- `.venv/bin/python -m pytest tests/ -v` — テスト実行
- `.venv/bin/python scripts/run_speedtest.py` — 手動計測
- `.venv/bin/python scripts/generate_report.py` — レポート生成
