FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN mkdir -p outputs .work outputs/saas
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r crm_vitoria_source/requirements.txt

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "crm_vitoria_source/app.py"]
