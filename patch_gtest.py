import re, sys, os

root = sys.argv[1]
main_cml = os.path.join(root, "CMakeLists.txt")
yarpl_cml = os.path.join(root, "yarpl", "CMakeLists.txt")

REPLACEMENT = """  # Modern googletest from the package manager. The vendored googletest 1.8.0
  # cannot compile as C++17 under MSVC (gtest-printers.h, std::tuple).
  find_package(GTest CONFIG REQUIRED)
  set(GMOCK_LIBS GTest::gmock GTest::gmock_main GTest::gtest)
"""

def patch_main(path):
    lines = open(path, encoding="utf-8").read().splitlines(True)
    start = end = None
    for i, l in enumerate(lines):
        if start is None and "ExternalProject_Add(" in l:
            # confirm this is the gmock one (next few lines mention gmock)
            if any("gmock" in x for x in lines[i:i+4]):
                start = i
                # walk back over a leading "# gmock" comment
                if i > 0 and lines[i-1].strip().startswith("# gmock"):
                    start = i - 1
        if start is not None and "GMOCK_SOURCE_DIR}/googletest/include" in l:
            end = i
            break
    if start is None or end is None:
        print("  !! gmock ExternalProject block NOT found"); return False
    print(f"  replacing lines {start+1}-{end+1} ({end-start+1} lines) with find_package(GTest)")
    lines[start:end+1] = [REPLACEMENT]
    open(path, "w", encoding="utf-8").write("".join(lines))
    return True

def strip_gmock_deps(path):
    src = open(path, encoding="utf-8").read()
    out, n_removed, n_deleted = [], 0, 0
    for line in src.splitlines(True):
        m = re.match(r'^(\s*)add_dependencies\(([^)]*)\)(.*)$', line, re.S)
        if m and "gmock" in m.group(2):
            indent, inner, tail = m.groups()
            toks = inner.split()
            toks = [t for t in toks if t != "gmock"]
            n_removed += 1
            if len(toks) <= 1:          # only the target left -> drop the call
                n_deleted += 1
                continue
            line = f"{indent}add_dependencies({' '.join(toks)}){tail}"
        out.append(line)
    open(path, "w", encoding="utf-8").write("".join(out))
    print(f"  add_dependencies: {n_removed} touched, {n_deleted} removed entirely")

print("== root CMakeLists ==");  patch_main(main_cml); strip_gmock_deps(main_cml)
print("== yarpl CMakeLists =="); strip_gmock_deps(yarpl_cml)
print("== remaining gmock refs (should be GMOCK_LIBS / comments only) ==")
for p in (main_cml, yarpl_cml):
    for i, l in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
        if "gmock" in l.lower():
            print(f"  {os.path.basename(os.path.dirname(p))}/{os.path.basename(p)}:{i}: {l.strip()[:90]}")
