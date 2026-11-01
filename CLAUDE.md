# HR Compass — project context for Claude

## What it is
The end-to-end project of the **AI Engineer** course (course materials are in Ukrainian).
**HR Compass** is an HR bot, an assistant for employees that knows the answers to questions
about the company.

## Course requirements
### What the repository must contain
- the service code and a diagram;
- a `prompts/` folder with versions and a changelog;
- `data/` with texts and a golden set;
- `results/` with model outputs;
- `REPORT.md` with a comparison report;
- `README.md`: how to run it and what to install.

### Technical requirements
- Python 3.11+, any provider (OpenAI, Anthropic, Gemini, etc.) **+ a local model**.
- Keys live in `.env`; only `.env.example` goes into the repository.
- Run with one command (`make run` or `python main.py`).
- Startup cost: free tiers are enough, or up to $5 for the API; the local model must
  run on an ordinary laptop.
