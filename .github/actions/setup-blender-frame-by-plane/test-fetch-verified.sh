#!/usr/bin/env bash
# Regression suite for fetch-verified.sh. Needs bash, curl, python3, coreutils.
# Usage: test-fetch-verified.sh path/to/fetch-verified.sh
set -uo pipefail

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: $0 path/to/fetch-verified.sh"
  exit 2
fi
SCRIPT=$(readlink -f "$1")
W=$(mktemp -d)
SP=""
cleanup() {
  if [ -n "$SP" ]; then
    kill "$SP" 2>/dev/null || true
  fi
  rm -rf "$W"
}
trap cleanup EXIT
cd "$W" || exit 2

# Remove only the backoff delay in a test copy; preserve all retry and budget logic.
sed 's/attempt \* attempt \* 5 + RANDOM % 5/attempt * attempt * 0 + 0/' "$SCRIPT" > fast.sh
if ! grep -q 'attempt \* attempt \* 0 + 0' fast.sh; then
  echo "backoff substitution failed; script changed?"
  exit 2
fi
chmod +x fast.sh

head -c 300000 /dev/urandom > good.bin
head -c 300000 /dev/urandom > other.bin
GOOD=$(sha256sum good.bin | cut -d' ' -f1)

cat > srv.py <<'PY'
import http.server
import socketserver
import time

good = open('good.bin', 'rb').read()
other = open('other.bin', 'rb').read()

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_headers(self, code, length=None):
        self.send_response(code)
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def do_GET(self):
        path = self.path
        with open('hits.log', 'a') as f:
            f.write(path + '\n')
        with open('ua.log', 'a') as f:
            f.write(self.headers.get('User-Agent', '') + '\n')
        try:
            if path == '/ok':
                self.send_headers(200, len(good)); self.wfile.write(good)
            elif path == '/redir':
                self.send_response(302); self.send_header('Location', '/ok'); self.send_header('Content-Length', '0'); self.end_headers()
            elif path == '/bad':
                self.send_headers(200, len(other)); self.wfile.write(other)
            elif path == '/trunc':
                self.send_headers(200, len(good)); self.wfile.write(good[:len(good)//2]); self.wfile.flush()
            elif path == '/nolen':
                self.send_headers(200); self.wfile.write(good[:len(good)//2]); self.wfile.flush()
            elif path == '/slow':
                self.send_headers(200, len(good))
                for _ in range(600):
                    self.wfile.write(b'x' * 100); self.wfile.flush(); time.sleep(1)
            elif path == '/hold25':
                self.send_headers(200, len(good))
                for _ in range(25):
                    self.wfile.write(b'x' * 100); self.wfile.flush(); time.sleep(1)
            elif path == '/403':
                body = b'Forbidden by test'; self.send_headers(403, len(body)); self.wfile.write(body)
            elif path == '/404':
                self.send_headers(404, 0)
        except (BrokenPipeError, ConnectionResetError):
            pass

class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

server = ThreadedServer(('127.0.0.1', 0), Handler)
with open('port.txt', 'w') as f:
    f.write(str(server.server_address[1]))
server.serve_forever()
PY
python3 srv.py &
SP=$!
for _ in $(seq 1 50); do
  [ -s port.txt ] && break
  sleep 0.1
done
if [ ! -s port.txt ]; then
  echo "test server failed to start"
  exit 2
fi
B="http://127.0.0.1:$(cat port.txt)"

fails=0
rc=0
elapsed=0
assert() {
  # Assertions are fixed test expressions authored in this file, not user input.
  # shellcheck disable=SC2294
  if eval "$2"; then
    echo "PASS  $1"
  else
    echo "FAIL  $1   [$2]"
    fails=$((fails+1))
  fi
}
hits() { grep -c "^$1\$" hits.log || true; }
dest_ok() {
  [ -f out/a.bin ] &&
    [ "$(sha256sum out/a.bin | cut -d' ' -f1)" = "$GOOD" ] &&
    [ ! -e out/a.bin.part ]
}
run() {
  : > hits.log
  : > ua.log
  rm -rf out
  : > gho
  local start=$SECONDS
  GITHUB_OUTPUT="$PWD/gho" "$@" > log.txt 2>&1
  rc=$?
  elapsed=$((SECONDS - start))
}

run ./fast.sh out/a.bin "$GOOD" "$B/ok"
assert "normal 200: verified, one request" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /ok)" -eq 1 ]'
assert "default User-Agent is curl own" 'grep -q "^curl/" ua.log'

run ./fast.sh out/a.bin "$GOOD" "$B/redir"
assert "redirect followed" '[ "$rc" -eq 0 ] && dest_ok'

run ./fast.sh out/a.bin "$GOOD" "$B/trunc" "$B/ok"
assert "declared-length truncation: retries then fallback" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /trunc)" -eq 3 ] && [ "$(hits /ok)" -eq 1 ]'

run ./fast.sh out/a.bin "$GOOD" "$B/nolen" "$B/ok"
assert "no-length truncation: hash reject then fallback" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /nolen)" -eq 1 ] && [ "$(hits /ok)" -eq 1 ] && grep -q "did not match the pinned SHA-256" log.txt'

run ./fast.sh out/a.bin "$GOOD" "$B/403" "$B/ok"
assert "403: retries, headers and body logged, fallback" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /403)" -eq 3 ] && grep -q "Forbidden by test" log.txt'

run ./fast.sh out/a.bin "$GOOD" "$B/404" "$B/ok"
assert "404: no retries, next source" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /404)" -eq 1 ] && [ "$(hits /ok)" -eq 1 ]'

run ./fast.sh out/a.bin "$GOOD" "$B/bad"
assert "wrong hash: fail closed, no installed archive" '[ "$rc" -eq 1 ] && [ ! -e out/a.bin ] && [ ! -e out/a.bin.part ] && [ "$(hits /bad)" -eq 1 ]'

FETCH_TOTAL_BUDGET_SECONDS=60 run ./fast.sh out/a.bin "$GOOD" "$B/hold25" "$B/ok"
assert "slow-then-drop source gets 3 attempts before fallback" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /hold25)" -eq 3 ] && [ "$(hits /ok)" -eq 1 ]'

FETCH_TOTAL_BUDGET_SECONDS=40 run ./fast.sh out/a.bin "$GOOD" "$B/slow" "$B/ok"
assert "hanging primary is cut off within its slice; fallback succeeds" '[ "$rc" -eq 0 ] && dest_ok && [ "$(hits /slow)" -eq 2 ] && [ "$(hits /ok)" -eq 1 ] && [ "$elapsed" -le 30 ]'

FETCH_TOTAL_BUDGET_SECONDS=40 run ./fast.sh out/a.bin "$GOOD" "$B/slow" "$B/slow"
assert "all sources hang: bounded failure (+3s tolerance)" '[ "$rc" -eq 1 ] && [ ! -e out/a.bin ] && [ "$(hits /slow)" -eq 4 ] && [ "$elapsed" -le 43 ]'

FETCH_USER_AGENT='custom-agent/1' run ./fast.sh out/a.bin "$GOOD" "$B/ok"
assert "custom User-Agent only when explicitly set" '[ "$rc" -eq 0 ] && grep -q "^custom-agent/1" ua.log'

mkdir -p out
printf 'junk\n' > out/a.bin
: > hits.log
: > gho
GITHUB_OUTPUT="$PWD/gho" ./fast.sh out/a.bin "$GOOD" "$B/ok" > log.txt 2>&1
rc=$?
assert "corrupt cached archive replaced and reported" '[ "$rc" -eq 0 ] && dest_ok && grep -q "^repaired=true" gho'

: > hits.log
: > gho
GITHUB_OUTPUT="$PWD/gho" ./fast.sh out/a.bin "$GOOD" "$B/ok" > log.txt 2>&1
rc=$?
assert "valid cached archive: zero network requests" '[ "$rc" -eq 0 ] && [ ! -s hits.log ] && grep -q "^repaired=false" gho'

run ./fast.sh out/a.bin NOT-A-HASH "$B/ok"
assert "malformed hash rejected" '[ "$rc" -eq 1 ] && [ ! -s hits.log ]'

FETCH_TOTAL_BUDGET_SECONDS=abc run ./fast.sh out/a.bin "$GOOD" "$B/ok"
assert "non-integer budget rejected" '[ "$rc" -eq 1 ] && [ ! -s hits.log ]'

echo
if [ "$fails" -eq 0 ]; then
  echo "ALL ASSERTIONS PASSED"
  exit 0
fi
echo "$fails ASSERTION(S) FAILED"
exit 1
