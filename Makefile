# P1 Staff Manager — ローカル開発用 Makefile
#
# 使い方:
#   make test       # 全テスト実行（CIと同じ内容）
#   make test-fast  # 軽量テストだけ（30秒以内）
#   make run        # ローカルでStreamlit起動
#   make lint       # 構文チェック
#   make help       # この一覧を表示

PY := .venv/bin/python
STREAMLIT := .venv/bin/streamlit

.PHONY: help test test-fast test-ui run lint install clean

help:
	@echo "P1 Staff Manager — Make コマンド一覧"
	@echo ""
	@echo "  make install      — venv 作成 + 依存インストール"
	@echo "  make test         — 全テストを実行（CIと同じ）"
	@echo "  make test-fast    — 軽量テストだけ（DB非依存・約30秒）"
	@echo "  make test-ui      — UI要素テストだけ"
	@echo "  make run          — ローカル起動 (http://localhost:8511)"
	@echo "  make lint         — 全Pythonファイルの構文チェック"
	@echo "  make clean        — __pycache__ など中間ファイル削除"

install:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	@echo ""
	@echo "✅ セットアップ完了。  make run で起動できます。"

lint:
	$(PY) -m py_compile app.py db.py utils/*.py scripts/*.py pages/*.py
	@echo "✅ 構文OK"

test-fast:
	@echo "⏱  軽量テスト（DB非依存）..."
	@$(PY) test_e2e/17_event_template_unit_test.py
	@$(PY) test_e2e/19_admin_guard_unit_test.py
	@$(PY) test_e2e/20_core_logic_unit_test.py
	@$(PY) test_e2e/22_security_behavior_test.py
	@$(PY) test_e2e/16_gform_importer_test.py
	@$(PY) test_e2e/4_receipt_unit_test.py
	@$(PY) test_e2e/8_contract_unit_test.py
	@$(PY) test_e2e/14_receipt_copy_original_test.py
	@$(PY) test_e2e/15_contract_template_import_test.py
	@echo ""
	@echo "✅ 軽量テスト完走"

test-ui:
	@echo "🎨 UI要素テスト（AppTest 全ページ）..."
	@$(PY) test_e2e/18_pages_smoke_test.py
	@$(PY) test_e2e/21_ui_elements_test.py

test: lint test-fast test-ui
	@echo ""
	@echo "🎉 全テストPASS"

run:
	$(STREAMLIT) run app.py --server.port 8511 --server.headless true --browser.gatherUsageStats false

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf test_e2e/test_*.pdf test_e2e/test_*.png 2>/dev/null || true
	@echo "✅ クリーンアップ完了"
