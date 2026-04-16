FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12

# Install dependencies
COPY infra/app/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt --no-cache-dir

# Copy handler
COPY infra/app/lambda_handler.py /var/task/lambda_handler.py

CMD ["lambda_handler.handler"]
