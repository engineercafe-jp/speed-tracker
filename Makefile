.PHONY: install test measure report clean

install:
	pip install -r requirements.txt

test:
	python -m pytest tests/ -v

measure:
	python scripts/run_speedtest.py

report:
	python scripts/generate_report.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
