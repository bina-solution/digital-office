#!/bin/bash
# Build libopus 1.5.2 with the neural models (Deep PLC, DRED, OSCE) into $PREFIX (default ~/opus/install).
# plc_opus.py loads $PREFIX/lib/libopus.so (pass --lib or set OPUS_LIB).  Needs gcc/make (build-essential).
set -e
PREFIX=${PREFIX:-$HOME/opus/install}
mkdir -p "$(dirname "$PREFIX")" && cd "$(dirname "$PREFIX")"
[ -f opus-1.5.2.tar.gz ] || curl -sL -o opus-1.5.2.tar.gz https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz
echo "65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1  opus-1.5.2.tar.gz" | sha256sum -c - || { echo "checksum mismatch"; exit 1; }
tar xzf opus-1.5.2.tar.gz && cd opus-1.5.2
./configure --prefix="$PREFIX" --enable-deep-plc --enable-dred --enable-osce >/dev/null
make -j"$(nproc)" >/dev/null && make install >/dev/null
ls -la "$PREFIX/lib/libopus.so"*
echo "OPUS_LIB=$PREFIX/lib/libopus.so"
