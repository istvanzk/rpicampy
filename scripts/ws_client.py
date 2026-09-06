import asyncio
import websockets
import json
import time

async def connect_to_server():
    uri = "ws://IzK.local:8765"
    #uri = "ws://rpi2.local:8765"
    #uri = "wss://ws.ifelse.io"
    try:
        async with websockets.connect(uri) as websocket:
            # Create a JSON handshake
            handshake = {
                "type": "handshake",
                "device_id": "raspi-002",
                "auth_tokens": "recv_status,send_cmd",
                "time": time.ctime(time.time())
            }

            # Send JSON handshake
            await websocket.send(json.dumps(handshake))
            print(f"Sent: {handshake}")

            # Receive and decode JSON response
            try:
                response = await websocket.recv()
                auth_data = json.loads(response)
                print(f"Received JSON: {auth_data}")
            except json.JSONDecodeError:
                print(f"Client received non-JSON message:\n{response}")
                raise

            if auth_data.get("type", "") == "handshake" \
                and "Authorized" in auth_data.get("handshake_string", ""): 
                while True:
                    payload = {
                        "type": "command",
                        "device_id": "raspi-001",
                        "time": time.ctime(time.time()),
                        "command_string": "cmd/1"
                    }

                    # Send JSON payload 
                    if "send_cmd" in auth_data.get("handshake_string", ""):
                        await websocket.send(json.dumps(payload))
                        print(f"Sent: {payload}")
 
                    # Receive and decode JSON response
                    if "recv_status" in auth_data.get("handshake_string", ""):
                        try:
                            response = await websocket.recv()
                            data = json.loads(response)
                            print(f"Received JSON: {data}")
                        except json.JSONDecodeError:
                            print(f"Client received non-JSON message:\n{response}")
                            pass

                    await asyncio.sleep(9.14)
            else:
                print(f"Handshake failed:\n{data}")

    except asyncio.CancelledError:
        print("Client listener task cancelled.")
        pass
    except websockets.exceptions.ConnectionClosed as e:
        print(f"Client connection closed\n{e}")
        pass

async def main():
    listener = asyncio.create_task(connect_to_server())
    try:
        await listener
    except KeyboardInterrupt:
        print("Keyboard interrupt received.")
        listener.cancel()
        await listener

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as e:
        print(f"{e}")
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        print("Program terminated.")
