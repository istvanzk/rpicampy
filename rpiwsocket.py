# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera (V7.1+)
    Copyright (C) 2025- Istvan Z. Kovacs

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

Implements the threaded WebSocketServer class, 
with support for client handshake/authetication for send/receive messages and broadcast to multiple clients.
# NOTE: Code generated with help from Microsoft Copilot
"""
import threading
import asyncio
import websockets
import queue
import json
from websockets.legacy.server import WebSocketServerProtocol
from typing import Any, Set, Dict, List

### The rpicampy modules
try:
    from rpilogger import rpiLogger
except ImportError:
    import logging
    rpiLogger = logging.getLogger()

# Server parameters
MAX_NUM_CLIENTS   = 3
# Receive parameters
RECEIVE_TIMEOUT   = 2 # seconds
# Broadcast/send parameters
SEND_RUN_SLEEP    = 0.1 # seconds
SEND_MAX_RETRIES  = 3
SEND_TIMEOUT      = 2 # seconds
SEND_RETRY_DELAY  = 1 # seconds

class WebSocketServerThread(threading.Thread):
    """ 
    A customized threaded WebSocket server setup
    with support for client authentication handshake and multiple clients.
    """
    def __init__(self, host:str='localhost', port:int=8765, key_file:str=''):
        super().__init__()

        # Host and port
        self.host:str = host
        self.port:int = port
        # Read the authentication tokens from the file.
        # These tokens are expected to be provided by any client connecting
        # to the server, during the initial handshake phase.
        # One or both tokens (send and/or recv) need to be provided by the clients during handshake.
        self.key_file:str = key_file
        if self.key_file == '':
            rpiLogger.error("websocket server:::: No clients authentication keys file was specified! Exiting!\n")
            raise ValueError("websocket server:::: No clients authentication keys file was specified!")

        try:
            with open(file=self.key_file, mode='r', encoding='utf-8') as f:
                _info = f.read().split('\n')
                _keys = _info[0].split(',',2)
                self.clients_recv_key  = _keys[0]
                if len(_keys) > 1:
                    self.clients_send_key  = _keys[1]
                if len(_keys) > 2:
                    self.clients_id = _keys[2]
                
        except (IOError, FileNotFoundError) as e:
            rpiLogger.error("websocket server:::: Clients authentication keys file '%s' not found! Exiting!\n%s\n", self.key_file, str(e))
            raise FileNotFoundError("websocket server:::: Clients authentication keys file '%s' not found!", self.key_file)
            
        rpiLogger.debug("websocket server:::: Clients authentication keys file read.")

        # Clients
        self.connected_clients_lock = asyncio.Lock()
        self.connected_clients: Dict[str, WebSocketServerProtocol] = dict()
        self.send_to_clients: Set[str] = set()
        self.recv_from_clients: Set[str] = set()

        # Queues for inter-thread communication
        self.incoming = queue.Queue(maxsize=1)
        self.outgoing = queue.Queue(maxsize=2)

        # Event loop and stop event
        self.loop = asyncio.new_event_loop()
        self.stop_event = threading.Event()


    async def handler(self, websocket):
        """
        Authorize clients, receive and process messages from connecting clients.
        """
        remote_address = websocket.remote_address
        rpiLogger.debug("websocket server:::: Client connected from %s", remote_address)

        # Receive handshake message
        try:
            # Wait for the first message — expected to be the handshake
            handshake_raw = await asyncio.wait_for(websocket.recv(), timeout=RECEIVE_TIMEOUT)
            handshake = json.loads(handshake_raw)

            if handshake.get("type", "") != "handshake":
                await websocket.send(json.dumps({"type": "error", "error_string": "Handshake required"}))
                await websocket.close(code=1008, reason="Handshake missing")
                return

            device_id = handshake.get("device_id", "")
            auth_token = handshake.get("auth_tokens", "")

            if not await self._validate_client(device_id, auth_token):
                await websocket.send(json.dumps({"type": "handshake", "handshake_string": "Unauthorized"}))
                await websocket.close(code=1008, reason="Unauthorized")
                return

            # Handshake successful, check if number of allowed clients has been reached
            if len(self.connected_clients) == MAX_NUM_CLIENTS:
                await websocket.send(json.dumps({"type": "handshake", "handshake_string": "Unauthorized - max number of clients exceeded"}))
                await websocket.close(code=1008, reason="Unauthorized")
                return
            
            # Send authorization message
            _auth_str = "Authorized for: "
            if device_id in self.send_to_clients:
                _auth_str += "recv_status"
            _auth_str += ","
            if device_id in self.recv_from_clients:
                _auth_str += "send_cmd"

            await websocket.send(json.dumps({"type": "handshake", "handshake_string": _auth_str}))

            # Store device_id and connection
            async with self.connected_clients_lock:
                self.connected_clients[device_id] = websocket

        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            rpiLogger.debug("websocket server:::: Receive from lient %s timeout\n%s", device_id, str(e))
            await websocket.send(json.dumps({"type": "error", "error_string": "Handshake timeout"}))
            await websocket.close(code=1001, reason="Timeout waiting for handshake")

        # Now enter the normal message loop with the authorized device
        if websocket:
            # Receive message
            try:
                async for message in websocket:
                    if device_id in self.recv_from_clients:
                        try:
                            self.incoming.put((device_id, remote_address, message), timeout=0.5)
                        except queue.Full:
                            self.incoming.get_nowait()
                            self.incoming.put_nowait((device_id, remote_address, message))
                            pass

            except websockets.exceptions.ConnectionClosed:
                rpiLogger.debug("websocket server:::: Client disconnected")
                await websocket.close(code=1001, reason="Client disconnected")
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                rpiLogger.debug("websocket server:::: Receive timeout error\n%s", str(e))
                await websocket.close(code=1001, reason="Receive timeout")
            except Exception as e:
                rpiLogger.debug("websocket server:::: Unexpected receive error\n%s", str(e))
                await websocket.close(code=1011, reason="Unexpected receive error")
            finally:
                async with self.connected_clients_lock:
                    self.connected_clients.pop(device_id, None)

    async def broadcaster(self):
        """
        Send message, if available, to all authorized clients.
        """
        try:
            message = self.outgoing.get_nowait()
            for _client in self.send_to_clients:
                _ws = self.connected_clients.get(_client, None)
                if _ws is None:
                    continue

                for _attempt in range(1, SEND_MAX_RETRIES + 1):
                    try:
                        await asyncio.wait_for(_ws.send(message), timeout=SEND_TIMEOUT)
                        rpiLogger.debug("websocket server:::: Broadcaster sent to connected client %s on attempt #%d:\n%s", _client, _attempt, message)
                        break  # Success, exit retry loop
                    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                        rpiLogger.debug("websocket server:::: Broadcaster send timeout to client %s on attempt #%d\n%s", _client, _attempt, str(e))
                    except Exception as e:
                        rpiLogger.debug("websocket server:::: Broadcaster send failed to lient %s on attempt #%d\n%s", _client, _attempt, str(e))
                    
                    if _attempt < SEND_MAX_RETRIES:
                        await asyncio.sleep(SEND_RETRY_DELAY * _attempt)
                    else:
                        rpiLogger.debug("websocket server:::: Broadcaster giving up sending to client %s after %d attempts.", _client, SEND_MAX_RETRIES)
                        await _ws.send(json.dumps({"type": "error", "error_string": "Timeout after send retries"}))
                        await _ws.close(code=1001, reason="Timeout after send retries")
                        async with self.connected_clients_lock:
                            self.connected_clients.pop(_client, None)

                #await asyncio.gather(*(client.send(message) for client in self.connected_clients))
        except queue.Empty:
            pass
        except RuntimeError as e:
            rpiLogger.debug("websocket server:::: Broadcaster run error\n%s", str(e))


    def run(self):
        """
        Main server run loop.
        It starts run_server() in event loop and handleds closing the loop.
        """
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_server())
        except RuntimeError as e:
            rpiLogger.error("websocket server:::: Run - RuntimeError!\n%s\n", str(e))
        except Exception as e:
            rpiLogger.error("websocket server:::: Run - Unexpected error!\n%s\n", str(e))
            raise
        finally:
            self.loop.run_until_complete(self._shutdown())
            self._cancel_pending_tasks()
            self.loop.close()

    def send_json(self, data: dict):
        """
        Insert a message, a JSON object, into the ougoing queue.
        Only the clients authorized in handler() to receive these messages from the server,
        will be sent to (see broadcast()).
        """
        try:
            self.outgoing.put(json.dumps(data, skipkeys=True, ensure_ascii=True, allow_nan=True), timeout=0.5)
        except queue.Full:
            self.outgoing.get_nowait()
            self.outgoing.put_nowait(json.dumps(data, skipkeys=True, ensure_ascii=True, allow_nan=True))
            pass
        except TypeError as e:
            rpiLogger.debug("websocket server:::: Could not serialize JSON message:\n%s\n%s", data, str(e))
            pass

    @property
    def receive_json(self) -> Dict:
        """
        Retrieves the last incoming message from the queue and converts it to JSON object.
        Only messsages from the clients authorized in handler() to send these messages to the server, 
        are available in the queue (see handler()).
        """
        data = dict()
        try:
            device_id, client_address, message = self.incoming.get_nowait()
            if message:
                data = json.loads(message)
                rpiLogger.debug("websocket server:::: Received JSON message from client %s (%s):\n%s", device_id, client_address, message)
        except queue.Empty:
            pass
        except json.JSONDecodeError:
            rpiLogger.debug("websocket server:::: Received non-JSON message from client %s (%s):\n%s", device_id, client_address, message)
        finally:
            return data
        

    def stop(self):
        """
        Stop the server main event loop.
        """
        self.stop_event.set()
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except RuntimeError:
            pass


    async def _run_server(self, send_sleep: float = SEND_RUN_SLEEP):
        """
        Run the tasks under the main server loop
        """
        async with websockets.serve(self.handler, self.host, self.port):
            rpiLogger.info("websocket server:::: Started at ws://%s:%s", self.host, self.port)
            while not self.stop_event.is_set():
                await self.broadcaster()
                await self._periodic_cleanup()
                await asyncio.sleep(send_sleep)

    ## Alternative: schedule broadcaster as a background task
    # async def _run_server(self):
    #     async with websockets.serve(self.handler, self.host, self.port):
    #         rpiLogger.info(f"WebSocket server started at ws://{self.host}:{self.port}")
    #         broadcaster_task = asyncio.create_task(self._broadcast_loop())
    #         try:
    #             while not self.stop_event.is_set():
    #                 await asyncio.sleep(0.1)
    #         finally:
    #             broadcaster_task.cancel()
    #             await broadcaster_task

    # async def _broadcast_loop(self):
    #     while not self.stop_event.is_set():
    #         await self.broadcaster()
    #         await asyncio.sleep(0.1)


    async def _validate_client(self, device_id: str, auth_token: str):
        """
        Helper function to validate/authorize the client for send and/or receive.
        """
        _keys = auth_token.split(',',2)
        _ok = False

        if _keys[0] != '' \
            and self.clients_recv_key == _keys[0]:
            async with self.connected_clients_lock:
                self.send_to_clients.add(device_id)
            _ok = True

        if len(_keys) > 1 \
            and _keys[1] != '' \
            and self.clients_send_key == _keys[1]:
            async with self.connected_clients_lock:
                self.recv_from_clients.add(device_id)
            _ok |= True
        
        return _ok

    async def _periodic_cleanup(self):
        """
        Helper function to remove clients which are not active anymore from the send/receive lists.
        """
        _clients_to_remove: List = list()

        rpiLogger.debug("websocket server:::: Periodic cleanup - connected clients: %s", self.connected_clients)

        for _client in self.send_to_clients:
            if self.connected_clients.get(_client, None) is None:
                _clients_to_remove.append(_client)

        for _client in self.recv_from_clients:
            if self.connected_clients.get(_client, None) is None:
                _clients_to_remove.append(_client)

        rpiLogger.debug("websocket server:::: Periodic cleanup - remove clients: %s", _clients_to_remove)
        for _client in _clients_to_remove:
            async with self.connected_clients_lock:
                try:
                    self.send_to_clients.remove(_client)
                    self.recv_from_clients.remove(_client)
                except KeyError:
                    pass

    async def _shutdown(self):
        """
        Helper function to close and clear active connections.
        """
        rpiLogger.info("websocket server:::: Closing all active connections...")
        tasks = [ws.close(code=1001, reason='Server shutdown') for ws in self.connected_clients.values()]
        await asyncio.gather(*tasks)
        self.connected_clients.clear()

    def _cancel_pending_tasks(self):
        """
        Helper function to cancel all async tasks related to the main event loop.
        """
        tasks = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
        for task in tasks:
            task.cancel()
        self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

