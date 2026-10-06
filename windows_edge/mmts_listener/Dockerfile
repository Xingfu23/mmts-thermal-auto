
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project directory into the container (usually paired with volumes in practice)
COPY . /app

# Set environment variables to force UTF-8 output and prevent Chinese character encoding errors
ENV PYTHONIOENCODING=utf-8

CMD ["python", "mqtt_listener.py"]