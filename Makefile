PY = backend/.venv/Scripts/python.exe

setup:          ## create the venv and install everything
	python -m venv backend/.venv
	$(PY) -m pip install -r backend/requirements.txt
	cd frontend && npm install

data:           ## generate 60 labelled synthetic invoices
	$(PY) scripts/generate_invoices.py --count 60

test:           ## end-to-end smoke test, no API key needed
	$(PY) scripts/smoke_test.py

eval:           ## run the real evaluation (needs an LLM key)
	$(PY) scripts/evaluate.py --limit 25 --tune

api:            ## run the backend
	cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

ui:             ## run the frontend
	cd frontend && npm run dev

.PHONY: setup data test eval api ui
