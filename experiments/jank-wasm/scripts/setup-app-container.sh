#!/usr/bin/env bash
# AI-assisted bootstrap, only inside the disposable Ubuntu 24.04 container.
set -euo pipefail
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl gnupg \
  git build-essential g++-14 cmake ninja-build pkg-config python3 file xz-utils \
  libssl-dev libdouble-conversion-dev libffi-dev libbz2-dev libboost-all-dev \
  zlib1g-dev libzstd-dev libxml2-dev libedit-dev
curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | \
  gpg --dearmor --yes -o /usr/share/keyrings/llvm.gpg
echo 'deb [signed-by=/usr/share/keyrings/llvm.gpg] https://apt.llvm.org/noble/ llvm-toolchain-noble-23 main' \
  > /etc/apt/sources.list.d/llvm.list
apt-get update
version='1:23.1.6~++20261116013850+5b10d2d74929-1~exp1~20261116133903.98'
apt-get install -y "clang-23=$version" "llvm-23-dev=$version" \
  "libclang-23-dev=$version" "libclang-cpp23-dev=$version" \
  "clang-tools-23=$version" "lld-23=$version"
