# Шифр Цезаря та XOR на PARCS-Python

Лаба 1 з хмарних обчислень. Паралельне шифрування/розшифрування тексту шифром Цезаря і XOR
на [PARCS-Python](https://github.com/Hummer12007/parcs-python) в Google Cloud. Порт моєї MPI-версії на C++.

- `solver.py` – розв'язок для PARCS, три режими (`mode=` у вхідному файлі):
  - `serial` – все рахує майстер
  - `local` – кожен воркер сам генерує свій шматок тексту, шифрує, повертає md5. Прискорення майже лінійне
  - `scatter` – як в MPI: майстер розсилає текст, збирає назад. Повільніше за serial, бо передача дорожча за сам шифр
- `cluster.sh` – майстер + воркери в Compute Engine
- `run_all.sh` – запускає всі заміри і збирає результати
- `report.py` – таблиці і графіки

Коректність: розшифрований текст порівнюється з вихідним, а md5 шифротексту має збігатись у всіх режимах
при будь-якій кількості воркерів.

## Запуск в GCP (Cloud Shell)

```bash
gcloud config set project <PROJECT_ID>
export ZONE=europe-north1-b          # в north1-a часто немає n1-standard-1
MY_IP=<свій ip> bash cluster.sh up 4  # майстер + 4 воркери, порт 8080 відкривається тільки для свого ip і cloud shell
bash run_all.sh $(bash cluster.sh ip)
pip3 install --user matplotlib && python3 report.py outputs/
bash cluster.sh down
```

`create-with-container` з офіційної інструкції вже deprecated, тому VM створюються на Container-Optimized OS
зі startup-скриптом, який робить `docker run --network=host hummer12007/parcs-node`. У COS свій firewall, який
пускає тільки ssh, тому скрипт ще додає правила iptables (без цього воркери не бачать майстра).

## Локально

```bash
printf 'mode=local\nworkers=0\nsizes=1000000, 10000000\n' > test.txt
python solver.py test.txt out.txt --workers 2
```

## Результати (n1-standard-1, 4 воркери)

| режим | обсяг | serial | 1 | 2 | 3 | 4 воркери |
|---|---|---|---|---|---|---|
| local, час с | 1 ГБ | 84,0 | 86,9 | 43,1 | 29,8 | 22,2 |
| local, прискорення | 1 ГБ | 1 | 0,97 | 1,95 | 2,82 | 3,78 |
| scatter, час с | 100 МБ | 5,2 | 67,5 | 45,3 | 34,9 | 31,8 |
| scatter, прискорення | 100 МБ | 1 | 0,08 | 0,11 | 0,15 | 0,16 |

Для scatter базою є тільки Цезар + XOR у serial (як і в MPI-версії, без генерації і перевірки).
