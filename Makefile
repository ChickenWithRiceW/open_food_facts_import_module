ENTRY = src/
CONFIG = example.txt

install:
	uv sync

run: install
	uv run python $(ENTRY) $(CONFIG)

debug: install
	uv run python -m pdb $(ENTRY) $(CONFIG)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +

lint:
	uv run ruff check $(ENTRY)
	uv run mypy src/
	uv run mypy $(ENTRY)

lint-strict:
	uv run ruff check $(ENTRY)
	uv run mypy src/ --strict
	uv run mypy $(ENTRY) --strict
lint-fix:
	uv run ruff check $(ENTRY) --fix 
	uv run ruff format $(ENTRY)

.PHONY: test demo
test:
	uv run pytest -q

demo:
	uv run unknown-data examples/products.csv
