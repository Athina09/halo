import httpx


class OllamaError(Exception):
    """Ollama is down, too slow, or returned something we cannot use.

    kind is "down", "slow" or "invalid". Down and slow switch the person to buttons at once;
    invalid does so only the second time.
    """

    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.kind = kind


class Ollama:
    def __init__(self, url: str, model: str, timeout: float = 20, client: httpx.Client | None = None):
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._http = client or httpx.Client()

    def reachable(self) -> bool:
        try:
            return self._http.get(f"{self._url}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One chat turn. Returns the assistant message: {"content": str, "tool_calls": [...]}."""
        body = {"model": self._model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        try:
            r = self._http.post(f"{self._url}/api/chat", json=body, timeout=self._timeout)
            r.raise_for_status()
            msg = r.json()["message"]
        except httpx.TimeoutException as e:
            raise OllamaError(f"timed out after {self._timeout}s", "slow") from e
        except httpx.HTTPError as e:
            raise OllamaError(f"request failed: {e}", "down") from e
        except (ValueError, KeyError, TypeError) as e:
            raise OllamaError(f"invalid reply: {e}") from e
        if not isinstance(msg, dict):
            raise OllamaError("invalid reply: message is not an object")
        msg.setdefault("content", "")
        msg["tool_calls"] = msg.get("tool_calls") or []
        return msg
