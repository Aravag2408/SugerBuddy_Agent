from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_team_info_returns_expected_shape():
    response = client.get("/api/team_info")

    assert response.status_code == 200
    body = response.json()
    assert body["team_name"] == "SugarBuddy"
    assert body["group_batch_order_number"] == "TODO_FILL_BEFORE_SUBMISSION"

    emails = {s["email"] for s in body["students"]}
    assert emails == {
        "aravag@campus.technion.ac.il",
        "ayagrabarsky@campus.technion.ac.il",
        "sofiat@campus.technion.ac.il",
    }
    names = {s["name"] for s in body["students"]}
    assert names == {"Arava Gendelman", "Aya Grabarsky", "Sofia Torgovezky"}
