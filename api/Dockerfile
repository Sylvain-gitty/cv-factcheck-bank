# factbank-api image: Python + dependencies ONLY.
# Build context is api/, so no fact-bank data can end up in a layer. The code and the bank
# are bind-mounted at /factbank at runtime (see docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && useradd --create-home app

USER app
WORKDIR /factbank
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "/factbank/api", "--host", "0.0.0.0", "--port", "8000"]
