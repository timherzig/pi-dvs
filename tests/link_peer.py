"""Independent UDP peer exercising production RPC/NFS framing with synthetic bytes."""

import hashlib
import socket
import struct
from threading import Event, Thread


def pack(*values):
    return struct.pack(f">{len(values)}I", *values)


def string(value):
    return pack(len(value)) + value + bytes(-len(value) % 4)


class Peer:
    def __init__(self, data=b"music" * 1000, *, sparse=False, fault="", files=None):
        self.data = data
        self.files = files
        self.handles = {b"R" * 32: ""}
        self.read_hook = None
        self.sparse = sparse
        self.fault = fault
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.socket.settimeout(0.05)
        self.stop = Event()
        self.reads = []
        self.read_received = Event()
        self.lookups = []
        self.cancel = None
        self.errors = []
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()

    def attrs(self, read=False, data=None):
        fields = [0] * 17
        fields[10] = 42
        if not (self.sparse and read):
            fields[0], fields[5], fields[9], fields[13] = (
                1,
                len(self.data if data is None else data),
                2,
                1234,
            )
        if read and self.fault == "changed":
            fields[10] += 1
        return pack(*fields)

    def run(self):
        while not self.stop.is_set():
            try:
                packet, address = self.socket.recvfrom(65535)
            except TimeoutError:
                continue
            try:
                xid, _, _, program, _, procedure = struct.unpack(">6I", packet[:24])
                payload = packet[60:]
                result = b""
                if program == 100000:
                    result = pack(self.port)
                elif program == 100005 and procedure == 1:
                    assert payload == string("/C/".encode("utf-16-le"))
                    result = pack(0) + b"R" * 32
                elif program == 100003 and procedure == 4:
                    size = struct.unpack(">I", payload[32:36])[0]
                    name = payload[36 : 36 + size].decode("utf-16-le")
                    self.lookups.append(name)
                    parent = self.handles.get(payload[:32], "")
                    path = parent + "/" + name
                    handle = hashlib.sha256(path.encode()).digest()
                    self.handles[handle] = path
                    result = pack(70) if name == "absent" else pack(0) + b"F" * 32 + self.attrs()
                    if self.files is not None:
                        if path in self.files:
                            result = pack(0) + handle + self.attrs(data=self.files[path])
                        elif any(p.startswith(path + "/") for p in self.files):
                            result = pack(0) + handle + self.attrs()
                        else:
                            result = pack(70)
                elif program == 100003 and procedure == 6:
                    offset, count, _ = struct.unpack(">3I", payload[32:])
                    self.reads.append((xid, offset, count))
                    self.read_received.set()
                    if self.fault == "timeout" or (self.fault == "drop" and len(self.reads) == 1):
                        continue
                    data = (
                        self.files[self.handles[payload[:32]]]
                        if self.files is not None
                        else self.data
                    )
                    content = b"" if self.fault == "empty" else data[offset : offset + count]
                    result = pack(0) + self.attrs(True, data=data) + string(content)
                    if self.read_hook:
                        self.read_hook(self.handles.get(payload[:32], ""))
                    if self.cancel:
                        self.cancel.set()
                reply = pack(xid, 1, 0, 0, 0, 0) + result
                if self.fault == "drop" and procedure == 6:
                    self.socket.sendto(pack(xid - 1, 1, 0, 0, 0, 0) + b"wrong", address)
                    self.socket.sendto(pack(xid, 1), address)
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stranger:
                        stranger.sendto(reply, address)
                self.socket.sendto(reply, address)
            except Exception as error:
                self.errors.append(error)

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.socket.close()
        assert not self.errors

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
