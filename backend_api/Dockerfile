FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY pipeline_runtime ./pipeline_runtime
RUN mkdir -p /app/var/jobs

ENV PIPELINE_ROOT=/app/pipeline_runtime
ENV PIPELINE_WORK_ROOT=/app/var/jobs
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

