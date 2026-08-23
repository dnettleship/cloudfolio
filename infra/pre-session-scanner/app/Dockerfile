FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12

# Install dependencies
COPY infra/pre-session-scanner/app/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt --no-cache-dir

# Reuse the scanner source directly — no separate Lambda-side reimplementation.
COPY pre-session-scanner/scanner.py /var/task/scanner.py
COPY pre-session-scanner/dashboard.py /var/task/dashboard.py
COPY pre-session-scanner/report.py /var/task/report.py
COPY pre-session-scanner/watchlist.json /var/task/watchlist.json

# Copy handler
COPY infra/pre-session-scanner/app/lambda_handler.py /var/task/lambda_handler.py

CMD ["lambda_handler.handler"]
