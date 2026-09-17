#!/usr/bin/env python3
import argparse
from studio.backend import FordBackend


def main():
    parser = argparse.ArgumentParser(description="Ford VBFlasher 2.0")
    parser.add_argument("interface", help="macOS: numer GS_USB, Linux: can0/can1")
    parser.add_argument("vbf", nargs="+", help="SBL i dowolna liczba plików VBF w kolejności programowania")
    parser.add_argument("--unlock-test", action="store_true", help="tylko sesja 0x02 i Security Access")
    args = parser.parse_args()

    backend = FordBackend()
    backend.load_files(args.vbf)
    if args.unlock_test:
        backend.connect(args.interface)
        try:
            backend.unlock_test()
        finally:
            backend.disconnect()
    else:
        backend.flash_all(args.interface)


if __name__ == "__main__":
    main()
