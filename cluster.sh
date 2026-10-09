#!/usr/bin/env bash
# Кластер PARCS-Python у Google Compute Engine (запускати в Cloud Shell).
#
#   bash cluster.sh up [N]    - firewall, master і N воркерів (за замовчуванням 4), чекає готовності
#   bash cluster.sh ip        - зовнішня IP-адреса майстра
#   bash cluster.sh status    - VM і скільки воркерів підключено до майстра
#   bash cluster.sh allow     - оновити firewall, якщо змінилася IP Cloud Shell або ваша
#   bash cluster.sh fix-firewall - відкрити порти host-firewall COS на вже створених VM
#   bash cluster.sh stop      - зупинити VM (кредит не витрачається на CPU), дані лишаються
#   bash cluster.sh start     - запустити знову (IP майстра зміниться)
#   bash cluster.sh down      - видалити VM і правило firewall
#
# Змінні: ZONE (europe-north1-a), MACHINE (n1-standard-1), MY_IP - IP вашого браузера,
# щоб відкривати веб-інтерфейс PARCS (дізнатися: https://ifconfig.me).
#
# Чому не create-with-container з офіційного гайду: у gcloud цей спосіб позначено як
# deprecated. Тут те саме зроблено напряму: Container-Optimized OS + docker run у
# startup-script, з тим самим образом hummer12007/parcs-node і мережею хоста.
set -euo pipefail

ZONE=${ZONE:-europe-north1-a}
MACHINE=${MACHINE:-n1-standard-1}
IMAGE=${IMAGE:-hummer12007/parcs-node}
MY_IP=${MY_IP:-}
RULE=parcs-web
TAG=parcs-master
LABEL=parcs

cmd=${1:-help}
if [ "$cmd" != help ] && [ -z "$(gcloud config get-value project 2>/dev/null || true)" ]; then
  echo "Не вибрано проєкт. Виконайте: gcloud config set project <PROJECT_ID>"
  exit 1
fi
gcloud config set compute/zone "$ZONE" >/dev/null 2>&1 || true

master_ip() {
  gcloud compute instances describe master --zone "$ZONE" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
}

workers_online() {
  curl -s --max-time 5 "http://$1:8080/api/worker" 2>/dev/null |
    python3 -c 'import sys, json; print(len(json.load(sys.stdin)["workers"]))' 2>/dev/null || echo 0
}

source_ranges() {
  local shell_ip ranges
  shell_ip=$(curl -s --max-time 10 https://ifconfig.me || true)
  ranges=""
  [ -n "$shell_ip" ] && ranges="$shell_ip/32"
  [ -n "$MY_IP" ] && ranges="${ranges:+$ranges,}$MY_IP/32"
  if [ -z "$ranges" ]; then
    echo "Не вдалося визначити IP. Задайте MY_IP=<ваш IP> і повторіть." >&2
    exit 1
  fi
  echo "$ranges"
}

startup_script() {   # $1 = PARCS_ARGS
  local f
  f=$(mktemp)
  # Host-firewall Container-Optimized OS пропускає лише SSH, тому відкриваємо:
  #  - увесь TCP з внутрішньої мережі VPC (Flask і Pyro4 на воркерах слухають випадкові порти);
  #  - порт 8080 (веб-інтерфейс майстра; зовні його і так обмежує правило GCP parcs-web).
  cat > "$f" <<EOF
#!/bin/bash
iptables -w -C INPUT -p tcp -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -p tcp -s 10.0.0.0/8 -j ACCEPT
iptables -w -C INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -p tcp --dport 8080 -j ACCEPT
docker start parcs 2>/dev/null || \\
  docker run -d --name parcs --restart=always --network=host \\
    -e PARCS_ARGS="$1" $IMAGE
EOF
  echo "$f"
}

create_vms() {   # $1 = PARCS_ARGS, $2 = мітка мережі (або ""), далі імена VM
  local args=$1 tags=$2 script
  shift 2
  script=$(startup_script "$args")
  gcloud compute instances create "$@" \
    --zone "$ZONE" --machine-type "$MACHINE" \
    --image-family cos-stable --image-project cos-cloud \
    --labels "app=$LABEL" ${tags:+--tags "$tags"} \
    --metadata-from-file startup-script="$script"
  rm -f "$script"
}

case "$cmd" in
  up)
    n=${2:-4}
    workers=()
    for i in $(seq 1 "$n"); do workers+=("worker$i"); done

    echo "== Compute Engine API"
    gcloud services enable compute.googleapis.com

    echo "== Firewall: порт 8080 майстра лише для Cloud Shell${MY_IP:+ і $MY_IP}"
    ranges=$(source_ranges)
    if gcloud compute firewall-rules describe "$RULE" >/dev/null 2>&1; then
      gcloud compute firewall-rules update "$RULE" --source-ranges="$ranges"
    else
      gcloud compute firewall-rules create "$RULE" --network=default --direction=INGRESS \
        --allow=tcp:8080 --target-tags="$TAG" --source-ranges="$ranges"
    fi

    echo "== Master"
    gcloud compute instances describe master --zone "$ZONE" >/dev/null 2>&1 ||
      create_vms "master" "$TAG" master
    master_int=$(gcloud compute instances describe master --zone "$ZONE" \
      --format='get(networkInterfaces[0].networkIP)')

    echo "== Воркери: ${workers[*]} (master $master_int)"
    missing=()
    for w in "${workers[@]}"; do
      gcloud compute instances describe "$w" --zone "$ZONE" >/dev/null 2>&1 || missing+=("$w")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      create_vms "worker $master_int" "" "${missing[@]}"
    fi

    ip=$(master_ip)
    echo "== Чекаю, поки воркери підключаться до http://$ip:8080 (зазвичай 2-3 хв)"
    for _ in $(seq 1 60); do
      online=$(workers_online "$ip")
      printf '\r   підключено %s з %s ' "$online" "$n"
      [ "$online" -ge "$n" ] && break
      sleep 10
    done
    echo
    echo
    echo "Майстер: http://$ip:8080   (воркери: http://$ip:8080/workers)"
    echo "Далі:    bash run_all.sh $ip"
    ;;
  ip)
    master_ip
    ;;
  status)
    gcloud compute instances list --filter="labels.app=$LABEL" \
      --format='table(name,status,networkInterfaces[0].networkIP:label=INTERNAL,networkInterfaces[0].accessConfigs[0].natIP:label=EXTERNAL)'
    ip=$(master_ip 2>/dev/null || true)
    if [ -n "$ip" ]; then
      echo "Підключено воркерів: $(workers_online "$ip")  (http://$ip:8080)"
    fi
    ;;
  allow)
    gcloud compute firewall-rules update "$RULE" --source-ranges="$(source_ranges)"
    ;;
  fix-firewall)   # відкрити порти на вже створених VM (host-firewall COS), без перестворення
    for vm in $(gcloud compute instances list --filter="labels.app=$LABEL" --format='value(name)'); do
      echo "== $vm"
      gcloud compute ssh "$vm" --zone "$ZONE" --quiet --command \
        'sudo iptables -w -I INPUT -p tcp -s 10.0.0.0/8 -j ACCEPT; sudo iptables -w -I INPUT -p tcp --dport 8080 -j ACCEPT'
    done
    echo "Воркери перепідключаться самі протягом 1-2 хв: bash cluster.sh status"
    ;;
  stop|start)
    names=$(gcloud compute instances list --filter="labels.app=$LABEL" --format='value(name)')
    if [ -n "$names" ]; then
      # shellcheck disable=SC2086
      gcloud compute instances "$cmd" $names --zone "$ZONE"
    fi
    if [ "$cmd" = start ]; then
      echo "Нова IP майстра: $(master_ip)"
    fi
    ;;
  down)
    names=$(gcloud compute instances list --filter="labels.app=$LABEL" --format='value(name)')
    if [ -n "$names" ]; then
      # shellcheck disable=SC2086
      gcloud compute instances delete $names --zone "$ZONE" --quiet
    fi
    gcloud compute firewall-rules delete "$RULE" --quiet 2>/dev/null || true
    echo "Кластер видалено."
    ;;
  *)
    sed -n '2,13p' "$0"
    ;;
esac
