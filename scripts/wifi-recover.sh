#!/bin/bash
#
# /usr/local/bin/wifi-recover.sh
# sudo chmod +x /usr/local/bin/wifi-recover.sh
#
# Used by:
# /etc/systemd/system/wifi-recover.service
# /etc/systemd/system/wifi-recover.timer
# Check logs:
# journalctl -b -t wifi-watchdog --no-pager | grep -iE "ERROR|CRITICAL"
#
# Generated with Microsoft Copilot
#

ROUTER_IP="192.168.18.1"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
STATEFILE="/run/wifi-watchdog-lastfail"
USB_ID="7392"   
INTERFACE="wlan0"
USB_PORT="1-1"      # Typical for Raspberry Pi A+ (adjust if needed)
REBOOT_TIMEOUT=300  # seconds Wi-Fi can be down before reboot
KERNEL_WINDOW="1 minute ago"

USB_POWER_PATTERNS="(usb .*reset|not accepting address|device descriptor read/64, error -71|over-current)"
WIFI_CRASH_PATTERNS="(failed to load firmware|failed to init|TX queue hang|TX hang|MAC reset|device descriptor read/64, error -71|not accepting address|reset high-speed USB device|usb_submit_urb failed|usbctrl_vendorreq failed|queue stalled)"

log() {
    logger -t wifi-watchdog "$TIMESTAMP - $1"
}

start_failure_timer() {
    log "INFO: Start failure timer"
    [ -f "$STATEFILE" ] || echo "$TIMESTAMP" > "$STATEFILE"
}

check_failure_timer_and_reboot() {
    if [ -f "$STATEFILE" ]; then
        FIRSTFAIL=$(cat "$STATEFILE")
        FAILSECONDS=$(( $(date +%s) - $(date -d "$FIRSTFAIL" +%s) ))
        if [ "$FAILSECONDS" -gt "$REBOOT_TIMEOUT" ]; then
            log "CRITICAL: WiFi/USB failure for >${REBOOT_TIMEOUT}s. Rebooting system"
            /usr/bin/systemctl reboot
        fi
    fi
}

clear_failure_timer() {
    if [ -f "$STATEFILE" ]; then
        rm "$STATEFILE"
        log "INFO: Clear failure timer"
    fi
}

usb_reset() {
    log "INFO: Attempting USB port reset via uhubctl on $USB_PORT"
    uhubctl -l "$USB_PORT" -a off
    sleep 2
    uhubctl -l "$USB_PORT" -a on
    sleep 5
}

# --- USB Presence Check ---
if ! lsusb | grep -qi "$USB_ID"; then
    log "CRITICAL: USB WiFi dongle missing from lsusb (possible power fault)"
    usb_reset

    # Check again
    if ! lsusb | grep -qi "$USB_ID"; then
        log "CRITICAL: USB WiFi still missing after uhubctl reset"
        start_failure_timer
        check_failure_timer_and_reboot
    else
        log "INFO: USB WiFi dongle reappeared after reset"
    fi
    exit 0
fi

# --- USB Power Fault Check ---
if journalctl -k --since "$KERNEL_WINDOW" | grep -qiE "$USB_POWER_PATTERNS"; then
    log "CRITICAL: USB power/reset fault detected"
    usb_reset
fi

# --- dmesg Crash Signature Check ---
if journalctl -k --since "$KERNEL_WINDOW" | grep -qiE "$WIFI_CRASH_PATTERNS"; then
    log "CRITICAL: dmesg reports WiFi/Realtek crash signature"
    usb_reset
fi

# --- Interface Presence Check ---
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    log "CRITICAL: Interface $INTERFACE missing"
    start_failure_timer
    check_failure_timer_and_reboot
    exit 0
fi

# --- Normal WiFi Connectivity Check ---
if ping -c1 -W2 "$ROUTER_IP" >/dev/null; then
    log "OK: WiFi reachable"
    clear_failure_timer
    exit 0
fi

log "ERROR: WiFi unreachable. Restarting $INTERFACE via NetworkManager"
nmcli device disconnect "$INTERFACE"
sleep 2
nmcli device connect "$INTERFACE"

if ping -c1 -W2 "$ROUTER_IP" >/dev/null; then
    log "INFO: wlan0 reconnected to primary AP"
    clear_failure_timer
    exit 0
fi

log "CRITICAL: WiFi still down after reconnect attempt"
start_failure_timer
check_failure_timer_and_reboot