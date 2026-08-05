from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_model_architecture_returns_png():
    response = client.get("/api/model_architecture")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
