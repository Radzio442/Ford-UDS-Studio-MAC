#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ford.uds import Ecu

def decode(value):
    return bytes(value).decode("ascii", errors="replace").strip("\x00") if value else "<brak odpowiedzi>"

def main():
    ap=argparse.ArgumentParser(description="FordLink full ISO-TP / UDS probe")
    ap.add_argument("port")
    ap.add_argument("--channel",type=int,choices=(0,1),default=0)
    ap.add_argument("--ecu",type=lambda x:int(x,0),default=0x720)
    args=ap.parse_args()
    interface=f"{'fordlink1' if args.channel else 'fordlink'}:{args.port}"
    ecu=Ecu(can_interface=interface,ecuid=args.ecu)
    try:
        print(f"Connected: {interface}, ECU=0x{args.ecu:03X}")
        if not ecu.UDSDiagnosticSessionControl(0x01):
            print("[!] Brak odpowiedzi na 10 01"); return 2
        print("[+] Session 0x01 OK")
        hw=ecu.UDSReadDataByIdentifier([0xF1,0x11])
        part=ecu.UDSReadDataByIdentifier([0xF1,0x13])
        strategy=ecu.UDSReadDataByIdentifier([0xF1,0x88])
        print(f"F111 Hardware:    {decode(hw)}")
        print(f"F113 Part number: {decode(part)}")
        print(f"F188 Strategy:    {decode(strategy)}")
        return 0 if part else 3
    finally:
        ecu.close()
if __name__=='__main__': raise SystemExit(main())
