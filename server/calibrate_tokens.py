"""Fits the token weights of a model's catalog entry (budget.py) against the model's own tokenizer.

Usage: calibrate_tokens.py --tokenizer LLAMA_TOKENIZE --model GGUF [--recordings DIR] [--files N] [--seed S]

LLAMA_TOKENIZE is llama.cpp's llama-tokenize of the commit that the app runs (pins.sh), which loads only the
model's vocabulary (cmake --build <llama.cpp>/build --target llama-tokenize). The texts are the saved texts before the
audio (recordings/<day>/<id>/text-before-audio.txt): the context and the prompt of real dictations. Half of them fit
the weights (least squares), the other half measure the error, so that the error is not of the texts it was fitted on.
It prints the weights for catalog.json and the error of the estimate on the held-out half.
"""
import argparse
import glob
import os
import random
import statistics
import subprocess

import budget


def tokens(tokenizer, model, path):
    out = subprocess.run([tokenizer, "-m", model, "-f", path, "--ids", "--log-disable"], capture_output=True,
                         text=True, check=True).stdout.strip()
    return out.count(",") + 1 if out.strip("[]").strip() else 0


def solve(a, b):
    """x of a·x = b, by Gaussian elimination with pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        for r in range(n):
            if r != i and m[i][i]:
                f = m[r][i] / m[i][i]
                m[r] = [x - f * y for x, y in zip(m[r], m[i])]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def fit(rows):
    xs = [[c[k] for k in budget.KINDS] for c, _ in rows]
    ys = [n for _, n in rows]
    k = len(budget.KINDS)
    a = [[sum(x[i] * x[j] for x in xs) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(k)]
    return dict(zip(budget.KINDS, solve(a, b)))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--recordings", default=os.path.expanduser("~/speech/recordings"))
    p.add_argument("--files", type=int, default=200)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    paths = sorted(glob.glob(os.path.join(args.recordings, "*", "*", "text-before-audio.txt")))
    paths = [f for f in paths if os.path.getsize(f) > 1024]
    random.Random(args.seed).shuffle(paths)
    rows = []
    for f in paths[:args.files]:
        with open(f, encoding="utf-8") as fh:
            rows.append((budget.counts(fh.read()), tokens(args.tokenizer, args.model, f)))
    train, test = rows[::2], rows[1::2]
    weights = {k: round(v, 3) for k, v in fit(train).items()}
    errors = sorted(abs(budget.count_from(c, weights) - n) / n for c, n in test)
    letters = [c["cyrillic"] / max(1, c["cyrillic"] + c["latin"]) for c, _ in rows]
    print(f'"tokenWeights": {weights}'.replace("'", '"'))
    print(f"{len(train)} texts fitted, {len(test)} measured: |error| median {statistics.median(errors):.1%}, "
          f"90th percentile {errors[int(len(errors) * 0.9)]:.1%}, largest {errors[-1]:.1%}; "
          f"tokens {min(n for _, n in rows)} to {max(n for _, n in rows)}; Cyrillic share of the letters, median "
          f"{statistics.median(letters):.0%}")


if __name__ == "__main__":
    main()
