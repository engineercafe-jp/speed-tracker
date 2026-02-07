# Repository Guidelines

## プロジェクト構成
このリポジトリは、エンジニアカフェ開館時間（`9:00-22:00`）の回線品質を継続計測し、快適度を可視化するツールである。主要構成は以下である。
- `src/`: 本体ロジック（`collector.py`, `storage.py`, `scoring.py`, `visualizer.py`, `config.py`）
- `scripts/`: 実行エントリポイント（`run_speedtest.py`, `generate_report.py`）
- `tests/`: 単体テスト
- `config.yaml`: 運用設定（時間帯、重み、リトライ、保存期間）
- `data/`, `logs/`, `assets/`: DB、ログ、画像出力

## 開発・確認コマンド
- 環境作成: `uv venv --python 3.12`
- 依存導入: `uv pip install -r requirements.txt`
- 計測実行: `.venv/bin/python scripts/run_speedtest.py`
- レポート生成: `.venv/bin/python scripts/generate_report.py`
- テスト実行: `.venv/bin/python -m pytest tests/ -v`
- 補助: `make measure`, `make report`, `make test`

## コーディング規約
- `README.md` の指示に従い、回答と Markdown は日本語の常体（だ・である調）で記述する。
- 可読性を優先し、docstring・コメント・ログを十分に記載する。
- 命名は役割が分かる小文字スネークケースを基本とする。例: `run_speedtest.py`
- 文字コードは UTF-8 を使用し、インデントは言語ごとに統一する。

## テスト方針
- テストは `tests/` に配置し、対象モジュールに対応する命名とする。例: `test_scoring.py`
- 新機能には正常系と異常系のテストを最低 1 件ずつ追加する。
- 仕様変更時は境界値（特にスコア閾値・時刻条件）のテストを追加する。

## コミット・PR方針
- コミットメッセージは Conventional Commits を推奨する。例: `feat: add daily speed chart`
- 1コミット1目的を守り、レビューしやすい粒度に分割する。
- PRには概要、変更理由、確認手順、必要に応じて生成画像の添付を含める。

## 運用注意
- `cron` では相対パスを使わず、`cd` と絶対パスの実行ファイルを使う。
- 計測コマンドは Ookla CLI（`speedtest`）前提である。
- 欠測データがあってもレポート生成が落ちないことを維持する。

## セキュリティと設定
- APIキーやネットワーク固有情報などの秘匿情報はコミットしない。
- 環境依存設定は `.env` などのローカルファイルで管理し、必ず `.gitignore` に追加する。
