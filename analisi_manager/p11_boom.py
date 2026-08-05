# -*- coding: utf-8 -*-
"""P11 - stima di P(reale >= 75 | ruolo, atteso_grezzo). Pure python."""
import math, json, bisect

BOOM = 75.0
CODICE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}


# ---------------------------------------------------------------- logistica
def fit_logistic_irls(X, y, l2=1e-6, iters=60):
    """X: lista di liste (senza intercetta). Newton/IRLS esatto."""
    n = len(X); d = len(X[0]) + 1
    Z = [[1.0] + list(r) for r in X]
    w = [0.0] * d
    for _ in range(iters):
        g = [0.0] * d
        H = [[0.0] * d for _ in range(d)]
        for i in range(n):
            z = sum(w[j] * Z[i][j] for j in range(d))
            z = max(-30.0, min(30.0, z))
            p = 1.0 / (1.0 + math.exp(-z))
            r = y[i] - p
            s = p * (1.0 - p)
            for j in range(d):
                g[j] += r * Z[i][j]
                zij = Z[i][j] * s
                for k in range(j, d):
                    H[j][k] += zij * Z[i][k]
        for j in range(d):
            g[j] -= l2 * w[j]
            H[j][j] += l2
            for k in range(j):
                H[j][k] = H[k][j]
        step = _solve(H, g)
        if step is None:
            break
        mx = 0.0
        for j in range(d):
            w[j] += step[j]
            mx = max(mx, abs(step[j]))
        if mx < 1e-9:
            break
    return w


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        for k in range(c, n + 1):
            M[c][k] /= pv
        for r in range(n):
            if r == c:
                continue
            f = M[r][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] for i in range(n)]


def predict(w, x):
    z = w[0] + sum(w[j + 1] * x[j] for j in range(len(x)))
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


# ------------------------------------------------------------------ metriche
def auc(scores, labels):
    npos = sum(labels); nneg = len(labels) - npos
    if npos == 0 or nneg == 0:
        return float('nan')
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    sp = sum(ranks[i] for i in range(len(labels)) if labels[i] == 1)
    return (sp - npos * (npos + 1) / 2.0) / (npos * nneg)


def brier(p, y):
    return sum((a - b) ** 2 for a, b in zip(p, y)) / len(y)


def tabella_calibrazione(p, y, nbin=10):
    idx = sorted(range(len(p)), key=lambda i: p[i])
    out = []
    for k in range(nbin):
        sl = idx[k * len(idx) // nbin:(k + 1) * len(idx) // nbin]
        if not sl:
            continue
        out.append((len(sl),
                    sum(p[i] for i in sl) / len(sl),
                    sum(y[i] for i in sl) / len(sl)))
    return out


def calibrazione_affine(p, y):
    """Regressione logistica di y su logit(p): (intercetta, pendenza).
    Ben calibrata => (0, 1)."""
    X = [[math.log(max(1e-9, min(1 - 1e-9, v)) / (1 - max(1e-9, min(1 - 1e-9, v))))] for v in p]
    w = fit_logistic_irls(X, y)
    return w[0], w[1]


# ------------------------------------------------------------------- modello
class ModelloBoom(object):
    """Un fit per ruolo: logit P(boom) = a_r + b_r * atteso_grezzo."""

    def __init__(self, coppie):
        self.w = {}
        self.n = {}
        self.base = {}
        for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
            righe = [c for c in coppie if c['_cod'] == ruolo]
            y = [1 if c['reale'] >= BOOM else 0 for c in righe]
            self.n[ruolo] = len(righe)
            self.base[ruolo] = (sum(y) / len(y)) if righe else 0.0
            if len(righe) < 200 or sum(y) < 10:
                self.w[ruolo] = None
                continue
            X = [[c['previsto']] for c in righe]
            self.w[ruolo] = fit_logistic_irls(X, y)

    def p(self, ruolo, atteso_raw):
        w = self.w.get(ruolo)
        if w is None:
            return self.base.get(ruolo, 0.12)
        return predict(w, [atteso_raw])


def carica_coppie(path):
    coppie = json.load(open(path, encoding='utf-8'))
    for c in coppie:
        c['_cod'] = CODICE.get(c['ruolo'], '?')
    return [c for c in coppie if c['_cod'] != '?' and c.get('previsto') is not None
            and c.get('reale') is not None]


class ModelliWalkForward(object):
    """Un ModelloBoom per ogni data di taglio richiesta, addestrato SOLO sulle
    coppie con data strettamente precedente."""

    def __init__(self, coppie, date_taglio):
        self.coppie = sorted(coppie, key=lambda c: c['data'])
        self._date = [c['data'] for c in self.coppie]
        self.modelli = {}
        self.n_train = {}
        for d in sorted(set(date_taglio)):
            k = bisect.bisect_left(self._date, d)
            sub = self.coppie[:k]
            self.n_train[d] = len(sub)
            self.modelli[d] = ModelloBoom(sub) if len(sub) >= 500 else None

    def get(self, data):
        return self.modelli.get(data)
