FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org fastapi uvicorn requests

COPY . .

EXPOSE 8000

CMD ["python", "broker/main.py"]
