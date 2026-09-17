#!/usr/bin/env python3
from __future__ import annotations
import argparse, glob, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fordlink import FordLinkBus

try:
    import can
except ImportError:
    can = None

def ports():
    found=[]
    for pattern in ('/dev/cu.usbmodem*','/dev/cu.usbserial*','/dev/ttyACM*','/dev/ttyUSB*'):
        found += glob.glob(pattern)
    return sorted(set(found))

def main():
    ap=argparse.ArgumentParser(description='FordLink/UCDS CH3.2 transport probe')
    ap.add_argument('port', nargs='?', help='e.g. /dev/cu.usbmodem1101')
    ap.add_argument('--channel', type=int, choices=(0,1), default=0)
    ap.add_argument('--read-f113', action='store_true', help='send ISO-TP single frame 22 F1 13 to IPC 0x720')
    args=ap.parse_args()
    if not args.port:
        print('Detected serial ports:')
        for p in ports(): print(' ',p)
        return
    bus=FordLinkBus(args.port, channel=args.channel)
    try:
        print(f'Connected: HW=0x{bus.info.hardware_id:02X}, name={bus.info.name}, FW={bus.info.firmware}, serial={bus.info.serial_hex}')
        if args.read_f113:
            data=bytes.fromhex('03 22 F1 13 00 00 00 00')
            msg=can.Message(arbitration_id=0x720,data=data,is_extended_id=False) if can else type('M',(),{'arbitration_id':0x720,'data':data,'is_extended_id':False,'is_remote_frame':False})()
            print('TX 720: ' + data.hex(' ').upper())
            bus.send(msg)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                frame=bus.recv(timeout=0.2)
                if frame is not None:
                    print(f'RX {frame.arbitration_id:03X}: {bytes(frame.data).hex(" ").upper()}')
                    if frame.arbitration_id==0x728: break
    finally:
        bus.shutdown()
if __name__=='__main__': main()
