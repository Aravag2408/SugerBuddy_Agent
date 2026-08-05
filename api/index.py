from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()

TEAM_INFO = {
    "group_batch_order_number": "TODO_FILL_BEFORE_SUBMISSION",
    "team_name": "SugarBuddy",
    "students": [
        {"name": "Arava Gendelman", "email": "aravag@campus.technion.ac.il"},
        {"name": "Aya Grabarsky", "email": "ayagrabarsky@campus.technion.ac.il"},
        {"name": "Sofia Torgovezky", "email": "sofiat@campus.technion.ac.il"},
    ],
}


@app.get("/api/team_info")
def team_info():
    return TEAM_INFO


ARCHITECTURE_DIAGRAM_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "architecture" / "pipeline_diagram.png"
)


@app.get("/api/model_architecture")
def model_architecture():
    return FileResponse(ARCHITECTURE_DIAGRAM_PATH, media_type="image/png")
