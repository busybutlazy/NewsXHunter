FROM python:3.11-slim

WORKDIR /edge_worker

COPY requirements.txt /edge_worker/requirements.txt
RUN pip install --no-cache-dir -r /edge_worker/requirements.txt

COPY /app /edge_worker/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
