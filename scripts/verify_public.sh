#!/usr/bin/env bash
# Checks the production deployment from the outside, the way a website visitor's browser reaches it.
#   make verify-public      or      DOMAIN=chat.coexistwithpawsitivity.com scripts/verify_public.sh
set -uo pipefail
DOMAIN=${DOMAIN:-chat.coexistwithpawsitivity.com}
SITE=${SITE:-https://coexistwithpawsitivity.com}
QUESTION=${QUESTION:-"Why are there no breed puppies for adoption?"}
BASE="https://$DOMAIN"

pass=0; fail=0
ok()  { echo "  ✅ $*"; pass=$((pass + 1)); }
bad() { echo "  ❌ $*"; fail=$((fail + 1)); }

echo "▶ DNS"
ip=$(python3 -c "import socket,sys; print(socket.gethostbyname(sys.argv[1]))" "$DOMAIN" 2>/dev/null)
[[ -n "$ip" ]] && ok "$DOMAIN -> $ip" || bad "$DOMAIN does not resolve yet (DNS record missing or not propagated)"

echo "▶ HTTPS certificate"
cert=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -issuer -enddate 2>/dev/null)
if echo "$cert" | grep -qi "let's encrypt"; then ok "Let's Encrypt certificate, $(echo "$cert" | grep notAfter)"
else bad "no Let's Encrypt certificate yet: ${cert:-none} (cert-manager may still be working, check: kubectl -n pawsitivity get certificate)"; fi

echo "▶ API and widget"
curl -fsS "$BASE/healthz" 2>/dev/null | grep -q '"ok":true' && ok "$BASE/healthz" || bad "$BASE/healthz not reachable with a valid certificate"
curl -fsS "$BASE/widget.js" 2>/dev/null | grep -q attachShadow && ok "$BASE/widget.js" || bad "widget.js not served"

echo "▶ CORS"
for origin in "$SITE" "${SITE/https:\/\//https://www.}"; do
  got=$(curl -s -o /dev/null -D - -X OPTIONS "$BASE/api/chat" -H "Origin: $origin" -H "Access-Control-Request-Method: POST" \
    | tr -d '\r' | grep -i "^access-control-allow-origin:" | cut -d' ' -f2)
  [[ "$got" == "$origin" ]] && ok "$origin allowed" || bad "$origin not allowed (check ALLOWED_ORIGINS in values-prod.yaml)"
done
evil=$(curl -s -o /dev/null -D - -X OPTIONS "$BASE/api/chat" -H "Origin: https://evil.example" \
  -H "Access-Control-Request-Method: POST" | grep -ci "^access-control-allow-origin:")
[[ "$evil" == "0" ]] && ok "foreign origin rejected" || bad "foreign origin allowed"

echo "▶ One real question"
body=$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1]}))' "$QUESTION")
resp=$(curl -s -X POST "$BASE/api/chat" -H "Content-Type: application/json" -H "Origin: $SITE" -d "$body")
status=$(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null)
[[ "$status" == "answered" ]] && ok "\"$QUESTION\" -> answered" || bad "\"$QUESTION\" -> ${status:-no response}"
echo "     $(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("answer","")[:160])' 2>/dev/null)"

echo
echo "Result: $pass passed, $fail failed"
[[ $fail -eq 0 ]]
