# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera (V8+)
    Copyright (C) 2026- Istvan Z. Kovacs

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

Implements a thin wrapper around the Adafruit IO Python library, 
providing a simple interface for sending and receiving rpicampy specific messages.
"""

from datetime import datetime
from typing import Any, Dict, Dict, List

from Adafruit_IO import Client, Feed, Data, RequestError

### The rpicampy modules
try:
    from rpilogger import rpiLogger
except ImportError:
    import logging
    rpiLogger = logging.getLogger()


class AIOClient(Client):
    """
    A thin wrapper around the Adafruit IO Client, 
    providing a simple interface for sending and receiving rpicampy specific messages.
    """
    def __init__(self, key_file: str, status_feeds: List[str] = [], cmd_feeds: List[str] = []):
        self.key_file = key_file
        self.status_feeds = status_feeds
        self.cmd_feeds = cmd_feeds

        try:
            # Read the Adafruit IO credentials from the specified key file
            with open(key_file, mode='r', encoding='utf-8') as f:
                _user, _key = f.read().strip().split(',')

            rpiLogger.debug("AIOClient::: Clients authentication keys file read.")

        except (IOError, FileNotFoundError) as e:
            rpiLogger.error("AIOClient::: Clients authentication keys file '%s' not found! Exiting!\n%s\n", self.key_file, str(e))
            raise FileNotFoundError("AIOClient::: Clients authentication keys file '%s' not found!", self.key_file)

        # Create an instance of the AIO client
        super().__init__(_user, _key)

        # Get all the feeds for the rpicampy application, creating them if they don't exist
        for _feed_name in self.status_feeds:
            try:
                setattr(self, _feed_name, self.feeds(_feed_name))
            except RequestError:
                feed = Feed(name=_feed_name)
                self.create_group("rpicampy_status")
                setattr(self, _feed_name, self.create_feed(feed, 'rpicampy_status'))

        for _feed_name in self.cmd_feeds:
            try:
                setattr(self, _feed_name, self.feeds(_feed_name))
            except RequestError:
                feed = Feed(name=_feed_name)
                self.create_group("rpicampy_command")
                setattr(self, _feed_name, self.create_feed(feed, 'rpicampy_command'))

        rpiLogger.info("AIOClient::: Adafruit IO client initialized successfully.")

    def send_status(self, status_dict: Dict[str, Any]) -> None:
        """
        Send status messages to the specified feeds.
        """
        today = datetime.now().isoformat()
        for feed_name, feed_value in status_dict.items():
            if feed_name not in self.status_feeds:
                rpiLogger.warning("AIOClient::: Feed '%s' is not in the list of monitoring feeds. Message not sent.", feed_name)
                continue
            try:
                self.send(getattr(self, feed_name).key, value=feed_value, metadata={'created_at': today})
                rpiLogger.debug("AIOClient::: Sent status message to feed '%s': %s", feed_name, feed_value)
            except RequestError as e:
                rpiLogger.error("AIOClient::: Error sending status message to feed '%s': %s", feed_name, str(e))    

    def receive_commands(self, feed_name: str = "commands_string") -> Dict[str, Any]:
        """
        Receive commands from the specified command feed.
        """
        _cmd = dict()
        if feed_name not in self.cmd_feeds:
            rpiLogger.warning("AIOClient::: Feed '%s' is not in the list of command feeds. No commands received.", feed_name)
            return _cmd
        
        try:
            _data = self.receive(getattr(self, feed_name).key)
            if _data:
                _cmd = {"command_string": str(_data.value)}
                rpiLogger.debug("AIOClient::: Received command string from feed '%s': %s", feed_name, str(_data.value))
        except RequestError as e:
            rpiLogger.error("AIOClient::: Error receiving command string from feed '%s': %s", feed_name, str(e))

        return _cmd
    