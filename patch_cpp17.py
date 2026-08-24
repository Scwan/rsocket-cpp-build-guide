import sys, os
root = sys.argv[1]

# --- 1. C++17: noexcept is part of the function type. These free functions are
#        passed to folly::Function<... noexcept>, so they must be noexcept too.
p = os.path.join(root, "rsocket", "test", "internal", "SetupResumeAcceptorTest.cpp")
s = open(p, encoding="utf-8").read()
fixes = [
 ("void setupFail(std::unique_ptr<DuplexConnection>, SetupParameters) {",
  "void setupFail(std::unique_ptr<DuplexConnection>, SetupParameters) noexcept {"),
 ("void resumeFail(std::unique_ptr<DuplexConnection>, ResumeParameters) {",
  "void resumeFail(std::unique_ptr<DuplexConnection>, ResumeParameters) noexcept {"),
]
n = 0
for old, new in fixes:
    if new in s:
        print("  already noexcept:", old.split("(")[0].split()[-1])
    elif old in s:
        s = s.replace(old, new); n += 1
        print("  + noexcept ->", old.split("(")[0].split()[-1])
    else:
        print("  !! not found:", old[:50])
if n:
    open(p, "w", encoding="utf-8").write(s)

# --- 2. modern folly removed Synchronized::operator->; take an explicit lock.
p2 = os.path.join(root, "rsocket", "test", "handlers", "HelloServiceHandler.cpp")
s2 = open(p2, encoding="utf-8").read()
old2 = """  auto itr = store_->find(token);
  CHECK(itr != store_->end());
  return itr->second;"""
new2 = """  auto locked = store_.rlock();
  auto itr = locked->find(token);
  CHECK(itr != locked->end());
  return itr->second;"""
if new2 in s2:
    print("  Synchronized: already patched")
elif old2 in s2:
    open(p2, "w", encoding="utf-8").write(s2.replace(old2, new2))
    print("  Synchronized: store_->find/end -> store_.rlock()")
else:
    print("  !! Synchronized block not found; actual text:")
    for i, l in enumerate(s2.splitlines(), 1):
        if "store_" in l: print(f"     {i}: {l.strip()}")
