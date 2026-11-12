FROM python:3.12-slim
WORKDIR /app
COPY his_mock/ /app/his_mock/
ENV PYTHONUNBUFFERED=1
EXPOSE 2575
CMD ["python", "-m", "his_mock.server"]
