PYTHON ?= python

PROMPT ?= prompts/v2_structured.md
SAMPLES ?= data/golden_set.jsonl

MODELS ?= haiku,deepseek

.PHONY: install run test eval compare

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m pytest -q

eval:
	$(PYTHON) -m hr_compass.evaluate --prompt $(PROMPT) --samples $(SAMPLES)

compare:
	$(PYTHON) -m hr_compass.evaluate --prompt $(PROMPT) --samples $(SAMPLES) --models $(MODELS)
