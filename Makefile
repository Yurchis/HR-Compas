PYTHON ?= python
HR = $(PYTHON) -m hr_compass.cli.main

QUERY ?= How many days a week can I work from home?
GROUPS ?= all_employees
MODELS ?= gpt4omini,haiku,deepseek

.PHONY: install run test lint pipeline prepare ingest index search lint-testset eval-search gate-search eval-answers compare

install:
	$(PYTHON) -m pip install -r requirements.txt

# the interactive bot on the data already prepared (data/data_clean); build it first with `make pipeline`
run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

# the full RAG pipeline: documents -> chunks -> index -> testset lint + search gate -> the interactive bot
pipeline:
	$(HR) run --check

# the same without the chat: rebuild and check the data only
prepare:
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
