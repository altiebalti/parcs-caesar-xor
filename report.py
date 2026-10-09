import csv
import glob
import os
import sys

FIELDS = ['mode', 'workers', 'size', 'time', 'time_avg', 'caesar', 'xor', 'gen', 'overhead', 'check']
COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
MARKERS = ['o', 's', '^', 'D']
INK, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'


def read_rows(paths):
    files = []
    for p in paths:
        files.extend(sorted(glob.glob(os.path.join(p, '*'))) if os.path.isdir(p) else [p])
    best = {}
    for path in files:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                if not line.startswith('CSV,'):
                    continue
                row = dict(zip(FIELDS, line.strip().split(',')[1:]))
                for k in ('workers', 'size'):
                    row[k] = int(row[k])
                for k in ('time', 'time_avg', 'caesar', 'xor', 'gen', 'overhead'):
                    row[k] = float(row[k])
                key = (row['mode'], row['workers'], row['size'])
                if key not in best or row['time'] < best[key]['time']:
                    best[key] = row
    return sorted(best.values(), key=lambda r: (r['mode'], r['size'], r['workers']))


def baseline(rows, mode, size):
    for r in rows:
        if r['mode'] == 'serial' and r['size'] == size:
            return r['time'] if mode == 'local' else r['caesar'] + r['xor']
    return None


def human(size):
    for unit, div in (('ГБ', 10 ** 9), ('МБ', 10 ** 6), ('КБ', 10 ** 3)):
        if size >= div:
            return ('%g %s' % (size / div, unit))
    return '%d Б' % size


def table(rows, mode):
    out = ['### Режим %s' % mode, '',
           '| Розмір | Воркери | Час, с | Прискорення | Ефективність, % | Перевірка |',
           '|---|---|---|---|---|---|']
    for size in sorted({r['size'] for r in rows if r['mode'] == mode}):
        base = baseline(rows, mode, size)
        if base is not None:
            out.append('| %s | послідовний | %.3f | 1.00 | 100 | |' % (human(size), base))
        for r in [r for r in rows if r['mode'] == mode and r['size'] == size]:
            s = base / r['time'] if base else float('nan')
            out.append('| %s | %d | %.3f | %.2f | %.0f | %s |'
                       % (human(size), r['workers'], r['time'], s, 100 * s / r['workers'], r['check']))
    return '\n'.join(out) + '\n'


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=12, loc='left', pad=10)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)


def plot(rows, mode, outdir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    sizes = sorted({r['size'] for r in rows if r['mode'] == mode})[:len(COLORS)]
    if not sizes:
        return []
    workers = sorted({r['workers'] for r in rows if r['mode'] == mode})
    files = []


    fig, ax = plt.subplots(figsize=(7, 4.2), facecolor=SURFACE)
    xs_labels = ['посл.'] + [str(w) for w in workers]
    for i, size in enumerate(sizes):
        base = baseline(rows, mode, size)
        pts = [(0, base)] if base is not None else []
        pts += [(1 + workers.index(r['workers']), r['time'])
                for r in rows if r['mode'] == mode and r['size'] == size]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=COLORS[i], marker=MARKERS[i],
                markersize=6, linewidth=2, label=human(size))
    ax.set_xticks(range(len(xs_labels)))
    ax.set_xticklabels(xs_labels)
    if max(sizes) / min(sizes) >= 10:
        ax.set_yscale('log')
    style(ax, 'Час виконання (%s)' % mode, 'Кількість воркерів', 'Час, с')
    ax.legend(title='Обсяг тексту', frameon=False, labelcolor=INK)
    fig.tight_layout()
    path = os.path.join(outdir, '%s_time.png' % mode)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    files.append(path)


    fig, ax = plt.subplots(figsize=(7, 4.2), facecolor=SURFACE)
    ax.plot(workers, workers, color=MUTED, linestyle='--', linewidth=1.2, label='ідеальне (S = p)')
    for i, size in enumerate(sizes):
        base = baseline(rows, mode, size)
        if base is None:
            continue
        pts = [(r['workers'], base / r['time']) for r in rows if r['mode'] == mode and r['size'] == size]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=COLORS[i], marker=MARKERS[i],
                markersize=6, linewidth=2, label=human(size))
    ax.set_xticks(workers)
    ax.set_ylim(bottom=0)
    style(ax, 'Прискорення відносно послідовного алгоритму (%s)' % mode, 'Кількість воркерів',
          'Прискорення S')
    ax.legend(frameon=False, labelcolor=INK)
    fig.tight_layout()
    path = os.path.join(outdir, '%s_speedup.png' % mode)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    files.append(path)
    return files


def main(args):
    if not args:
        print(__doc__)
        return 1
    rows = read_rows(args)
    if not rows:
        print('No CSV lines found in the given files.')
        return 1
    outdir = os.path.dirname(os.path.abspath(args[0])) if not os.path.isdir(args[0]) else args[0]
    with open(os.path.join(outdir, 'results.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    modes = [m for m in ('local', 'scatter') if any(r['mode'] == m for r in rows)]
    md = '\n'.join(table(rows, m) for m in modes)
    with open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    for m in modes:
        for p in plot(rows, m, outdir):
            print('saved', p)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
