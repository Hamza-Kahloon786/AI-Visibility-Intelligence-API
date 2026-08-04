FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run.py

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Timeout > 120s: a full pipeline run makes 1 + N + 1 sequential LLM calls
# (N = discovered queries, up to MAX_DISCOVERY_QUERIES), which the spec
# itself notes can take 10-30s+ -- gunicorn's default 30s worker timeout
# would kill a healthy in-progress request.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "180", "run:app"]
