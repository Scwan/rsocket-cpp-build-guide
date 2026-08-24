# rsocket-cpp Cross-Platform Build Guide

Building [rsocket-cpp](https://github.com/rsocket/rsocket-cpp) — an archived C++ library
whose last commit is `45ed594`, **2021-08-26** — on macOS, Linux and Windows in 2026,
with the **full test suite passing on all of them**.

## Verified results

| Platform | Arch | Toolchain | Library | Tests |
|---|---|---|---|---|
| macOS (native) | arm64 | Apple clang 21 | ✅ | **131 / 131** |
| Linux (Docker) | arm64 | gcc 13 | ✅ | **131 / 131** |
| Linux (Docker) | x86_64 | gcc 13 | ✅ | **131 / 131** |
| Windows (native) | x86_64 | MSVC 14.43 / VS 2022 | ✅ | **131 / 131** |

Four configurations, two architectures, three compilers, one recipe.

---

## The single most important decision

> **Use vcpkg, and let it give you a *modern* folly. Do not pin folly to the project's own era.**

The instinct to pin folly to a 2021 commit (`2a20a79`, the same day as rsocket-cpp's last
commit) is wrong, and it costs you real bugs:

| Symptom with folly 2021 | With vcpkg's folly 2026 |
|---|---|
| 3 × `*TestLargePayload` fail — payload corruption at byte 16,776,190 | pass |
| `RequestResponseTest.Cancel` **hangs forever** on macOS | passes in ~20 ms |

Both were fixed upstream in folly years ago. Pinning folly to match the project's age
reintroduces them. They are *not* rsocket-cpp bugs and *not* platform bugs — measured on
clang 21, gcc 9/13 and MSVC 14.43.

vcpkg has an `rsocket` port pinned to this exact commit, carrying seven patches
(`use-cpp-17.patch`, `fix-folly.patch`, `fix-c2665.patch`, …) that adapt the 2021 code to a
current folly. That port is the foundation of everything below.

---

## Quick start

Each platform is self-contained. Linux is by far the least work.

### Linux — Docker (recommended)

Everything is in the [Dockerfile](#appendix-a--dockerfile-linux). One command:

```bash
docker build -t rsocket-vcpkg:linux . && docker run --rm rsocket-vcpkg:linux
```

Builds the library and the tests, then runs the suite. ~10–15 min from cold.
Works on both arm64 and x86_64 hosts — the triplet is selected from `uname -m`.

### macOS

```bash
# vcpkg needs pkg-config. With no Homebrew, build pkgconf from source:
curl -sL -o pkgconf.tar.gz https://github.com/pkgconf/pkgconf/releases/download/pkgconf-3.0.6/pkgconf-3.0.6.tar.gz
tar -xzf pkgconf.tar.gz && (cd pkgconf-3.0.6 && ./configure --prefix="$PWD/../pkgconf-install" && make -j"$(sysctl -n hw.ncpu)" && make install)
ln -sf pkgconf pkgconf-install/bin/pkg-config
export PATH="$PWD/pkgconf-install/bin:$PATH"

git clone --depth 1 https://github.com/microsoft/vcpkg.git
./vcpkg/bootstrap-vcpkg.sh -disableMetrics
./vcpkg/vcpkg install rsocket --triplet arm64-osx --editable
./vcpkg/vcpkg install gtest  --triplet arm64-osx

SRC=$(ls -d vcpkg/buildtrees/rsocket/src/*/ | head -1)
python3 patch_gtest.py  "$SRC"
python3 patch_cpp17.py  "$SRC"
python3 patch_cpp17b.py "$SRC"

cmake -S "$SRC" -B build-tests \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/vcpkg/scripts/buildsystems/vcpkg.cmake" \
  -DVCPKG_TARGET_TRIPLET=arm64-osx -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF -DBUILD_BENCHMARKS=OFF
cmake --build build-tests --target tests -j"$(sysctl -n hw.ncpu)"
./build-tests/tests
```

Use `x64-osx` instead of `arm64-osx` on Intel Macs. No extra link flags are needed —
all the `dbghelp` / glog / boost_thread wiring below is MSVC-only.

### Windows

Requires **Visual Studio 2022** with the *Desktop development with C++* workload.

```powershell
git clone --depth 1 https://github.com/microsoft/vcpkg.git C:\vcpkg
C:\vcpkg\bootstrap-vcpkg.bat -disableMetrics
C:\vcpkg\vcpkg.exe install rsocket:x64-windows-static --editable
C:\vcpkg\vcpkg.exe install gtest:x64-windows-static
```

The triplet **must be static** — the port calls `vcpkg_check_linkage(ONLY_STATIC_LIBRARY)`,
so `x64-windows` is rejected.

```powershell
$SRC = (Get-ChildItem C:\vcpkg\buildtrees\rsocket\src -Directory | Select-Object -First 1).FullName
python patch_gtest.py  $SRC
python patch_cpp17.py  $SRC
python patch_cpp17b.py $SRC

$INST = "C:/vcpkg/installed/x64-windows-static"
cmake -S $SRC -B C:\rs-tests -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_TOOLCHAIN_FILE=C:\vcpkg\scripts\buildsystems\vcpkg.cmake `
  -DVCPKG_TARGET_TRIPLET=x64-windows-static `
  -DCMAKE_POLICY_DEFAULT_CMP0091=NEW `
  -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded `
  -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF -DBUILD_BENCHMARKS=OFF `
  -DGLOG_LIBRARY_RELEASE="$INST/lib/glog.lib" `
  -DCMAKE_EXE_LINKER_FLAGS="dbghelp.lib $INST/lib/boost_thread-vc143-mt-x64-1_92.lib"

cmake --build C:\rs-tests --target tests --config Release --parallel 16
C:\rs-tests\Release\tests.exe
```

---

## Source changes

These are needed on **every** platform — identical text on clang, gcc and MSVC. They are
real C++17 conformance bugs in rsocket-cpp, not compiler quirks. Only three edits, in two files.

### 1–2. `noexcept` is part of the function type in C++17

`SetupResumeAcceptor` declares its callbacks as `folly::Function<... noexcept>`:

```cpp
using OnSetup  = folly::Function<void(std::unique_ptr<DuplexConnection>, SetupParameters)  noexcept>;
using OnResume = folly::Function<void(std::unique_ptr<DuplexConnection>, ResumeParameters) noexcept>;
```

but the tests pass **non-`noexcept`** callables to them. C++14 allowed this silently; C++17
made `noexcept` part of the function type, so it is now a hard error (MSVC `C2664`).
Five call sites in `rsocket/test/internal/SetupResumeAcceptorTest.cpp`:

```diff
-void setupFail(std::unique_ptr<DuplexConnection>, SetupParameters) {
+void setupFail(std::unique_ptr<DuplexConnection>, SetupParameters) noexcept {

-void resumeFail(std::unique_ptr<DuplexConnection>, ResumeParameters) {
+void resumeFail(std::unique_ptr<DuplexConnection>, ResumeParameters) noexcept {

-      [&](auto, auto) { setupCalled = true; },
+      [&](auto, auto) noexcept { setupCalled = true; },

-      [&](std::unique_ptr<DuplexConnection> connection, auto) {
+      [&](std::unique_ptr<DuplexConnection> connection, auto) noexcept {
```

(the last lambda pattern occurs twice)

### 3. Modern folly removed `Synchronized::operator->`

In `rsocket/test/handlers/HelloServiceHandler.cpp`. Note the same file already uses the
modern `.lock()->` form two functions earlier — this was a straggler:

```diff
-  auto itr = store_->find(token);
-  CHECK(itr != store_->end());
+  auto locked = store_.lock();
+  auto itr = locked->find(token);
+  CHECK(itr != locked->end());
   return itr->second;
```

Use `.lock()`, **not** `.rlock()` — this `Synchronized` uses a plain mutex, so the
shared-lock accessor does not exist.

### 4. Replace the vendored googletest

rsocket-cpp vendors **googletest 1.8.0** (2017) as a zip and builds it via
`ExternalProject_Add`. It cannot compile as C++17 under MSVC — `gtest-printers.h` fails with
`C2955: 'std::tuple': use of class template requires template argument list`. And C++17 is
mandatory, because modern folly requires it.

In the root `CMakeLists.txt`, replace the whole `ExternalProject_Add(gmock …)` block
(~20 lines, including the `ExternalProject_Get_Property` calls and the two
`include_directories`) with:

```cmake
find_package(GTest CONFIG REQUIRED)
set(GMOCK_LIBS GTest::gmock GTest::gmock_main GTest::gtest)
```

Then remove `gmock` from all six `add_dependencies(...)` calls (four in the root
`CMakeLists.txt`, two in `yarpl/CMakeLists.txt`). Three of them list *only* `gmock` and must
be deleted entirely — CMake rejects `add_dependencies()` with no dependencies.

**No test-code changes are needed for the gtest upgrade.** rsocket-cpp uses none of the
renamed APIs (`INSTANTIATE_TEST_CASE_P`, `TYPED_TEST_CASE`, `SetUpTestCase`,
`testing::internal`, `tr1` — zero occurrences), and modern googletest still defines the
legacy `MOCK_METHOD0-9` / `MOCK_CONST_METHOD0-9` macros the mocks rely on (52 uses).

---

## Platform-specific build wiring

None of this touches source — it is packaging.

### Windows / MSVC

| Flag | Why |
|---|---|
| `-DCMAKE_POLICY_DEFAULT_CMP0091=NEW` | Without it `CMAKE_MSVC_RUNTIME_LIBRARY` is **silently ignored**, and you get `LNK2038: RuntimeLibrary mismatch MT_StaticRelease vs MD_DynamicRelease`. The policy is gated behind `cmake_minimum_required`, and rsocket-cpp declares `3.2`. |
| `-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded` | Match the `x64-windows-static` triplet's `/MT`. |
| `-DGLOG_LIBRARY_RELEASE=…/lib/glog.lib` | Module-mode `find_package` sets this to the **debug** library by default, producing `MTd_StaticDebug` vs `MT_StaticRelease` conflicts. |
| `dbghelp.lib` | glog needs `SymInitialize`, `UnDecorateSymbolName`, … |
| `boost_thread-…​.lib` (full path) | folly's `PThread.cpp` needs `boost::detail::get_tss_data`. A bare name fails with `LNK1181` — that directory is not on the linker search path. |

Generator: the **Visual Studio** generator works. Ninja also works *after* the gtest swap —
but if you keep the vendored `ExternalProject_Add(gmock)`, Ninja fails with
`ninja: error: 'gmock.lib', needed by 'tests.exe', missing and no known rule to make it`,
because ExternalProject outputs need explicit `BUILD_BYPRODUCTS`. MSBuild does not enforce that.

### Linux

- **Use a modern base image.** `ubuntu:24.04`, not 20.04 — vcpkg's folly 2026 needs a
  current compiler. (This is the opposite of what an apt-based, folly-2021 build wants.)
- **Install CMake ≥ 3.29 yourself.** 24.04 ships 3.28.3; `double-conversion` 3.4.0 requires
  3.29. You cannot rely on vcpkg fetching its own, because `VCPKG_FORCE_SYSTEM_BINARIES=1`
  is mandatory on arm64.
- **`autoconf autoconf-archive automake libtool`** — `libunwind` (a folly dependency on
  Linux only) builds with autotools.

### macOS

- **vcpkg requires `pkg-config`.** With no Homebrew, build pkgconf from source and symlink
  it as `pkg-config` (see Quick start). The failure is
  `Could not find pkg-config. Please install it via your package manager`, and it happens
  *after* double-conversion has already compiled — it's the `vcpkg_fixup_pkgconfig` step.
- Nothing else. No extra link flags, no policy overrides.

---

## Dead ends — don't repeat these

**Do not use folly's own `getdeps.py` on Windows.** Six attempts, all fatal. Boost.Build
never generates `bin.v2/standalone/msvc/msvc-14.3/msvc-setup.nup`, so `cl.exe` is never
invoked and *every* configuration probe reports "no" (`compiler supports SSE2 : no`) while
`cl.exe` itself works perfectly. Along the way you will need — and still fail after —
`--vcvars-path` (getdeps looks for VS in pre-2019 paths), `toolset=msvc` (getdeps passes no
toolset on Windows at all), `architecture=x86`, and clearing b2's poisoned
`bin.v2/project-cache.jam`.

**Do not pin folly to 2021.** See [the top of this document](#the-single-most-important-decision).
The getdeps + folly-2021 route works on macOS and Linux but needs ~11 separate fixes
(dead SourceForge boost mirror, Boost.MPL enum UB vs clang 21, `std::unary_function` removed
in C++17, googletest `-Werror`, getdeps building OpenSSL as `darwin64-x86_64-cc` on Apple
Silicon…) and still fails 3–4 tests.

**Do not use CMake 4.x.** It refuses `cmake_minimum_required(VERSION 3.2)` outright. Use the
3.31 line, or pass `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`.

**Driving Docker Desktop on Windows over SSH:** `buildx` invokes a credential helper that
needs an interactive desktop logon, so a remote `docker build` dies with
`error getting credentials … Anmeldesitzung ist nicht vorhanden` before pulling anything.
`docker pull` and `docker run` are fine. Workaround — use the classic builder:

```
set "DOCKER_BUILDKIT=0" && docker build -t rsocket-vcpkg:linux .
```

---

## Known issues

- **`rsocket` is unmaintained.** Last commit 2021-08-26. Its CI (Travis) is long dead and
  only ever covered Linux with gcc-5/6 and clang-6.
- **vcpkg's folly port warns "The library is UNSTABLE on Windows."** That is Microsoft's own
  description. It concerns runtime behaviour, not compilation — a green test suite does not
  refute it.
- **One test is disabled** in the suite (`YOU HAVE 1 DISABLED TEST`); that is upstream's own
  `DISABLED_` marker, not something introduced here.
- The upstream `CMakeLists.txt` hardcodes `set(OPENSSL_ROOT_DIR "/usr/local/opt/openssl")`
  on Apple, clobbering any value you pass. It doesn't bite on the vcpkg route (the toolchain
  file resolves OpenSSL first), but it will if you build against system libraries.

---

## Appendix A — Dockerfile (Linux)

Self-contained: builds the library, applies the patches, builds the tests, and runs them
as the default command. Requires `patch_gtest.py`, `patch_cpp17.py` and `patch_cpp17b.py`
in the build context.

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git curl zip unzip tar pkg-config \
      python3 ca-certificates linux-libc-dev \
      autoconf autoconf-archive automake libtool \
    && rm -rf /var/lib/apt/lists/*

# 24.04 ships cmake 3.28.3 but double-conversion 3.4.0 needs >= 3.29, and vcpkg
# cannot download its own tools on arm64 (VCPKG_FORCE_SYSTEM_BINARIES).
ARG CMAKE_VER=3.31.12
RUN ARCH="$(uname -m)" \
 && curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VER}/cmake-${CMAKE_VER}-linux-${ARCH}.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local \
 && cmake --version

ENV VCPKG_FORCE_SYSTEM_BINARIES=1
RUN git clone --depth 1 https://github.com/microsoft/vcpkg.git /opt/vcpkg \
 && /opt/vcpkg/bootstrap-vcpkg.sh -disableMetrics

RUN TRIPLET="$([ "$(uname -m)" = "aarch64" ] && echo arm64-linux || echo x64-linux)" \
 && /opt/vcpkg/vcpkg install rsocket --triplet "$TRIPLET" --editable

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
```

## Appendix B — patch scripts

Three small Python scripts, run against the vcpkg source tree
(`vcpkg/buildtrees/rsocket/src/<hash>/`). They are idempotent and report what they changed.

| Script | Does |
|---|---|
| `patch_gtest.py` | Swaps `ExternalProject_Add(gmock)` for `find_package(GTest CONFIG)`; strips `gmock` from six `add_dependencies` calls |
| `patch_cpp17.py` | Adds `noexcept` to `setupFail`/`resumeFail`; converts `store_->find()` to a held lock |
| `patch_cpp17b.py` | Adds `noexcept` to the three lambdas; corrects `.rlock()` to `.lock()` |

`--editable` on the `vcpkg install` is what keeps that source tree around; without it vcpkg
cleans it up and the patches have nothing to apply to.
