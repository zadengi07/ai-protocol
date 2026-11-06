import socket, time
HOST = "ep-falling-moon-bdukf8m0.c-8.us-east-2.aws.neon.tech"
ip = "3.142.41.151"
t0 = time.time()
s = socket.create_connection((ip, 5432), timeout=10)
s.sendall(bytes.fromhex("00000008" "04d2162f"))  # PostgreSQL SSLRequest
try:
    print("Javob:", s.recv(1), f"({time.time()-t0:.1f}s)")  # kutilgan: b'S'
except Exception as e:
    print("Javob yo'q:", type(e).__name__, f"({time.time()-t0:.1f}s)")
s.close()