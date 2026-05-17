import typer
import sys

app = typer.Typer(help="DataForge commands")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = True):
    """Start the FastAPI upload server."""
    import uvicorn

    uvicorn.run("ui.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        sys.argv.pop(1)
    app()
