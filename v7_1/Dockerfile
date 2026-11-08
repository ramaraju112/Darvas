FROM python:3.12-slim
WORKDIR /app
COPY v7_1/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY v7_1 /app/v7_1
WORKDIR /app/v7_1
ENV DARVAS_DB_PATH=/data/darvas.sqlite3
EXPOSE 8501
CMD ["streamlit","run","app.py","--server.address=0.0.0.0","--server.port=8501","--server.headless=true","--server.enableCORS=true","--server.enableXsrfProtection=true"]
