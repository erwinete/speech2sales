FROM python:3.12-slim

# Инжектор звонков (doc 09 §3): датасет → monitor-файлы + CDR в Postgres
RUN pip install --no-cache-dir "psycopg[binary]>=3.1"

COPY inject_calls.py /opt/devstand/inject_calls.py
ENTRYPOINT ["python", "/opt/devstand/inject_calls.py"]
