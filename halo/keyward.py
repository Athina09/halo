import base64

import httpx


class KeywardError(Exception):
    pass


class Keyward:
    """Client for the Keyward broker. Halo holds only the agent token, never a real key."""

    def __init__(self, url: str, agent_token: str, client: httpx.Client | None = None):
        self._url = url.rstrip("/")
        self._agent = {"x-keyward-agent": agent_token}
        self._http = client or httpx.Client(timeout=10)

    def healthy(self) -> bool:
        try:
            r = self._http.get(f"{self._url}/health", timeout=3)
            return r.status_code == 200 and r.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False

    def new_pass(self, subject: str, routes: list[str], uses: int = 10, ttl: int = 600) -> dict:
        """A fresh task pass for one message. Returns the header to send with /use calls."""
        try:
            r = self._http.post(
                f"{self._url}/passes",
                headers=self._agent,
                json={"subject": subject[:64], "routes": routes, "uses": uses, "ttl": ttl},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise KeywardError(f"could not get a pass: {e}") from e
        return {"x-keyward-pass": r.json()["pass"]}

    def drop_pass(self, p: dict) -> None:
        try:
            self._http.request("DELETE", f"{self._url}/passes", headers=p)
        except httpx.HTTPError:
            pass  # the pass expires on its own

    def verify_whatsapp(self, raw: bytes, signature: str) -> bool:
        return bool(self._proof("/verify/whatsapp", raw, signature).get("valid"))

    def forward_inbound(self, raw: bytes, signature: str) -> bool:
        """Hand the owner's raw message to Keyward. True if Keyward handled it (YES/NO/FREEZE...)."""
        return bool(self._proof("/channels/whatsapp/inbound", raw, signature).get("handled"))

    def send_whatsapp(self, p: dict, phone_number_id: str, payload: dict) -> None:
        try:
            r = self._http.post(
                f"{self._url}/use/whatsapp/v21.0/{phone_number_id}/messages",
                headers=p,
                json={"messaging_product": "whatsapp", **payload},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise KeywardError(f"could not send WhatsApp message: {e}") from e

    def use_form(self, p: dict, route: str, path: str, data: dict) -> dict:
        """POST a form through a Keyward route (e.g. Twilio). Keyward adds the credential."""
        try:
            r = self._http.post(f"{self._url}/use/{route}{path}", headers=p, data=data)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise KeywardError(f"{route} call failed: {e}") from e

    def _proof(self, path: str, raw: bytes, signature: str) -> dict:
        try:
            r = self._http.post(
                f"{self._url}{path}",
                headers=self._agent,
                json={"payload_b64": base64.b64encode(raw).decode(), "signature": signature},
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise KeywardError(f"{path} failed: {e}") from e
