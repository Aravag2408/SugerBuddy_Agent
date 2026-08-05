from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_gui_route_returns_html_with_run_button():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Run Agent" in response.text
