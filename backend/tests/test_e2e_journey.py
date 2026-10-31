"""The finale path, end to end through the HTTP API (DEMO_MODE=replay; any LLM cache miss uses the policy and
template fallbacks, so the outcome never depends on the LLM)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ASSETS = Path(__file__).resolve().parent.parent / "demo_assets"
HERO = "M0001"


@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post("/api/demo/reset").status_code == 200
        yield c
        c.post("/api/demo/reset")  # leave seeded data as other tests expect it


def upload(c, mid, name, doc_type, expect=200):
    with open(ASSETS / name, "rb") as f:
        r = c.post(f"/api/journeys/{mid}/upload", files={"file": (name, f, "image/jpeg")}, data={"doc_type": doc_type})
    assert r.status_code == expect, r.text
    return r.json()


def chat(c, mid):
    return c.get(f"/api/merchants/{mid}/chat").json()["messages"]


def events(c, mid):
    return c.get(f"/api/events/recent?merchant_id={mid}").json()["events"]


def is_subsequence(needles, haystack):
    it = iter(haystack)
    return all(n in it for n in needles)


def test_finale_path_for_the_hero_merchant(client):
    # 1. M0001 tops the queue
    assert client.get("/api/queue?limit=1").json()["items"][0]["merchant_id"] == HERO

    # 2. start: Soundbox prompt + Hindi WhatsApp request for the PAN
    v = client.post(f"/api/journeys/{HERO}/start").json()
    assert v["waiting_for"] == {"waiting_for": "shopkeeper", "doc_type": "PAN"}
    assert v["qr_status"] == "IN_PROGRESS" and v["step"] == "COLLECT"
    msg = chat(client, HERO)[-1]
    assert msg["channel"] == "WHATSAPP" and any("ऀ" <= ch <= "ॿ" for ch in msg["text_hi"])
    assert any(e["type"] == "soundbox.speak" for e in events(client, HERO))
    assert v["attempts"] == {"SOUNDBOX": 1, "WHATSAPP": 1}

    # blurry PAN -> rejected with a specific fix, still waiting for the PAN
    v = upload(client, HERO, "pan_blurry.jpg", "PAN")
    check = v["state"]["last_check"]
    assert check["decision"] == "REJECTED" and check["reason_code"] == "BLURRY"
    assert "good light" in check["fix_en"]
    fix_msg = chat(client, HERO)[-1]
    assert fix_msg["sender"] == "agent" and ("धुंधली" in fix_msg["text_hi"] or "blurry" in fix_msg["text_en"].lower())
    assert v["waiting_for"]["doc_type"] == "PAN"

    # sharp PAN -> accepted and verified with the issuing authority; then the ID proof
    v = upload(client, HERO, "pan_sharp.jpg", "PAN")
    assert v["state"]["last_check"]["decision"] == "ACCEPTED"
    assert v["waiting_for"]["doc_type"] == "OVD"
    v = upload(client, HERO, "ovd_sharp.jpg", "OVD")
    assert v["state"]["last_check"]["decision"] == "ACCEPTED"

    # 3. visit booked in the quiet hour, on today's route of the nearest employee
    assert v["waiting_for"]["waiting_for"] == "field_employee"
    assert v["step"] == "FIELD_VISIT" and v["visit_slot"].endswith("T15:10:00")
    assert v["assigned_employee"] == "E04"
    visit = next(x for x in client.get("/api/field/visits?employee_id=E04").json()["visits"] if x["merchant_id"] == HERO)
    assert visit["completed_at"] is None
    route = client.get("/api/field/route?employee_id=E04").json()  # OR-Tools day plan with the pre-booked stops
    stop = next(x for x in route["stops"] if x["merchant_id"] == HERO)
    assert route["status"] == "optimal" and len(route["stops"]) > 1
    assert stop["eta"].endswith("T15:10:00") and stop["order"] == visit["route_order"]

    # CPV cannot be skipped: before the field check the rules engine says not compliant
    comp = client.get(f"/api/merchants/{HERO}/compliance").json()
    assert not comp["compliant"]
    assert {r["requirement"]: r["passed"] for r in comp["results"]} == {
        "PAN_OR_FORM60_VERIFIED": True, "OVD_COLLECTED": True, "NAME_MATCH": True, "CPV_DONE": False,
        "NO_OPEN_RISK_FLAG": True}

    # 4. field employee completes the in-person check -> 5. compliant, sealed, LIVE
    r = client.post(f"/api/field/visits/{visit['id']}/complete", json={
        "employee_id": "E04", "lat": visit["lat"], "lng": visit["lng"], "signboard_photo": "signboard_M0001.jpg"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["qr_status"] == "LIVE" and v["step"] == "LIVE" and v["waiting_for"] is None
    assert v["state"]["compliance"] == {"compliant": True, "route": "SMALL_MERCHANT", "failed": []}
    assert v["chain"]["ok"]

    actions = [e["action"] for e in v["timeline"]]
    assert is_subsequence(["TRIAGED", "DECISION", "DOCUMENT_REQUESTED", "DOCUMENT_CHECKED", "DOCUMENT_CHECKED",
                           "DOCUMENT_CHECKED", "VISIT_BOOKED", "CPV_COMPLETED", "COMPLIANCE_EVALUATED",
                           "AUDIT_SEALED", "QR_REACTIVATED", "JOURNEY_COMPLETED"], actions)
    assert next(e for e in v["timeline"] if e["action"] == "CPV_COMPLETED")["actor"] == "human:E04"
    decisions = [e["payload"] for e in v["timeline"] if e["action"] == "DECISION"]
    assert decisions and all(d["verdict"] in ("accepted", "overrode", "decided_alone") for d in decisions)
    assert all(d["final"] in d["valid"] for d in decisions)

    evs = events(client, HERO)
    assert any(e["type"] == "soundbox.status" and e["data"]["status"] == "LIVE" for e in evs)
    assert any(e["type"] == "soundbox.speak" and "फिर से चालू" in e["data"]["text_hi"] for e in evs)
    assert "QR" in chat(client, HERO)[-1]["text_hi"]


def test_upload_is_refused_when_the_journey_is_not_waiting_for_one(client):
    upload(client, HERO, "pan_sharp.jpg", "PAN", expect=409)  # not started
    client.post(f"/api/journeys/{HERO}/start")
    assert client.post(f"/api/journeys/{HERO}/start").status_code == 200  # starting twice is a no-op
    upload(client, HERO, "pan_sharp.jpg", "PAN")
    upload(client, HERO, "ovd_sharp.jpg", "OVD")
    upload(client, HERO, "pan_sharp.jpg", "PAN", expect=409)  # now waiting for the field employee


def test_field_completion_needs_photo_confirmation_and_a_geo_tag_at_the_shop(client):
    client.post(f"/api/journeys/{HERO}/start")
    upload(client, HERO, "pan_sharp.jpg", "PAN")
    v = upload(client, HERO, "ovd_sharp.jpg", "OVD")
    visit_id = v["state"]["visit_id"]
    url = f"/api/field/visits/{visit_id}/complete"
    good = {"employee_id": "E04", "lat": 28.6270, "lng": 77.3650, "signboard_photo": "sign.jpg"}
    assert client.post(url, json={**good, "signboard_photo": " "}).status_code == 422
    assert client.post(url, json={**good, "confirmed": False}).status_code == 422
    assert client.post(url, json={**good, "employee_id": "agent"}).status_code == 403
    assert client.post(url, json={**good, "lat": 28.70}).status_code == 422  # ~8 km away
    assert client.get(f"/api/journeys/{HERO}").json()["qr_status"] == "IN_PROGRESS"
    assert client.post(url, json=good).json()["qr_status"] == "LIVE"
    assert client.post(url, json=good).status_code == 409
