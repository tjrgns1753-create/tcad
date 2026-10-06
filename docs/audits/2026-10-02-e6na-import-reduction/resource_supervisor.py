"""엔진 없는 Windows 후보 감독. Working set은 주기 관측이며 commit 제한이 아니다."""
import ctypes as C
from ctypes import wintypes as W
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

INTERVAL_S = 0.5
WORKING_SET_CAP = 6 * 1024**3
TRIANGLE_CAP = 400000
FILE_CAP = 120 * 1024**2
TOTAL_CAP = 200 * 1024**2


def require_elements(count, callback):
    if type(count) is not int or not 0 < count <= TRIANGLE_CAP:
        raise ValueError('ELEMENT_RESOURCE_CAP')
    return callback()


def payload_check(raw_bytes, file_bytes, previous_bytes=0):
    if any(type(v) is not int or v < 0 for v in (raw_bytes, file_bytes, previous_bytes)):
        raise ValueError('INVALID_SIZE_EVIDENCE')
    if max(raw_bytes, file_bytes) > FILE_CAP or previous_bytes + max(raw_bytes, file_bytes) > TOTAL_CAP:
        raise ValueError('OUTPUT_RESOURCE_CAP')


class Job:
    """별도 작업만 소유. breakaway 허용 안 함; 마지막 handle close 시 트리 종료."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('WINDOWS_JOB_REQUIRED')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.ps = C.WinDLL('psapi', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
        self.k.CreateJobObjectW.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.CloseHandle.restype = W.BOOL
        self.k.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        self.k.SetInformationJobObject.restype = W.BOOL
        self.k.QueryInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p]
        self.k.QueryInformationJobObject.restype = W.BOOL
        self.k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        self.k.AssignProcessToJobObject.restype = W.BOOL
        self.k.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        self.k.TerminateJobObject.restype = W.BOOL
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.ps.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.c_void_p, W.DWORD]
        self.ps.GetProcessMemoryInfo.restype = W.BOOL

        class Basic(C.Structure):
            _fields_ = [('per_process', C.c_int64), ('per_job', C.c_int64), ('flags', W.DWORD),
                        ('min_ws', C.c_size_t), ('max_ws', C.c_size_t), ('active', W.DWORD),
                        ('affinity', C.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class IO(C.Structure):
            _fields_ = [(n, C.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(C.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', C.c_size_t),
                        ('job_memory', C.c_size_t), ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        if not self.k.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            err = C.get_last_error()
            self.close()
            raise C.WinError(err)

    def assign(self, process):
        if not self.k.AssignProcessToJobObject(self.handle, W.HANDLE(int(process._handle))):
            raise C.WinError(C.get_last_error())

    def pids(self):
        # Overflow/query failure is fail-closed, never a partial process list.
        buf = C.create_string_buffer(65536)
        if not self.k.QueryInformationJobObject(self.handle, 3, buf, len(buf), None):
            raise C.WinError(C.get_last_error())
        assigned, listed = (W.DWORD * 2).from_buffer(buf)
        if assigned != listed or 8 + listed * C.sizeof(C.c_size_t) > len(buf):
            raise RuntimeError('PROCESS_LIST_INCOMPLETE')
        return list((C.c_size_t * listed).from_buffer(buf, 8))

    def memory(self):
        class Memory(C.Structure):
            _fields_ = [('cb', W.DWORD), ('faults', W.DWORD)] + [(n, C.c_size_t) for n in
                        ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
        ws = commit = 0
        for pid in self.pids():
            handle = self.k.OpenProcess(0x410, False, pid)
            if not handle:
                raise RuntimeError('MEMORY_METRIC_UNAVAILABLE')
            try:
                mem = Memory()
                mem.cb = C.sizeof(mem)
                if not self.ps.GetProcessMemoryInfo(handle, C.byref(mem), mem.cb):
                    raise RuntimeError('MEMORY_METRIC_UNAVAILABLE')
                ws += mem.ws
                commit += mem.pagefile
            finally:
                self.k.CloseHandle(handle)
        return ws, commit

    def stop(self):
        if not self.k.TerminateJobObject(self.handle, 1):
            raise C.WinError(C.get_last_error())

    def close(self):
        if self.handle:
            if not self.k.CloseHandle(self.handle):
                raise C.WinError(C.get_last_error())
            self.handle = None


def supervise(argv, cwd, log, *, candidate_s=600, total_deadline=None,
              memory_cap=WORKING_SET_CAP, interval=INTERVAL_S, job_factory=Job):
    """부모는 엔진을 읽지 않는다. 짧은 예산은 합성 테스트에서만 사용한다."""
    if not argv or not all(isinstance(v, str) for v in argv):
        raise ValueError('INVALID_ARGV')
    if not all(math.isfinite(v) and v > 0 for v in (candidate_s, interval, memory_cap)):
        raise ValueError('INVALID_RESOURCE_POLICY')
    started = time.monotonic()
    deadline = min(started + candidate_s, total_deadline if total_deadline is not None else math.inf)
    rec = {'status':'STARTED', 'started_unix':time.time(), 'cleanup_ok':False,
           'peak_sampled_tree_working_set':0, 'peak_sampled_tree_commit':0,
           'memory_semantics':'sampled process-tree working-set sum; commit separately observed',
           'interval_s':interval, 'candidate_budget_s':candidate_s}
    job = process = None
    try:
        if started >= deadline:
            raise TimeoutError('TOTAL_WALL_RESOURCE_CAP')
        job = job_factory()
        with tempfile.TemporaryDirectory(prefix='e6na_release_') as tmp:
            release = Path(tmp)/'release'
            with open(log, 'wb') as stream:
                process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                                            '--bootstrap', str(release), *argv], cwd=cwd,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                rec['pid'] = process.pid
                job.assign(process)
                release.touch()  # The target cannot start before successful assignment.
                while True:
                    now = time.monotonic()
                    if now >= deadline:
                        raise TimeoutError('WALL_RESOURCE_CAP')
                    ws, commit = job.memory()
                    rec['peak_sampled_tree_working_set'] = max(ws, rec['peak_sampled_tree_working_set'])
                    rec['peak_sampled_tree_commit'] = max(commit, rec['peak_sampled_tree_commit'])
                    if ws > memory_cap:
                        raise MemoryError('WORKING_SET_RESOURCE_CAP')
                    if Path(log).stat().st_size > FILE_CAP:
                        raise ValueError('LOG_RESOURCE_CAP')
                    rc = process.poll()
                    if rc is not None:
                        rec['exit_code'] = rc
                        if job.pids():
                            raise RuntimeError('DESCENDANTS_REMAIN')
                        rec['status'] = 'COMPLETED' if rc == 0 else 'FAIL'
                        break
                    time.sleep(min(interval, max(0, deadline - now)))
    except Exception as exc:
        rec.update(status='TIMEOUT' if isinstance(exc, TimeoutError) else 'FAIL',
                   reason=str(exc), error_type=type(exc).__name__)
    finally:
        try:
            if job is not None:
                job.stop()
                until = time.monotonic() + 5
                while job.pids() and time.monotonic() < until:
                    time.sleep(0.05)
                if job.pids():
                    raise RuntimeError('PROCESS_TREE_STOP_FAILED')
            if process is not None:
                if job is None or process.poll() is None:
                    process.kill()  # Only the owned bootstrap, never an unrelated PID.
                process.wait(timeout=5)
                rec.setdefault('exit_code', process.returncode)
            rec['cleanup_ok'] = True
        except Exception as exc:
            rec.update(status='FAIL', cleanup_error=str(exc))
        finally:
            if job is not None:
                try:
                    job.close()
                except Exception as exc:
                    rec.update(status='FAIL', cleanup_ok=False, cleanup_error=str(exc))
        rec.update(ended_unix=time.time(), duration_s=time.monotonic()-started)
    return rec


if __name__ == '__main__':
    if len(sys.argv) < 5 or sys.argv[1] != '--bootstrap':
        raise SystemExit('BOOTSTRAP_ARGUMENTS_REQUIRED')
    release = Path(sys.argv[2])
    end = time.monotonic()+30
    while not release.is_file():
        if time.monotonic() >= end:
            raise SystemExit('JOB_ASSIGNMENT_NOT_RELEASED')
        time.sleep(0.02)
    # Target Python runs inside the assigned Job and inherits its process-tree protection.
    raise SystemExit(subprocess.call(sys.argv[3:]))
