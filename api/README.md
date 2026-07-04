# Pratham AI — Production Infrastructure Build

## Deployment Stack
* **Backend:** Flask served via WSGI Gunicorn (Optimized for Render/Railway).
* **Frontend:** Static SPA distribution (Optimized for Vercel Static Hosting).

## Local Execution Runtime Node Initialization
1. Ensure a virtual environment context is instantiated: `python -m venv venv && source venv/bin/activate`
2. Run installation vectors: `pip install -r requirements.txt`
3. Execute localized server thread: `python app.py`