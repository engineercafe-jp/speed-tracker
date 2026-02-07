# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

エンジニアカフェのネットワーク回線速度を継続的に監視し、日毎の速度変化を画像として出力するスクリプト。

## Language & Style Rules

- 回答とmarkdownドキュメントは日本語の常体（だ・である調）で記述する
- docstring・コメント・ログは多めに記載する
- Conventional Commits を使用する（例: `feat: add speed sampling script`）

## Project Layout (convention)

- `src/` — アプリケーションコード
- `tests/` — テストコード（ソースのパス構造をミラーする）
- `assets/` — 生成されたグラフ画像・静的リソース
- `scripts/` — 運用ユーティリティ（データ収集、プロット、クリーンアップ）
