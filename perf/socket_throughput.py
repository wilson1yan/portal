import collections
import time

import zerofun


def main():

  # size = 1024 ** 3 // 4
  # parts = 64
  # prefetch = 16
  # twoway = False  # True
  # assert size % parts == 0

  size = 1024 ** 2
  parts = 1
  prefetch = 16
  twoway = True
  assert size % parts == 0

  def server(port):
    server = zerofun.ServerSocket(port)
    while True:
      addr, data = server.recv()
      if twoway:
        server.send(addr, data)
      else:
        server.send(addr, b'ok')
      assert len(data) == size

  def client(port):
    data = [bytearray(size // parts) for _ in range(parts)]
    client = zerofun.ClientSocket('localhost', port)
    for _ in range(prefetch):
      client.send(*data)
    durations = collections.deque(maxlen=50)
    start = time.time()
    while True:
      client.send(*data)
      result = client.recv()
      if twoway:
        assert len(result) == size
      else:
        assert result == b'ok'
      end = time.time()
      durations.append(end - start)
      start = end
      avgdur = sum(durations) / len(durations)
      mbps = size / avgdur / (1024 ** 2)
      mbps *= 2 if twoway else 1
      print(mbps)  # ~4000

  port = zerofun.free_port()
  zerofun.run([
      zerofun.Process(server, port),
      zerofun.Process(client, port),
  ])


if __name__ == '__main__':
  main()


# import collections
# import time
#
# import zerofun
#
#
# def main():
#
#   size = 1024 ** 3 // 4
#   parts = 64
#   prefetch = 16
#
#   def server(port):
#     server = zerofun.ServerSocket(port)
#     durations = collections.deque(maxlen=50)
#     start = time.time()
#     while True:
#       addr, data = server.recv()
#       server.send(addr, b'ok')
#       assert len(data) == size // parts * parts
#       end = time.time()
#       durations.append(end - start)
#       start = end
#       avgdur = sum(durations) / len(durations)
#       mbps = size / avgdur / (1024 ** 2)
#       print(mbps)  # ~5000
#
#   def client(port):
#     data = [bytearray(size // parts) for _ in range(parts)]
#     client = zerofun.ClientSocket('localhost', port)
#     for _ in range(prefetch):
#       client.send(*data)
#     while True:
#       client.send(*data)
#       client.recv()
#
#   port = zerofun.free_port()
#   zerofun.run([
#       zerofun.Process(server, port),
#       zerofun.Process(client, port),
#   ])
#
#
# if __name__ == '__main__':
#   main()