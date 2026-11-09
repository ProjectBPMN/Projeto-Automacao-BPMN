"""Infraestrutura fail-closed para a avaliação confirmatória do projeto.

O pacote não contém dados confirmatórios e não abre nenhum holdout por importação.
As operações com efeito são expostas apenas por funções e pela CLI explícita.
"""

from .amostra import (
    clopper_pearson_upper_unilateral,
    planejar_zero_eventos,
    tamanho_minimo_zero_eventos,
)
from .avaliar import (
    executar_avaliacao_confirmatoria,
    reservar_abertura_confirmatoria,
    status_execucao,
)
from .familias import import_registry, validate_registry
from .preregistro import (
    congelar_preregistro,
    criar_rascunho,
    verificar_preregistro_congelado,
)

__all__ = [
    "clopper_pearson_upper_unilateral",
    "tamanho_minimo_zero_eventos",
    "planejar_zero_eventos",
    "import_registry",
    "validate_registry",
    "criar_rascunho",
    "congelar_preregistro",
    "verificar_preregistro_congelado",
    "reservar_abertura_confirmatoria",
    "executar_avaliacao_confirmatoria",
    "status_execucao",
]
