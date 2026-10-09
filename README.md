# parcs-caesar-xor

Лаба з хмарних обчислень: шифр Цезаря і XOR на PARCS-Python в Google Cloud.
Переніс свою MPI-версію на C++ на PARCS і порівняв послідовний варіант з паралельним на 1-4 воркерах.

Є три режими (`mode=` у вхідному файлі): `serial`, `local` (кожен воркер сам генерує і шифрує свій шматок)
і `scatter` (майстер розсилає текст воркерам, як в MPI). Другий дає майже лінійне прискорення, третій
повільніший за послідовний, бо передати байт по мережі дорожче, ніж його зашифрувати.

Запуск в Cloud Shell:

```
MY_IP=<свій ip> bash cluster.sh up 4
bash run_all.sh $(bash cluster.sh ip)
python3 report.py outputs/
bash cluster.sh down
```

Локально без хмари: `python solver.py input.txt out.txt --workers 2`
