#!/usr/bin/env bash
# Download an archive from an ordered list of sources and accept it only if its
# SHA-256 matches the pinned value. Never substitutes another version.
#
# Usage: fetch-verified.sh DEST SHA256 URL [URL...]
# Exit 0: verified archive is at DEST. Exit 1: no source produced a verified archive.
# If GITHUB_OUTPUT is set, writes repaired=true|false (true = a pre-existing
# DEST failed verification and was replaced).
#
# Time budget: ONE deadline (default 1200 s, FETCH_TOTAL_BUDGET_SECONDS) covers all
# attempts, backoff sleeps and sources. Each source gets an equal share of the time
# remaining when it starts; unused time rolls over to later sources. Within a
# source, the remaining slice is divided across the remaining attempts.
#
# User-Agent: curl's default is used unless FETCH_USER_AGENT is set. Production
# does not set it, so requests match the original failing run.
#
# fetch() is only called as an "if" condition, so errexit is disabled in it.
# No set +e / set -e toggling is used.
set -euo pipefail
SECONDS=0

if [ "$#" -lt 3 ]; then
  echo "::error::usage: fetch-verified.sh DEST SHA256 URL [URL...]"
  exit 1
fi
DEST=$1
SHA256=$2
shift 2
if [[ ! "$SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "::error::SHA-256 must be 64 lowercase hex characters"
  exit 1
fi

TOTAL_BUDGET=${FETCH_TOTAL_BUDGET_SECONDS:-1200}
if [[ ! "$TOTAL_BUDGET" =~ ^[0-9]+$ ]] || [ "$TOTAL_BUDGET" -lt 1 ]; then
  echo "::error::FETCH_TOTAL_BUDGET_SECONDS must be a positive integer"
  exit 1
fi
MAX_ATTEMPTS=3
PER_ATTEMPT_CAP=600
MIN_ATTEMPT=10

UA_ARGS=()
if [ -n "${FETCH_USER_AGENT:-}" ]; then
  UA_ARGS=(-A "$FETCH_USER_AGENT")
fi

mkdir -p "$(dirname "$DEST")"
PART="${DEST}.part"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$PART"' EXIT
HDR="$TMP/headers.txt"

verify() {
  printf '%s  %s\n' "$SHA256" "$1" | sha256sum -c --status
}

emit() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"
  fi
  return 0
}

# fetch URL MAX_SECONDS
# Return: 0 = complete HTTP 200 transfer at PART
#         2 = retryable (curl error, 403, 408, 429, 5xx)
#         3 = not retryable on this URL (other status)
fetch() {
  local url=$1 max_time=$2 out rc http eff
  rm -f "$PART" "$HDR"
  if out=$(curl -sS -L --connect-timeout 20 --max-time "$max_time" \
              --speed-time 30 --speed-limit 51200 "${UA_ARGS[@]}" \
              -D "$HDR" -o "$PART" -w '%{http_code} %{url_effective}' "$url"); then
    rc=0
  else
    rc=$?
  fi
  http=${out%% *}
  eff=${out#* }
  echo "curl_exit=${rc} http=${http:-none} final_url=${eff:-unknown} requested=${url} max_time=${max_time}s elapsed_total=${SECONDS}s"

  if [ "$rc" -eq 0 ] && [ "$http" = "200" ]; then
    return 0
  fi

  echo "--- response headers (last 40 lines) ---"
  tail -n 40 "$HDR" 2>/dev/null || true
  # Show a body only for small HTTP error responses, never binary archive data.
  if [[ "$http" =~ ^[45][0-9][0-9]$ ]] && [ -f "$PART" ] && [ "$(stat -c %s "$PART")" -le 4096 ]; then
    echo "--- error body ---"
    head -c 500 "$PART" | tr -c '[:print:]\n' '?' || true
    echo
  fi
  rm -f "$PART"

  if [ "$rc" -ne 0 ]; then
    return 2
  fi
  case "$http" in
    403|408|429|5[0-9][0-9]) return 2 ;;
    *) return 3 ;;
  esac
}

was_corrupt=false
if [ -f "$DEST" ]; then
  if verify "$DEST"; then
    echo "Existing archive at $DEST passed SHA-256 verification."
    emit repaired false
    exit 0
  fi
  echo "::warning::Existing archive failed SHA-256 verification; discarding it."
  rm -f "$DEST"
  was_corrupt=true
fi

sources_left=$#
for url in "$@"; do
  left=$(( TOTAL_BUDGET - SECONDS ))
  if [ "$left" -lt "$MIN_ATTEMPT" ]; then
    echo "::warning::Download time budget exhausted before trying $url"
    break
  fi
  source_deadline=$(( SECONDS + left / sources_left ))
  sources_left=$(( sources_left - 1 ))

  attempt=1
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    # Divide remaining source time across remaining attempts. Recalculate each time.
    attempts_left=$(( MAX_ATTEMPTS - attempt + 1 ))
    source_left=$(( source_deadline - SECONDS ))
    if [ "$source_left" -lt "$MIN_ATTEMPT" ]; then
      echo "Time slice for $url is used up."
      break
    fi
    allowed=$(( source_left / attempts_left ))
    if [ "$allowed" -lt "$MIN_ATTEMPT" ]; then
      allowed=$MIN_ATTEMPT
    fi
    if [ "$allowed" -gt "$PER_ATTEMPT_CAP" ]; then
      allowed=$PER_ATTEMPT_CAP
    fi

    if fetch "$url" "$allowed"; then
      if verify "$PART"; then
        mv "$PART" "$DEST"
        echo "Verified archive obtained from $url after ${SECONDS}s"
        emit repaired "$was_corrupt"
        exit 0
      fi
      echo "::warning::Complete download from $url did not match the pinned SHA-256; not retrying this source."
      rm -f "$PART"
      break
    else
      r=$?
    fi
    if [ "$r" -eq 3 ]; then
      echo "Non-retryable response from $url; moving to the next source."
      break
    fi

    delay=$(( attempt * attempt * 5 + RANDOM % 5 ))
    room=$(( source_deadline - SECONDS ))
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ] || [ $(( room - delay )) -lt "$MIN_ATTEMPT" ]; then
      echo "No further attempts possible for $url within its time slice."
      break
    fi
    echo "Attempt ${attempt}/${MAX_ATTEMPTS} failed; sleeping ${delay}s."
    sleep "$delay"
    attempt=$(( attempt + 1 ))
  done
done

echo "::error::No listed source produced an archive matching the pinned SHA-256 (elapsed ${SECONDS}s of ${TOTAL_BUDGET}s budget)."
exit 1
