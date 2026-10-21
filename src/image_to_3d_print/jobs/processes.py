"""回收本worker产生的整个进程树，包括工具自己的进程组。"""
import os
import psutil


def kill_tree(pid, include_parent=True):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try: child.kill()
            except psutil.NoSuchProcess: pass
        if include_parent:
            try: parent.kill()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs(children + ([parent] if include_parent else []), timeout=5)
    except psutil.NoSuchProcess: pass


def stop_owned_runner(row):
    pid = row.get('runner_pid')
    if not pid: return
    try:
        process = psutil.Process(pid)
        cmd = process.cmdline()
        if (abs(process.create_time() - row['runner_birth']) < .01
                and 'image_to_3d_print.jobs.runner' in cmd and row['run'] in cmd):
            kill_tree(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied): pass


class SingleWorker:
    def __init__(self, root): self.path = root / 'worker.lock'

    def __enter__(self):
        self.file = self.path.open('a+b')
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('该存储目录已有单worker运行') from exc
        return self

    def __exit__(self, *args):
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()
