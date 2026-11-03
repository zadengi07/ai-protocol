"""Staging-only load test for /api/kt student flow.

Run only against a disposable/staging database. Each virtual user creates a new attempt.
"""
import os
import uuid
from locust import HttpUser, between, task


class StudentExamUser(HttpUser):
    wait_time = between(2, 5)

    def on_start(self):
        self.attempt_id = None
        self.answers = {}
        meta = self.client.get("/api/kt/meta", name="GET /api/kt/meta")
        if meta.status_code != 200:
            return
        payload = meta.json()
        if not payload.get("exam_open") or not payload.get("groups"):
            return
        name = f"Load Student {uuid.uuid4().hex[:12]}"
        started = self.client.post(
            "/api/kt/start",
            json={"student": name, "group": payload["groups"][0]},
            name="POST /api/kt/start",
        )
        if started.status_code == 200:
            data = started.json()
            self.attempt_id = data.get("attempt_id")
            self.answers = {q["id"]: "Load test answer" for q in data.get("questions", [])}

    @task(5)
    def status(self):
        if self.attempt_id:
            self.client.get(
                f"/api/kt/attempt/{self.attempt_id}",
                name="GET /api/kt/attempt/[id]",
            )

    @task(3)
    def autosave(self):
        if self.attempt_id:
            self.client.post(
                "/api/kt/save",
                json={"attempt_id": self.attempt_id, "answers": self.answers},
                name="POST /api/kt/save",
            )
