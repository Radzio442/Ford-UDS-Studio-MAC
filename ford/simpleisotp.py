"""
This is by no means a full/proper ISOTP implementation. It aims to work with just the BROKEN Ford implementation.


This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""

import sys
from time import sleep
from io import BytesIO
import can
import platform
import time

class SimpleISOTP:
	def __init__(self, can_interface, can_tx, can_rx):
		self.state = 0
		self.can_id = can_tx
		try:
			if isinstance(can_interface, str) and can_interface.startswith("fordlink"):
				from fordlink import FordLinkBus
				prefix, port = can_interface.split(":", 1)
				channel = 1 if prefix == "fordlink1" else 0
				self.bus = FordLinkBus(port=port, serial_baudrate=1_000_000, channel=channel, bitrate=500000)
			elif platform.system() == "Darwin":
				# macOS: python-can komunikuje się bezpośrednio z adapterem GS_USB.
				self.bus = can.Bus(
					interface="gs_usb",
					channel=int(can_interface),
					bitrate=500000,
				)
			else:
				# Linux: natywny SocketCAN, np. can0 lub can1.
				self.bus = can.Bus(
					interface="socketcan",
					channel=can_interface,
					bitrate=500000,
					receive_own_messages=False,
				)
		except Exception as e:
			print("[!] Unable to open {}: {}".format(can_interface, e))
			sys.exit(-1)

		can_filters = [{"can_id": can_rx, "can_mask": 0xfff, "extended": False}]
		self.bus.set_filters(can_filters)

	def close(self):
		"""Bezpiecznie zamyka backend python-can (szczególnie GS_USB na macOS)."""
		bus = getattr(self, "bus", None)
		if bus is None:
			return
		self.bus = None
		try:
			bus.shutdown()
		except Exception as e:
			print("[!] CAN shutdown warning: {}".format(e))


	def putoncan(self, msg):
		sleep(0.002)
		return self.bus.send(msg)

	def send(self, payload):
		size = len(payload)

		if size < 8:
			self.state = 0
			data = bytearray([len(payload)]) + payload + bytearray([0x00] * (7-size))
			msg = can.Message(arbitration_id=self.can_id, data=data, is_extended_id=False)
			self.putoncan(msg)
		else:
			data = bytearray().fromhex('1{:03x}'.format(size)) + payload[:6]
			msg = can.Message(arbitration_id=self.can_id, data=data, is_extended_id=False)
			self.putoncan(msg)
			while True:
				fc = self.bus.recv(timeout=5.0)
				if fc is None:
					raise TimeoutError("Timeout oczekiwania na ISO-TP Flow Control")
				if not fc.data:
					continue
				flow_status = fc.data[0] & 0x0F
				if (fc.data[0] & 0xF0) != 0x30:
					continue
				if flow_status == 0x01:  # WAIT
					continue
				if flow_status != 0x00:
					raise RuntimeError(f"ISO-TP Flow Control rejected: 0x{flow_status:02X}")
				stmin_raw = int(fc.data[2]) if len(fc.data) > 2 else 0
				if stmin_raw <= 0x7F:
					stmin_seconds = stmin_raw / 1000.0
				elif 0xF1 <= stmin_raw <= 0xF9:
					stmin_seconds = (stmin_raw - 0xF0) / 10000.0
				else:
					stmin_seconds = 0.0
				break

			self.state = 1
			ds = BytesIO(payload[6:])

			while True:
				part = ds.read(7)
				if not part:
					self.state = 0
					break

				data = bytearray([0x20+self.state]) + part + bytearray([0x00] * (7-len(part)))
				msg = can.Message(arbitration_id=self.can_id, data=data, is_extended_id=False)
				self.putoncan(msg)
				if stmin_seconds > 0:
					time.sleep(stmin_seconds)
				if self.state < 0x0f:
					self.state += 1
				else:
					self.state = 0

	def recv(self, timeout=5.0):
		"""Receive and reassemble one ISO-TP message."""
		import time
		deadline = time.monotonic() + timeout
		buf = None
		total_size = 0
		received = 0
		expected_sn = 1

		while time.monotonic() < deadline:
			remaining = deadline - time.monotonic()
			frame = self.bus.recv(timeout=max(0.0, remaining))
			if frame is None:
				return None
			data = bytes(frame.data)
			if not data:
				continue

			pci = data[0] & 0xF0

			# Single Frame
			if pci == 0x00:
				size = data[0] & 0x0F
				self.state = 0
				return data[1:1 + size]

			# First Frame
			if pci == 0x10:
				total_size = ((data[0] & 0x0F) << 8) | data[1]
				buf = bytearray(data[2:])
				received = min(6, total_size)
				expected_sn = 1
				self.state = 1

				fc_data = bytearray([0x30, 0x00, 0x00]) + bytearray(5)
				fc = can.Message(arbitration_id=self.can_id, data=fc_data, is_extended_id=False)
				self.putoncan(fc)
				if received >= total_size:
					self.state = 0
					return bytes(buf[:total_size])
				continue

			# Consecutive Frame
			if pci == 0x20 and buf is not None:
				sn = data[0] & 0x0F
				if sn != expected_sn:
					self.state = 0
					return None
				expected_sn = (expected_sn + 1) & 0x0F
				remaining_data = total_size - received
				chunk = data[1:1 + min(7, remaining_data)]
				buf.extend(chunk)
				received += len(chunk)
				if received >= total_size:
					self.state = 0
					return bytes(buf[:total_size])
				continue

			# Flow Control belongs to the transmit path; ignore here.
			if pci == 0x30:
				continue

		self.state = 0
		return None

