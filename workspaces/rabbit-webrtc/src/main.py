#!/usr/bin/env python3

import asyncio
from webrtc import WebRTCClient


def handle_robot_commands(controller_data):
    """
    Handle gamepad commands from the browser
    """
    print(f"Received robot commands: {controller_data}")
    
    # Example processing:
    # if 'axes' in controller_data:
    #     left_stick_x = controller_data['axes'][0]
    #     left_stick_y = controller_data['axes'][1]
    #     # Control robot movement based on left stick
    #     
    # if 'buttons' in controller_data:
    #     # Handle button presses
    #     for i, pressed in enumerate(controller_data['buttons']):
    #         if pressed:
    #             print(f"Button {i} pressed")


async def main():
    # Create WebRTC client with NATS
    client = WebRTCClient(
        nats_url="nats://localhost:4222",
        on_message=handle_robot_commands
    )
    
    # Keep trying to connect with automatic reconnection
    while True:
        try:
            await client.connect()
        except KeyboardInterrupt:
            print("Shutting down...")
            break
        except Exception as e:
            print(f"Connection failed: {e}")
            print("Retrying in 5 seconds...")
            await asyncio.sleep(5)
    
    await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
