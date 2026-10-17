PYTHON ?= python3

seed:
	$(PYTHON) scripts/seed.py

test:
	$(PYTHON) -m pytest -q

run-local: seed
	PYTHONPATH=src $(PYTHON) -m triage run fixtures/eml --db .triage.sqlite

why:
	PYTHONPATH=src $(PYTHON) -m triage why $(EML)

tf-validate:
	terraform fmt -check -recursive infra
	terraform -chdir=infra init -backend=false
	terraform -chdir=infra validate

.PHONY: seed test run-local why tf-validate
