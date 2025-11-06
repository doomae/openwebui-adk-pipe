"""
title: PowerPoint Generator Pipe
author: Dominik Nowatschin
author_url: https://github.com/doomae
git_url: https://github.com/doomae/openwebui-adk-pipe
description: Pipe code to connect agents running with ADK in Cloud Run as models in Open WebUI.
required_open_webui_version: 0.6.26
version: 0.1
"""

from pydantic import BaseModel, Field
import json
import time
from typing import Any, AsyncGenerator

import aiohttp
import google.auth.transport.requests
import google.oauth2.id_token

from starlette.responses import StreamingResponse

import requests


class Pipe:
    class Valves(BaseModel):
        APP_URL: str = Field(
            default="",
            description="ADK App URL",
        )
        APP_NAME: str = Field(
            default="", description="ADK App Name"
        )
        MODEL_NAME: str = Field(
            default="", description="Model Name"
        )
        PREFERRED_LANGUAGE: str = Field(
            default="English", description="Preferred Language"
        )


    def __init__(self):
        # Initialize 'valves' with specific configurations. Using 'Valves' instance helps encapsulate settings,
        # which ensures settings are managed cohesively and not confused with operational flags like 'file_handler'.
        self.valves = self.Valves()

    def get_identity_token(self):
        """
        Get an OAuth token for the specified service.

        This function uses the google.auth library to fetch an OAuth token for the given service URL (accessor).
        """
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(
            auth_req,
            self.valves.APP_URL,
        )
        return id_token

    async def _split_message(self, message: str) -> AsyncGenerator[str, Any]:
        for i in range(0, len(message), 10):
            yield message[i : i + 10]

    async def _create_streaming_chunk(self, chunk):
        generic_streaming_chunk = {
            "created": time.time(),
            "model": self.valves.MODEL_NAME,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": chunk, "role": "assistant"}}],
        }
        return f"data: {json.dumps(generic_streaming_chunk)}"

    async def _stream_response(self, metadata, user, event_emitter, conversation):
        if len(conversation) == 1:
            user_input = json.dumps(conversation)
        else:
            user_input = (
                "You need to take over from another agent and help the user, here is the conversation so far with the last user question at the end: "
                + json.dumps(conversation)
            )

        user = user["id"]

        # session in ADK should correspond to chat in Open WebUI
        session_id = metadata["chat_id"]

        session_url = f"{self.valves.APP_URL}/apps/{self.valves.APP_NAME}/users/{user}/sessions/{session_id}"

        token = self.get_identity_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {"state": {"preferred_language": self.valves.PREFERRED_LANGUAGE}}

        # initialize ADK session
        _ = requests.post(session_url, headers=headers, json=data)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.valves.APP_URL}/run_sse",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                data=json.dumps(
                    {
                        "app_name": self.valves.APP_NAME,
                        "user_id": user,
                        "session_id": session_id,
                        "new_message": {
                            "role": "user",
                            "parts": [{"text": user_input}],
                        },
                        "streaming": True,
                    }
                ),
            ) as r:
                async for line in r.content:
                    line = line.decode("utf-8").strip()
                    print(line)

                    # Skip empty lines
                    if not line:
                        continue

                    if line.startswith("data: "):
                        # Remove 'data: ' prefix
                        data = line[6:]
                    event = json.loads(data)
                    if "content" in event:
                        if "parts" in event["content"]:
                            parts = event["content"]["parts"]
                            for part in parts:
                                if "text" in part and event.get("partial", False):
                                    text_content = part["text"]
                                    # split the message to create nice streaming effect
                                    async for chunk in self._split_message(
                                        text_content
                                    ):
                                        generic_streaming_chunk = (
                                            await self._create_streaming_chunk(chunk)
                                        )
                                        yield generic_streaming_chunk
                                elif "functionCall" in part:
                                    await event_emitter(
                                        {
                                            "type": "status",
                                            "data": {
                                                "description": "⊙ Executing tool...",
                                                "done": False,
                                                "hidden": False,
                                            },
                                        }
                                    )
                                    text_content = json.dumps(part["functionCall"])
                                    yield await self._create_streaming_chunk(
                                        "<details>\n<summary>Function Call:</summary>\n```json\n"
                                    )
                                    pretty_json = json.dumps(
                                        json.loads(text_content), indent=4
                                    )
                                    generic_streaming_chunk = (
                                        await self._create_streaming_chunk(pretty_json)
                                    )
                                    yield generic_streaming_chunk
                                    yield await self._create_streaming_chunk(
                                        "\n```\n</details>\n"
                                    )
                                elif "functionResponse" in part:
                                    await event_emitter(
                                        {
                                            "type": "status",
                                            "data": {
                                                "description": "✓ Tool execution completed",
                                                "done": True,
                                                "hidden": False,
                                            },
                                        }
                                    )
                                    text_content = json.dumps(part["functionResponse"])
                                    yield await self._create_streaming_chunk(
                                        "<details>\n<summary>Function Response:</summary>\n```json\n"
                                    )
                                    pretty_json = json.dumps(
                                        json.loads(text_content), indent=4
                                    )
                                    generic_streaming_chunk = (
                                        await self._create_streaming_chunk(pretty_json)
                                    )
                                    yield generic_streaming_chunk
                                    yield await self._create_streaming_chunk(
                                        "\n```\n</details>\n"
                                    )
                                else:
                                    continue
                    elif "actions" in event:
                        text_content = json.dumps(event["actions"])
                        yield await self._create_streaming_chunk(
                            "<details>\n<summary>Action:</summary>\n"
                        )
                        async for chunk in self._split_message(text_content):
                            generic_streaming_chunk = (
                                await self._create_streaming_chunk(chunk)
                            )
                            yield generic_streaming_chunk
                        yield await self._create_streaming_chunk("\n</details>\n")

    async def pipe(self, body, __metadata__, __event_emitter__, __user__, **kwargs):

        if not (self.valves.APP_URL and self.valves.APP_URL and self.valves.MODEL_NAME):
            raise ValueError(
                "At least one of the following valves is not set: APP_URL, APP_NAME, MODEL_NAME."
            )

        return StreamingResponse(
            self._stream_response(__metadata__, __user__, __event_emitter__, body["messages"]),
            media_type="text/event-stream",
        )
