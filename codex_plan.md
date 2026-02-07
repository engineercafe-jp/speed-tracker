# Speed Tracker 実装プラン

## 1. ゴール定義
最終ゴールは「ネットワーク速度の時間ごとの快適度」を可視化することである。  
速度そのもの（download/upload）だけでなく、遅延（ping/jitter）を含めた体感指標を作り、日次で画像出力する。
また、エンジニアカフェの開館時間（`9:00-22:00`）を主要分析対象として扱う。

## 2. 既存ソフトからの参考点
以下の既存ソフトの設計を取り入れる。

### Speedtest Tracker（Laravel + React）
- 毎時実行して履歴をグラフ化する構成
- 実測データ収集と可視化を分離している点が有効
- 通知やCSV/JSONエクスポートは将来拡張に適する

### MySpeed
- Cron式で測定間隔を柔軟に制御できる
- Ookla/LibreSpeed/Cloudflare の複数プロバイダ対応が現実的
- 保存期間（例: 30日）を設ける運用が分かりやすい

### LibreSpeed CLI
- Ping/Jitter/Download/Upload を1回で取得できる
- カスタムサーバ指定が可能で、継続観測の再現性を上げやすい

### SmokePing
- 計測デーモンと可視化を分離する構成
- 時系列の劣化検知・アラート設計の考え方が有効

## 2.1 測定ツール選定
測定ツールは `Ookla公式CLI speedtest` を採用する。  
`Python製 speedtest-cli` ではなく公式バイナリを使う理由は、計測負荷と品質指標の信頼性の観点で有利だからである。

- インストール（macOS）: `brew tap teamookla/speedtest && brew install speedtest`
- 出力形式: `speedtest -f json`
- 期待値: JSONが標準出力されるため `collector.py` の実装を単純化できる

## 3. このリポジトリ向けアーキテクチャ
`src/` を以下の責務で分離する。
- `collector.py`: `speedtest -f json` 実行、再試行、結果JSON化
- `scheduler.py`: 定期実行（cron想定）
- `storage.py`: SQLite保存
- `scoring.py`: 快適度スコア算出
- `plotter.py`: 日次画像生成（ヒートマップ + 折れ線）
- `config.py`: 設定ファイル読み込み（時間帯、重み、閾値、タイムアウト等）

保存スキーマ案（SQLite）:
- `measurements(ts, provider, server_id, download_mbps, upload_mbps, ping_ms, jitter_ms, raw_json)`
- `hourly_scores(date, hour, comfort_score, comfort_label)`

失敗時記録用の拡張案:
- `measurements` に `status`（`ok`/`error`）と `error_message` を持たせる
- 取得失敗も履歴化し、可視化時に欠測理由を追えるようにする

開館時間対応:
- `scheduler.py` は `9:00-22:00` のみ定期計測し、閉館時間は計測しない（運用コスト削減）
- 可視化は `9-21時台` を主グラフにし、閉館時間帯データは別枠または非表示にする
- `hourly_scores` 集計時は「開館時間内平均」と「全時間平均」を分けて保持する
- cron設定例（15分間隔）: `*/15 9-21 * * * cd /path/to/speed-tracker && /usr/bin/python3 src/collector.py >> logs/collector.log 2>&1`

## 4. 快適度スコア設計（初期案）
0-100 点で算出する。重みは初期値として以下を採用する。
- Download 35%
- Upload 20%
- Ping 30%
- Jitter 15%

ラベル:
- `90-100: 非常に快適`
- `70-89: 快適`
- `50-69: やや不安定`
- `0-49: 不快`

正規化は閾値ベース（上限・下限クリップ）で実装し、実データに合わせて重みを再調整する。
欠損値（計測失敗時間帯）は初期方針として「計算除外」とする（0点扱いはしない）。

## 4.1 エラーハンドリング方針
- 再試行: 失敗時は数秒待機し、最大3回再試行する
- タイムアウト: `subprocess.run(..., timeout=xx)` で無限待ちを防ぐ
- 終了コード異常やJSONパース失敗は `status=error` として保存する
- cron実行ログは `logs/collector.log` に追記し、障害切り分けを容易にする

## 4.2 設定外部化方針
調整しやすい項目は `config.yaml`（または `.env`）へ切り出す。
- 開館時間: `open_hour=9`, `close_hour=22`
- 計測間隔: `interval_minutes=15`
- スコア重み: `download/upload/ping/jitter`
- 正規化閾値: `download_min/max` など
- 実行制御: `retry_count`, `retry_wait_sec`, `command_timeout_sec`

## 5. 実装フェーズ
1. **MVP計測**
- `speedtest`（Ookla公式CLI）で計測
- `9:00-22:00` の間で10〜30分間隔でSQLiteへ保存（初期推奨: 15分）
- 失敗時の最大3回再試行とタイムアウトを実装

2. **可視化MVP**
- 日次で `assets/YYYY-MM-DD.png` を出力
- 上段: 開館時間（`9:00-22:00`）の時間帯別快適度ヒートマップ、下段: download/ping推移

3. **スコア改善**
- 実測データ1〜2週間分で閾値・重みを調整
- 欠測時の補間方針（欠測表示/前値保持）を決定
- 開館直後（9時台）と閉館前（21時台）の特性差を見て重み調整の要否を判断

4. **運用安定化**
- ログ整備、再実行耐性、保存期間ローテーション
- 異常値検知（急落/高遅延）と通知（任意）

## 6. 直近の着手順
最初の1週間は以下に限定する。
1. `collector.py` + `storage.py` で `9:00-22:00` の測定を継続保存
2. `config.yaml` 読み込みと再試行/タイムアウトを導入
3. `scoring.py` で欠損除外ルールの時間別快適度を算出
4. `plotter.py` で開館時間中心の日次画像を自動生成

この順序なら「まず見える化」を最短で達成でき、後続の通知・UI拡張にも接続しやすい。

## 参考
- https://github.com/henrywhitaker3/Speedtest-Tracker
- https://github.com/gnmyt/MySpeed
- https://github.com/librespeed/speedtest-cli
- https://github.com/oetiker/SmokePing
