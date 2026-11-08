import io, os, sys, re

ROOT = r"C:/Users/jch/WorkBuddy/2026-10-26-19-36-31/aerial-tools/ssm-smali"

REPL = {
    (r"com/stv/signalsourcemanager/SourceBase.smali", "enableSignalDesktop"): """.method public enableSignalDesktop()Z
    .registers 2

    .prologue
    const/4 v0, 0x0

    iput-boolean v0, p0, Lcom/stv/signalsourcemanager/SourceBase;->mEnableDesktop:Z

    return v0
.end method
""",
    (r"com/stv/signalsourcemanager/BaseUIActivity.smali", "toRightDesktop"): """.method public toRightDesktop()V
    .registers 1

    .prologue
    return-void
.end method
""",
}


def patch(path, method, new_body):
    with io.open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(".method") and re.search(r"->\s*" + re.escape(method) + r"\(", ln):
            start = i
            break
        if ln.startswith(".method") and re.search(r"\b" + re.escape(method) + r"\(.*\)", ln):
            start = i
            break
    if start is None:
        raise SystemExit("method not found: %s in %s" % (method, path))
    end = None
    for j in range(start, len(lines)):
        if lines[j].strip() == ".end method":
            end = j
            break
    if end is None:
        raise SystemExit("end method not found for %s" % method)
    print("patching %s :: %s  lines %d-%d" % (os.path.basename(path), method, start + 1, end + 1))
    out = lines[:start] + [new_body] + lines[end + 1:]
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)


for (rel, method), body in REPL.items():
    patch(os.path.join(ROOT, rel), method, body)
print("done")
