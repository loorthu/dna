"""Tests for the Vexa Transcription Provider."""

import asyncio
import json
from datetime import datetime
from unittest import mock

import httpx
import pytest

from dna.models.transcription import (
    BotSession,
    BotStatus,
    BotStatusEnum,
    Platform,
    Transcript,
    TranscriptSegment,
)
from dna.transcription_providers.vexa import VexaTranscriptionProvider


@pytest.fixture
def vexa_provider():
    """Create a VexaTranscriptionProvider with mocked environment variables."""
    with mock.patch.dict(
        "os.environ",
        {
            "VEXA_API_URL": "https://api.test.vexa.ai",
            "VEXA_API_KEY": "test-api-key",
        },
    ):
        provider = VexaTranscriptionProvider()
        yield provider


class TestVexaProviderInit:
    """Tests for VexaTranscriptionProvider initialization."""

    def test_init_uses_default_url(self):
        """Test that provider uses default URL when env var not set."""
        with mock.patch.dict("os.environ", {}, clear=True):
            provider = VexaTranscriptionProvider()
            assert provider.base_url == "https://api.cloud.vexa.ai"
            assert provider.api_key == ""

    def test_init_uses_env_vars(self, vexa_provider):
        """Test that provider uses environment variables."""
        assert vexa_provider.base_url == "https://api.test.vexa.ai"
        assert vexa_provider.api_key == "test-api-key"

    def test_init_internal_state(self, vexa_provider):
        """Test that internal state is initialized correctly."""
        assert vexa_provider._client is None
        assert vexa_provider._ws_connection is None
        assert vexa_provider._ws_task is None
        assert vexa_provider._subscribed_meetings == {}
        assert vexa_provider._meeting_id_to_key == {}
        assert vexa_provider._pending_subscriptions == []


class TestVexaProviderWsUrl:
    """Tests for ws_url property."""

    def test_ws_url_converts_https_to_wss(self, vexa_provider):
        """Test that https is converted to wss."""
        vexa_provider.base_url = "https://api.test.vexa.ai"
        assert vexa_provider.ws_url == "wss://api.test.vexa.ai/ws"

    def test_ws_url_converts_http_to_ws(self, vexa_provider):
        """Test that http is converted to ws."""
        vexa_provider.base_url = "http://localhost:8000"
        assert vexa_provider.ws_url == "ws://localhost:8000/ws"

    def test_ws_url_handles_trailing_slash(self, vexa_provider):
        """Test that trailing slash is handled."""
        vexa_provider.base_url = "https://api.test.vexa.ai/"
        assert vexa_provider.ws_url == "wss://api.test.vexa.ai/ws"

    def test_ws_url_defaults_to_wss(self, vexa_provider):
        """Test that URL without protocol defaults to wss."""
        vexa_provider.base_url = "api.test.vexa.ai"
        assert vexa_provider.ws_url == "wss://api.test.vexa.ai/ws"


class TestVexaProviderClient:
    """Tests for client property."""

    def test_client_creates_client_on_first_access(self, vexa_provider):
        """Test that client is created on first access."""
        assert vexa_provider._client is None
        client = vexa_provider.client
        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        assert vexa_provider._client is client

    def test_client_returns_same_client_on_subsequent_access(self, vexa_provider):
        """Test that same client is returned on subsequent access."""
        client1 = vexa_provider.client
        client2 = vexa_provider.client
        assert client1 is client2


class TestDispatchBot:
    """Tests for dispatch_bot method."""

    @pytest.mark.asyncio
    async def test_dispatch_bot_success(self, vexa_provider):
        """Test successful bot dispatch."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"meeting_id": 12345}
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.post.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.dispatch_bot(
            platform=Platform.GOOGLE_MEET,
            meeting_id="abc-defg-hij",
            playlist_id=42,
        )

        assert isinstance(result, BotSession)
        assert result.platform == Platform.GOOGLE_MEET
        assert result.meeting_id == "abc-defg-hij"
        assert result.playlist_id == 42
        assert result.status == BotStatusEnum.JOINING
        assert result.vexa_meeting_id == 12345

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/bots"
        payload = call_args[1]["json"]
        assert payload["platform"] == "google_meet"
        assert payload["native_meeting_id"] == "abc-defg-hij"

    @pytest.mark.asyncio
    async def test_dispatch_bot_with_optional_params(self, vexa_provider):
        """Test bot dispatch with optional parameters."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"id": 99999}
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.post.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.dispatch_bot(
            platform=Platform.TEAMS,
            meeting_id="teams-meeting-123",
            playlist_id=100,
            passcode="1234",
            bot_name="DNA Bot",
            language="en-US",
        )

        assert result.bot_name == "DNA Bot"
        assert result.language == "en-US"
        assert result.vexa_meeting_id == 99999

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["passcode"] == "1234"
        assert payload["bot_name"] == "DNA Bot"
        assert payload["language"] == "en-US"


class TestStopBot:
    """Tests for stop_bot method."""

    @pytest.mark.asyncio
    async def test_stop_bot_success(self, vexa_provider):
        """Test successful bot stop."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200

        mock_client = mock.AsyncMock()
        mock_client.delete.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.stop_bot(Platform.GOOGLE_MEET, "abc-defg-hij")

        assert result is True
        mock_client.delete.assert_called_once_with("/bots/google_meet/abc-defg-hij")

    @pytest.mark.asyncio
    async def test_stop_bot_failure(self, vexa_provider):
        """Test bot stop failure."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 404

        mock_client = mock.AsyncMock()
        mock_client.delete.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.stop_bot(Platform.TEAMS, "unknown-meeting")

        assert result is False


class TestGetBotStatus:
    """Tests for get_bot_status method."""

    @pytest.mark.asyncio
    async def test_get_bot_status_found(self, vexa_provider):
        """Test getting status when meeting is found."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "meetings": [
                {
                    "platform": "google_meet",
                    "native_meeting_id": "abc-defg-hij",
                    "status": "active",
                }
            ]
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_bot_status(
            Platform.GOOGLE_MEET, "abc-defg-hij"
        )

        assert isinstance(result, BotStatus)
        assert result.platform == Platform.GOOGLE_MEET
        assert result.meeting_id == "abc-defg-hij"
        assert result.status == BotStatusEnum.IN_CALL
        assert result.message == "active"

    @pytest.mark.asyncio
    async def test_get_bot_status_not_found(self, vexa_provider):
        """Test getting status when meeting is not found."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"meetings": []}
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_bot_status(Platform.TEAMS, "unknown-meeting")

        assert result.status == BotStatusEnum.IDLE
        assert result.message == "Meeting not found"

    @pytest.mark.asyncio
    async def test_get_bot_status_various_statuses(self, vexa_provider):
        """Test status mapping for various Vexa statuses."""
        status_mappings = [
            ("requested", BotStatusEnum.JOINING),
            ("joining", BotStatusEnum.JOINING),
            ("awaiting_admission", BotStatusEnum.WAITING_ROOM),
            ("active", BotStatusEnum.IN_CALL),
            ("in_call", BotStatusEnum.IN_CALL),
            ("transcribing", BotStatusEnum.TRANSCRIBING),
            ("recording", BotStatusEnum.TRANSCRIBING),
            ("failed", BotStatusEnum.FAILED),
            ("stopped", BotStatusEnum.STOPPED),
            ("completed", BotStatusEnum.COMPLETED),
            ("ended", BotStatusEnum.COMPLETED),
            ("unknown_status", BotStatusEnum.IDLE),
        ]

        for vexa_status, expected_status in status_mappings:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                "meetings": [
                    {
                        "platform": "google_meet",
                        "native_meeting_id": "test-meeting",
                        "status": vexa_status,
                    }
                ]
            }
            mock_response.raise_for_status = mock.MagicMock()
            mock_response.is_error = False

            mock_client = mock.AsyncMock()
            mock_client.get.return_value = mock_response
            vexa_provider._client = mock_client

            result = await vexa_provider.get_bot_status(
                Platform.GOOGLE_MEET, "test-meeting"
            )
            assert result.status == expected_status, f"Failed for status: {vexa_status}"

    @pytest.mark.asyncio
    async def test_get_bot_status_http_error(self, vexa_provider):
        """Test handling HTTP errors."""
        mock_client = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=mock.MagicMock(), response=mock.MagicMock()
        )
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_bot_status(
            Platform.GOOGLE_MEET, "test-meeting"
        )

        assert result.status == BotStatusEnum.IDLE
        assert result.message == "Failed to get status"

    @pytest.mark.asyncio
    async def test_get_bot_status_general_exception(self, vexa_provider):
        """Test handling general exceptions."""
        mock_client = mock.AsyncMock()
        mock_client.get.side_effect = Exception("Connection failed")
        vexa_provider._client = mock_client

        result = await vexa_provider.get_bot_status(
            Platform.GOOGLE_MEET, "test-meeting"
        )

        assert result.status == BotStatusEnum.IDLE
        assert "Connection failed" in result.message


class TestGetTranscript:
    """Tests for get_transcript method."""

    @pytest.mark.asyncio
    async def test_get_transcript_success(self, vexa_provider):
        """Test successful transcript retrieval."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "segments": [
                {
                    "text": "Hello everyone",
                    "speaker": "John",
                    "start_time": 0.0,
                    "end_time": 1.5,
                },
                {
                    "text": "Welcome to the meeting",
                    "speaker": "Jane",
                    "start_time": 2.0,
                    "end_time": 4.0,
                },
            ],
            "language": "en",
            "duration": 120.5,
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_transcript(
            Platform.GOOGLE_MEET, "abc-defg-hij"
        )

        assert isinstance(result, Transcript)
        assert result.platform == Platform.GOOGLE_MEET
        assert result.meeting_id == "abc-defg-hij"
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello everyone"
        assert result.segments[0].speaker == "John"
        assert result.language == "en"
        assert result.duration == 120.5

        mock_client.get.assert_called_once_with("/transcripts/google_meet/abc-defg-hij")

    @pytest.mark.asyncio
    async def test_get_transcript_empty_segments(self, vexa_provider):
        """Test transcript with no segments."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "segments": [],
            "language": "en",
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_transcript(Platform.TEAMS, "teams-meeting")

        assert result.segments == []


class TestGetActiveBots:
    """Tests for get_active_bots method."""

    @pytest.mark.asyncio
    async def test_get_active_bots_success(self, vexa_provider):
        """Test successful active bots retrieval."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "running_bots": [
                {
                    "platform": "google_meet",
                    "native_meeting_id": "abc-123",
                    "status": "active",
                },
                {
                    "platform": "teams",
                    "native_meeting_id": "def-456",
                    "status": "transcribing",
                },
            ]
        }
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.is_error = False

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_active_bots()

        assert len(result) == 2
        assert result[0]["platform"] == "google_meet"
        assert result[1]["platform"] == "teams"
        mock_client.get.assert_called_once_with("/bots/status")

    @pytest.mark.asyncio
    async def test_get_active_bots_http_error(self, vexa_provider):
        """Test handling HTTP errors."""
        mock_client = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=mock.MagicMock(), response=mock.MagicMock()
        )
        mock_client.get.return_value = mock_response
        vexa_provider._client = mock_client

        result = await vexa_provider.get_active_bots()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_bots_general_exception(self, vexa_provider):
        """Test handling general exceptions."""
        mock_client = mock.AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        vexa_provider._client = mock_client

        result = await vexa_provider.get_active_bots()

        assert result == []


class TestRegisterMeetingIdMapping:
    """Tests for register_meeting_id_mapping method."""

    def test_register_meeting_id_mapping(self, vexa_provider):
        """Test registering a meeting ID mapping."""
        vexa_provider.register_meeting_id_mapping(123, "google_meet", "abc-defg-hij")

        assert vexa_provider._meeting_id_to_key[123] == "google_meet:abc-defg-hij"

    def test_register_multiple_mappings(self, vexa_provider):
        """Test registering multiple mappings."""
        vexa_provider.register_meeting_id_mapping(1, "google_meet", "meet-1")
        vexa_provider.register_meeting_id_mapping(2, "teams", "teams-2")

        assert vexa_provider._meeting_id_to_key[1] == "google_meet:meet-1"
        assert vexa_provider._meeting_id_to_key[2] == "teams:teams-2"


class TestWebSocketHandlers:
    """Tests for WebSocket message handlers."""

    @pytest.mark.asyncio
    async def test_handle_ws_message_subscribed(self, vexa_provider):
        """Test handling subscribed message."""
        vexa_provider._pending_subscriptions = ["google_meet:abc-123"]

        await vexa_provider._handle_ws_message(
            {"type": "subscribed", "meetings": [{"id": 456}]}
        )

        assert vexa_provider._meeting_id_to_key[456] == "google_meet:abc-123"
        assert vexa_provider._pending_subscriptions == []

    @pytest.mark.asyncio
    async def test_handle_ws_message_subscribed_with_int_meeting(self, vexa_provider):
        """Test handling subscribed message with integer meeting ID."""
        vexa_provider._pending_subscriptions = ["teams:teams-meeting"]

        await vexa_provider._handle_ws_message(
            {"type": "subscribed", "meetings": [789]}
        )

        assert vexa_provider._meeting_id_to_key[789] == "teams:teams-meeting"

    @pytest.mark.asyncio
    async def test_handle_ws_message_error(self, vexa_provider):
        """Test handling error message (should log but not raise)."""
        await vexa_provider._handle_ws_message({"type": "error", "error": "Test error"})

    @pytest.mark.asyncio
    async def test_handle_ws_message_pong(self, vexa_provider):
        """Test handling pong message (should be ignored)."""
        await vexa_provider._handle_ws_message({"type": "pong"})

    @pytest.mark.asyncio
    async def test_handle_ws_message_transcript(self, vexa_provider):
        """Test handling the new flat `transcript` frame from Vexa WS."""
        callback_called = False
        callback_event = None
        callback_data = {}

        async def callback(event_type, data):
            nonlocal callback_called, callback_event, callback_data
            callback_called = True
            callback_event = event_type
            callback_data = data

        vexa_provider._meeting_id_to_key[100] = "google_meet:abc-123"
        vexa_provider._subscribed_meetings["google_meet:abc-123"] = callback

        confirmed = [{"segment_id": "s1", "text": "Hello"}]
        pending = [{"segment_id": "s2", "text": "world"}]
        await vexa_provider._handle_ws_message(
            {
                "type": "transcript",
                "meeting": {"id": 100},
                "speaker": "Alice",
                "confirmed": confirmed,
                "pending": pending,
                "ts": "2026-04-20T19:00:00.000Z",
            }
        )

        assert callback_called
        assert callback_event == "transcript.updated"
        assert callback_data["platform"] == "google_meet"
        assert callback_data["meeting_id"] == "abc-123"
        assert callback_data["speaker"] == "Alice"
        assert callback_data["confirmed"] == confirmed
        assert callback_data["pending"] == pending
        assert callback_data["ts"] == "2026-04-20T19:00:00.000Z"

    @pytest.mark.asyncio
    async def test_handle_ws_message_transcript_defaults_empty_lists(
        self, vexa_provider
    ):
        """Missing `confirmed`/`pending` keys default to empty lists."""
        callback_data = {}

        async def callback(event_type, data):
            callback_data.update(data)

        vexa_provider._meeting_id_to_key[100] = "google_meet:abc-123"
        vexa_provider._subscribed_meetings["google_meet:abc-123"] = callback

        await vexa_provider._handle_ws_message(
            {"type": "transcript", "meeting": {"id": 100}}
        )

        assert callback_data["confirmed"] == []
        assert callback_data["pending"] == []

    @pytest.mark.asyncio
    async def test_handle_ws_message_transcript_unknown_meeting(self, vexa_provider):
        """Test handling transcript for unknown meeting."""
        await vexa_provider._handle_ws_message(
            {
                "type": "transcript",
                "meeting": {"id": 999},
                "confirmed": [],
                "pending": [],
            }
        )

    @pytest.mark.asyncio
    async def test_handle_ws_message_transcript_no_callback(self, vexa_provider):
        """Test handling transcript with no registered callback."""
        vexa_provider._meeting_id_to_key[100] = "google_meet:abc-123"

        await vexa_provider._handle_ws_message(
            {
                "type": "transcript",
                "meeting": {"id": 100},
                "confirmed": [],
                "pending": [],
            }
        )

    @pytest.mark.asyncio
    async def test_handle_ws_message_meeting_status(self, vexa_provider):
        """Test handling meeting.status message."""
        callback_called = False

        async def callback(event_type, data):
            nonlocal callback_called
            callback_called = True

        vexa_provider._subscribed_meetings["google_meet:abc-123"] = callback

        await vexa_provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting": {
                    "id": 200,
                    "platform": "google_meet",
                    "native_id": "abc-123",
                },
                "payload": {"status": "active"},
                "ts": "2024-01-01T00:00:00Z",
            }
        )

        assert callback_called
        assert vexa_provider._meeting_id_to_key[200] == "google_meet:abc-123"

    @pytest.mark.asyncio
    async def test_handle_ws_message_meeting_status_no_callback(self, vexa_provider):
        """Test handling meeting.status without callback."""
        await vexa_provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting": {
                    "id": 200,
                    "platform": "google_meet",
                    "native_id": "abc-123",
                },
                "payload": {"status": "active"},
            }
        )

    @pytest.mark.asyncio
    async def test_handle_ws_message_meeting_status_empty_key(self, vexa_provider):
        """Test handling meeting.status with empty platform/native_id."""
        await vexa_provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting": {"id": 200, "platform": "", "native_id": ""},
                "payload": {"status": "active"},
            }
        )

        assert 200 not in vexa_provider._meeting_id_to_key

    @pytest.mark.asyncio
    async def test_handle_ws_message_unhandled_type(self, vexa_provider):
        """Test handling unhandled message type."""
        await vexa_provider._handle_ws_message({"type": "unknown.type"})


class TestSubscribeToMeeting:
    """Tests for subscribe_to_meeting method."""

    @pytest.mark.asyncio
    async def test_subscribe_to_meeting(self, vexa_provider):
        """Test subscribing to a meeting."""
        mock_ws = mock.AsyncMock()
        vexa_provider._ws_connection = mock_ws

        async def dummy_callback(event_type, data):
            pass

        with mock.patch.object(
            vexa_provider, "_ensure_ws_connection", new_callable=mock.AsyncMock
        ):
            await vexa_provider.subscribe_to_meeting(
                "google_meet", "abc-123", dummy_callback
            )

        assert "google_meet:abc-123" in vexa_provider._subscribed_meetings
        assert "google_meet:abc-123" in vexa_provider._pending_subscriptions
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["action"] == "subscribe"
        assert sent_msg["meetings"][0]["platform"] == "google_meet"
        assert sent_msg["meetings"][0]["native_id"] == "abc-123"


class TestUnsubscribeFromMeeting:
    """Tests for unsubscribe_from_meeting method."""

    @pytest.mark.asyncio
    async def test_unsubscribe_from_meeting(self, vexa_provider):
        """Test unsubscribing from a meeting."""
        mock_ws = mock.MagicMock()
        mock_ws.closed = False
        mock_ws.send = mock.AsyncMock()
        vexa_provider._ws_connection = mock_ws

        async def dummy_callback(event_type, data):
            pass

        vexa_provider._subscribed_meetings["google_meet:abc-123"] = dummy_callback

        await vexa_provider.unsubscribe_from_meeting("google_meet", "abc-123")

        assert "google_meet:abc-123" not in vexa_provider._subscribed_meetings
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["action"] == "unsubscribe"

    @pytest.mark.asyncio
    async def test_unsubscribe_from_meeting_closed_connection(self, vexa_provider):
        """Test unsubscribing when connection is closed."""
        mock_ws = mock.MagicMock()
        mock_ws.closed = True
        mock_ws.send = mock.AsyncMock()
        vexa_provider._ws_connection = mock_ws

        vexa_provider._subscribed_meetings["google_meet:abc-123"] = lambda: None

        await vexa_provider.unsubscribe_from_meeting("google_meet", "abc-123")

        assert "google_meet:abc-123" not in vexa_provider._subscribed_meetings
        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_from_meeting_no_connection(self, vexa_provider):
        """Test unsubscribing when there is no connection."""
        vexa_provider._subscribed_meetings["google_meet:abc-123"] = lambda: None

        await vexa_provider.unsubscribe_from_meeting("google_meet", "abc-123")

        assert "google_meet:abc-123" not in vexa_provider._subscribed_meetings


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_cleans_up_all_resources(self, vexa_provider):
        """Test that close cleans up all resources."""
        mock_ws = mock.AsyncMock()
        mock_client = mock.AsyncMock()

        async def cancelled_coro():
            raise asyncio.CancelledError()

        mock_ws_task = asyncio.create_task(cancelled_coro())
        await asyncio.sleep(0)

        vexa_provider._ws_task = mock_ws_task
        vexa_provider._ws_connection = mock_ws
        vexa_provider._client = mock_client

        await vexa_provider.close()

        mock_ws.close.assert_called_once()
        mock_client.aclose.assert_called_once()

        assert vexa_provider._ws_task is None
        assert vexa_provider._ws_connection is None
        assert vexa_provider._client is None

    @pytest.mark.asyncio
    async def test_close_handles_no_resources(self, vexa_provider):
        """Test that close handles case when no resources exist."""
        await vexa_provider.close()


class TestWsListener:
    """Tests for _ws_listener method."""

    @pytest.mark.asyncio
    async def test_ws_listener_handles_connection_closed(self, vexa_provider):
        """Test that listener handles connection closed."""
        from websockets.exceptions import ConnectionClosed

        mock_ws = mock.MagicMock()

        async def raise_connection_closed():
            raise ConnectionClosed(None, None)
            yield

        mock_ws.__aiter__ = lambda self: raise_connection_closed()
        vexa_provider._ws_connection = mock_ws

        await vexa_provider._ws_listener()

    @pytest.mark.asyncio
    async def test_ws_listener_handles_no_connection(self, vexa_provider):
        """Test that listener returns early with no connection."""
        vexa_provider._ws_connection = None
        await vexa_provider._ws_listener()

    @pytest.mark.asyncio
    async def test_ws_listener_handles_json_decode_error(self, vexa_provider):
        """Test that listener handles JSON decode errors."""
        messages = ["not valid json"]
        idx = 0

        class MockWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                nonlocal idx
                if idx >= len(messages):
                    raise StopAsyncIteration
                msg = messages[idx]
                idx += 1
                return msg

        vexa_provider._ws_connection = MockWS()
        await vexa_provider._ws_listener()

    @pytest.mark.asyncio
    async def test_ws_listener_handles_general_exception(self, vexa_provider):
        """Test that listener handles general exceptions."""

        class MockWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise Exception("Unexpected error")

        vexa_provider._ws_connection = MockWS()
        await vexa_provider._ws_listener()


class TestVexaProviderRecordings:
    """The recording relay's upstream half.

    Each of these is a route the airgap collector's media reaches DNA through, so the thing worth
    pinning is the REQUEST: the wrong path, verb or query parameter is a silent behaviour change
    that only shows up as a 404 during a live meeting.
    """

    @staticmethod
    def _wire(vexa_provider, handler):
        """Drive the provider against a mocked transport, capturing what it asked for."""
        seen: list[httpx.Request] = []

        def capture(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        vexa_provider._client = httpx.AsyncClient(
            base_url=vexa_provider.base_url, transport=httpx.MockTransport(capture)
        )
        return seen

    async def test_list_recordings_filters_to_one_meeting_client_side(
        self, vexa_provider
    ):
        """The upstream route is API-key-scoped and returns everything the credential can see."""
        self._wire(
            vexa_provider,
            lambda r: httpx.Response(
                200,
                json={
                    "recordings": [
                        {"id": 1, "meeting_id": 8},
                        {"id": 2, "meeting_id": 9},
                    ]
                },
            ),
        )

        assert [r["id"] for r in await vexa_provider.list_recordings(8)] == [1]
        assert len(await vexa_provider.list_recordings(None)) == 2

    async def test_get_recording_master_asks_for_the_requested_stream(
        self, vexa_provider
    ):
        seen = self._wire(
            vexa_provider,
            lambda r: httpx.Response(
                200, json={"media_file_id": 7, "start_time_utc": "t"}
            ),
        )

        result = await vexa_provider.get_recording_master(42, media_type="audio")

        assert result["media_file_id"] == 7
        assert seen[0].url.path == "/recordings/42/master"
        assert seen[0].url.params["type"] == "audio"

    async def test_list_recording_chunks_passes_the_after_cursor(self, vexa_provider):
        """`after` is what makes polling cheap — without it every pass re-reads the whole index."""
        seen = self._wire(
            vexa_provider,
            lambda r: httpx.Response(200, json={"chunks": [], "complete": False}),
        )

        await vexa_provider.list_recording_chunks(42, 7, after_seq=3)

        assert seen[0].url.path == "/recordings/42/media/7/chunks"
        assert seen[0].url.params["after"] == "3"

    async def test_get_recording_chunk_returns_bytes_and_the_advertised_hash(
        self, vexa_provider
    ):
        seen = self._wire(
            vexa_provider,
            lambda r: httpx.Response(
                200, content=b"PARTBYTES", headers={"X-Chunk-Sha256": "abc123"}
            ),
        )

        data, sha = await vexa_provider.get_recording_chunk(42, 7, 2)

        assert (data, sha) == (b"PARTBYTES", "abc123")
        assert seen[0].url.path == "/recordings/42/media/7/chunks/2"

    async def test_get_recording_media_raw_fetches_the_assembled_master(
        self, vexa_provider
    ):
        """The audio half of the mux: whole bytes, not parts."""
        seen = self._wire(vexa_provider, lambda r: httpx.Response(200, content=b"OPUS"))

        data = await vexa_provider.get_recording_media_raw(42, 9, media_type="audio")

        assert data == b"OPUS"
        assert seen[0].url.path == "/recordings/42/media/9/raw"
        assert seen[0].url.params["type"] == "audio"

    async def test_delete_recording_uses_DELETE(self, vexa_provider):
        seen = self._wire(
            vexa_provider, lambda r: httpx.Response(200, json={"deleted": 12})
        )

        assert await vexa_provider.delete_recording(42) == {"deleted": 12}
        assert seen[0].method == "DELETE"
        assert seen[0].url.path == "/recordings/42"

    async def test_an_upstream_error_is_raised_not_swallowed(self, vexa_provider):
        """The collector decides what to do about a failure; silently returning empty would look
        like 'no parts yet' and let a truncated recording finalize."""
        self._wire(
            vexa_provider, lambda r: httpx.Response(500, json={"detail": "boom"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await vexa_provider.list_recording_chunks(42, 7)


class TestRecordingIsAskedForNotAssumed:
    """Whether a meeting is recorded is DNA's decision to state, not Vexa's to default.

    Omitting `recording_enabled` makes Vexa fall back to RECORDING_ENABLED on its own host — so
    a meeting's fate would be decided by a setting on another machine, invisible from DNA and
    liable to change under us. It is therefore always sent, including when False.
    """

    @staticmethod
    def _client(vexa_provider, response_json):
        response = mock.MagicMock()
        response.json.return_value = response_json
        response.raise_for_status = mock.MagicMock()
        response.is_error = False
        client = mock.AsyncMock()
        client.post.return_value = response
        vexa_provider._client = client
        return client

    async def test_false_is_sent_explicitly_rather_than_omitted(self, vexa_provider):
        client = self._client(vexa_provider, {"meeting_id": 1})

        await vexa_provider.dispatch_bot(
            platform=Platform.GOOGLE_MEET, meeting_id="m", playlist_id=1
        )

        payload = client.post.await_args.kwargs["json"]
        assert (
            payload["recording_enabled"] is False
        ), "omitting it hands the decision to a deployment default on the Vexa host"

    async def test_true_is_passed_through(self, vexa_provider):
        client = self._client(vexa_provider, {"meeting_id": 1})

        await vexa_provider.dispatch_bot(
            platform=Platform.GOOGLE_MEET,
            meeting_id="m",
            playlist_id=1,
            recording_enabled=True,
        )

        assert client.post.await_args.kwargs["json"]["recording_enabled"] is True

    async def test_the_session_reports_what_vexa_resolved_not_what_was_asked(
        self, vexa_provider
    ):
        """A deployment that ignores the request must not leave the UI claiming a recording.

        Vexa echoes the flags it actually resolved; that echo wins over the request.
        """
        self._client(
            vexa_provider,
            {"meeting_id": 1, "data": {"recording_enabled": False}},
        )

        session = await vexa_provider.dispatch_bot(
            platform=Platform.GOOGLE_MEET,
            meeting_id="m",
            playlist_id=1,
            recording_enabled=True,  # asked for
        )

        assert session.recording_enabled is False  # but not granted

    async def test_falls_back_to_the_request_when_vexa_does_not_echo(
        self, vexa_provider
    ):
        self._client(vexa_provider, {"meeting_id": 1})

        session = await vexa_provider.dispatch_bot(
            platform=Platform.GOOGLE_MEET,
            meeting_id="m",
            playlist_id=1,
            recording_enabled=True,
        )

        assert session.recording_enabled is True


class TestStatusFramesInBothShapes:
    """Vexa writes meeting.status from two publishers, in two shapes, on the same socket.

    Only the per-meeting shape was read, and every frame seen in practice is the other one — so
    every bot status was dropped: the key came out as ":" and matched no subscription. The bot
    joined and the UI never heard; the meeting ended and the completion handler never ran, so
    subscriptions leaked, playlist mappings leaked, and the in-review mark was never cleared.
    Nothing errored: an unattributable status is indistinguishable from one we are not watching.

    The frames below are copied verbatim from the live socket on 2026-08-26.
    """

    @pytest.fixture
    def subscribed(self, vexa_provider):
        seen = []

        async def callback(event_type, payload):
            seen.append((event_type, payload))

        vexa_provider._subscribed_meetings["google_meet:duv-anrv-ztp"] = callback
        return vexa_provider, seen

    @pytest.mark.asyncio
    async def test_the_flat_user_scoped_frame_is_delivered(self, subscribed):
        """The shape actually observed — no `meeting` object, status at the top level."""
        provider, seen = subscribed
        provider._meeting_id_to_key[36] = "google_meet:duv-anrv-ztp"

        await provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting_id": 36,
                "native": "duv-anrv-ztp",
                "status": "active",
                "when": "2026-08-26T01:08:21.163346+00:00",
            }
        )

        assert seen == [
            (
                "bot.status_changed",
                {
                    "platform": "google_meet",
                    "meeting_id": "duv-anrv-ztp",
                    "status": "in_call",
                    "timestamp": "2026-08-26T01:08:21.163346+00:00",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_the_per_meeting_frame_still_works(self, subscribed):
        provider, seen = subscribed

        await provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting": {
                    "id": 36,
                    "platform": "google_meet",
                    "native_id": "duv-anrv-ztp",
                },
                "payload": {"status": "completed"},
                "ts": "2026-08-26T01:20:00Z",
            }
        )

        assert seen[0][1]["status"] == "completed"
        assert seen[0][1]["meeting_id"] == "duv-anrv-ztp"

    @pytest.mark.asyncio
    async def test_a_flat_frame_resolves_by_native_id_without_a_prior_mapping(
        self, subscribed
    ):
        """The id map is populated by earlier frames; a restart mid-meeting empties it.

        Losing the terminal status because the process restarted is exactly the case that leaves
        a subscription leaked and a mark uncleared, so the native id is worth falling back to.
        """
        provider, seen = subscribed

        await provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting_id": 99,
                "native": "duv-anrv-ztp",
                "status": "completed",
            }
        )

        assert seen[0][1]["status"] == "completed"
        assert seen[0][1]["platform"] == "google_meet"

    @pytest.mark.asyncio
    async def test_a_status_for_someone_elses_meeting_is_still_ignored(
        self, subscribed
    ):
        """The socket also carries the whole user's meetings — not all of them are ours."""
        provider, seen = subscribed

        await provider._handle_ws_message(
            {
                "type": "meeting.status",
                "meeting_id": 12345,
                "native": "not-our-room",
                "status": "active",
            }
        )

        assert seen == []

    @pytest.mark.asyncio
    async def test_the_terminal_status_reaches_the_callback(self, subscribed):
        """The one that matters: it drives unsubscribe, mapping cleanup and the in-review clear."""
        provider, seen = subscribed
        provider._meeting_id_to_key[36] = "google_meet:duv-anrv-ztp"

        for status in ("stopping", "completed"):
            await provider._handle_ws_message(
                {
                    "type": "meeting.status",
                    "meeting_id": 36,
                    "native": "duv-anrv-ztp",
                    "status": status,
                }
            )

        assert [p["status"] for _, p in seen] == ["stopping", "completed"]
