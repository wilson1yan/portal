import collections
import dataclasses
import queue
import selectors
import socket

from . import buffers
from . import contextlib
from . import thread
from . import utils


class Connection:

  def __init__(self, sock, addr):
    self.sock = sock
    self.addr = addr
    self.recvbuf = None
    self.sendbufs = collections.deque()

  def fileno(self):
    return self.sock.fileno()


@dataclasses.dataclass
class Options:

  ipv6: bool = False
  max_msg_size: int = 4 * 1024 ** 3
  max_recv_queue: int = 4096
  max_send_queue: int = 4096
  logging: bool = True


class ServerSocket:

  def __init__(self, port, name='Server', **kwargs):
    if isinstance(port, str):
      port = int(port.rsplit(':', 1)[1])
    self.name = name
    self.options = Options(**kwargs)
    hostname = contextlib.context.hostname
    if self.options.ipv6:
      self.sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
      self.addr = (hostname, port, 0, 0)
    else:
      self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      self.addr = (hostname, port)
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.bind(self.addr)
    self.sock.setblocking(False)
    self.sock.listen()
    self.sel = selectors.DefaultSelector()
    self.sel.register(self.sock, selectors.EVENT_READ, data=None)
    self._log(f'Listening at {self.addr[0]}:{self.addr[1]}')
    self.conns = {}
    self.recvq = queue.Queue()  # [(addr, bytes)]
    self.running = True
    self.error = None
    self.thread = thread.Thread(self._loop, name=f'{name}Loop', start=True)

  @property
  def connections(self):
    return tuple(self.conns.keys())

  def recv(self, timeout=None):
    if self.error:
      raise self.error
    assert self.running
    try:
      return self.recvq.get(block=(timeout != 0), timeout=timeout)
    except queue.Empty:
      raise TimeoutError

  def send(self, addr, *data):
    if self.error:
      raise self.error
    assert self.running
    if self._numsending() > self.options.max_send_queue:
      raise RuntimeError('Too many outgoing messages enqueued')
    maxsize = self.options.max_msg_size
    try:
      self.conns[addr].sendbufs.append(
          buffers.SendBuffer(*data, maxsize=maxsize))
    except KeyError:
      self._log('Dropping message to disconnected client')

  def close(self, timeout=None):
    self.running = False
    self.thread.join(timeout)
    [conn.sock.close() for conn in self.conns.values()]
    self.sock.close()
    self.sel.close()

  def _loop(self):
    try:
      while self.running or self._numsending():
        writeable = []
        for key, mask in self.sel.select(timeout=0.2):
          if key.data is None:
            assert mask & selectors.EVENT_READ
            self._accept(key.fileobj)
          elif mask & selectors.EVENT_READ:
            self._recv(key.data)
          elif mask & selectors.EVENT_WRITE:
            writeable.append(key.data)
        for conn in writeable:
          if not conn.sendbufs:
            continue
          try:
            conn.sendbufs[0].send(conn.sock)
            if conn.sendbufs[0].done():
              conn.sendbufs.popleft()
          except BlockingIOError:
            pass
          except ConnectionResetError:
            # The client is gone but we may have buffered messages left to
            # read, so we keep the socket open until recv() fails.
            pass  # self._disconnect(conn, recvrest=True)  # TODO: Needed?
    except Exception as e:
      self.error = e

  def _accept(self, sock):
    sock, addr = sock.accept()
    self._log(f'Accepted connection from {addr[0]}:{addr[1]}')
    sock.setblocking(False)
    conn = Connection(sock, addr)
    self.sel.register(
        sock, selectors.EVENT_READ | selectors.EVENT_WRITE, data=conn)
    self.conns[addr] = conn

  def _recv(self, conn):
    if not conn.recvbuf:
      conn.recvbuf = buffers.RecvBuffer(maxsize=self.options.max_msg_size)
    try:
      conn.recvbuf.recv(conn.sock)
    except ConnectionResetError:
      self._disconnect(conn, recvrest=False)
      return
    if conn.recvbuf.done():
      if self.recvq.qsize() > self.options.max_recv_queue:
        raise RuntimeError('Too many incoming messages enqueued')
      self.recvq.put((conn.addr, conn.recvbuf.result()))
      conn.recvbuf = None

  def _disconnect(self, conn, recvrest):
    if recvrest and False:  # TODO: Needed?
      try:
        while True:
          self._recv(conn)
      except OSError:
        pass
    self._log(f'Closed connection to {conn.addr[0]}:{conn.addr[1]}')
    conn = self.conns.pop(conn.addr)
    if conn.sendbufs:
      count = len(conn.sendbufs)
      conn.sendbufs.clear()
      self._log(f'Dropping {count} messages to disconnected client')
    self.sel.unregister(conn.sock)
    conn.sock.close()

  def _numsending(self):
    return sum(len(x.sendbufs) for x in self.conns.values())

  def _log(self, *args, **kwargs):
    if self.options.logging:
      style = utils.style(color='blue', bold=True)
      reset = utils.style(reset=True)
      print(style + f'[{self.name}]', *args, reset)
