FROM python:3.11-slim

WORKDIR /app

COPY sandbox/requirements.sandbox.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
ENV PYTHONPATH=/app

CMD ["sleep", "infinity"]
