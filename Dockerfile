# rsocket-cpp on Linux via vcpkg (modern folly), mirroring the Windows recipe.
# NOTE: unlike the apt-based Dockerfile, this needs a MODERN base image -
# vcpkg's folly (2026) requires a recent compiler, so 20.04's gcc-9 is too old.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git curl zip unzip tar pkg-config \
      python3 ca-certificates linux-libc-dev \
      autoconf autoconf-archive automake libtool \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships cmake 3.28.3, but double-conversion 3.4.0 needs >= 3.29.
# vcpkg cannot download its own tools on arm64 (VCPKG_FORCE_SYSTEM_BINARIES),
# so install a current CMake ourselves.
ARG CMAKE_VER=3.31.12
RUN ARCH="$(uname -m)" \
 && curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VER}/cmake-${CMAKE_VER}-linux-${ARCH}.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local \
 && cmake --version

ENV VCPKG_FORCE_SYSTEM_BINARIES=1
RUN git clone --depth 1 https://github.com/microsoft/vcpkg.git /opt/vcpkg \
 && /opt/vcpkg/bootstrap-vcpkg.sh -disableMetrics

# Build the library exactly as the Windows path does. Tests are wired up
# afterwards from the patched source vcpkg leaves in buildtrees.
RUN TRIPLET="$([ "$(uname -m)" = "aarch64" ] && echo arm64-linux || echo x64-linux)" \
 && echo "using triplet: $TRIPLET" \
 && /opt/vcpkg/vcpkg install rsocket --triplet "$TRIPLET" --editable

WORKDIR /work

# ---- tests -------------------------------------------------------------
# The vcpkg port builds with BUILD_TESTS=OFF. To build them we need modern
# googletest (the vendored 1.8.0 predates C++17) plus three genuine C++17
# fixes in rsocket's own test code. See the patch scripts for details.
RUN TRIPLET="$([ "$(uname -m)" = "aarch64" ] && echo arm64-linux || echo x64-linux)" \
 && /opt/vcpkg/vcpkg install gtest --triplet "$TRIPLET"

COPY patch_gtest.py patch_cpp17.py patch_cpp17b.py /tmp/

RUN TRIPLET="$([ "$(uname -m)" = "aarch64" ] && echo arm64-linux || echo x64-linux)" \
 && SRC="$(ls -d /opt/vcpkg/buildtrees/rsocket/src/*/ | head -1)" \
 && python3 /tmp/patch_gtest.py  "$SRC" \
 && python3 /tmp/patch_cpp17.py  "$SRC" \
 && python3 /tmp/patch_cpp17b.py "$SRC" \
 && cmake -S "$SRC" -B /opt/rs-tests -G Ninja \
      -DCMAKE_TOOLCHAIN_FILE=/opt/vcpkg/scripts/buildsystems/vcpkg.cmake \
      -DVCPKG_TARGET_TRIPLET="$TRIPLET" -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF -DBUILD_BENCHMARKS=OFF \
 && cmake --build /opt/rs-tests --target tests -j"$(nproc)"

WORKDIR /opt/rs-tests
CMD ["./tests"]
