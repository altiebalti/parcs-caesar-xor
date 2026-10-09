#!/usr/bin/env python3
"""Збирає report/body.tex з report.md (pandoc) і компілює report.tex у PDF (xelatex).

    python3 report/build_tex.py            # з папки parcs-caesar-xor
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

md = open('report.md', encoding='utf-8').read()

# 1. Тіло звіту починається після титульної сторінки (перший розрив сторінки)
parts = md.split('```{=openxml}', 1)
body = '```{=openxml}' + parts[1]
# розриви сторінок для docx -> \newpage для LaTeX
body = re.sub(r'```\{=openxml\}\n.*?\n```', '```{=latex}\n\\\\newpage\n```', body, flags=re.S)

# 2. Підписи таблиць: рядок «Таблиця N — текст» перед таблицею стає pandoc-підписом після неї
lines = body.split('\n')
out, i = [], 0
while i < len(lines):
    m = re.match(r'^Таблиця \d+ — (.+)$', lines[i])
    if m:
        caption = m.group(1)
        i += 1
        while i < len(lines) and not lines[i].startswith('|'):
            i += 1
        while i < len(lines) and lines[i].startswith('|'):
            out.append(lines[i]); i += 1
        out.append('')
        out.append(': ' + caption)
        continue
    out.append(lines[i]); i += 1
body = '\n'.join(out)

# 3. Підписи рисунків: номер ставить LaTeX
body = re.sub(r'!\[Рисунок \d+ — ', '![', body)

# 4. Лістинги в додатках
body = body.replace('SOLVER_LISTING', '```{=latex}\n\\lstinputlisting[language=Python]{../solver.py}\n```')
body = body.replace('```\nLOCAL_W4_LISTING\n```', '```{=latex}\n\\lstinputlisting[language={}]{../outputs/local_w4.txt}\n```')

open('body.md', 'w', encoding='utf-8').write(body)
subprocess.run(['pandoc', 'body.md', '-f', 'markdown', '-t', 'latex', '--syntax-highlighting=none', '--wrap=preserve',
                '-o', 'body.tex'], check=True)
tex = open('body.tex', encoding='utf-8').read()
# pandoc ставить рисунки як figure[H]? ні: залишає плаваючими; притискаємо до місця
tex = tex.replace('\\begin{figure}', '\\begin{figure}[H]')
tex = tex.replace('\\begin{verbatim}', '\\begin{lstlisting}').replace('\\end{verbatim}', '\\end{lstlisting}')
open('body.tex', 'w', encoding='utf-8').write(tex)
os.remove('body.md')

# 5. Компіляція (двічі, для посилань і змісту)
if '--no-pdf' not in sys.argv:
    os.makedirs('build', exist_ok=True)
    for _ in range(2):
        r = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', '-output-directory=build', 'report.tex'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log = open('build/report.log', encoding='utf-8', errors='replace').read()
            errs = [l for l in log.split('\n') if l.startswith('!') or 'Error' in l]
            print('\n'.join(errs[:20]))
            sys.exit('xelatex failed, see report/build/report.log')
    shutil.copy('build/report.pdf', 'report.pdf')
    print('report/report.pdf')
