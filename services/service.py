from prometheus_client import start_http_server, Counter
import random
import time
import os

# Read the service name from the environment variable set in docker-compose
SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown-service")

# HTTP request counter labelled by service and HTTP status code
REQUESTS = Counter('http_requests_total', 'Total requests', ['service', 'status'])

if __name__ == '__main__':
    # Start the Prometheus metrics endpoint on port 8000
    print(f"Starting service {SERVICE_NAME} on port 8000...")
    start_http_server(8000)

    while True:
        # Simulate different error rates per service: payments is more reliable (0.5%) than catalog (4%)
        if SERVICE_NAME == "payments":
            status = "200" if random.random() > 0.005 else "500"
        else:
            status = "200" if random.random() > 0.04 else "500"

        REQUESTS.labels(service=SERVICE_NAME, status=status).inc()
        time.sleep(1)
