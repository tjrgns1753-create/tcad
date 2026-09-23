"""Remote run driver. Reads remote/request.json, validates it against remote/profiles.py,
runs the selected profile (argv list, no shell) on a GitHub-hosted runner and writes
remote-out/summary.json, remote-out/run.log (sanitized) and allowed output files.

Refuses to execute a profile anywhere except a GitHub-hosted runner (use --validate-only
locally: it validates and hashes inputs but runs nothing).
Exit code: 0 only if the profile exited 0. Failure, timeout and validation errors are
recorded as such and give a non-zero exit code; nothing is ever converted to PASS.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import profiles as P  # noqa: E402

SECRET_PATTERNS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "<TOKEN>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "<TOKEN>"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "<TOKEN>"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "<TOKEN>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer <TOKEN>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "<PRIVATE-KEY>"),
]
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")
EXACT_PATH_LABELS = [("GITHUB_WORKSPACE", "<WORKSPACE>"), ("RUNNER_TEMP", "<RUNNER_TEMP>"),
                     ("RUNNER_TOOL_CACHE", "<TOOL_CACHE>"), ("HOME", "<HOME>"), ("USERPROFILE", "<HOME>")]


class Sanitizer:
    """Removes absolute paths and token-like strings from every line that leaves the runner."""

    def __init__(self):
        self.counts = {}
        pairs = []
        for var, label in EXACT_PATH_LABELS:
            v = os.environ.get(var)
            if v and len(v) > 3:
                for form in {v, v.replace("\\", "/"), v.replace("/", "\\"), os.path.normpath(v)}:
                    pairs.append((form, label))
        pairs.append((ROOT, "<WORKSPACE>"))
        pairs.append((ROOT.replace("\\", "/"), "<WORKSPACE>"))
        self.pairs = sorted(set(pairs), key=lambda p: -len(p[0]))

    def _bump(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def clean(self, text):
        for src, label in self.pairs:
            if src in text:
                self._bump(label, text.count(src))
                text = text.replace(src, label)
        text, n = USER_PATH.subn("<USERPROFILE>", text)
        if n:
            self._bump("<USERPROFILE>", n)
        for rx, label in SECRET_PATTERNS:
            text, n = rx.subn(label, text)
            if n:
                self._bump(label, n)
        return text


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    except OSError:
        return ""


def validate(request):
    if request.get("schema") != 1:
        raise ValueError("request.schema must be 1")
    rid = request.get("request_id", "")
    if not re.match(P.REQUEST_ID_PATTERN, str(rid)):
        raise ValueError("request_id must match " + P.REQUEST_ID_PATTERN)
    name = request.get("profile")
    if name not in P.PROFILES:
        raise ValueError(f"profile {name!r} is not in the allowlist {sorted(P.PROFILES)}")
    allowed_keys = {"schema", "request_id", "profile", "params", "note"}
    extra = set(request) - allowed_keys
    if extra:
        raise ValueError(f"unknown request field(s) {sorted(extra)}; commands are never accepted from a request")
    prof = P.PROFILES[name]
    params = request.get("params", {}) or {}
    for k in params:
        if k not in prof["params"]:
            raise ValueError(f"parameter {k!r} is not declared by profile {name}")
    resolved = {}
    for k, spec in prof["params"].items():
        if k not in params:
            raise ValueError(f"missing parameter {k!r}")
        v = params[k]
        if "choices" in spec:
            if v not in spec["choices"]:
                raise ValueError(f"parameter {k!r}={v!r} not in {spec['choices']}")
        elif "int" in spec:
            lo, hi = spec["int"]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValueError(f"parameter {k!r}={v!r} must be an int in [{lo}, {hi}]")
        else:
            raise ValueError(f"profile {name}: parameter {k!r} has no validator")
        resolved[k] = str(v)
    entry = os.path.normpath(os.path.join(ROOT, prof["entry"]))
    if not entry.startswith(ROOT + os.sep) or not os.path.isfile(entry):
        raise ValueError(f"profile entry {prof['entry']!r} is not a file inside the repository")
    args = [a.format(**resolved) for a in prof["args"]]
    return name, prof, resolved, entry, args


def package_versions():
    from importlib import metadata
    out = {}
    for n in ("ViennaPS", "ViennaLS", "devsim", "mkl", "intel-openmp", "tbb", "numpy", "meshio", "matplotlib", "pillow"):
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = None
    return out


def devsim_info():
    code = ("import json, devsim; i = devsim.get_parameter(name='info'); "
            "print(json.dumps({k: i.get(k) for k in ('version','extended_precision','direct_solver','math_libraries')}))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "devsim info unavailable", "exit_code": r.returncode}


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=os.path.join(HERE, "request.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "remote-out"))
    ap.add_argument("--validate-only", action="store_true", help="validate the request and hash inputs; run nothing")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    san = Sanitizer()
    started = utc_now()
    t0 = time.time()
    summary = {"schema": 1, "status": "ERROR", "started_utc": started.isoformat()}
    log_path = os.path.join(out, "run.log")
    rc = 1
    try:
        request = json.load(open(a.request, encoding="utf-8"))
        summary["request"] = request
        name, prof, params, entry, args = validate(request)
        summary["profile"] = name
        summary["inputs"] = [{"path": p, "sha256": sha256_file(os.path.join(ROOT, p)), "bytes": os.path.getsize(os.path.join(ROOT, p))}
                             for p in prof["inputs"]]
        summary["request_sha256"] = sha256_file(a.request)
        cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
        head = git("rev-parse", "HEAD")
        code_paths = ["tcad", "tests", "tcad_2d_stagewise.py", "examples"]
        same = subprocess.run(["git", "diff", "--quiet", cfg["review_sha"], "HEAD", "--", *code_paths], cwd=ROOT).returncode
        summary["source"] = {"github_sha": os.environ.get("GITHUB_SHA") or head, "git_head": head,
                             "ref": os.environ.get("GITHUB_REF"), "repository": os.environ.get("GITHUB_REPOSITORY"),
                             "run_id": os.environ.get("GITHUB_RUN_ID"), "run_number": os.environ.get("GITHUB_RUN_NUMBER"),
                             "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "review_sha": cfg["review_sha"],
                             "code_paths_identical_to_review_sha": same == 0, "code_paths_checked": code_paths}
        hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        summary["runner"] = {"github_actions": os.environ.get("GITHUB_ACTIONS"), "runner_environment": os.environ.get("RUNNER_ENVIRONMENT"),
                             "runner_os": os.environ.get("RUNNER_OS"), "runner_arch": os.environ.get("RUNNER_ARCH"),
                             "github_hosted_confirmed": hosted, "platform": platform.platform(), "python": sys.version.split()[0],
                             "cpu_count": os.cpu_count()}
        if a.validate_only:
            summary.update({"status": "VALIDATED_ONLY", "argv": [os.path.relpath(entry, ROOT), *args], "timeout_s": prof["timeout_s"]})
            rc = 0
            raise SystemExit
        if not hosted:
            raise RuntimeError("refusing to run: not a GitHub-hosted runner (GITHUB_ACTIONS/RUNNER_ENVIRONMENT). "
                               "Long computations run remotely; use --validate-only locally.")
        summary["packages"] = package_versions()
        summary["devsim"] = devsim_info()
        argv = [sys.executable, entry, *args]
        summary["argv"] = ["<python>", prof["entry"], *args]
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        timed_out = threading.Event()

        def watchdog():
            timed_out.set()
            kill_tree(proc)

        timer = threading.Timer(prof["timeout_s"], watchdog)
        timer.start()
        max_log = P.MAX_LOG_MB * 1024 * 1024
        written = 0
        truncated = False
        with open(log_path, "w", encoding="utf-8", newline="\n") as lf:
            for line in proc.stdout:
                line = san.clean(line.rstrip("\n").rstrip("\r"))
                print(line, flush=True)
                if written < max_log:
                    lf.write(line + "\n")
                    written += len(line) + 1
                elif not truncated:
                    truncated = True
                    lf.write("[log truncated at MAX_LOG_MB; console output continues]\n")
        proc.wait()
        timer.cancel()
        summary["exit_code"] = proc.returncode
        summary["log_truncated"] = truncated
        summary["status"] = "TIMEOUT" if timed_out.is_set() else ("PASS" if proc.returncode == 0 else "FAIL")
        rc = 0 if summary["status"] == "PASS" else 1
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001 - recorded, never swallowed into a PASS
        summary["status"] = "ERROR"
        summary["error"] = san.clean(f"{type(e).__name__}: {e}")
        rc = 1
    ended = utc_now()
    summary["ended_utc"] = ended.isoformat()
    summary["duration_s"] = round(time.time() - t0, 3)
    # outputs: declared globs, within budget; everything else is reported as omitted
    outputs, omitted = [], []
    prof = P.PROFILES.get(summary.get("profile"), {})
    budget = P.MAX_TOTAL_OUTPUT_MB * 1024 * 1024
    used = 0
    if summary["status"] in ("PASS", "FAIL", "TIMEOUT"):
        for spec in prof.get("outputs", []):
            for f in sorted(glob.glob(os.path.join(ROOT, spec["glob"]), recursive=True)):
                if not os.path.isfile(f):
                    continue
                size = os.path.getsize(f)
                rel = os.path.relpath(f, ROOT).replace("\\", "/")
                rec = {"path": rel, "bytes": size, "sha256": sha256_file(f)}
                if size > spec["max_mb"] * 1024 * 1024 or used + size > budget:
                    omitted.append({**rec, "reason": "over size budget"})
                    continue
                dest = os.path.join(out, "outputs", rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(f, dest)
                used += size
                outputs.append(rec)
    summary["outputs"] = outputs
    summary["omitted_outputs"] = omitted
    summary["regenerate"] = prof.get("regenerate")
    if os.path.exists(log_path):
        summary["log"] = {"file": "run.log", "sha256": sha256_file(log_path), "bytes": os.path.getsize(log_path)}
    summary["redactions"] = san.counts
    text = json.dumps(summary, indent=1)
    residual = [rx.pattern for rx, _ in SECRET_PATTERNS if rx.search(text)] + ([USER_PATH.pattern] if USER_PATH.search(text) else [])
    if residual:
        summary = {"schema": 1, "status": "ERROR", "error": "summary contained sensitive-looking text and was withheld", "patterns": residual}
        text = json.dumps(summary, indent=1)
        rc = 1
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    md = os.environ.get("GITHUB_STEP_SUMMARY")
    if md:
        with open(md, "a", encoding="utf-8") as f:
            f.write(f"### remote run `{summary.get('request', {}).get('request_id')}` : **{summary['status']}**\n\n"
                    f"- profile: `{summary.get('profile')}`, exit_code: `{summary.get('exit_code')}`, duration_s: `{summary.get('duration_s')}`\n"
                    f"- source: `{summary.get('source', {}).get('github_sha')}`, code identical to review SHA: "
                    f"`{summary.get('source', {}).get('code_paths_identical_to_review_sha')}`\n"
                    f"- GitHub-hosted confirmed: `{summary.get('runner', {}).get('github_hosted_confirmed')}`\n")
    print(f"[remote-run] status={summary['status']} exit_code={summary.get('exit_code')} duration_s={summary.get('duration_s')}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
