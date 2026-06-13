FROM python:3.10-slim

WORKDIR /app
COPY . /app/

RUN pip install prometheus_client pyyaml

EXPOSE 8000
CMD ["python", "service.py"]