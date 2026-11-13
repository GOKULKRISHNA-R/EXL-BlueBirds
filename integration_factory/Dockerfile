FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
COPY integration_factory ./integration_factory
RUN pip install --no-cache-dir fastapi uvicorn pydantic httpx python-dotenv
EXPOSE 8080
CMD ["uvicorn","integration_factory.api:app","--host","0.0.0.0","--port","8080"]
