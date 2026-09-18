#!/bin/bash
cd "$(dirname "$0")"
./build_macos_release.sh
open "dist/Ford UDS Studio.app"
