PYTHON ?= python
HR = $(PYTHON) -m hr_compass.cli.main

QUERY ?= How many days a week can I work from home?
GROUPS ?= all_employees
MODELS ?= gpt4omini,haiku,deepseek

.PHONY: install run test lint pipeline ingest index search lint-testset eval-search gate-search eval-answers compare

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

# documents -> chunks -> index, then check the testset and the search quality (no chat)
pipeline:
	$(HR) run --no-chat --check

ingest:
	$(HR) ingest

index:
	$(HR) index

search:
	$(HR) search "$(QUERY)" --groups $(GROUPS)

lint-testset:
	$(HR) eval lint

eval-search:
	$(HR) eval retrieval

gate-search:
	$(HR) eval retrieval --gate

# calls the model (OpenRouter): costs money
eval-answers:
	$(HR) eval answers --judge

compare:
	$(HR) eval answers --models $(MODELS) --judge
