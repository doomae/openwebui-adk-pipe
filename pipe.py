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
import subprocess

import asyncio
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
        PREFERRED_LANGUAGE: str = Field(
            default="English", description="Preferred Language"
        )
        STREAMING_DELAY: float | None = Field(
            default=None, description="Streaming Delay for smoother-looking output"
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
        try:
            auth_req = google.auth.transport.requests.Request()
            id_token = google.oauth2.id_token.fetch_id_token(
                auth_req,
                self.valves.APP_URL,
            )
        except:
            # brute-force workaround for local development, if fetch_id_token might somehow not work; might lead to
            # increased latency
            id_token = subprocess.check_output(
                ["gcloud", "auth", "print-identity-token"], text=True
            ).strip()
        return id_token

    async def _split_message(self, message: str) -> AsyncGenerator[str, Any]:
        for i in range(0, len(message), 5):
            if self.valves.STREAMING_DELAY:
                # create an artificial delay to make streaming look smoother in
                await asyncio.sleep(self.valves.STREAMING_DELAY)
            yield message[i : i + 5]

    async def _create_streaming_chunk(self, chunk):
        generic_streaming_chunk = {
            "created": time.time(),
            "model": self.valves.APP_NAME,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": chunk, "role": "assistant"}}],
        }
        return f"data: {json.dumps(generic_streaming_chunk)}"

    def _prepare_user_input(self, conversation):
        """Prepare user input based on conversation length."""
        if len(conversation) == 1:
            return json.dumps(conversation)
        else:
            return (
                "You need to take over from another agent and help the user, here is the conversation so far with the last user question at the end: "
                + json.dumps(conversation)
            )

    def _initialize_session(self, user_id, session_id):
        """Initialize ADK session with user preferences."""
        session_url = f"{self.valves.APP_URL}/apps/{self.valves.APP_NAME}/users/{user_id}/sessions/{session_id}"
        token = self.get_identity_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {"state": {"preferred_language": self.valves.PREFERRED_LANGUAGE}}

        # Initialize ADK session
        requests.post(session_url, headers=headers, json=data)
        return token

    def _build_sse_request_payload(self, user_id, session_id, user_input):
        """Build the payload for the SSE request to ADK."""
        return {
            "app_name": self.valves.APP_NAME,
            "user_id": user_id,
            "session_id": session_id,
            "new_message": {
                "role": "user",
                "parts": [{"text": user_input}],
            },
            "streaming": True,
        }

    async def _handle_text_content(self, text_content):
        """Handle streaming text content by splitting into chunks."""
        async for chunk in self._split_message(text_content):
            yield await self._create_streaming_chunk(chunk)

    async def _handle_function_call(self, part, event_emitter):
        """Handle function call events with status updates and formatted output."""
        await event_emitter({
            "type": "status",
            "data": {
                "description": "⊙ Executing tool...",
                "done": False,
                "hidden": False,
            },
        })

        text_content = json.dumps(part["functionCall"])
        yield await self._create_streaming_chunk(
            "<details>\n<summary>Function Call:</summary>\n```json\n"
        )

        pretty_json = json.dumps(json.loads(text_content), indent=4)
        yield await self._create_streaming_chunk(pretty_json)
        yield await self._create_streaming_chunk("\n```\n</details>\n")

    async def _handle_function_response(self, part, event_emitter):
        """Handle function response events with status updates and formatted output."""
        await event_emitter({
            "type": "status",
            "data": {
                "description": "✓ Tool execution completed",
                "done": True,
                "hidden": False,
            },
        })

        text_content = json.dumps(part["functionResponse"])
        yield await self._create_streaming_chunk(
            "<details>\n<summary>Function Response:</summary>\n```json\n"
        )

        pretty_json = json.dumps(json.loads(text_content), indent=4)
        yield await self._create_streaming_chunk(pretty_json)
        yield await self._create_streaming_chunk("\n```\n</details>\n")

    async def _handle_actions(self, actions):
        """Handle action events with formatted output."""
        text_content = json.dumps(actions)
        yield await self._create_streaming_chunk(
            "<details>\n<summary>Action:</summary>\n"
        )

        async for chunk in self._split_message(text_content):
            yield await self._create_streaming_chunk(chunk)

        yield await self._create_streaming_chunk("\n</details>\n")

    async def _stream_response(self, metadata, user, event_emitter, conversation):
        """Main streaming response handler that coordinates the entire flow."""
        # Prepare input and extract user/session info
        user_input = self._prepare_user_input(conversation)
        user_id = user["id"]
        session_id = metadata["chat_id"]

        # Initialize session and get auth token
        token = self._initialize_session(user_id, session_id)

        # Build request payload
        payload = self._build_sse_request_payload(user_id, session_id, user_input)

        # Create headers for the SSE request
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        # Stream the response from ADK
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.valves.APP_URL}/run_sse",
                headers=headers,
                data=json.dumps(payload),
            ) as response:
                async for chunk in self._process_sse_stream(response, event_emitter):
                    yield chunk

    async def _process_sse_stream(self, response, event_emitter):
        """Process the Server-Sent Events stream from ADK."""
        async for line in response.content:
            line = line.decode("utf-8").strip()
            print(line)

            # Skip empty lines
            if not line:
                continue

            # Parse SSE data
            if line.startswith("data: "):
                data = line[6:]  # Remove 'data: ' prefix

                try:
                    event = json.loads(data)
                    async for chunk in self._handle_event(event, event_emitter):
                        yield chunk
                except json.JSONDecodeError:
                    continue  # Skip invalid JSON

    async def _handle_event(self, event, event_emitter):
        """Handle different types of events from the SSE stream."""
        if "content" in event and "parts" in event["content"]:
            async for chunk in self._handle_content_parts(event, event_emitter):
                yield chunk
        elif "actions" in event:
            async for chunk in self._handle_actions(event["actions"]):
                yield chunk

    async def _handle_content_parts(self, event, event_emitter):
        """Handle content parts from the event."""
        parts = event["content"]["parts"]
        for part in parts:
            if "text" in part and event.get("partial", False):
                async for chunk in self._handle_text_content(part["text"]):
                    yield chunk
            elif "functionCall" in part:
                async for chunk in self._handle_function_call(part, event_emitter):
                    yield chunk
            elif "functionResponse" in part:
                async for chunk in self._handle_function_response(part, event_emitter):
                    yield chunk

    async def pipe(self, body, __metadata__, __event_emitter__, __user__, **kwargs):

        if not (self.valves.APP_URL and self.valves.APP_URL):
            raise ValueError(
                "At least one of the following valves is not set: APP_URL, APP_NAME."
            )

        return StreamingResponse(
            self._stream_response(__metadata__, __user__, __event_emitter__, body["messages"]),
            media_type="text/event-stream",
        )
