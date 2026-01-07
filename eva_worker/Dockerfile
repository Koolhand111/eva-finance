FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy EVERYTHING (worker.py, scoring.py, etc)
COPY . .

CMD ["python3", "worker.py"]
