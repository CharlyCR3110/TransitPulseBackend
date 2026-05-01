FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0 \
  /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /var/task

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY bin ./bin

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
