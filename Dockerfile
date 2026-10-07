FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=true \
    LLM_PROVIDER=mock \
    REMINDER_DRY_RUN=true \
    REMINDER_DAYS=30 \
    PROCESS_SAMPLES_ON_START=true \
    WATCH_ENABLED=true \
    SCHEDULER_ENABLED=true \
    HOST=0.0.0.0 \
    PORT=8741 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY schemas ./schemas
COPY scripts ./scripts
COPY samples ./samples

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data /app/inbox/coi /app/inbox/invoice

EXPOSE 8741

# Refresh sample dates, then serve the dashboard. No API key required.
CMD ["sh", "-c", "python scripts/generate_samples.py && python -m doc_extractor serve --host 0.0.0.0 --port 8741"]
