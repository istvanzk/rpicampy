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

Implements the rpiTimer class to manage the main timer events & actions
including the handling of the status monitoring and remote commands.
"""
import signal
import time
from typing import Any, Dict, List, Tuple

### The rpicampy modules
from rpilogger import rpiLogger
from rpievents import rpiEventsClass
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE
from rpiconfig import RPIJOBNAMES, HOST_NAME, RPICAMPY_VER
from rpiwsocket import WebSocketServerThread

class rpiTimerClass(rpiBaseClass):
    """
    Implements the rpiTimer class to manage the main timer events & actions
    including the handling of the status monitoring and remote commands
    """

    def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, rc_config, imgcam, imgdbx, imgdir):

        ### Get events defined (for all the other jobs)
        self._rpi_events: rpiEventsClass  = rpi_events

        ### Get the Remote Control configurations
        self._rc_config: Dict = rc_config

        ### References to the other jobs interfaces
        self._imgcam: rpiBaseClass = imgcam
        self._imgdbx: rpiBaseClass = imgdbx
        self._imgdir: rpiBaseClass = imgdir

        ### Custom config parameters for ThingSpeak monitoring and remote control option
        self._ts_config: Dict = dict()

        ### Custom config parameters for Websocket monitoring and remote control option
        self._ws_config: Dict = dict()

        ### Init base class
        # As last step, it runs automatically the initClass()
        super().__init__(name, rpi_apscheduler, rpi_events, rpi_config)

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), config=%s, TS config=%s, WS config=%s)>" % \
            (self.__class__.__name__, self.name, self._sched, self._config, self._ts_config, self._ws_config)

    def __str__(self):
        msg = super().__str__()
        return "%s::: config: %s, TS config: %s, WS config: %s, \n%s" % \
                (self.name, self._config, self._ts_config, self._ws_config, msg)

    def __del__(self):
        ### Clean base class
        super().__del__()


    #
    # Main interface methods
    #

    def jobRun(self):

        ### 
        if not self._eventErr.is_set():

            try:
                # Collect status info from rpicampy jobs and send status info to remote device(s)
                self._procsend_status()

                # Retrieve remote control commands received from remote device(s) and dispatch commands to rpicampy jobs
                self._recvproc_cmds()

            except OSError as e:
                self.statusUpdate = (self.name, ERRLEV2)
                rpiLogger.warning("rpitimer::: jobRun() OSError \n%s", str(e))
                raise rpiBaseClassError("rpitimer::: jobRun() OSError!", ERRLEV2)

            except Exception as e:
                self.statusUpdate = (self.name, ERRCRIT)
                rpiLogger.error("rpitimer::: jobRun(): Unhandled Exception!\n%s\n", str(e))
                raise rpiBaseClassError("rpitimer::: jobRun(): Unhandled Exception!", ERRCRIT)

            finally:
                pass

        else:
            # Update status
            self.statusUpdate = (self.name, ERRLEV0)
            rpiLogger.debug("rpitimer::: eventErr is set!")




    def initClass(self):
        """"
        (re)Initialize the class
        """
        # Jobs enabled/disabled
        self.jobs_enabled: bool = False

        # Cmd mode active/standby
        self.cmd_mode: bool = False

        # Statuss messages from all jobs        
        self.status_msg_all_jobs: Dict = dict()

        # Reset the state values (own and all jobs)
        self._stateval      = 0
        self._jobs_stateval = 0

        # Initialize ThingSpeak clients if configured
        if 'ts-status' in self._rc_config['rc_type'] \
            or 'ts-cmd' in self._rc_config['rc_type']:

            import thingspk

            if 'ts-status' in self._rc_config['rc_type']:
                self._ts_config['RESTfeed'] = thingspk.ThingSpeakAPIClient(self._rc_config['token_file'])
                if self._rc_config['RESTfeed'] is not None:

                    self._ts_config['mon_fields'] = dict()
                    for indx, item in enumerate(RPIJOBNAMES):
                        self._ts_config['mon_fields'][item] = 'field%d' % indx

                    for tsf in self._ts_config['mon_fields'].values():
                        self._ts_config['RESTfeed'].setfield(tsf, 0)

                    self._ts_config['RESTfeed'].setfield('status', 'n/a')
                    rpiLogger.info("rpitimer::: ThingSpeak client Channel ID %d initialized. Fields: %s", self._ts_config['RESTfeed'].channel_id, self._ts_config['mon_fields'])

                else:
                    rpiLogger.warning("rpitimer::: ThingSpeak API could not be initialized.")

            if 'ts-cmd' in self._rc_config['rc_type']:
                self._ts_config['RESTTalkB'] = thingspk.ThingSpeakTBClient(self._rc_config['token_file'])
                if self._ts_config['RESTTalkB'] is not None:
                    rpiLogger.info("rpitimer::: ThingSpeak TalkBack client ID %d initialized.", self._ts_config['RESTTalkB'].talkback_id)
                else:
                    rpiLogger.warning("rpitimer::: ThingSpeak TalkBack could not be initialized.")

        else:
            self._ts_config['RESTfeed'] = None
            self._ts_config['RESTTalkB'] = None


        # Initialize WebSocket server if configured
        if 'ws-status' in self._rc_config['rc_type'] \
            or 'ws-cmd' in self._rc_config['rc_type']:
            
            # Websocket server interrupt signal handler
            def signal_handler(sig, frame):
                rpiLogger.info("Signal received: %s. Shutting down WS server...", sig)
                self._ws_config['server'].stop()
                self._ws_config['server'].join()
                self._ws_config['server'] = None

            # Enable send messages (as server) if configured
            if 'ws-status' in self._rc_config['rc_type']:
                self._ws_config["mon_json"] = {
                    "type": "status",
                    "device_id": RPICAMPY_VER,
                    "time": time.ctime(time.time()),
                    "status_dict": dict()
                }
                for _, item in enumerate(RPIJOBNAMES):
                    self._ws_config["mon_json"]["status_dict"][item] = ""
            else:
                self._ws_config["mon_json"] = None

            # Enable receive messages (as server) if configured
            if 'ws-cmd' in self._rc_config['rc_type']:
                self._ws_config["cmd_json"] = {
                    "type": "command",
                    "device_id": "",
                    "time": "",
                    "command_string": ""
                }
            else:
                self._ws_config["cmd_json"] = None

            # Stop server if it is running
            if self._ws_config['server'] is not None:
                signal_handler(signal.SIGINT, None)

            # Start server on the local hostname and domain
            self._ws_config['server'] = WebSocketServerThread(
                host = f"{HOST_NAME}.local",
                port = self._rc_config['port'],
                key_file = self._rc_config['token_file'])
            self._ws_config['server'].start()
            rpiLogger.info("rpitimer::: WebSocket server started.")

            # Register server interrupt signal handler
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

        else:
            self._ws_config['server'] = None

        # Update status
        self.statusUpdate = (self.name, ERRNONE)



#   def endDayOAM(self):
#       """
#       End-of-Day 0AM
#       """

#   def endOAM(self):
#       """
#       End OAM procedure.
#       """

    def _recvproc_cmds(self):
        """
        Receive remote control commands through the configured options:
        - ThingSpeak TalkBack APP
        - WebSocket JSON message
        Process and dispatch/send the commands to the target rpicampy jobs.
        """
        # Defaults
        cmdstr = u'none'
        cmdval = -1

        # Get command from ThingSpeak TalkBack APP if configured/available
        if self._ts_config['RESTTalkB'] is not None:
            self._ts_config['RESTTalkB'].talkback.execcmd()
            res = self._ts_config['RESTTalkB'].talkback.response
            if res is not None:
                # Get cmd string and value
                cmdrx = res.get('command_string')
                cmdstr = cmdrx.split('/',1)[0]
                cmdval = int(cmdrx.split('/',1)[1])

                rpiLogger.debug("rpitimer::: TB command: %s", res)

        # Receive command via WebSocket if configured/available
        if self._ws_config['server'] is not None \
            and self._ws_config["cmd_json"] is not None:

            res = self._ws_config['server'].receive_json
            if res is not {} \
                and res.get('type') == "command" \
                and "command_string" in res:

                self._ws_config["cmd_json"] = res

                # Get cmd string and value
                cmdrx  = res.get('command_string')
                cmdstr = cmdrx.split('/',1)[0]
                cmdval = int(cmdrx.split('/',1)[1])

                rpiLogger.debug("rpitimer::: WS command: %s", res)

        # Handle and dispatch the received commands (if any)
        # Timer job commands
        self.cmd_mode = False
        if cmdstr==u'sch':
            if cmdval==1 and not self.jobs_enabled:
                self.jobs_enabled = True
                rpiLogger.debug("rpitimer::: JobSch Enabled.")

            elif cmdval==0 and self.jobs_enabled:
                self.jobs_enabled = False
                rpiLogger.debug("rpitimer::: JobSch disabled.")

        # Cmd mode
        elif cmdstr==u'cmd':
            if cmdval==1 and not self.cmd_mode:
                self.cmd_mode = True
                #schedRPi.reschedule_job(job_id="TIMERJob", trigger='interval', seconds=timerConfig['interval_sec'][1])
                #self.timePeriodIntv = (None, None, timerConfig['interval_sec'][1])
                #self._reschedule_run()
                rpiLogger.debug("rpitimer::: Cmd mode Activate.")

            elif cmdval==0 and self.cmd_mode:
                self.cmd_mode = False
                #schedRPi.reschedule_job(job_id="TIMERJob", trigger='interval', seconds=timerConfig['interval_sec'][0])
                #self.timePeriodIntv = (None, None, timerConfig['interval_sec'][0])
                #self._reschedule_run()
                rpiLogger.debug("rpitimer::: Cmd mode in Standby.")

        # Dispatch the commands meant for other rpicampy jobs
        # These commands are active only in Cmd mode!
        if self.cmd_mode:

            # Cam control
            if cmdstr == u'cam':
                self._imgcam.queueCmd((cmdstr,cmdval))

            # Dir control
            elif cmdstr == u'dir':
                self._imgdir.queueCmd((cmdstr,cmdval))

            # Dbx control
            elif cmdstr == u'dbx':
                self._imgdbx.queueCmd((cmdstr,cmdval))

    def _procsend_status(self):
        """
        Collect the combined state values and the status messages from all the rpicampy jobs.
        Send status messages through the configured monitoring options:
        - ThingSpeak REST API post feed data
        - WebSocket JSON message 
        """
        # Get the combined state value
        self._proc_stateval()

        # Get status messages
        self._get_status_messages()

        # Update ThingSpeak feed if configured/available
        if self._ts_config['RESTfeed'] is not None:
            _status_message = ''
            _messages: List = list()
            for k, (msg, val) in self.status_msg_all_jobs.items():
                if msg is not None:
                    _messages.append(msg)

                if ( val > ERRNONE or \
                    ( val == ERRNONE and msg is not None ) ):
                    self._ts_config['RESTfeed'].setfield(self._ts_config['mon_fields'][k], val)
                
                if not _messages==[]:
                    _status_message = ' || '.join(_messages)
                    self._ts_config['RESTfeed'].setfield('status', _status_message)

                # Update feed
                self._ts_config['RESTfeed'].update()

        # Update status via WebSocket if configured/available
        if self._ws_config['server'] is not None \
            and self._ws_config["mon_json"] is not None:

            self._ws_config["mon_json"]["time"] = time.ctime(time.time())
            for k, (msg, val) in self.status_msg_all_jobs.items():
                if msg is not None:
                    self._ws_config["mon_json"]["status_dict"][k] = f"{msg}:{val}"
                else:
                    self._ws_config["mon_json"]["status_dict"][k] = "n/a"

                # Send status
                self._ws_config['server'].send_json(self._ws_config["mon_json"])

    def _proc_stateval(self):
        """
        Calculate the combined state (cmd and err) values for all rpicampy jobs.
        """
        # Add the self job enabled state (lower 4 bits)
        self._stateval = 0
        if self.jobs_enabled:
            self._stateval += 1

        # Add the self job cmd state (upper 4 bits)
        if self.cmd_mode:
            self._stateval += 16

        # The combined state values for all 5 rpicampy jobs (5 bytes).
        # For each job, the state value is stored as one byte:
        # - job error state in lower 4 bits
        # - job cmd state in upper 4 bits
        self._jobs_stateval = \
            self._stateval + \
            256*self._rpi_events.stateValList[self.name] + \
            256*256*self._rpi_events.stateValList[self._imgcam.name] + \
            256*256*256*self._rpi_events.stateValList[self._imgdir.name] + \
            256*256*256*256*self._rpi_events.stateValList[self._imgdbx.name]

        # Update status
        self.statusUpdate = (f"{self.name} StateVals", self._jobs_stateval)

    def _get_status_messages(self):
        """
        Retrieve the latest status messages from all rpicampy jobs.
        """
        self.status_msg_all_jobs = dict()
        self.status_msg_all_jobs[[k for k,v in RPIJOBNAMES.items() if v == self.name][0]] = self.statusUpdate
        self.status_msg_all_jobs[[k for k,v in RPIJOBNAMES.items() if v == self._imgcam.name][0]] = self._imgcam.statusUpdate
        self.status_msg_all_jobs[[k for k,v in RPIJOBNAMES.items() if v == self._imgdir.name][0]] = self._imgdir.statusUpdate
        self.status_msg_all_jobs[[k for k,v in RPIJOBNAMES.items() if v == self._imgdbx.name][0]] = self._imgdbx.statusUpdate
