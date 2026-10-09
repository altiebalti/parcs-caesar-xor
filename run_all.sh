#!/usr/bin/env bash
# ./run_all.sh <MASTER_IP> [outputs_dir]
# генерує вхідні файли, шле всі задачі на майстер по черзі і складає результати
set -u
MASTER=${1:?usage: ./run_all.sh <MASTER_IP> [outputs_dir]}
OUT=${2:-outputs}
BASE="http://$MASTER:8080"
SOLVER="$(dirname "$0")/solver.py"
IN=$(mktemp -d)
mkdir -p "$OUT"

COMMON="shift=3
key=SecretKey123!@#
seed=2026"

gen_input() {
  printf 'mode=%s\n%s\nsizes=%s\n%s\n' "$1" "$2" "$3" "$COMMON" > "$IN/$4.txt"
}

gen_input serial "" "100000000, 500000000, 1000000000" serial
for w in 1 2 3 4; do gen_input local "workers=$w" "100000000, 500000000, 1000000000" local_w$w; done
gen_input serial "" "10000000, 50000000, 100000000" serial_small
for w in 1 2 3 4; do gen_input scatter "workers=$w" "10000000, 50000000, 100000000" scatter_w$w; done

next_id() {
  local id=0
  while [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/job/$id/input")" = "200" ]; do
    id=$((id + 1))
  done
  echo "$id"
}

for name in local_w1 local_w2 local_w3 local_w4 scatter_w1 scatter_w2 scatter_w3 scatter_w4 serial_small serial; do
  id=$(next_id)
  echo -n "[$name] job $id ... "
  curl -s -o /dev/null -F "job_name=$name" -F "solution_file=@$SOLVER" -F "input_file=@$IN/$name.txt" "$BASE/api/job"
  start=$(date +%s)
  while true; do
    code=$(curl -s -o "$OUT/$name.txt" -w '%{http_code}' "$BASE/api/job/$id/output")
    [ "$code" = "200" ] && { echo "done in $(( $(date +%s) - start )) s"; break; }
    if [ "$code" = "404" ]; then
      rm -f "$OUT/$name.txt"
      echo "FAILED (see $BASE/jobs)"; break
    fi
    sleep 3
  done
done

rm -rf "$IN"
echo
grep -h "^CSV," "$OUT"/*.txt 2>/dev/null
echo
echo "Next: python report.py $OUT"
