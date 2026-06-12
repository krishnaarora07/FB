from __future__ import annotations

import time
from pathlib import Path

from ..config import Settings
from ..http import ApiError, put_bytes, request_json


class ShotstackClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.require(settings.shotstack_api_key, "SHOTSTACK_API_KEY")

    @property
    def edit_base_url(self) -> str:
        return f"https://api.shotstack.io/edit/{self.settings.shotstack_version}"

    @property
    def ingest_base_url(self) -> str:
        return f"https://api.shotstack.io/ingest/{self.settings.shotstack_version}"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }

    def request_signed_upload(self) -> tuple[str, str]:
        """Request a signed upload URL from Shotstack ingest API.

        Returns (signed_url, source_id).
        """
        endpoint = f"{self.ingest_base_url}/upload"
        response = request_json("POST", endpoint, headers=self.headers)
        data = response.get("data", {})
        signed_url = data.get("attributes", {}).get("url", "")
        source_id = data.get("id", "")
        if not signed_url or not source_id:
            raise RuntimeError(f"Shotstack upload response missing url or id: {response}")
        return signed_url, source_id

    def wait_for_source(self, source_id: str, *, poll_seconds: int = 3, timeout_seconds: int = 120) -> str:
        """Poll GET /ingest/v1/sources/{id} until the source is ready.

        Returns the accessible URL for use in render timelines.
        """
        endpoint = f"{self.ingest_base_url}/sources/{source_id}"
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = request_json("GET", endpoint, headers=self.headers)
            data = response.get("data", response)
            attrs = data.get("attributes", data)
            status = attrs.get("status", "")
            print(f"  Source {source_id}: status={status}")
            if status == "ready":
                url = attrs.get("source") or attrs.get("url", "")
                if url:
                    return url
                raise RuntimeError(f"Source ready but no URL in response: {response}")
            if status == "failed":
                raise RuntimeError(f"Shotstack source ingest failed: {response}")
            time.sleep(poll_seconds)
        raise TimeoutError(f"Timed out waiting for Shotstack source {source_id}")

    def upload_file(self, path: Path, content_type: str = "audio/mpeg") -> str:
        """Upload a file via the Shotstack ingest API and return a render-accessible URL."""
        signed_url, source_id = self.request_signed_upload()
        # Include x-amz-acl header if the signed URL expects it.
        headers = {"x-amz-acl": "public-read"} if "x-amz-acl" in signed_url else None
        put_bytes(signed_url, path.read_bytes(), headers=headers, content_type=content_type)
        print(f"  Uploaded to Shotstack (source_id={source_id}), waiting for ingest...")
        # Poll until Shotstack has processed the file and it's accessible.
        return self.wait_for_source(source_id)

    def render(self, edit: dict) -> str:
        response = request_json("POST", f"{self.edit_base_url}/render", headers=self.headers, body=edit)
        render_id = (
            response.get("response", {}).get("id")
            or response.get("data", {}).get("id")
            or response.get("id")
        )
        if not render_id:
            raise RuntimeError(f"Shotstack render response did not include an id: {response}")
        return render_id

    def get_render(self, render_id: str) -> dict:
        return request_json("GET", f"{self.edit_base_url}/render/{render_id}", headers=self.headers)

    def wait_for_render(self, render_id: str, *, poll_seconds: int = 8, timeout_seconds: int = 1800) -> dict:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = self.get_render(render_id)
            status = self._find_status(response)
            if status in {"done", "failed"}:
                if status == "failed":
                    raise RuntimeError(f"Shotstack render failed: {response}")
                return response
            time.sleep(poll_seconds)
        raise TimeoutError(f"Timed out waiting for Shotstack render {render_id}")

    @staticmethod
    def _find_status(response: dict) -> str | None:
        candidates = [
            response.get("response", {}).get("status"),
            response.get("data", {}).get("attributes", {}).get("status"),
            response.get("status"),
        ]
        return next((item for item in candidates if item), None)

    @staticmethod
    def find_output_url(response: dict) -> str | None:
        candidates = [
            response.get("response", {}).get("url"),
            response.get("response", {}).get("output", {}).get("url"),
            response.get("data", {}).get("attributes", {}).get("url"),
            response.get("data", {}).get("attributes", {}).get("output", {}).get("url"),
            response.get("url"),
        ]
        return next((item for item in candidates if item), None)

