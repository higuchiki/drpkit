"""Write an output file atomically, never overwriting an existing path.

The data goes to a temporary file in the destination directory first. The temporary file is read back,
compared with the data and handed to an optional ``check`` callback; only when all of that passes is it
moved into place. On any failure the temporary file is removed, so a partial output is never left at
``dst``.
"""
import os
import tempfile


def write_new_file(dst, data, check=None):
    """Create ``dst`` with ``data``. Raises FileExistsError if ``dst`` exists (also when it appears meanwhile).

    ``check(path)`` is called with the temporary file's path after the read-back comparison and may raise
    to reject the output.
    """
    dst = os.fspath(dst)
    if os.path.lexists(dst):
        raise FileExistsError(dst)
    folder = os.path.dirname(os.path.abspath(dst))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(dst) + ".", suffix=".partial", dir=folder)
    try:
        # mkstemp creates 0600; give the output the permissions a plain open() would (0666 minus umask)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb") as f:
            if f.read() != data:
                raise OSError("read-back of the temporary output differs: " + tmp)
        if check is not None:
            check(tmp)
        try:
            # hard link = atomic "create only if absent"; the name appears complete or not at all
            os.link(tmp, dst)
        except FileExistsError:
            raise
        except OSError:
            # file systems without hard links: atomic rename after a last existence check
            if os.path.lexists(dst):
                raise FileExistsError(dst)
            os.rename(tmp, dst)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
