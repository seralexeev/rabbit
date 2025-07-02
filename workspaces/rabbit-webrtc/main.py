import asyncio
import json
import websockets
from typing import Optional, Any
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    RTCIceCandidate,
)
from aiortc.sdp import candidate_from_sdp
from datetime import datetime
import os


class RobotClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url

        self.ws: Optional[Any] = None
        self.pc: Optional[RTCPeerConnection] = None
        self.data_channel: Optional[RTCDataChannel] = None

        self.running = False
        self.last_activity = None
        self.offer_task = None
        self.connection_timeout = 30
        self.watchdog_task = None

    async def connect(self):
        try:
            print("Connecting to ws", {"ws_url": self.ws_url})

            self.ws = await websockets.connect(self.ws_url)
            print("Connected to WebSocket server")

            await self.setup_webrtc_connection()
            await self.create_and_send_offer()

            self.running = True
            self.offer_task = asyncio.create_task(self.periodic_offer())
            self.watchdog_task = asyncio.create_task(self.connection_watchdog())

            await self.listen_websocket()

        except Exception as e:
            print("Connection error", e)
            await self.cleanup()
            print("Waiting before reconnecting...")
            await asyncio.sleep(2)

    async def send_ws_message(self, message):
        """Send message via WebSocket"""
        try:
            if self.ws:
                await self.ws.send(json.dumps(message))
                print("Sent WS message", {message.get("type", "unknown")})
        except Exception as e:
            print("Error sending WS message", e)

    async def create_and_send_offer(self):
        """Create and send WebRTC offer"""
        try:
            if not self.pc:
                print("Peer connection not initialized")
                return

            offer = await self.pc.createOffer()
            print(offer)
            await self.pc.setLocalDescription(offer)

            await self.send_ws_message(
                {"type": "offer", "sdp": self.pc.localDescription.sdp}
            )
            print("WebRTC offer created and sent")

        except Exception as e:
            print("Error creating offer", e)

    async def listen_websocket(self):
        """Listen for WebSocket messages"""
        try:
            if self.ws:
                async for message in self.ws:
                    if not self.running:
                        break

                    try:
                        data = json.loads(message)
                        await self.handle_ws_message(data)
                    except json.JSONDecodeError as e:
                        print("JSON parsing error", e)

        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
        except Exception as e:
            print("WebSocket error", e)
        finally:
            await self.cleanup()

    async def handle_ws_message(self, message):
        """Handle incoming WebSocket messages"""
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

                candidate = RTCIceCandidate(
                    message.get("sdpMid"),
                    message.get("sdpMLineIndex"),
                    message.get("candidate", ""),
                )
                await self.pc.addIceCandidate(candidate)
                print("ICE candidate added")
            except Exception as e:
                print("Failed to add ICE candidate", e)

        elif msg_type == "request_offer":
            # Browser requests a new offer - reset connection and create new one
            print("Browser requested new offer - resetting connection")
            await self.reset_webrtc_connection()

        else:
            print("Received unknown message", {msg_type})

    def handle_controller_message(self, message):
        """Handle messages from controller"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            browser_ts = data.get("ts")
            if browser_ts is not None:
                now_ms = int(datetime.now().timestamp() * 1000)
                delay = now_ms - int(browser_ts)

            if msg_type == "joy/STATE":
                # Log controller state
                controller_data = data.get("data", {})
                buttons = controller_data.get("buttons", {})
                sticks = controller_data.get("sticks", {})

                # Only log if there are active buttons or stick movement
                active_buttons = [
                    name
                    for name, state in buttons.items()
                    if state.get("pressed", False)
                ]
                left_stick = sticks.get("left", {"x": 0, "y": 0})
                right_stick = sticks.get("right", {"x": 0, "y": 0})

                # Check for significant changes (threshold value for sticks)
                stick_threshold = 0.1
                has_stick_movement = (
                    abs(left_stick["x"]) > stick_threshold
                    or abs(left_stick["y"]) > stick_threshold
                    or abs(right_stick["x"]) > stick_threshold
                    or abs(right_stick["y"]) > stick_threshold
                )

                if active_buttons or has_stick_movement:
                    log_parts = [f"🎮 [{delay}ms]:"]

                    if active_buttons:
                        log_parts.append(f"Buttons: {', '.join(active_buttons)}")

                    if has_stick_movement:
                        stick_info = []
                        if (
                            abs(left_stick["x"]) > stick_threshold
                            or abs(left_stick["y"]) > stick_threshold
                        ):
                            stick_info.append(
                                f"L({left_stick['x']:.2f}, {left_stick['y']:.2f})"
                            )
                        if (
                            abs(right_stick["x"]) > stick_threshold
                            or abs(right_stick["y"]) > stick_threshold
                        ):
                            stick_info.append(
                                f"R({right_stick['x']:.2f}, {right_stick['y']:.2f})"
                            )
                        log_parts.append(f"Sticks: {', '.join(stick_info)}")

                    print(" | ".join(log_parts))

                    # Here you can add robot command processing
                    # self.process_robot_commands(controller_data)

            else:
                print(f"[{timestamp}] Received message type: {msg_type}")

        except Exception as e:
            print("Controller message handling error", e)

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
                print(f"Error cancelling task: {e}")

        # Close WebRTC components
        if self.data_channel:
            try:
                self.data_channel.close()
                print("Data channel closed")
            except Exception as e:
                print(f"Error closing data channel: {e}")
            finally:
                self.data_channel = None

        if self.pc:
            try:
                await self.pc.close()
                print("Peer connection closed")
            except Exception as e:
                print(f"Error closing peer connection: {e}")
            finally:
                self.pc = None

        # Close WebSocket
        if self.ws:
            try:
                await self.ws.close()
                print("WebSocket closed")
            except Exception as e:
                print(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None

        print("Cleanup completed successfully")

    async def periodic_offer(self):
        """Send periodic offers to enable browser reconnection"""
        while self.running:
            await asyncio.sleep(10)

            if self.pc and self.ws:
                try:
                    # Check if we have an active data channel connection
                    if not self.data_channel or self.data_channel.readyState != "open":
                        # Recreate offer if no active connection
                        offer = await self.pc.createOffer()
                        await self.pc.setLocalDescription(offer)

                        await self.send_ws_message(
                            {
                                "type": "offer",
                                "sdp": self.pc.localDescription.sdp,
                            }
                        )
                        print("Periodic offer sent for reconnection")

                except Exception as e:
                    print(f"Error sending periodic offer: {e}")

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

            # Close existing data channel
            if self.data_channel:
                self.data_channel.close()
                self.data_channel = None

            # Close existing peer connection
            if self.pc:
                await self.pc.close()
                self.pc = None

            # Reinitialize WebRTC components
            await self.setup_webrtc_connection()

            # Send new offer immediately
            await self.create_and_send_offer()

        except Exception as e:
            print(f"Error resetting WebRTC connection: {e}")

    async def setup_webrtc_connection(self):
        """Setup WebRTC peer connection with all handlers"""
        self.pc = RTCPeerConnection()
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
        def on_message(message):
            self.handle_controller_message(message)
            self.last_activity = datetime.now()

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                await self.send_ws_message(
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
            print(f"WebRTC connection state: {state}")

            if state == "failed" or state == "disconnected":
                print("WebRTC connection lost")
            elif state == "connected":
                print("WebRTC connection established")
                self.last_activity = datetime.now()


async def main():
    ws_url = os.environ.get("RABBIT_WS_URL")
    if ws_url is None:
        raise ValueError("RABBIT_WS_URL environment variable is not set")

    while True:
        client = RobotClient(ws_url=ws_url)

        try:
            await client.connect()
        except KeyboardInterrupt:
            print("Stop signal received")
            await client.cleanup()
            break
        except Exception as e:
            print(f"Connection error: {e}")
            await client.cleanup()

            print("Reconnecting in 3 seconds...")
            await asyncio.sleep(3)
            continue


if __name__ == "__main__":
    print("Starting robot client...")
    asyncio.run(main())
