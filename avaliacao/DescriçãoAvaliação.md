# Avaliação experimental V9

O protocolo avalia deduplicação, classificação, eficiência e desempenho
do fluxo GLPI → WF06 → WF02/WF03. Cada execução congela exatamente um papel
aceito pelo gateway: `LOCAL` (padrão) ou `SECONDARY` (`gemini-3.5-flash`), sem
fallback dentro do experimento.

## Garantias

- WF06 é o único ingresso público e persiste antes do `202`.
- WF02 é worker interno e restringe candidatos por `run_id/episode_id`.
- Retentativas voltam à fila com backoff; falhas finais entram na DLQ.
- Prompts TXT e JSON Schemas são fontes canônicas e têm identidade verificada
  no JSON real.
- Probabilidades inválidas não são reconstruídas a partir do gabarito.
- Piloto, calibração e teste usam IDs, textos e hashes separados.
- Benchmark não conclui sem auditoria humana do próprio teste.

Os builders Python são infraestrutura como código: permitem revisão, diff,
hash e deploy reproduzível. A lógica executada continua dentro dos nós n8n; os
scripts externos não substituem o motor operacional.

## Preparação

```powershell
python -m pip install -r requirements.txt
python "n8n\workflows\Versão9\validate_v9_static.py"
python "avaliacao\scripts\sincronizar_manifesto.py" --check
```

## 1. Piloto

Antes do novo piloto, configure `IA_CONFIANCA_MINIMA=0.50` em `n8n/.env` e
recrie o serviço n8n. O executor recusa outro valor para não truncar a curva de
sensibilidade.

```powershell
python "avaliacao\scripts\executar_avaliacao.py" piloto
```

O piloto possui 50 tickets, 35 episódios e 94 decisões. O gabarito sintético é registrado diretamente para avaliação estatística da acurácia.

```powershell
python "avaliacao\scripts\conferir_gabarito.py" `
  --run-id "<PILOTO-ID>" `
  --registrar-gabarito `
  --concluir
```

## 2. Calibração da fila

Execute em janela isolada, com fila operacional vazia:

```powershell
python "avaliacao\scripts\calibrar_vazao.py" `
  --configuracoes "1@60,2@45,3@30" `
  --repeticoes 3 `
  --tickets-por-repeticao 12 `
  --warmup 2 `
  --concorrencia-ingresso 4
```

A ordem dos tratamentos é randomizada. A aprovação exige todas as repetições
sem rate limit, erro, probabilidade inválida, timeout ou inversão.

Calibre também o limiar de sensibilidade do modelo. A curva padrão
vai de 0,50 a 0,95:

```powershell
python "avaliacao\scripts\calibrar_limiar.py" `
  --run-id "<PILOTO-ID>" `
  --saida "avaliacao\resultados\limiar_aprovado.json"
```

Se o valor selecionado diferir do `.env`, atualize, regenere e republique os
workflows antes do congelamento.

Valide separadamente a transição operacional para equipe DEMO indisponível.
O comando recusa fila não vazia e restaura a configuração padrão ao terminar:

```powershell
python "avaliacao\scripts\executar_demo_off.py"
```

## 3. Limite da validação automática e benchmark confirmatório

`executar_avaliacao.py` aceita somente as rotas efetivas `LOCAL` e
`SECONDARY`. Seu padrão é `LOCAL`. O comando legado com a fase `benchmark`
agora falha antes de criar diretório, chamado ou registro, porque a mesma rota
usa gabarito sintético e o `ORACULO_GABARITO`, incompatíveis com uma conclusão
confirmatória.

O oráculo automático apenas exercita tecnicamente os webhooks WF04/WF05 depois
da predição persistida. Ele preserva os pontos de confirmação do workflow,
mas não é uma pessoa, não substitui revisão humana e não estima validade
externa. Seus resultados devem ser rotulados como validação técnica não
confirmatória.

O benchmark confirmatório permanece uma etapa separada: exige holdout
independente, congelamento prévio, um único modelo por execução sem fallback e
rótulos humanos normativos importados. Enquanto essa rota dedicada não estiver
implementada e executada, não se deve usar `--concluir` nem apresentar os
resultados automáticos como validação científica final.

Predições de outro LLM ou modelo próprio podem ser comparadas sem alterar o
teste:

```powershell
python "avaliacao\scripts\comparar_baselines.py" `
  --piloto "<piloto.jsonl>" --teste "<teste.jsonl>" `
  --predicoes "GEMINI=<gemini.csv>" `
  --predicoes "MODELO_PROPRIO=<alternativa.csv>" `
  --saida "<comparacao.json>"
```

## Interpretação

Sem chamados reais anonimizados, a distribuição e o estilo são sintéticos.
Resultados sustentam comparação interna e análise de falhas, não desempenho
em produção. Se local, ativo ou sintoma ausentes dominarem os erros, o resultado
favorece melhorar o formulário GLPI antes de treinar modelo próprio.
