#!/bin/sh

### BEGIN INIT INFO
# Provides:          RPiCamTest
# Required-Start:    $remote_fs $syslog
# Required-Stop:     $remote_fs $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Runs the /usr/local/bin/rpicam
# Description:       RPi based webcam process
### END INIT INFO

# sudo /etc/init.d/NameOfYourScript status/start/stop
# To register/remove your script to be run at start-up and shutdown:
# sudo update-rc.d NameOfYourScript defaults
# sudo update-rc.d -f NameOfYourScript remove

# Change the next 3 lines to suit where you install your script and what you want to call it
DIR=/usr/local/bin/rpicam
DAEMON=rpicam_sch.py
DAEMON_NAME=rpicamtest

# This next line determines what user the script runs as.
# Root generally not recommended but necessary if you are using the Raspberry Pi GPIO from Python
DAEMON_USER=root

# The process ID of the script when it runs is stored here:
PIDFILE=/var/run/$DAEMON_NAME.pid

# Exit if the package is not installed
[ -x "$DIR/$DAEMON" ] || exit 0

# Load the VERBOSE setting and other rcS variables
#. /lib/init/vars.sh

# Define LSB log_* functions.
# Depend on lsb-base (>= 3.2-14) to ensure that this file is present
# and status_of_proc is working.
. /lib/lsb/init-functions

do_start () {
    log_daemon_msg "Starting system $DAEMON_NAME daemon"
    start-stop-daemon -d $DIR --start  --background --pidfile $PIDFILE --make-pidfile --user $DAEMON_USER --startas $DAEMON
    log_end_msg $?
}

do_stop () {
    log_daemon_msg "Stopping system $DAEMON_NAME daemon"
    start-stop-daemon --stop --pidfile $PIDFILE --retry 10
    log_end_msg $?
}

case "$1" in

    start|stop)
        do_${1}
        ;;

    restart|reload|force-reload)
        do_stop
        do_start
        ;;

    status)
        status_of_proc "$DAEMON_NAME" "$DAEMON" && exit 0 || exit $?
        ;;
    *)
        echo "Usage: /etc/init.d/$DEAMON_NAME {start|stop|restart|status}"
        exit 1
        ;;

esac
exit 0