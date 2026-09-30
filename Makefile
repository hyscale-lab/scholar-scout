.PHONY: lint test test-live clean  # Declare phony targets (not actual files)

PYTHON ?= python

# Format code using autoflake and black
format:
	autoflake --in-place --recursive --remove-all-unused-imports --remove-unused-variables .
	black .

# Check if code needs formatting without making changes
format-check:
	black . --check --diff

# Run linting checks
lint:
	flake8 . --count --statistics --show-source

# Run all unit tests with verbose output
test:
	RUN_LIVE_TESTS=0 $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

test-live:
	RUN_LIVE_TESTS=1 $(PYTHON) -m unittest discover -s tests -p test_gmail_connection.py -v
	RUN_LIVE_TESTS=1 $(PYTHON) -m unittest discover -s tests -p test_integration.py -v

# Clean up Python cache and build files
clean:
	# Remove Python cache directories
	find . -type d -name "__pycache__" -exec rm -r {} +
	# Remove compiled Python files
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	# Remove coverage data
	find . -type f -name ".coverage" -delete
	# Remove package build directories
	find . -type d -name "*.egg-info" -exec rm -r {} +
	find . -type d -name "*.egg" -exec rm -r {} +
	find . -type d -name ".pytest_cache" -exec rm -r {} +
	find . -type d -name ".tox" -exec rm -r {} +
	find . -type d -name "build" -exec rm -r {} +
	find . -type d -name "dist" -exec rm -r {} +

# Install development dependencies
install-dev:
	pip install -r requirements-dev.txt

# Install production dependencies
install:
	pip install -r requirements.txt
