.PHONY: setup api web seed test clean

setup:
	cd backend && python3 -m pip install -r requirements.txt
	cd frontend && npm install

api:
	cd backend && PYTHONPATH=. python3 -m uvicorn app.main:app --port 8123 --reload

web:
	cd frontend && npm run dev

seed:
	cd backend && PYTHONPATH=. python3 ../scripts/seed.py

test:
	cd backend && PYTHONPATH=. python3 -m pytest -q

clean:
	rm -rf backend/data/*.db frontend/dist
