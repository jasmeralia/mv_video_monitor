PYTHON ?= .venv/bin/python
PIP ?= $(PYTHON) -m pip

.PHONY: venv install lint-fix lint test clean

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

lint-fix: install
	$(PYTHON) -m ruff check --fix src
	$(PYTHON) -m ruff format src

lint: install
	$(PYTHON) -m ruff check src
	$(PYTHON) -m ruff format --check src
	$(PYTHON) -m mypy src

clean:
	rm -rf .venv .mypy_cache .ruff_cache
