# Histórico público e sanitizado dos workflows V1–V8

Este diretório preserva a evolução técnica anterior à V9 sem publicar
credenciais, dados de execução ou estado interno da instância n8n. Os arquivos
em `workflows/` são cópias históricas: não são a release operacional atual e
não constituem evidência de que aquelas versões eram corretas em produção.

## Conteúdo

| Versão | Artefato público | Nós | Origem selecionada |
|---|---|---:|---|
| V1 | `workflows/v1_triagem.json` | 14 | `Teste01_v1.json` |
| V2 | `workflows/v2_triagem.json` | 32 | `Teste01_v2.json` |
| V3 | `workflows/v3_triagem.json` | 49 | `Teste01_v3.json` |
| V4 | `workflows/v4_triagem.json` | 52 | `Teste01_v4.json` |
| V5 | `workflows/v5_triagem.json` | 39 | `Teste01_v5.json` |
| V6 | `workflows/v6_triagem_postgres.json` | 49 | ID `AutoFinal20260422A` do bundle auditado |
| V7 | `workflows/v7_triagem_postgres.json` | 66 | `v7_current.json`, estado mais recente auditado |
| V8 | `workflows/v8_wf01_orquestrador.json` | 20 | desenho WF01 |
| V8 | `workflows/v8_wf02_triagem.json` | 33 | desenho WF02 |
| V8 | `workflows/v8_wf03_fiscal.json` | 28 | desenho WF03 |

O `manifest.json` registra o SHA-256 do arquivo-fonte privado, o SHA-256 do
objeto de workflow selecionado e o SHA-256 de cada cópia sanitizada. Também
registra os snapshots V6, V7 e V8 que foram auditados, mas não escolhidos como
canônicos. Isso permite verificar a proveniência sem redistribuir os originais,
que permanecem inalterados no ambiente privado.

## Transformações de publicação

O gerador aplica somente uma camada de segurança e portabilidade:

- força `active` para `false`;
- remove `pinData`, `staticData`, `shared`, `activeVersion*` e dados de execução;
- remove referências a credenciais cadastradas na instância;
- substitui valores sensíveis de cabeçalhos por expressões de ambiente;
- omite IDs e metadados de implantação do workflow;
- preserva nomes, nós, parâmetros não sensíveis, conexões e configurações.

Por isso, uma importação nunca ativa o fluxo automaticamente. Antes de qualquer
ensaio, reconecte as credenciais pela interface do n8n e configure as variáveis
`GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` e, quando aplicável,
`GLPI_SESSION_TOKEN`. Revise cada nó: endpoints e contratos históricos podem
não ser compatíveis com a arquitetura atual.

## Reconstrução e validação

No diretório raiz do projeto:

```powershell
python n8n/history/build_history.py --check
python n8n/history/validate_history.py --check-sources
python -m unittest discover -s n8n/history/tests -p "test_*.py" -v
```

Sem acesso aos originais privados, ainda é possível conferir o pacote já
publicado sem tentar reconstruí-lo:

```powershell
python n8n/history/validate_history.py --skip-determinism
```

O validador confere cobertura V1–V8, hashes, inatividade, ausência de campos de
runtime, ausência de referências de credenciais, padrões conhecidos de segredo
e artefatos binários. Esse controle reduz risco de publicação acidental, mas não
substitui a rotação de qualquer chave que tenha sido exposta em outro local.

## Limite histórico

As datas de criação e a compatibilidade com versões específicas do n8n não
foram inferidas. Os snapshots de 63 e 65 nós da V7 são variantes reais, porém
foram excluídos porque o estado de 66 nós é o mais recente entre os artefatos
auditados. Essa escolha é de proveniência, não uma alegação de desempenho.
