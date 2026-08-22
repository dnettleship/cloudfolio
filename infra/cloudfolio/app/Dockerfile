FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12

# Install dependencies
COPY infra/cloudfolio/app/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt --no-cache-dir

# Copy handler
COPY infra/cloudfolio/app/lambda_handler.py /var/task/lambda_handler.py

CMD ["lambda_handler.handler"]
