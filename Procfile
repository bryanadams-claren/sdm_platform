web: gunicorn config.asgi:application --bind :8000 --worker-class uvicorn.workers.UvicornWorker --timeout 120 --log-level debug --access-logfile - --error-logfile - --preload
