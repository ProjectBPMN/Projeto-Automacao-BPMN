# Retirada do override pós-hoc de deduplicação

**Estado:** retirado em 26/08/2026

O override que comparava posições de ranking e escolhia um candidato de
deduplicação não deve ser usado. Ele dependia da seleção posteriormente
invalidada e de episódios nominais derivados de poucas famílias-fonte.

Não existe candidato substituto autorizado por este documento. O operacional
permanece `local-hybrid-v1.8.0` por estabilidade de engenharia, não por vitória
estatística. A tentativa V2.1 de deduplicação foi bloqueada por insuficiência
de grupos independentes. Qualquer promoção exige novo protocolo viável, ainda
rotulado como desenvolvimento, seguido de evidência humana, regressão/E2E,
versão e rollback.

Critérios mínimos:

- grupos por `source_dependency_group_sha256` sem sobreposição;
- hash de dataset/config reproduzível;
- FN/FP, NPV, precisão e cobertura com intervalos por família-fonte;
- recuperação recall@k separada da decisão;
- calibração, latência e análise dos erros;
- nenhuma seleção pós-hoc baseada em olhar o holdout.

O histórico original permanece recuperável pelo Git, mas seus rankings não são
evidência corrente.
