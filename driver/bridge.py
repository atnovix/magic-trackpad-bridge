"""Seriële verbinding met de ESP32-brug: regels lezen in een eigen thread, automatisch herverbinden.

De poort wordt geopend met DTR en RTS laag vóór het openen, zodat de CP2102 het bordje niet reset.
"""
import logging
import threading
import time

import serial

log = logging.getLogger("bridge")


class BridgeReader(threading.Thread):
    def __init__(self, port, baud, on_line, on_status):
        super().__init__(name="bridge-serial", daemon=True)
        self.port, self.baud = port, baud
        self.on_line = on_line          # callback(str) voor elke regel
        self.on_status = on_status      # callback(connected: bool, text: str)
        self._stop = threading.Event()
        self._ser = None
        self._reopen = threading.Event()

    def stop(self):
        self._stop.set()

    def reconnect(self):
        self._reopen.set()

    def send(self, text):
        ser = self._ser
        if ser is not None:
            try:
                ser.write(text.encode("ascii", errors="ignore"))
            except serial.SerialException as e:
                log.warning("schrijven naar %s mislukt: %s", self.port, e)

    def run(self):
        while not self._stop.is_set():
            try:
                ser = serial.Serial()
                ser.port, ser.baudrate, ser.timeout = self.port, self.baud, 0.2
                ser.dtr = False
                ser.rts = False
                ser.open()
                ser.reset_input_buffer()
                self._ser = ser
                self.on_status(True, f"seriële poort {self.port} open")
                self._reopen.clear()
                with ser:
                    while not self._stop.is_set() and not self._reopen.is_set():
                        raw = ser.readline()
                        if not raw:
                            continue
                        s = raw.decode("utf-8", errors="replace").strip()
                        if s:
                            self.on_line(s)
            except serial.SerialException as e:
                self.on_status(False, f"{self.port}: {e}")
                log.warning("seriële poort: %s", e)
                time.sleep(2.0)
            finally:
                self._ser = None
        self.on_status(False, "gestopt")
