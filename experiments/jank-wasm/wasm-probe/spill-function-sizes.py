"""AI-assisted binary size/local-count report; no WAT expansion or SDK needed."""
from pathlib import Path
import sys


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def byte(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value

    def uint(self) -> int:
        result = shift = 0
        while True:
            value = self.byte()
            result |= (value & 127) << shift
            if value < 128:
                return result
            shift += 7
            if shift > 63:
                raise ValueError('Invalid LEB')

    def chunk(self) -> bytes:
        size = self.uint()
        end = self.pos + size
        if end > len(self.data):
            raise ValueError('Truncated chunk')
        result = self.data[self.pos:end]
        self.pos = end
        return result


for filename in sys.argv[1:]:
    reader = Reader(Path(filename).read_bytes())
    if reader.data[:8] != b'\0asm\1\0\0\0':
        raise ValueError('Expected Wasm v1')
    reader.pos = 8
    names = {}
    rows = []
    imports = 0
    while reader.pos < len(reader.data):
        section = reader.byte()
        payload = Reader(reader.chunk())
        if section == 0 and payload.chunk() == b'name':
            while payload.pos < len(payload.data):
                kind = payload.byte()
                subsection = Reader(payload.chunk())
                if kind == 1:
                    for _ in range(subsection.uint()):
                        index = subsection.uint()
                        names[index] = subsection.chunk().decode()
        elif section == 2:
            for _ in range(payload.uint()):
                payload.chunk()
                payload.chunk()
                kind = payload.byte()
                if kind == 0:
                    payload.uint()
                    imports += 1
                elif kind == 4:
                    payload.byte()
                    payload.uint()
                else:
                    raise ValueError(f'Unsupported import kind {kind}')
        elif section == 10:
            for index in range(payload.uint()):
                body = Reader(payload.chunk())
                locals_count = 0
                for _ in range(body.uint()):
                    locals_count += body.uint()
                    body.byte()
                rows.append((len(body.data), locals_count, imports + index))
    print(filename)
    for size, locals_count, index in sorted(rows, reverse=True)[:15]:
        print(f'index={index} bytes={size} locals={locals_count} {names.get(index, "?")}')
