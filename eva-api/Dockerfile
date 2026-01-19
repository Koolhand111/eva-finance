FROM python:3.12-slim

WORKDIR /app

# Install eva_common dependencies first (shared layer)
COPY eva_common/requirements.txt ./eva_common/requirements.txt
RUN pip install --no-cache-dir -r eva_common/requirements.txt

# Install service-specific dependencies
COPY eva-api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module
COPY eva_common/ ./eva_common/

# Copy service code
COPY eva-api/app.py .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
