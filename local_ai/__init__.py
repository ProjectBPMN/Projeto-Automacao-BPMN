"""Serviço local e auditável de IA para os workflows V9.

O pacote mantém o runtime principal sem dependências externas. O backend Granite
é carregado apenas na primeira inferência que realmente precisa de embeddings.
"""

from __future__ import annotations

import os


# Evita que BLAS/Torch ocupem todos os núcleos do i3. O operador ainda pode
# sobrescrever cada variável antes de iniciar o processo.
_DEFAULT_THREADS = os.getenv("LOCAL_AI_CPU_THREADS", "4")
for _name in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_name, _DEFAULT_THREADS)


__version__ = "0.1.0"
