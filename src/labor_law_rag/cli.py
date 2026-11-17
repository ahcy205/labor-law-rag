"""명령줄 도구 `llr`."""

import typer

app = typer.Typer(help="labor-law-rag: 말뭉치 수집 · 평가 세트 · 평가 도구", no_args_is_help=True)


@app.callback()
def main() -> None:
    """labor-law-rag 명령 모음."""
