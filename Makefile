PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf '%s/.venv/bin/python\n' "$$(pwd)"; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
TOOL_BIN := $(dir $(PYTHON))

.PHONY: check lint quality mutation-test

check: quality mutation-test

lint:
	$(TOOL_BIN)ruff format --check custom_components tests scripts
	$(TOOL_BIN)ruff check custom_components tests scripts

quality: lint
	mkdir -p .verification
	$(TOOL_BIN)pytest -q --cov --cov-branch --cov-report=term-missing --cov-report=json:.verification/coverage.json
	$(PYTHON) scripts/quality_metrics.py .verification/coverage.json
	$(TOOL_BIN)complexipy custom_components/kinosail --max-complexity-allowed 21
	$(TOOL_BIN)vulture custom_components/kinosail --min-confidence 80
	$(TOOL_BIN)pylint --disable=all --enable=duplicate-code --min-similarity-lines=4 custom_components/kinosail

mutation-test:
	$(PYTHON) -c "import shutil; from pathlib import Path; path = Path('mutants'); path.exists() and shutil.rmtree(path)"
	$(TOOL_BIN)mutmut run --max-children 4
	$(TOOL_BIN)mutmut export-cicd-stats
	$(PYTHON) scripts/check_mutation.py mutants/mutmut-cicd-stats.json
