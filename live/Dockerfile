FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.32.1" "openai>=1.80,<3"
COPY app.py index.html plan_tools.py ./
COPY 결과 ./결과
ENV PORT=8080
CMD ["python", "app.py"]
