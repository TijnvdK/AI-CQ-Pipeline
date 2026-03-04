FROM python:3.14-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
