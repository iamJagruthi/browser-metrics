# Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY Frontend/package*.json ./
RUN npm ci
COPY Frontend ./
RUN npm run build

# Final image
FROM python:3.11-slim AS final
WORKDIR /app
COPY Backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY Backend ./Backend
COPY --from=frontend-builder /app/dist ./Frontend/dist
EXPOSE 8000
ENV PORT=8000
CMD ["python", "Backend/run_server.py"]
