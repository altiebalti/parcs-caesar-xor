#!/usr/bin/env bash
# Надсилає на майстер PARCS усі вхідні файли по черзі й зберігає результати.
#
#   ./run_all.sh <MASTER_IP> [папка_з_inputs] [папка_для_outputs]
#   ./run_all.sh 35.228.130.74
#   ./run_all.sh 35.228.130.74 inputs outputs "serial.txt local_w*.txt"
#
# PARCS виконує задачі по одній, тому скрипт чекає завершення кожної.
set -u
MASTER=${1:?usage: ./run_all.sh <MASTER_IP> [inputs_dir] [outputs_dir] [file_glob]}
IN=${2:-inputs}
OUT=${3:-outputs}
GLOB=${4:-"serial.txt local_w*.txt serial_small.txt scatter_w*.txt"}
BASE="http://$MASTER:8080"
SOLVER="$(dirname "$0")/solver.py"
mkdir -p "$OUT"

# наступний вільний номер задачі (майстер нумерує задачі з 0)
next_id() {
  local id=0
  while [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/job/$id/input")" = "200" ]; do
    id=$((id + 1))
  done
  echo "$id"
}

cd "$IN" >/dev/null || exit 1
FILES=$(ls $GLOB 2>/dev/null)
cd - >/dev/null || exit 1
[ -n "$FILES" ] || { echo "No input files in $IN matching: $GLOB"; exit 1; }

for f in $FILES; do
  id=$(next_id)
  name="${f%.txt}"
  echo -n "[$name] job $id ... "
  curl -s -o /dev/null -F "job_name=$name" -F "solution_file=@$SOLVER" -F "input_file=@$IN/$f" "$BASE/api/job"
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

echo
grep -h "^CSV," "$OUT"/*.txt 2>/dev/null
echo
echo "Next: python report.py $OUT"
