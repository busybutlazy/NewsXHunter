import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict
from urllib import error, request


class LineMessagingService:
    def __init__(
        self,
        *,
        channel_access_token: str | None = None,
        channel_secret: str | None = None,
    ):
        self.channel_access_token = channel_access_token or os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.channel_secret = channel_secret or os.getenv("LINE_CHANNEL_SECRET", "")

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        if not self.channel_secret or not signature:
            return False
        digest = hmac.new(
            self.channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    def push_text(self, *, line_user_id: str, message: str) -> Dict[str, Any]:
        payload = {
            "to": line_user_id,
            "messages": [{"type": "text", "text": message[:5000]}],
        }
        return self._post_json("https://api.line.me/v2/bot/message/push", payload)

    def reply_text(self, *, reply_token: str, message: str) -> Dict[str, Any]:
        payload = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": message[:5000]}],
        }
        return self._post_json("https://api.line.me/v2/bot/message/reply", payload)

    def _post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.channel_access_token:
            return {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN is missing"}

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {self.channel_access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as resp:
                return {
                    "ok": 200 <= resp.status < 300,
                    "status_code": resp.status,
                    "line_request_id": resp.headers.get("x-line-request-id"),
                }
        except error.HTTPError as exc:
            resp_body = exc.read().decode("utf-8", errors="ignore")
            return {
                "ok": False,
                "status_code": exc.code,
                "error": f"http_{exc.code}:{resp_body}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
