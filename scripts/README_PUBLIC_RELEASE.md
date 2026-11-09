# Barreira de publicação pública

O arquivo `public_release_manifest.json` é a lista positiva do conteúdo que
pode entrar no repositório público. O `.gitignore` não é usado como controle de
segurança e também não integra a lista: ignorar um arquivo não prova que ele
nunca foi indexado pelo Git.

## Verificações

Na raiz do projeto, valide primeiro os arquivos elegíveis no diretório de
trabalho:

```powershell
python scripts/validate_public_release.py --source manifest
```

Antes de publicar, a verificação obrigatória é a do índice Git que formará o
commit:

```powershell
python scripts/validate_public_release.py --source git-index
```

O comando termina com código `0` somente quando todos os arquivos indexados
estão na lista positiva, todos os itens obrigatórios estão presentes e nenhuma
regra de conteúdo falha. A opção `--source staged` é uma conferência incremental
útil antes de um commit, mas não substitui a verificação completa do índice.

Para conferir um diretório montado como pacote de publicação:

```powershell
python scripts/validate_public_release.py --source tree --root CAMINHO_DO_PACOTE
```

Use `--json` em qualquer modo quando a integração de CI precisar de saída
estruturada. O relatório nunca reproduz o valor que acionou uma regra de
segredo.

## Política aplicada

A barreira rejeita, mesmo que sejam adicionados acidentalmente à lista:

- `.env`, `.gitignore`, credenciais exportadas e diretórios de credenciais;
- ZIP, SQLite, SQL, bancos, dumps, pesos, caches e arquivos binários de modelo;
- `docs/`, corpora, datasets, resultados, experimentos e backups internos;
- chaves com formato conhecido, autorização literal, senha em URL, chave
  privada e atribuições sensíveis codificadas no arquivo;
- arquivo fora da lista positiva, link simbólico, arquivo acima do limite ou
  texto que não seja UTF-8;
- `staticData`, `pinData` não vazio e export de credencial em workflow n8n.

Os seis workflows canônicos V9 podem conservar apenas referências simbólicas e
portáveis (`PG_TRIAGEM`, `SMTP_MAILPIT_LOCAL`) compostas por `id` e `name`.
Identificadores reais de instância ou dados de credencial são recusados. Um
`pinData` vazio é aceito porque não contém amostra nem estado; qualquer conteúdo
nesse campo é recusado.

O histórico V1–V8 incluído na lista é exclusivamente o pacote sanitizado de
`n8n/history`. Os exports privados que deram origem a ele continuam fora da
publicação.
