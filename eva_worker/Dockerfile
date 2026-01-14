FROM python:3.12-slim

WORKDIR /app

# Install eva_common dependencies first (shared layer)
COPY eva_common/requirements.txt ./eva_common/requirements.txt
RUN pip install --no-cache-dir -r eva_common/requirements.txt

# Install service-specific dependencies
COPY eva_worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module
COPY eva_common/ ./eva_common/

# Copy worker service code
COPY eva_worker/ .

CMD ["python3", "worker.py"]
