#!/bin/bash
cd /var/www/shortgen
source venv/bin/activate
rq worker --url redis://localhost:6379
