# dataforge

Minimal scaffolding for the DataForge platform.

Run `dataforge` CLI commands (scaffold only). See individual modules for implementation.

## Upload data

Start the upload server:

```bash
python -m core.cli serve
```

Open `http://127.0.0.1:8000/` in your browser to pick a file and upload it.

Then upload a file:

```bash
curl -F "file=@data/raw/sales.csv" -F "goal=clean for analytics" http://127.0.0.1:8000/upload
```

Uploaded files are saved to `data/raw/` and the `CleaningAgent` starts processing them in the background, saving cleaned outputs in `data/processed/`.
