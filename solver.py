# -*- coding: utf-8 -*-
# Цезар + XOR на PARCS-Python. Python 2.7 (такий в образі parcs-node) і 3.
from __future__ import print_function, division

import base64
import binascii
import hashlib
import random
import sys
import time

try:
    from Pyro4 import expose
except ImportError:
    def expose(f):
        return f

PY2 = sys.version_info[0] == 2
if PY2:
    range = xrange

DEFAULTS = {
    'mode': 'local',
    'sizes': '100000000',
    'workers': '0',
    'shift': '3',
    'key': 'SecretKey123!@#',
    'seed': '2026',
    'block': '1048576',
    'repeat': '1',
}


def make_table(fn):
    \
    return bytes(bytearray(fn(b) % 256 for b in range(256)))


PRINTABLE = make_table(lambda b: 32 + b % 95)


def caesar_tables(shift):
    \
    return make_table(lambda b: b + shift), make_table(lambda b: b - shift)


# текст генерується блоками, кожен блок зі свого seed - тому дані однакові при будь-якій кількості воркерів
def gen_block(seed, idx, n):
    \
    if n <= 0:
        return b''
    rng = random.Random(seed * 1000003 + idx)
    raw = binascii.unhexlify(format(rng.getrandbits(8 * n), '0%dx' % (2 * n)))
    return raw.translate(PRINTABLE)


def keystream(key, offset, n):
    \
    s = offset % len(key)
    rotated = key[s:] + key[:s]
    return (rotated * (n // len(key) + 1))[:n]


# xor через великі int, бо numpy в образі немає, а цикл по байтах в python занадто повільний
def xor_bytes(data, key, offset):
    \
    n = len(data)
    if n == 0:
        return data
    x = int(binascii.hexlify(data), 16) ^ int(binascii.hexlify(keystream(key, offset, n)), 16)
    return binascii.unhexlify(format(x, '0%dx' % (2 * n)))


def md5hex(data):
    return hashlib.md5(data).hexdigest()


def fingerprint(digests):
    \
    return md5hex(''.join(digests).encode('ascii'))


# pyro4 (serpent) не любить bytes, ганяємо base64
def to_wire(data):
    \
    s = base64.b64encode(data)
    return s if PY2 else s.decode('ascii')


def from_wire(s):
    if not isinstance(s, bytes):
        s = s.encode('ascii')
    return base64.b64decode(s)


def as_bytes(s):
    if isinstance(s, bytes):
        return s
    return s.encode('latin-1')


def value(result):
    \
    return result.value if hasattr(result, 'value') else result


# розподіл як у parallel.cpp
def split_counts(total, parts):
    \
    counts, displs, rest, pos = [], [], total, 0
    for i in range(parts):
        c = rest // (parts - i)
        counts.append(c)
        displs.append(pos)
        rest -= c
        pos += c
    return counts, displs


# один і той самий код для serial (на майстрі) і local (на воркері)
def process_blocks(seed, first, count, block, size, shift, key):
    \
    enc_t, dec_t = caesar_tables(shift)
    t = {'gen': 0.0, 'caesar': 0.0, 'xor': 0.0, 'verify': 0.0}
    caesar_ok = xor_ok = True
    c_digests, x_digests = [], []
    nbytes = 0
    start = time.time()
    for idx in range(first, first + count):
        offset = idx * block
        n = min(block, size - offset)
        nbytes += n

        t0 = time.time()
        text = gen_block(seed, idx, n)
        t1 = time.time()
        c_enc = text.translate(enc_t)
        c_dec = c_enc.translate(dec_t)
        t2 = time.time()
        x_enc = xor_bytes(text, key, offset)
        x_dec = xor_bytes(x_enc, key, offset)
        t3 = time.time()
        caesar_ok = caesar_ok and c_dec == text
        xor_ok = xor_ok and x_dec == text
        c_digests.append(md5hex(c_enc))
        x_digests.append(md5hex(x_enc))
        t4 = time.time()

        t['gen'] += t1 - t0
        t['caesar'] += t2 - t1
        t['xor'] += t3 - t2
        t['verify'] += t4 - t3
    t['total'] = time.time() - start
    return {'first': first, 'count': count, 'bytes': nbytes,
            'caesar_ok': caesar_ok, 'xor_ok': xor_ok,
            'caesar_digests': c_digests, 'xor_digests': x_digests, 'times': t}


class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers


    def solve(self):
        cfg = self.read_input()
        workers = list(self.workers or [])
        if cfg['workers'] > 0:
            workers = workers[:cfg['workers']]
        mode = cfg['mode']
        if mode != 'serial' and not workers:
            raise ValueError('mode=%s needs at least one worker' % mode)
        print('Job started: mode=%s workers=%d sizes=%s' % (mode, len(workers), cfg['sizes']))

        rows = []
        for size in cfg['sizes']:
            runs = []
            for _ in range(cfg['repeat']):
                if mode == 'serial':
                    runs.append(self.run_serial(cfg, size))
                elif mode == 'local':
                    runs.append(self.run_local(cfg, size, workers))
                elif mode == 'scatter':
                    runs.append(self.run_scatter(cfg, size, workers))
                else:
                    raise ValueError('unknown mode: %s' % mode)
            best = min(runs, key=lambda r: r['wall'])
            best['wall_avg'] = sum(r['wall'] for r in runs) / len(runs)
            best['repeat'] = len(runs)
            rows.append(best)
            print('size=%d wall=%.3f s ok=%s' % (size, best['wall'], best['caesar_ok'] and best['xor_ok']))

        self.write_output(format_report(cfg, rows))
        print('Job finished')

    def run_serial(self, cfg, size):
        \
        nblocks = -(-size // cfg['block'])
        start = time.time()
        r = process_blocks(cfg['seed'], 0, nblocks, cfg['block'], size, cfg['shift'], cfg['key'])
        wall = time.time() - start
        return self.summary('serial', 1, size, wall, [r])

    # дані лежать на воркерах, по мережі тільки параметри і md5
    def run_local(self, cfg, size, workers):
        \
        k = len(workers)
        nblocks = -(-size // cfg['block'])
        bounds = [nblocks * i // k for i in range(k + 1)]
        key_wire = to_wire(cfg['key'])
        start = time.time()
        futures = []
        for i in range(k):
            count = bounds[i + 1] - bounds[i]
            if count > 0:
                futures.append(workers[i].process_range(cfg['seed'], bounds[i], count, cfg['block'],
                                                        size, cfg['shift'], key_wire))
        parts = [value(f) for f in futures]
        wall = time.time() - start
        return self.summary('local', k, size, wall, parts)

    # порт MPI версії: майстер розсилає текст і збирає назад (Scatterv/Gatherv)
    def run_scatter(self, cfg, size, workers):
        \
        k = len(workers)
        block, seed, shift, key = cfg['block'], cfg['seed'], cfg['shift'], cfg['key']
        nblocks = -(-size // block)


        t0 = time.time()
        text = b''.join(gen_block(seed, i, min(block, size - i * block)) for i in range(nblocks))
        t_gen = time.time() - t0

        counts, displs = split_counts(size, k)
        key_wire = to_wire(key)

        def scatter_gather(method, data, extra):
            futures = [getattr(workers[i], method)(to_wire(data[displs[i]:displs[i] + counts[i]]),
                                                   *extra(i))
                       for i in range(k)]
            return b''.join(from_wire(value(f)) for f in futures)

        start = time.time()
        c_enc = scatter_gather('caesar_chunk', text, lambda i: (shift, False))
        c_dec = scatter_gather('caesar_chunk', c_enc, lambda i: (shift, True))
        t_caesar = time.time() - start

        start = time.time()
        x_enc = scatter_gather('xor_chunk', text, lambda i: (key_wire, displs[i]))
        x_dec = scatter_gather('xor_chunk', x_enc, lambda i: (key_wire, displs[i]))
        t_xor = time.time() - start


        t0 = time.time()
        part = {
            'first': 0, 'count': nblocks, 'bytes': size,
            'caesar_ok': c_dec == text, 'xor_ok': x_dec == text,
            'caesar_digests': [md5hex(c_enc[i * block:(i + 1) * block]) for i in range(nblocks)],
            'xor_digests': [md5hex(x_enc[i * block:(i + 1) * block]) for i in range(nblocks)],
            'times': {'gen': t_gen, 'caesar': t_caesar, 'xor': t_xor, 'verify': 0.0,
                      'total': t_caesar + t_xor},
        }
        part['times']['verify'] = time.time() - t0
        return self.summary('scatter', k, size, t_caesar + t_xor, [part])

    @staticmethod
    def summary(mode, workers, size, wall, parts):
        parts = sorted(parts, key=lambda p: p['first'])
        times = [p['times'] for p in parts]
        slowest = max(times, key=lambda t: t['total'])
        c_digests, x_digests = [], []
        for p in parts:
            c_digests.extend(p['caesar_digests'])
            x_digests.extend(p['xor_digests'])
        return {
            'mode': mode, 'workers': workers, 'size': size, 'wall': wall,
            'caesar': slowest['caesar'], 'xor': slowest['xor'],
            'gen': slowest['gen'], 'verify': slowest['verify'],
            'compute': slowest['total'],
            'overhead': max(0.0, wall - slowest['total']) if mode == 'local' else 0.0,
            'bytes': sum(p['bytes'] for p in parts),
            'caesar_ok': all(p['caesar_ok'] for p in parts),
            'xor_ok': all(p['xor_ok'] for p in parts),
            'fp_caesar': fingerprint(c_digests), 'fp_xor': fingerprint(x_digests),
        }


    # --- те, що викликається на воркерах ---
    @staticmethod
    @expose
    def process_range(seed, first, count, block, size, shift, key_wire):
        return process_blocks(seed, first, count, block, size, shift, from_wire(key_wire))

    @staticmethod
    @expose
    def caesar_chunk(chunk_wire, shift, decrypt):
        enc_t, dec_t = caesar_tables(shift)
        return to_wire(from_wire(chunk_wire).translate(dec_t if decrypt else enc_t))

    @staticmethod
    @expose
    def xor_chunk(chunk_wire, key_wire, offset):
        return to_wire(xor_bytes(from_wire(chunk_wire), from_wire(key_wire), offset))


    def read_input(self):
        cfg = dict(DEFAULTS)
        with open(self.input_file_name) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                name, val = line.split('=', 1)
                name = name.strip().lower()

                cfg[name] = val.strip() if name == 'key' else val.split('#', 1)[0].strip()
        out = {
            'mode': cfg['mode'].lower(),
            'sizes': [int(s) for s in cfg['sizes'].replace(',', ' ').split()],
            'workers': int(cfg['workers']),
            'shift': int(cfg['shift']),
            'key': as_bytes(cfg['key']),
            'seed': int(cfg['seed']),
            'block': int(cfg['block']),
            'repeat': max(1, int(cfg['repeat'])),
        }
        if not out['key']:
            raise ValueError('key must not be empty')
        return out

    def write_output(self, text):
        with open(self.output_file_name, 'w') as f:
            f.write(text)


def format_report(cfg, rows):
    lines = []
    head = rows[0]
    lines.append('=== Caesar / XOR on PARCS-Python ===')
    lines.append('mode=%s  workers=%d  shift=%d  key_len=%d  block=%d  repeat=%d'
                 % (head['mode'], head['workers'], cfg['shift'], len(cfg['key']), cfg['block'], cfg['repeat']))
    lines.append('')
    fmt = '%-12s | %-10s | %-10s | %-10s | %-10s | %-10s | %-10s | %-6s'
    lines.append(fmt % ('Data size', 'Time, s', 'Avg, s', 'Caesar, s', 'XOR, s', 'Gen, s', 'Overhead,s', 'Check'))
    lines.append('-' * 100)
    for r in rows:
        lines.append(fmt % (r['size'], '%.3f' % r['wall'], '%.3f' % r['wall_avg'], '%.3f' % r['caesar'],
                            '%.3f' % r['xor'], '%.3f' % r['gen'], '%.3f' % r['overhead'],
                            'PASSED' if r['caesar_ok'] and r['xor_ok'] else 'FAILED'))
    lines.append('')
    lines.append('Fingerprints (must be identical in every mode for the same size):')
    for r in rows:
        lines.append('  %-12d caesar=%s  xor=%s' % (r['size'], r['fp_caesar'], r['fp_xor']))
    lines.append('')
    lines.append('# CSV: mode,workers,size,time,time_avg,caesar,xor,gen,overhead,check')
    for r in rows:
        lines.append('CSV,%s,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%s'
                     % (r['mode'], r['workers'], r['size'], r['wall'], r['wall_avg'], r['caesar'], r['xor'],
                        r['gen'], r['overhead'], 'PASSED' if r['caesar_ok'] and r['xor_ok'] else 'FAILED'))
    lines.append('')
    return '\n'.join(lines)


# локальний запуск без PARCS, воркери = процеси
def _call(name, args):
    return getattr(Solver, name)(*args)


class _LocalFuture(object):
    def __init__(self, async_result):
        self._r = async_result

    @property
    def value(self):
        return self._r.get()


class _LocalWorker(object):
    def __init__(self, pool):
        self._pool = pool

    def __getattr__(self, name):
        def call(*args):
            return _LocalFuture(self._pool.apply_async(_call, (name, args)))
        return call


def main(argv):
    import argparse
    import multiprocessing
    parser = argparse.ArgumentParser(description='Local run of the PARCS solver (workers = processes)')
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(argv)
    pools = [multiprocessing.Pool(1) for _ in range(args.workers)]
    try:
        Solver([_LocalWorker(p) for p in pools], args.input, args.output).solve()
    finally:
        for p in pools:
            p.terminate()
    with open(args.output) as f:
        print(f.read())


if __name__ == '__main__':
    main(sys.argv[1:])
