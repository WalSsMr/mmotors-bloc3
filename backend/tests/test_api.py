import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def login(client, email="admin@mmotors.fr", password="Admin123!"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]



def test_health_ok(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["database"] == "sqlite"


def test_login_and_list_vehicles(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = login(client)
    assert token
    r = client.get("/vehicles")
    assert r.status_code == 200
    assert len(r.json()) >= 4


def test_user_application_and_upload(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = login(client, "user@mmotors.fr", "User123!")
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/applications", json={"vehicle_id": 1, "mode": "sale", "message": "test"}, headers=headers)
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    upload = client.post(
        f"/applications/{app_id}/documents",
        headers=headers,
        files={"file": ("piece.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text
    docs = client.get(f"/applications/{app_id}/documents", headers=headers)
    assert docs.status_code == 200
    assert docs.json()[0]["filename"] == "piece.pdf"


def test_admin_can_add_switch_and_decide(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = login(client)
    headers = {"Authorization": f"Bearer {token}"}
    added = client.post("/vehicles", json={"brand":"BMW","model":"Serie 1","year":2021,"mileage":30000,"price":21900,"mode":"sale"}, headers=headers)
    assert added.status_code == 200, added.text
    vehicle_id = added.json()["id"]
    switched = client.patch(f"/vehicles/{vehicle_id}/switch", headers=headers)
    assert switched.status_code == 200
    assert switched.json()["mode"] == "rental"
    user_token = login(client, "user@mmotors.fr", "User123!")
    app = client.post("/applications", json={"vehicle_id": vehicle_id, "mode": "rental"}, headers={"Authorization": f"Bearer {user_token}"}).json()
    decision = client.patch(f"/applications/{app['id']}/decision", json={"status":"accepted","admin_comment":"OK"}, headers=headers)
    assert decision.status_code == 200
    assert decision.json()["status"] == "accepted"


def test_security_user_cannot_admin_action(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = login(client, "user@mmotors.fr", "User123!")
    r = client.post("/vehicles", json={"brand":"Audi","model":"A3","year":2021,"mileage":1,"price":1,"mode":"sale"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403

def test_admin_logs_and_document_download(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    admin_token = login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    alert = client.post('/health/alert-test', headers=admin_headers)
    assert alert.status_code == 200
    logs = client.get('/admin/logs', headers=admin_headers)
    assert logs.status_code == 200
    assert logs.json()['count'] >= 1

    user_token = login(client, 'user@mmotors.fr', 'User123!')
    user_headers = {"Authorization": f"Bearer {user_token}"}
    app = client.post('/applications', json={'vehicle_id': 1, 'mode': 'sale', 'message': 'download test'}, headers=user_headers)
    assert app.status_code == 200
    app_id = app.json()['id']
    upload = client.post(
        f'/applications/{app_id}/documents',
        headers=user_headers,
        files={'file': ('carte-grise.pdf', b'%PDF-1.4 demo', 'application/pdf')},
    )
    assert upload.status_code == 200
    doc_id = upload.json()['id']
    download = client.get(f'/documents/{doc_id}?token={user_token}')
    assert download.status_code == 200
    assert download.content.startswith(b'%PDF')
    refused = client.get(f'/documents/{doc_id}')
    assert refused.status_code == 401
