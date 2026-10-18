"""Чтение файлов, которыми владеет агент (статусы, состояние): root не должен зависать или раздуваться на подмене."""
import os
import stat

LIMIT = 4 << 20


def read_text(path, limit=LIMIT):
    """Обычный файл без перехода по симлинку на последнем компоненте, не больше limit байт; иначе OSError/ValueError."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f'{path}: не обычный файл')
        if st.st_size > limit:
            raise ValueError(f'{path}: больше {limit} байт')
        data = b''
        while len(data) <= limit:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            data += chunk
        if len(data) > limit:
            raise ValueError(f'{path}: больше {limit} байт')
        return data.decode('utf-8', 'replace')
    finally:
        os.close(fd)
