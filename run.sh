#!/bin/bash
cd /var/www/shortgen
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
