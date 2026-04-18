# Integration-test container for amatelier.
#
# Mirrors the Python environment of GitHub Actions Ubuntu runners so that
# test results in `docker run` match CI byte-for-byte.
#
# Usage:
#   docker build -t amatelier-test .
#   docker run --rm amatelier-test                    # run the integration test
#   docker run --rm amatelier-test pytest             # run all pytest suites
#   docker run --rm amatelier-test bash               # drop into a shell
#   docker run --rm -v "$PWD:/app" amatelier-test     # mount source for live iteration

FROM python:3.12-slim

WORKDIR /app

# Minimal OS packages: git for hatch VCS version, build tools for any C-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject + source first so dep install is layer-cached across
# source-only changes
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY docs /app/docs
COPY examples /app/examples
COPY scripts /app/scripts
COPY tests /app/tests

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# Default: run the integration test. Override CMD to run something else.
ENV AMATELIER_WORKSPACE=/tmp/amatelier-test-workspace
CMD ["pytest", "tests/test_db_integration.py", "-v", "--tb=short"]
