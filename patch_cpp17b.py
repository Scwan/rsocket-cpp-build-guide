import sys, os
root = sys.argv[1]

# 1. this Synchronized uses a plain mutex -> only .lock() exists, not .rlock()
p = os.path.join(root, "rsocket", "test", "handlers", "HelloServiceHandler.cpp")
s = open(p, encoding="utf-8").read()
if "store_.rlock()" in s:
    s = s.replace("store_.rlock()", "store_.lock()")
    open(p, "w", encoding="utf-8").write(s)
    print("  rlock() -> lock()")
else:
    print("  rlock: nothing to do")

# 2. lambdas bound to folly::Function<... noexcept> must themselves be noexcept (C++17)
p2 = os.path.join(root, "rsocket", "test", "internal", "SetupResumeAcceptorTest.cpp")
s2 = open(p2, encoding="utf-8").read()
subs = [
  ("[&](auto, auto) { setupCalled = true; }",
   "[&](auto, auto) noexcept { setupCalled = true; }"),
  ("[&](std::unique_ptr<DuplexConnection> connection, auto) {",
   "[&](std::unique_ptr<DuplexConnection> connection, auto) noexcept {"),
]
total = 0
for old, new in subs:
    if new in s2 and old.replace("{", "noexcept {") not in s2:
        print("  already noexcept:", old[:46]); continue
    c = s2.count(old)
    if c:
        s2 = s2.replace(old, new); total += c
        print(f"  + noexcept x{c}: {old[:46]}")
    else:
        print("  !! not found:", old[:46])
if total:
    open(p2, "w", encoding="utf-8").write(s2)
print(f"  total lambda fixes: {total}")
