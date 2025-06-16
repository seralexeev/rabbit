import asyncio
import json
import logging
import websockets
from typing import Optional
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel
from datetime import datetime

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RobotClient:
    def __init__(self, ws_url="ws://localhost:3000?role=robot"):
        self.ws_url = ws_url
        self.ws: Optional[websockets.WebSocketServerProtocol] = None
        self.pc: Optional[RTCPeerConnection] = None
        self.data_channel: Optional[RTCDataChannel] = None
        self.running = False
        self.last_activity = None
        self.offer_task = None
        
    async def connect(self):
        """Connect to WebSocket server and establish WebRTC connection"""
        try:
            logger.info(f"🔌 Connecting to {self.ws_url}")
            self.ws = await websockets.connect(self.ws_url)
            logger.info("🟢 Connected to WebSocket server")
            
            # Initialize WebRTC peer connection
            self.pc = RTCPeerConnection()
            pc = self.pc  # Local variable for typing
            
            # Create data channel (as connection initiator)
            self.data_channel = pc.createDataChannel('chat')  # type: ignore
            data_channel = self.data_channel
            
            @data_channel.on("open")  # type: ignore
            def on_open():
                logger.info("🟢 Data channel opened and ready to receive data")
                
            @data_channel.on("close")  # type: ignore
            def on_close():
                logger.info("🟡 Data channel closed")
                
            @data_channel.on("message")  # type: ignore
            def on_message(message):
                self.handle_controller_message(message)
            
            # ICE candidate handler
            @pc.on("icecandidate")  # type: ignore
            async def on_icecandidate(candidate):
                if candidate:
                    await self.send_ws_message({
                        "type": "ice",
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex
                    })
            
            # Connection state monitoring
            @pc.on("connectionstatechange")  # type: ignore
            def on_connectionstatechange():
                state = pc.connectionState  # type: ignore
                logger.info(f"� WebRTC connection state: {state}")
                
                if state == "failed" or state == "disconnected":
                    logger.warning("� WebRTC connection lost")
                elif state == "connected":
                    logger.info("🟢 WebRTC connection established")
            
            # Create offer and send it
            await self.create_and_send_offer()
            
            self.running = True
            
            # Start periodic offer sending task
            self.offer_task = asyncio.create_task(self.periodic_offer())
            
            # Start listening for WebSocket messages
            await self.listen_websocket()
            
        except Exception as e:
            logger.error(f"🔴 Connection error: {e}")
            await self.cleanup()
            
    async def send_ws_message(self, message):
        """Send message via WebSocket"""
        try:
            if self.ws:
                await self.ws.send(json.dumps(message))
                logger.debug(f"📤 Sent WS message: {message.get('type', 'unknown')}")
        except Exception as e:
            logger.error(f"🔴 Error sending WS message: {e}")
            
    async def create_and_send_offer(self):
        """Create and send WebRTC offer"""
        try:
            if not self.pc:
                logger.error("🔴 Peer connection not initialized")
                return
                
            # Create offer and send it
            offer = await self.pc.createOffer()  # type: ignore
            await self.pc.setLocalDescription(offer)  # type: ignore
            
            await self.send_ws_message({
                "type": "offer",
                "sdp": self.pc.localDescription.sdp  # type: ignore
            })
            logger.info("📤 WebRTC offer created and sent")
            
        except Exception as e:
            logger.error(f"🔴 Error creating offer: {e}")
            
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
                        logger.error(f"🔴 JSON parsing error: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("🟡 WebSocket connection closed")
        except Exception as e:
            logger.error(f"🔴 WebSocket error: {e}")
        finally:
            await self.cleanup()
            
    async def handle_ws_message(self, message):
        """Handle incoming WebSocket messages"""
        msg_type = message.get("type")
        
        if msg_type == "answer":
            # Handle WebRTC answer from browser
            try:
                if not self.pc:
                    logger.error("🔴 Peer connection not initialized")
                    return
                    
                answer = RTCSessionDescription(sdp=message["sdp"], type=message["type"])
                await self.pc.setRemoteDescription(answer)
                logger.info("📥 WebRTC answer received and set")
                
            except Exception as e:
                logger.error(f"🔴 Error handling answer: {e}")
                
        elif msg_type == "ice":
            # Handle ICE candidate
            try:
                if not self.pc:
                    logger.error("🔴 Peer connection not initialized")
                    return
                    
                candidate = RTCIceCandidate(
                    candidate=message.get("candidate", ""),
                    sdpMid=message.get("sdpMid"),
                    sdpMLineIndex=message.get("sdpMLineIndex")
                )
                await self.pc.addIceCandidate(candidate)
                logger.debug("🔵 ICE candidate added")
            except Exception as e:
                logger.warning(f"🟡 Failed to add ICE candidate: {e}")
        
        elif msg_type == "request_offer":
            # Browser requests a new offer - create and send one
            logger.info("🔄 Browser requested new offer")
            await self.create_and_send_offer()
        
        else:
            logger.debug(f"🔵 Received unknown message type: {msg_type}")
                
    def handle_controller_message(self, message):
        """Handle messages from controller"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            if msg_type == "joy/STATE":
                # Log controller state
                controller_data = data.get("data", {})
                buttons = controller_data.get("buttons", {})
                sticks = controller_data.get("sticks", {})
                
                # Only log if there are active buttons or stick movement
                active_buttons = [name for name, state in buttons.items() if state.get("pressed", False)]
                left_stick = sticks.get("left", {"x": 0, "y": 0})
                right_stick = sticks.get("right", {"x": 0, "y": 0})
                
                # Check for significant changes (threshold value for sticks)
                stick_threshold = 0.1
                has_stick_movement = (
                    abs(left_stick["x"]) > stick_threshold or 
                    abs(left_stick["y"]) > stick_threshold or
                    abs(right_stick["x"]) > stick_threshold or 
                    abs(right_stick["y"]) > stick_threshold
                )
                
                if active_buttons or has_stick_movement:
                    log_parts = [f"[{timestamp}] 🎮 CONTROLLER:"]
                    
                    if active_buttons:
                        log_parts.append(f"Buttons: {', '.join(active_buttons)}")
                    
                    if has_stick_movement:
                        stick_info = []
                        if abs(left_stick["x"]) > stick_threshold or abs(left_stick["y"]) > stick_threshold:
                            stick_info.append(f"L({left_stick['x']:.2f}, {left_stick['y']:.2f})")
                        if abs(right_stick["x"]) > stick_threshold or abs(right_stick["y"]) > stick_threshold:
                            stick_info.append(f"R({right_stick['x']:.2f}, {right_stick['y']:.2f})")
                        log_parts.append(f"Sticks: {', '.join(stick_info)}")
                    
                    logger.info(" | ".join(log_parts))
                    
                    # Here you can add robot command processing
                    # self.process_robot_commands(controller_data)
                    
            else:
                logger.info(f"[{timestamp}] 📨 Received message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"🔴 Controller message parsing error: {e}")
        except Exception as e:
            logger.error(f"🔴 Controller message handling error: {e}")
            
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
        self.running = False
        
        # Cancel periodic offer task
        if self.offer_task:
            self.offer_task.cancel()
            try:
                await self.offer_task
            except asyncio.CancelledError:
                pass
        
        if self.data_channel:
            self.data_channel.close()
            
        if self.pc:
            await self.pc.close()
            
        try:
            if self.ws:
                await self.ws.close()
        except Exception as e:
            logger.debug(f"Error closing WebSocket: {e}")
            
        logger.info("🧹 Resources cleaned up")
        
    async def periodic_offer(self):
        """Send periodic offers to enable browser reconnection"""
        while self.running:
            await asyncio.sleep(10)  # Send offer every 10 seconds
            
            if self.pc and self.ws:
                try:
                    # Check if we have an active data channel connection
                    if not self.data_channel or self.data_channel.readyState != "open":
                        # Recreate offer if no active connection
                        offer = await self.pc.createOffer()  # type: ignore
                        await self.pc.setLocalDescription(offer)  # type: ignore
                        
                        await self.send_ws_message({
                            "type": "offer",
                            "sdp": self.pc.localDescription.sdp  # type: ignore
                        })
                        logger.debug("� Periodic offer sent for reconnection")
                        
                except Exception as e:
                    logger.debug(f"Error sending periodic offer: {e}")
            

async def main():
    """Main function with automatic reconnection"""
    while True:
        client = RobotClient()
        
        try:
            await client.connect()
        except KeyboardInterrupt:
            logger.info("� Stop signal received")
            await client.cleanup()
            break
        except Exception as e:
            logger.error(f"🔴 Connection error: {e}")
            await client.cleanup()
            
            # Wait before reconnecting
            logger.info("� Reconnecting in 3 seconds...")
            await asyncio.sleep(3)
            continue

if __name__ == "__main__":
    logger.info("🤖 Starting robot client...")
    asyncio.run(main())