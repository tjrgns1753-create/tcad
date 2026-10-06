"""승인 전 순수 정책 prototype. 프로세스/엔진/운영 실행기에 연결되지 않는다."""
import math


def decision(elapsed_candidate, elapsed_total, working_set, metric_ok=True):
    if not metric_ok or not all(isinstance(v,(int,float)) and math.isfinite(v) and v>=0
                               for v in (elapsed_candidate,elapsed_total,working_set)):
        return 'MONITOR_UNAVAILABLE'
    if elapsed_candidate>=600 or elapsed_total>=1800:
        return 'TIMEOUT'
    if working_set>6*1024**3:
        return 'MEMORY_LIMIT'
    return 'CONTINUE'


def payload_budget(files):
    if not files or any(type(v) is not int or v<0 for v in files.values()):
        return 'INVALID_SIZE_EVIDENCE'
    if max(files.values())>120*1024**2 or sum(files.values())>200*1024**2:
        return 'OUTPUT_LIMIT'
    return 'WITHIN_BUDGET'


def supervise_snapshot(snapshot, stop, finalize):
    """합성 clock/프로세스 callback용. 실제 watchdog이 아니다."""
    status=decision(**snapshot)
    if status!='CONTINUE':
        try:
            stop()
        except Exception:
            status='PROCESS_TREE_STOP_FAILED'
        finalize(status)
    return status
