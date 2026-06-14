from __future__ import annotations

import time

from ..config import Settings
from ..http import request_json


class CreatomateClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.require(settings.creatomate_api_key, "CREATOMATE_API_KEY")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    def render(self, source: dict) -> str:
        """Sends the JSON source to Creatomate to start a render.
        
        Returns the Render ID.
        """
        payload = {"source": source}
        response = request_json("POST", "https://api.creatomate.com/v1/renders", headers=self.headers, body=payload)
        
        # The API normally returns an array of renders if we didn't specify multiple, it's just one.
        if isinstance(response, list) and len(response) > 0:
            render_id = response[0].get("id")
        else:
            render_id = response.get("id")

        if not render_id:
            raise RuntimeError(f"Creatomate render response missing ID: {response}")
            
        return render_id

    def get_render(self, render_id: str) -> dict:
        """Gets the current status of a render."""
        response = request_json("GET", f"https://api.creatomate.com/v1/renders/{render_id}", headers=self.headers)
        if isinstance(response, list) and len(response) > 0:
            return response[0]
        return response

    def wait_for_render(self, render_id: str, *, poll_seconds: int = 5, timeout_seconds: int = 1800) -> dict:
        """Polls until the render is complete or fails."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = self.get_render(render_id)
            status = response.get("status", "")
            
            if status in {"succeeded", "failed"}:
                if status == "failed":
                    raise RuntimeError(f"Creatomate render failed: {response.get('error_message')}")
                return response
                
            print(f"  Creatomate render status: {status}...")
            time.sleep(poll_seconds)
            
        raise TimeoutError(f"Timed out waiting for Creatomate render {render_id}")

    @staticmethod
    def find_output_url(response: dict) -> str | None:
        return response.get("url")
