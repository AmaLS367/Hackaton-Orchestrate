# Offline deletion-audit agent. No model API, credential or network access is needed to run.
#
#   docker build -t ghost-audit .
#   docker run --rm --network none \
#     -v "<dataset dir>:/data:ro" -v "<output dir>:/output" ghost-audit
#
# The dataset and every prediction artifact stay outside the image.

# --- Stage 1: install the locked runtime dependencies (no dev tools, no project install) ---
FROM python:3.12-slim-bookworm AS builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv==0.9.16

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# --- Stage 2: runtime image ---
FROM python:3.12-slim-bookworm

# Tesseract is part of the reference environment: without it every screenshot stays
# deferred and the predictions change (see README "Optional local OCR").
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ghost

COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml README.md LICENSE /app/
COPY code /app/code

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER ghost

# /data is the read-only participant dataset; /output is the writable artifact directory.
# Diagnostics are directed beside the CSV because the code tree is read-only at runtime.
ENTRYPOINT ["python", "code/main.py"]
CMD ["--dataset", "/data", "--predictions", "/output/output.csv", \
     "--diagnostics", "/output/full_prediction_diagnostics.json"]
