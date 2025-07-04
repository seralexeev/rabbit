import asyncio
import json
import nats
from typing import Optional, Any
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.sdp import candidate_from_sdp
from datetime import datetime


class WebRTCClient:
    def __init__(
        self, nats_url: str = "nats://localhost:4222", on_message: Optional[Any] = None
    ):
        self.nats_url = nats_url
        self.on_message = on_message

        self.nc: Optional[Any] = None
        self.pc: Optional[RTCPeerConnection] = None
        self.data_channel: Optional[RTCDataChannel] = None

        self.running = False
        self.last_activity = None
        self.offer_task = None
        self.connection_timeout = 30
        self.watchdog_task = None
        self.subscription = None

    async def connect(self):
        try:
            print("Connecting to NATS", {"nats_url": self.nats_url})

            self.nc = await nats.connect(self.nats_url)
            print("Connected to NATS server")

            await self.setup_webrtc_connection()
            await self.create_and_send_offer()

            self.running = True
            self.offer_task = asyncio.create_task(self.periodic_offer())
            self.watchdog_task = asyncio.create_task(self.connection_watchdog())

            await self.listen_nats()

        except Exception as e:
            print("Connection error", e)
            await self.cleanup()
            print("Waiting before reconnecting...")
            await asyncio.sleep(2)

    async def send_nats_message(self, message):
        """Send message via NATS"""
        try:
            if self.nc:
                await self.nc.publish(
                    "webrtc.signaling.rabbit", json.dumps(message).encode()
                )
                print("Sent NATS message", message.get("type", "unknown"))
        except Exception as e:
            print("Error sending NATS message", e)

    async def create_and_send_offer(self):
        """Create and send WebRTC offer"""
        try:
            if not self.pc:
                print("Peer connection not initialized")
                return

            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            await self.send_nats_message(
                {"type": "offer", "sdp": self.pc.localDescription.sdp}
            )
            print("WebRTC offer created and sent")

        except Exception as e:
            print("Error creating offer", e)

    async def listen_nats(self):
        """Listen for NATS messages"""
        try:
            if self.nc:

                async def message_handler(msg):
                    if not self.running:
                        return

                    try:
                        data = json.loads(msg.data.decode())
                        await self.handle_nats_message(data)
                    except json.JSONDecodeError as e:
                        print("JSON parsing error", e)

                self.subscription = await self.nc.subscribe(
                    "webrtc.signaling.browser", cb=message_handler
                )
                print("Subscribed to NATS topic webrtc.signaling.browser")

                # Send ws_connected message to signal that we're ready
                await self.send_nats_message({"type": "ws_connected"})

                # Keep the connection alive
                while self.running:
                    await asyncio.sleep(1)

        except Exception as e:
            print("NATS error", e)
        finally:
            await self.cleanup()

    async def handle_nats_message(self, message):
        """Handle incoming NATS messages"""
        msg_type = message.get("type")

        if msg_type == "answer":
            # Handle WebRTC answer from browser
            try:
                if not self.pc:
                    print("Peer connection not initialized")
                    return

                # Check if this is a new connection (browser refresh)
                if self.pc.connectionState in ["connected", "connecting"]:
                    print(
                        "Received answer while already connecting/connected - resetting"
                    )
                    await self.reset_webrtc_connection()
                    return

                answer = RTCSessionDescription(sdp=message["sdp"], type=message["type"])
                await self.pc.setRemoteDescription(answer)
                print("WebRTC answer received and set")

            except Exception as e:
                print("Error handling answer", e)
                # Try to reset connection on error
                await self.reset_webrtc_connection()

        elif msg_type == "ice":
            # Handle ICE candidate
            try:
                if not self.pc:
                    print("Peer connection not initialized")
                    return

                candidate_sdp = message.get("candidate", "")
                candidate = candidate_from_sdp(candidate_sdp)

                if candidate:
                    candidate.sdpMid = message.get("sdpMid")
                    candidate.sdpMLineIndex = message.get("sdpMLineIndex")
                    await self.pc.addIceCandidate(candidate)
                    print("ICE candidate added successfully")
                else:
                    print("Failed to parse ICE candidate from SDP")
            except Exception as e:
                print("Failed to add ICE candidate", e)

        elif msg_type == "request_offer":
            # Browser requests a new offer - reset connection and create new one
            print("Browser requested new offer - resetting connection")
            await self.reset_webrtc_connection()

        else:
            print("Received unknown message", {msg_type})

    def process_robot_commands(self, controller_data):
        """Process robot commands (stub for future implementation)"""
        # Robot control logic will go here
        # For example:
        # - Movement based on left stick
        # - Camera rotation based on right stick
        # - Special actions based on buttons
        pass

    async def cleanup(self):
        """Clean up resources"""
        print("Starting cleanup process...")
        self.running = False

        # Cancel all background tasks
        tasks_to_cancel = []

        if self.offer_task:
            tasks_to_cancel.append(self.offer_task)

        if self.watchdog_task:
            tasks_to_cancel.append(self.watchdog_task)

        # Cancel all tasks
        for task in tasks_to_cancel:
            task.cancel()

        # Wait for tasks to be cancelled
        for task in tasks_to_cancel:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print("Error cancelling task", e)

        # Close WebRTC components
        if self.data_channel:
            try:
                self.data_channel.close()
                print("Data channel closed")
            except Exception as e:
                print("Error closing data channel", e)
            finally:
                self.data_channel = None

        if self.pc:
            try:
                await self.pc.close()
                print("Peer connection closed")
            except Exception as e:
                print("Error closing peer connection", e)
            finally:
                self.pc = None

        # Close NATS components
        if self.subscription:
            try:
                await self.subscription.unsubscribe()
                print("NATS subscription closed")
            except Exception as e:
                print("Error closing NATS subscription", e)
            finally:
                self.subscription = None

        if self.nc:
            try:
                await self.nc.close()
                print("NATS connection closed")
            except Exception as e:
                print("Error closing NATS connection", e)
            finally:
                self.nc = None

        print("Cleanup completed successfully")

    async def periodic_offer(self):
        """Send periodic offers to enable browser reconnection"""
        while self.running:
            await asyncio.sleep(10)

            if self.pc and self.nc:
                try:
                    # Check if we have an active data channel connection
                    if not self.data_channel or self.data_channel.readyState != "open":
                        # Recreate offer if no active connection
                        offer = await self.pc.createOffer()
                        await self.pc.setLocalDescription(offer)

                        await self.send_nats_message(
                            {
                                "type": "offer",
                                "sdp": self.pc.localDescription.sdp,
                            }
                        )
                        print("Periodic offer sent for reconnection")

                except Exception as e:
                    print("Error sending periodic offer", e)

    async def connection_watchdog(self):
        """Monitor connection health and cleanup stale connections"""
        while self.running:
            await asyncio.sleep(5)

            if not self.running:
                break

            # Check if WebRTC connection is still alive
            if self.pc and self.data_channel:
                if self.pc.connectionState in ["failed", "disconnected", "closed"]:
                    print("WebRTC connection lost, cleaning up...")
                    await self.reset_webrtc_connection()
                elif self.data_channel.readyState == "closed":
                    print("Data channel closed, cleaning up...")
                    await self.reset_webrtc_connection()

    async def reset_webrtc_connection(self):
        """Reset WebRTC connection and prepare for new one"""
        try:
            print("Resetting WebRTC connection...")

            if self.data_channel:
                self.data_channel.close()
                self.data_channel = None

            if self.pc:
                await self.pc.close()
                self.pc = None

            await self.setup_webrtc_connection()
            await self.create_and_send_offer()

        except Exception as e:
            print("Error resetting WebRTC connection", e)

    async def setup_webrtc_connection(self):
        """Setup WebRTC peer connection with all handlers"""
        configuration = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
            ]
        )
        self.pc = RTCPeerConnection(configuration)
        pc = self.pc  # Local variable for typing

        self.data_channel = pc.createDataChannel("chat")
        data_channel = self.data_channel

        @data_channel.on("open")
        def on_open():
            print("Data channel opened and ready to receive data")
            self.last_activity = datetime.now()

        @data_channel.on("close")
        def on_close():
            print("Data channel closed")
            asyncio.create_task(self.reset_webrtc_connection())

        @data_channel.on("message")
        def on_message_impl(message):
            self.last_activity = datetime.now()
            try:
                parsed = json.loads(message)
                if self.on_message:
                    self.on_message(parsed)
            except Exception as e:
                print(f"Error processing message from data channel: {e}")

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                await self.send_nats_message(
                    {
                        "type": "ice",
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    }
                )

        # Connection state monitoring
        @pc.on("connectionstatechange")
        def on_connectionstatechange():
            state = pc.connectionState
            print(f"WebRTC connection state", state)

            if state == "failed" or state == "disconnected":
                print("WebRTC connection lost")
            elif state == "connected":
                print("WebRTC connection established")
                self.last_activity = datetime.now()
