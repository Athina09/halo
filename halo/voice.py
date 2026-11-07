from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response

from .calls import Calls

XML = "application/xml"


def build_voice_router(calls: Calls) -> APIRouter:
    router = APIRouter()

    def reply(xml: str | None) -> Response:
        return Response(content=xml, media_type=XML) if xml else Response(status_code=404)

    async def form(request: Request) -> dict:
        return {k: v[0] for k, v in parse_qs((await request.body()).decode(errors="replace")).items()}

    @router.api_route("/voice/{token}", methods=["GET", "POST"])
    def intro(token: str):
        return reply(calls.intro(token))

    @router.post("/voice/{token}/answer")
    async def answer(token: str, request: Request):
        return reply(calls.answer(token, (await form(request)).get("SpeechResult", "")))

    @router.post("/voice/{token}/status")
    async def status(token: str, request: Request):
        calls.status(token, (await form(request)).get("CallStatus", ""))
        return Response(status_code=204)

    return router
