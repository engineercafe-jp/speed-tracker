# Speed Tracker

## 概要

エンジニアカフェのネットワーク回線速度を継続的に監視し、**時間帯ごとの快適度**をヒートマップ画像で可視化するツールである。

開館時間（9:00〜22:00）内の各時間帯について、ダウンロード速度・アップロード速度・Ping・Jitter から算出した快適度スコア（0〜100）をヒートマップで表示する。

## 機能

- **速度計測**: Ookla Speedtest CLI による定期的な回線速度計測（再試行・タイムアウト対応）
- **データ保存**: SQLite によるローカル保存（90日間の保存期間）
- **快適度スコア**: 4指標の重み付けスコア（0〜100）
- **可視化**: 曜日×時間帯のヒートマップ + 直近24時間の速度推移グラフ

## セットアップ

### 前提条件

- Python 3.11 以上
- Ookla Speedtest CLI

### Ookla Speedtest CLI のインストール

```bash
# macOS (Homebrew)
brew tap teamookla/speedtest
brew install teamookla/speedtest/speedtest

# Linux (Debian/Ubuntu)
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
sudo apt install speedtest
```

インストール確認:

```bash
speedtest --version
```

### プロジェクトのセットアップ

```bash
git clone <repository-url>
cd speed-tracker
make install
```

## 使い方

### 手動計測

```bash
make measure
```

### レポート生成

```bash
# デフォルト（過去28日間）
make report

# 期間を指定
python scripts/generate_report.py --days 14

# 出力先を指定
python scripts/generate_report.py -o assets/custom.png
```

### テスト実行

```bash
make test
```

## cron 設定例

```bash
# 計測: 15分間隔、開館時間内（9:00-21:45）
*/15 9-21 * * * cd /path/to/speed-tracker && python scripts/run_speedtest.py >> logs/cron.log 2>&1

# レポート生成: 毎日22時（閉館時）に実行
0 22 * * * cd /path/to/speed-tracker && python scripts/generate_report.py >> logs/cron.log 2>&1

# データクリーンアップ: 毎月1日に90日超のデータを削除
0 3 1 * * cd /path/to/speed-tracker && python -c "from src.storage import cleanup_old_data; cleanup_old_data()" >> logs/cron.log 2>&1
```

## ディレクトリ構成

```
speed-tracker/
├── src/               # アプリケーションコード
│   ├── config.py      # 設定読み込み
│   ├── collector.py   # Speedtest CLI ラッパー
│   ├── storage.py     # SQLite 操作
│   ├── scoring.py     # 快適度スコア算出
│   └── visualizer.py  # ヒートマップ・グラフ生成
├── tests/             # テストコード
├── scripts/           # 運用スクリプト
│   ├── run_speedtest.py     # 計測エントリポイント
│   └── generate_report.py  # レポート生成
├── config.yaml        # 設定ファイル
├── data/              # SQLite DB（.gitignore 対象）
├── logs/              # 実行ログ（.gitignore 対象）
└── assets/            # 生成されたレポート画像
```

## 設定

`config.yaml` で以下の項目を調整できる:

- **cafe**: 開館・閉館時間
- **speedtest**: コマンド、タイムアウト、リトライ回数
- **storage**: DB パス、保存期間
- **scoring**: 各指標の重み・閾値、快適度ラベル
- **visualization**: カラーマップ、DPI、曜日ラベル
