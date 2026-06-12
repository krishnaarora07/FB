from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


def _url_with_params(url: str, params: dict | None) -> str:
    if not params:
        return url
    query = urlencode(params, doseq=True)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def _error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return f"{exc.code} {exc.reason}: {body[:1200]}"


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    body: dict | None = None,
    timeout: int = 60,
) -> dict:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = Request(_url_with_params(url, params), data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raise ApiError(_error_message(exc)) from exc
    except URLError as exc:
        raise ApiError(str(exc)) from exc

    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def request_bytes(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    body: dict | None = None,
    timeout: int = 120,
) -> bytes:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = Request(_url_with_params(url, params), data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise ApiError(_error_message(exc)) from exc
    except URLError as exc:
        raise ApiError(str(exc)) from exc


def put_bytes(url: str, data: bytes, *, headers: dict[str, str] | None = None, content_type: str, timeout: int = 240) -> None:
    req_headers = {"Content-Type": content_type}
    if headers:
        req_headers.update(headers)
    request = Request(url, data=data, headers=req_headers, method="PUT")
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
    except HTTPError as exc:
        raise ApiError(_error_message(exc)) from exc
    except URLError as exc:
        raise ApiError(str(exc)) from exc

