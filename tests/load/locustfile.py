import os
import random

from locust import HttpUser, between, task

# Read API Key from environment to easily switch (or default to test_key)
API_KEY = os.getenv("ARGOS_API_KEY", "test_key")


class ArgosTrafficUser(HttpUser):
    # Simulate a realistic wait time between user actions (0.5 to 2 seconds)
    wait_time = between(0.5, 2.0)

    @task(2)
    def test_run_async_endpoint(self):
        """
        Simulates heavy API client traffic triggering async workflow jobs.
        """
        payload = {
            "task": "Extract the data from the website quickly please",
            "require_confirmation": False,
            "max_steps": 5,
            "webhook_url": "https://webhook.site/dummy-webhook",
        }
        headers = {"Content-Type": "application/json", "X-ARGOS-API-KEY": API_KEY}

        with self.client.post(
            "/run_async", json=payload, headers=headers, catch_response=True
        ) as response:
            if response.status_code == 202:
                response.success()
            elif response.status_code == 429:
                response.success()  # Rate limit is a handled scenario, not an application crash!
            else:
                response.failure(
                    f"Got unexpected HTTP {response.status_code}: {response.text}"
                )

    @task(4)
    def test_telegram_chat_endpoint(self):
        """
        Simulates Telegram bot traffic via webhook payload.
        Rate limiting is distinct here because Telegram sends random user_ids.
        """
        # Randomize user_id out of a fixed tiny pool (1 to 5) to aggressively trigger the DB UPSERT rate-limit code
        user_id = random.randint(1, 5)

        payload = {
            "user_id": user_id,
            "chat_id": user_id,
            "first_name": "Locust",
            "username": f"locusto_{user_id}",
            "text": "Tell me a joke about concurrent connections",
        }
        headers = {"Content-Type": "application/json", "X-ARGOS-API-KEY": API_KEY}

        with self.client.post(
            "/telegram/chat", json=payload, headers=headers, catch_response=True
        ) as response:
            if response.status_code == 200:
                body = response.json()
                if body.get("status") in ["ok", "pending", "disabled", "error"]:
                    response.success()
                else:
                    response.failure(f"Unexpected JSON Status: {body}")
            elif (
                response.status_code == 429
            ):  # Explicit exception raise hook from FastAPI
                response.success()
            else:
                response.failure(
                    f"Got unexpected HTTP {response.status_code}: {response.text}"
                )
