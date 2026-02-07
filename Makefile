.PHONY: install test measure report clean

install:
	uv pip install -r requirements.txt

test:
	.venv/bin/python -m pytest tests/ -v

measure:
	.venv/bin/python scripts/run_speedtest.py

report:
	.venv/bin/python scripts/generate_report.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
