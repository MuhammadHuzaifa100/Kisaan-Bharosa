 ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   `SECRET_KEY` and the Gemini key are read only from the environment, never from the
   frontend. The app starts and every non-AI feature works **without** `GEMINI_API_KEY`;
   scans are stored as `PENDING_ANALYSIS` and the API returns `503 ANALYSIS_UNAVAILABLE`
   with a plain-language reason. Add a key to enable verdicts:
   with a plain-language reason. Two ways to get a verdict:

   ```env
   GEMINI_API_KEY="your-gemini-api-key"   # free key at https://aistudio.google.com
   # 1. Server-side, needs your own key (free at https://aistudio.google.com)
   GEMINI_API_KEY="your-gemini-api-key"

   # 2. No key at all: the portal offers "Analyse in my browser", which calls a vision
   #    model through each visitor's own Puter session. Those verdicts are stored and
   #    displayed as browser-supplied, never as server-verified evidence.
   PUTER_AI_ENABLED=true
   PUTER_AI_MODEL=gpt-5.6-luna
   ```

5. **Start the Application:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   * The web application will be accessible at: `http://localhost:8000`
   * Interactive Swagger API documentation: `http://localhost:8000/docs`

6. **Accounts:**
   * Sign-up from the portal always creates a **farmer** account; the role is never taken from the form.
   * An **inspector** account is provisioned at startup from `.env`:
  -e UPLOAD_DIR=/app/static/uploads \
  -v kisaan-data:/app/data \
  -v kisaan-uploads:/app/static/uploads \
  kisaan-bharosa:latest
```
The container runs as a non-root user and reports health on `/health`. Point
`DATABASE_URL` and `UPLOAD_DIR` at the mounted volumes: photographs and the SQLite file
otherwise disappear with the container. Prefer managed Postgres and object storage as
soon as more than one instance serves traffic.

### Cloud Platforms (Render / Railway / Fly.io / GCP Cloud Run)
* **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
  (`$PORT` is provided by the platform; on Render it defaults to `10000`.)

