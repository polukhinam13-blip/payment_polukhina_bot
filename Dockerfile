FROM python:3.11-slim

WORKDIR /app

RUN pip install --upgrade pip && \
    pip install --only-binary=:all: pydantic-core && \
    pip install aiogram==3.4.1

COPY bot.py .

CMD ["python", "bot.py"]
