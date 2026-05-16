FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN mkdir -p outputs .work outputs/saas

ENV PYTHONUNBUFFERED=1

EXPOSE 8790

CMD ["python", "-m", "saas.app.server"]
